#!/usr/bin/env python3
"""Render AWS Lambda APM skill assets.

Reads a YAML or JSON spec (default: ``template.example``) and emits a
numbered, render-first plan tree under ``--output-dir``:

- ``01-overview.md`` through ``05-validation.md``
- ``coverage-report.json``
- ``iam/``       (IAM policies for ingest egress when local collector disabled)
- ``aws-cli/``   (per-function ``aws lambda update-function-configuration`` plans)
- ``terraform/`` (``aws_lambda_function`` + layer references)
- ``cloudformation/`` (CloudFormation snippets)
- ``scripts/``   (token-secret helper + cross-skill handoff drivers)

The renderer never accepts a secret value as an argument or writes one
into any rendered file. Access tokens are delivered via Secrets Manager or
SSM SecureString references; the token path is written as ``${SPLUNK_LAMBDA_TOKEN_FILE}``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "lib"))
from yaml_compat import YamlCompatError, load_yaml_or_json  # noqa: E402

# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------

SKILL_NAME = "splunk-observability-aws-lambda-apm-setup"
API_VERSION = f"{SKILL_NAME}/v1"

LAMBDA_LAYER_PUBLISHER = "254067382080"
LAYER_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "references" / "layer-versions.snapshot.json"
METRICS_LAYER_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "references" / "lambda-metrics-layer-versions.snapshot.json"
RUNTIME_WRAPPERS_PATH = Path(__file__).resolve().parents[1] / "references" / "runtime-wrappers.json"

SUPPORTED_REALMS: tuple[str, ...] = (
    "us0", "us1", "us2", "us3", "eu0", "eu1", "eu2", "au0", "jp0", "sg0",
)

GOVCLOUD_REGION_PREFIX = "us-gov-"
CHINA_REGION_PREFIX = "cn-"

SECRET_BACKENDS: tuple[str, ...] = ("secretsmanager", "ssm")

VENDOR_CONFLICT_ENV_PATTERNS: tuple[tuple[str, str], ...] = (
    ("DD_", "Datadog"),
    ("NEW_RELIC_LAMBDA_HANDLER", "New Relic"),
    ("APPDYNAMICS_", "AppDynamics"),
    ("DT_TENANT", "Dynatrace"),
)
VENDOR_CONFLICT_LAYER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("datadog", "Datadog"),
    ("NewRelicLambdaExtension", "New Relic"),
    ("Dynatrace_", "Dynatrace"),
    ("aws-otel-", "ADOT (AWS Distro for OpenTelemetry)"),
)
ADOT_LAYER_PUBLISHER = "901920570463"

NUMBERED_PLAN_FILES: tuple[tuple[str, str], ...] = (
    ("01-overview.md", "overview"),
    ("02-targets.md", "targets"),
    ("03-layers.md", "layers"),
    ("04-env.md", "env"),
    ("05-validation.md", "validation"),
)

SECTION_ORDER: tuple[str, ...] = (
    "prerequisites",
    "targets",
    "layers",
    "env",
    "iam",
    "terraform",
    "cloudformation",
    "aws_cli",
    "validation",
    "handoff",
)


# ---------------------------------------------------------------------------
# Layer manifest.
# ---------------------------------------------------------------------------

def _load_manifest() -> dict[str, Any]:
    return json.loads(LAYER_MANIFEST_PATH.read_text())


def _load_metrics_manifest() -> dict[str, Any]:
    return json.loads(METRICS_LAYER_MANIFEST_PATH.read_text())


def _load_wrappers() -> dict[str, str]:
    return json.loads(RUNTIME_WRAPPERS_PATH.read_text())


def _resolve_metrics_layer_arn(metrics_manifest: dict[str, Any], region: str, arch: str) -> str | None:
    arch_map: dict[str, Any] = metrics_manifest.get(arch, {})
    entry = arch_map.get(region)
    if entry is None:
        return None
    return entry["arn"]


def _resolve_layer_arn(manifest: dict[str, Any], region: str, arch: str) -> str:
    arch_map: dict[str, Any] = manifest.get(arch, {})
    entry = arch_map.get(region)
    if entry is None:
        if arch == "arm64":
            raise RendererError(
                f"arm64 layer is not published for region '{region}'. "
                "Set arch: x86_64 or pick a supported arm64 region "
                f"(published: {sorted(arch_map)})."
            )
        raise RendererError(
            f"No '{arch}' layer found for region '{region}'. "
            "Run --list-layer-arns to see all published regions."
        )
    return entry["arn"]


def _runtime_family(runtime: str) -> str:
    if runtime.startswith("nodejs"):
        return "nodejs"
    if runtime.startswith("python"):
        return "python"
    if runtime.startswith("java"):
        return "java"
    return "unknown"


def _exec_wrapper(wrappers: dict[str, str], runtime: str, handler_type: str = "default") -> str:
    family = _runtime_family(runtime)
    if family == "nodejs":
        return wrappers["nodejs"]
    if family == "python":
        return wrappers["python"]
    if family == "java":
        key_map = {
            "default": "java",
            "stream": "java_stream",
            "apigw_proxy": "java_apigw_proxy",
            "sqs": "java_sqs",
        }
        k = key_map.get(handler_type, "java")
        return wrappers[k]
    raise RendererError(f"No exec wrapper for runtime '{runtime}'. Unsupported runtime family.")


def _is_unsupported_runtime(manifest: dict[str, Any], runtime: str) -> bool:
    unsupported: list[str] = manifest.get("supported_runtimes", {}).get("unsupported", [])
    return runtime in unsupported or _runtime_family(runtime) == "unknown"


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------

class RendererError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Spec validation.
# ---------------------------------------------------------------------------

def validate_spec(raw: dict[str, Any]) -> dict[str, Any]:
    spec = dict(raw)
    if spec.get("api_version", "").split("/")[0] != SKILL_NAME:
        spec.setdefault("api_version", API_VERSION)

    realm = spec.get("realm", "us1")
    if realm not in SUPPORTED_REALMS:
        if realm.startswith(GOVCLOUD_REGION_PREFIX) or realm.startswith(CHINA_REGION_PREFIX):
            raise RendererError(
                f"realm '{realm}' looks like an AWS region. "
                "Set realm to your Splunk Observability Cloud realm (e.g. us1)."
            )
        raise RendererError(
            f"Unsupported realm '{realm}'. Supported: {', '.join(SUPPORTED_REALMS)}"
        )
    spec["realm"] = realm

    # Accept-beta gate.
    if not spec.get("accept_beta", False):
        raise RendererError(
            "The Splunk OpenTelemetry Lambda layer (signalfx/splunk-otel-lambda) is BETA. "
            "Set accept_beta: true in the spec or pass --accept-beta to acknowledge."
        )

    targets = spec.get("targets", [])
    if not isinstance(targets, list) or len(targets) == 0:
        raise RendererError(
            "spec.targets must be a non-empty list of function targets. "
            "See template.example for the required shape."
        )

    manifest = _load_manifest()

    for idx, tgt in enumerate(targets):
        fn = tgt.get("function_name", "")
        if not fn:
            raise RendererError(f"targets[{idx}].function_name is required.")

        region = tgt.get("region", "")
        if not region:
            raise RendererError(f"targets[{idx}].region is required.")

        if region.startswith(GOVCLOUD_REGION_PREFIX) or region.startswith(CHINA_REGION_PREFIX):
            raise RendererError(
                f"targets[{idx}] region '{region}': GovCloud and China regions have no published "
                "Splunk Lambda APM layers (coverage: not_applicable). Remove this target or use a commercial region."
            )

        runtime = tgt.get("runtime", "")
        if not runtime:
            raise RendererError(f"targets[{idx}].runtime is required (e.g. python3.11, nodejs20.x, java17).")

        if _is_unsupported_runtime(manifest, runtime):
            unsupported = manifest.get("supported_runtimes", {}).get("unsupported", [])
            if runtime in unsupported:
                raise RendererError(
                    f"targets[{idx}] runtime '{runtime}' has no published Splunk Lambda APM layer. "
                    "Unsupported runtimes: Go, Ruby, .NET, provided.al2/al2023. "
                    "Use Node.js (18/20/22), Python (3.8-3.13), or Java (8/11/17/21)."
                )
            raise RendererError(
                f"targets[{idx}] runtime '{runtime}' is unrecognised. "
                "Use Node.js (nodejs18.x/20.x/22.x), Python (python3.8-3.13), or Java (java8/8.al2/11/17/21)."
            )

        # Warn on AWS-deprecated runtime.
        deprecated = manifest.get("supported_runtimes", {}).get("deprecated_but_supported", [])
        if runtime in deprecated:
            import warnings as _warnings
            _warnings.warn(
                f"targets[{idx}] runtime '{runtime}' is deprecated by AWS (EOL 2024-10). "
                "A layer is published but no new development occurs. Upgrade when possible.",
                UserWarning,
                stacklevel=2,
            )

    secret_backend = spec.get("secret_backend", "secretsmanager")
    if secret_backend not in SECRET_BACKENDS:
        raise RendererError(
            f"secret_backend must be 'secretsmanager' or 'ssm', got '{secret_backend}'."
        )
    spec["secret_backend"] = secret_backend

    return spec


# ---------------------------------------------------------------------------
# Coverage.
# ---------------------------------------------------------------------------

def coverage_for(spec: dict[str, Any]) -> dict[str, str]:
    h = spec.get("handoffs", {})
    local_collector = spec.get("local_collector_enabled", True)
    return {
        "prerequisites.beta_acknowledgement": "api_validate",
        "prerequisites.govcloud_china_refused": "not_applicable",
        "targets.function_list": "api_validate",
        "targets.runtime_validation": "api_validate",
        "layers.arn_resolution": "api_validate",
        "layers.attach_plan": "api_validate",
        "env.exec_wrapper": "api_validate",
        "env.token_delivery": "handoff",
        "env.xray_coexistence": "api_validate",
        "iam.ingest_egress": "api_validate" if not local_collector else "not_applicable",
        "terraform.lambda_config": "handoff",
        "cloudformation.lambda_config": "handoff",
        "sam.lambda_config": "handoff",
        "cdk.lambda_config": "handoff",
        "sar.advisory": "handoff",
        "container_image.dockerfile": "handoff" if any(t.get("package_type") == "image" for t in spec.get("targets", [])) else "not_applicable",
        "execution_modes.snapstart": "api_validate",
        "execution_modes.lambda_at_edge": "not_applicable",
        "execution_modes.provisioned_concurrency": "api_validate",
        "metrics_extension.layer": "api_validate" if spec.get("metrics_extension") else "not_applicable",
        "aws_cli.update_function_config": "api_validate",
        "validation.span_attributes": "api_validate",
        "validation.vendor_coexistence": "api_validate",
        "handoff.cloudwatch_metrics": "handoff" if h.get("cloudwatch_metrics") else "not_applicable",
        "handoff.dashboards": "handoff" if h.get("dashboards") else "not_applicable",
        "handoff.detectors": "handoff" if h.get("detectors") else "not_applicable",
        "handoff.logs": "handoff" if h.get("logs") else "not_applicable",
        "handoff.gateway_otel_collector": "handoff" if h.get("gateway_otel_collector") else "not_applicable",
    }


# ---------------------------------------------------------------------------
# Plan-file renderers.
# ---------------------------------------------------------------------------

def _render_overview(spec: dict[str, Any]) -> str:
    realm = spec["realm"]
    n = len(spec.get("targets", []))
    backend = spec.get("secret_backend", "secretsmanager")
    local = spec.get("local_collector_enabled", True)
    return f"""# AWS Lambda APM Setup — Overview

**Realm**: {realm}
**Targets**: {n} function(s)
**Secret backend**: {backend}
**Local collector (Lambda Extension)**: {"enabled" if local else "disabled"}
**Layer publisher**: `{LAMBDA_LAYER_PUBLISHER}`
**Source**: `signalfx/splunk-otel-lambda` (BETA)

## What this plan does

1. Resolves the correct Splunk OTel Lambda layer ARN for each function's
   runtime and architecture from the baked `references/layer-versions.snapshot.json`.
2. Emits `aws lambda update-function-configuration` commands to attach the layer
   and set the required environment variables.
3. Emits Terraform (`terraform/`) and CloudFormation (`cloudformation/`) variants
   for GitOps workflows.
4. Emits a one-time token-write helper (`scripts/write-splunk-token.sh`) so
   `SPLUNK_ACCESS_TOKEN` is stored in {backend} without appearing in argv or
   shell history.
5. Renders cross-skill handoff drivers for CloudWatch metrics, dashboards,
   detectors, and logs as requested.

## Safety

- `SPLUNK_ACCESS_TOKEN` is delivered via `{{resolve:{backend}:...}}` references;
  the token value never appears in rendered files or argv.
- Run `--validate` to check the rendered tree for secret-looking content before
  applying.
- Run `--doctor` to detect vendor/ADOT conflicts and X-Ray coexistence issues
  before attaching layers.

## BETA disclaimer

The Splunk OpenTelemetry Lambda layer is BETA. Test in a non-production
environment first. Run `--doctor` after each layer version update.

## Apply command

```bash
bash skills/{SKILL_NAME}/scripts/setup.sh \\
  --apply \\
  --spec <your-spec.yaml> \\
  --realm {realm} \\
  --token-file /tmp/splunk_o11y_token
```
"""


def _render_targets(spec: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = ["# Targets\n"]
    for i, tgt in enumerate(spec.get("targets", []), 1):
        fn = tgt["function_name"]
        region = tgt["region"]
        runtime = tgt["runtime"]
        arch = tgt.get("arch", "x86_64")
        handler_type = tgt.get("handler_type", "default")
        lines.append(f"## Function {i}: {fn}")
        lines.append(f"- **Region**: {region}")
        lines.append(f"- **Runtime**: {runtime}")
        lines.append(f"- **Arch**: {arch}")
        lines.append(f"- **Handler type**: {handler_type}")
        try:
            arn = _resolve_layer_arn(manifest, region, arch)
            lines.append(f"- **Layer ARN**: `{arn}`")
        except RendererError as e:
            lines.append(f"- **Layer ARN**: ERROR — {e}")
        lines.append("")
    return "\n".join(lines)


def _render_layers(spec: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = ["# Layer Attachment Plan\n"]
    lines.append(f"Publisher AWS account: `{LAMBDA_LAYER_PUBLISHER}`\n")
    for tgt in spec.get("targets", []):
        fn = tgt["function_name"]
        region = tgt["region"]
        arch = tgt.get("arch", "x86_64")
        try:
            layer_arn = _resolve_layer_arn(manifest, region, arch)
        except RendererError as e:
            lines.append(f"## {fn}: ERROR\n{e}\n")
            continue
        lines.append(f"## {fn}")
        lines.append(f"```bash")
        lines.append(f"aws lambda get-function-configuration \\")
        lines.append(f"  --function-name {fn} \\")
        lines.append(f"  --region {region} \\")
        lines.append(f"  --query 'Layers[].Arn'")
        lines.append(f"```")
        lines.append("")
        lines.append("Layer ARN to attach:")
        lines.append(f"```")
        lines.append(layer_arn)
        lines.append(f"```")
        lines.append("")
    return "\n".join(lines)


def _render_env(spec: dict[str, Any], wrappers: dict[str, str]) -> str:
    realm = spec["realm"]
    backend = spec.get("secret_backend", "secretsmanager")
    local = spec.get("local_collector_enabled", True)
    xray = spec.get("xray_coexistence", False)

    if backend == "secretsmanager":
        token_ref = "{{resolve:secretsmanager:splunk-lambda-access-token:SecretString:::}}"
    else:
        token_ref = "{{resolve:ssm-secure:/splunk/lambda/access-token}}"

    lines = ["# Environment Variables\n"]
    lines.append("The following env vars must be set on each instrumented function.")
    lines.append(f"`SPLUNK_ACCESS_TOKEN` is delivered via `{backend}` resolve reference;\n"
                 "the token value never appears here or in apply commands.\n")

    for tgt in spec.get("targets", []):
        fn = tgt["function_name"]
        runtime = tgt["runtime"]
        handler_type = tgt.get("handler_type", "default")
        try:
            wrapper = _exec_wrapper(wrappers, runtime, handler_type)
        except RendererError as e:
            lines.append(f"## {fn}: ERROR\n{e}\n")
            continue

        otlp_endpoint = f"https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp"

        lines.append(f"## {fn} ({runtime})")
        lines.append("```json")
        env: dict[str, str] = {
            "AWS_LAMBDA_EXEC_WRAPPER": wrapper,
            "SPLUNK_REALM": realm,
            "SPLUNK_ACCESS_TOKEN": token_ref,
            "OTEL_SERVICE_NAME": fn,
        }
        if not local:
            env["SPLUNK_LAMBDA_LOCAL_COLLECTOR_ENABLED"] = "false"
            env["OTEL_EXPORTER_OTLP_ENDPOINT"] = otlp_endpoint
        if xray:
            env["OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION"] = "true"
        # Node.js only: Server-Timing traceparent header for RUM<->APM linking.
        if _runtime_family(runtime) == "nodejs":
            env["SPLUNK_TRACE_RESPONSE_HEADER_ENABLED"] = "true"
        lines.append(json.dumps(env, indent=2))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def _render_validation(spec: dict[str, Any]) -> str:
    realm = spec["realm"]
    lines = ["# Validation Plan\n"]
    lines.append("## Static checks")
    lines.append("```bash")
    lines.append(f"bash skills/{SKILL_NAME}/scripts/validate.sh \\")
    lines.append(f"  --output-dir splunk-observability-aws-lambda-apm-rendered")
    lines.append("```\n")

    lines.append("## Expected span attributes")
    lines.append("After a successful invocation, verify in Splunk Observability APM:")
    lines.append("```")
    lines.append("cloud.platform = aws_lambda")
    lines.append("faas.name = <function-name>")
    lines.append("faas.version = <version>")
    lines.append("cloud.region = <region>")
    lines.append("cloud.account.id = <aws-account-id>")
    lines.append("```\n")

    lines.append("## Live trace probe")
    lines.append("```bash")
    lines.append("aws lambda invoke \\")
    lines.append("  --function-name <function-name> \\")
    lines.append("  --region <region> \\")
    lines.append("  --payload '{}' \\")
    lines.append("  /tmp/response.json")
    lines.append("")
    lines.append(f"# Then check in Splunk Observability APM for realm: {realm}")
    lines.append("```\n")

    lines.append("## Doctor check")
    lines.append("```bash")
    lines.append(f"bash skills/{SKILL_NAME}/scripts/setup.sh --doctor --realm {realm}")
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# IAM.
# ---------------------------------------------------------------------------

def _render_iam_ingest_egress(spec: dict[str, Any]) -> dict[str, Any]:
    realm = spec.get("realm", "us1")
    endpoint = f"https://ingest.{realm}.observability.splunkcloud.com"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "SplunkLambdaIngestEgress",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": "arn:aws:logs:*:*:*",
            },
            {
                "Sid": "SplunkOTLPEgress",
                "Effect": "Allow",
                "Action": "lambda:InvokeFunction",
                "Resource": "*",
                "_comment": (
                    f"When local_collector_enabled=false, the Lambda runtime sends OTLP "
                    f"directly to {endpoint}. Ensure the function's VPC/security-group "
                    "allows outbound HTTPS to that endpoint."
                ),
            },
        ],
    }


# ---------------------------------------------------------------------------
# AWS CLI plan.
# ---------------------------------------------------------------------------

def _render_aws_cli_plan(spec: dict[str, Any], manifest: dict[str, Any], wrappers: dict[str, str]) -> str:
    realm = spec["realm"]
    backend = spec.get("secret_backend", "secretsmanager")
    local = spec.get("local_collector_enabled", True)
    xray = spec.get("xray_coexistence", False)

    # {{resolve:...}} is CloudFormation-only syntax and must NOT appear in AWS
    # CLI commands — the CLI would pass the literal string as the token value.
    # Fetch the token from the secret backend at apply time instead.
    if backend == "secretsmanager":
        token_fetch_lines = [
            'echo "==> Fetching SPLUNK_ACCESS_TOKEN from Secrets Manager..."',
            '_SPLUNK_TOKEN="$(aws secretsmanager get-secret-value \\',
            '  --secret-id splunk-lambda-access-token \\',
            '  --query SecretString \\',
            '  --output text)"',
        ]
    else:
        token_fetch_lines = [
            'echo "==> Fetching SPLUNK_ACCESS_TOKEN from SSM Parameter Store..."',
            '_SPLUNK_TOKEN="$(aws ssm get-parameter \\',
            '  --name /splunk/lambda/access-token \\',
            '  --with-decryption \\',
            '  --query Parameter.Value \\',
            '  --output text)"',
        ]

    lines = ["#!/usr/bin/env bash", "set -euo pipefail", "# AWS CLI apply plan — review before running", ""]
    lines.append(f"# Run scripts/write-splunk-token.sh once to store the token in {backend}.")
    lines.append("# Token is fetched from the secret backend at apply time; it never appears")
    lines.append("# as a literal value in process arguments.")
    lines.append("")
    lines.extend(token_fetch_lines)
    lines.append("")
    lines.append('if [[ -z "${_SPLUNK_TOKEN:-}" ]]; then')
    lines.append('  echo "ERROR: Could not fetch SPLUNK_ACCESS_TOKEN from the secret backend." >&2')
    lines.append('  echo "Run scripts/write-splunk-token.sh first." >&2')
    lines.append('  exit 2')
    lines.append('fi')
    lines.append("")

    for tgt in spec.get("targets", []):
        fn = tgt["function_name"]
        region = tgt["region"]
        runtime = tgt["runtime"]
        arch = tgt.get("arch", "x86_64")
        handler_type = tgt.get("handler_type", "default")

        try:
            layer_arn = _resolve_layer_arn(manifest, region, arch)
            wrapper = _exec_wrapper(wrappers, runtime, handler_type)
        except RendererError as e:
            lines.append(f"# ERROR for {fn}: {e}")
            lines.append("")
            continue

        # Build env var pairs. Token is injected last via shell variable so the
        # value is never visible in ps output or shell history.
        env_var_pairs: list[tuple[str, str]] = [
            ("AWS_LAMBDA_EXEC_WRAPPER", wrapper),
            ("SPLUNK_REALM", realm),
            ("OTEL_SERVICE_NAME", fn),
        ]
        if not local:
            env_var_pairs.append(("SPLUNK_LAMBDA_LOCAL_COLLECTOR_ENABLED", "false"))
            env_var_pairs.append((
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                f"https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp",
            ))
        if xray:
            env_var_pairs.append(("OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION", "true"))
        if _runtime_family(runtime) == "nodejs":
            env_var_pairs.append(("SPLUNK_TRACE_RESPONSE_HEADER_ENABLED", "true"))

        env_parts = [f"{k}={v}" for k, v in env_var_pairs]
        env_parts.append("SPLUNK_ACCESS_TOKEN=${_SPLUNK_TOKEN}")
        env_json = ",".join(env_parts)

        lines.append(f"# --- {fn} ---")
        lines.append(f'echo "==> Updating {fn} in {region}..."')
        lines.append(f"aws lambda update-function-configuration \\")
        lines.append(f"  --function-name {fn} \\")
        lines.append(f"  --region {region} \\")
        lines.append(f"  --layers '{layer_arn}' \\")
        lines.append(f'  --environment "Variables={{{env_json}}}"')
        lines.append("")

    lines.append("unset _SPLUNK_TOKEN")
    lines.append('echo "==> apply-plan: done"')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Terraform.
# ---------------------------------------------------------------------------

def _render_terraform(spec: dict[str, Any], manifest: dict[str, Any], wrappers: dict[str, str]) -> str:
    realm = spec["realm"]
    backend = spec.get("secret_backend", "secretsmanager")
    local = spec.get("local_collector_enabled", True)
    xray = spec.get("xray_coexistence", False)

    lines = [
        "# Terraform — Splunk Lambda APM layer attachment",
        "# Provider: hashicorp/aws ~> 5.0",
        "",
    ]

    if backend == "secretsmanager":
        lines += [
            'data "aws_secretsmanager_secret_version" "splunk_token" {',
            '  secret_id = "splunk-lambda-access-token"',
            "}",
            "",
        ]
        token_ref = 'data.aws_secretsmanager_secret_version.splunk_token.secret_string'
    else:
        lines += [
            'data "aws_ssm_parameter" "splunk_token" {',
            '  name = "/splunk/lambda/access-token"',
            '  with_decryption = true',
            "}",
            "",
        ]
        token_ref = 'data.aws_ssm_parameter.splunk_token.value'

    for tgt in spec.get("targets", []):
        fn = tgt["function_name"]
        region = tgt["region"]
        runtime = tgt["runtime"]
        arch = tgt.get("arch", "x86_64")
        handler_type = tgt.get("handler_type", "default")

        try:
            layer_arn = _resolve_layer_arn(manifest, region, arch)
            wrapper = _exec_wrapper(wrappers, runtime, handler_type)
        except RendererError as e:
            lines.append(f"# ERROR for {fn}: {e}")
            lines.append("")
            continue

        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", fn)
        env_vars: dict[str, str] = {
            "AWS_LAMBDA_EXEC_WRAPPER": wrapper,
            "SPLUNK_REALM": realm,
            "OTEL_SERVICE_NAME": fn,
        }
        if not local:
            env_vars["SPLUNK_LAMBDA_LOCAL_COLLECTOR_ENABLED"] = "false"
            env_vars["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp"
        if xray:
            env_vars["OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION"] = "true"
        if _runtime_family(runtime) == "nodejs":
            env_vars["SPLUNK_TRACE_RESPONSE_HEADER_ENABLED"] = "true"

        env_block_lines = []
        for k, v in env_vars.items():
            env_block_lines.append(f'      {k} = "{v}"')
        env_block_lines.append(f'      SPLUNK_ACCESS_TOKEN = {token_ref}')

        lines += [
            f"# Function: {fn}",
            f'resource "aws_lambda_function" "{safe_name}" {{',
            f'  # Reference your existing function or import it.',
            f'  function_name = "{fn}"',
            f'  layers        = ["{layer_arn}"]',
            f'  environment {{',
            f'    variables = {{',
        ] + env_block_lines + [
            f'    }}',
            f'  }}',
            f'}}',
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CloudFormation.
# ---------------------------------------------------------------------------

def _render_cloudformation(spec: dict[str, Any], manifest: dict[str, Any], wrappers: dict[str, str]) -> str:
    realm = spec["realm"]
    backend = spec.get("secret_backend", "secretsmanager")
    local = spec.get("local_collector_enabled", True)
    xray = spec.get("xray_coexistence", False)

    lines = [
        "# CloudFormation — Splunk Lambda APM layer attachment",
        "# Include these resource snippets in your SAM template or CloudFormation stack.",
        "",
    ]

    for tgt in spec.get("targets", []):
        fn = tgt["function_name"]
        region = tgt["region"]
        runtime = tgt["runtime"]
        arch = tgt.get("arch", "x86_64")
        handler_type = tgt.get("handler_type", "default")

        try:
            layer_arn = _resolve_layer_arn(manifest, region, arch)
            wrapper = _exec_wrapper(wrappers, runtime, handler_type)
        except RendererError as e:
            lines.append(f"# ERROR for {fn}: {e}")
            lines.append("")
            continue

        if backend == "secretsmanager":
            token_ref = "{{resolve:secretsmanager:splunk-lambda-access-token:SecretString:::}}"
        else:
            token_ref = "{{resolve:ssm-secure:/splunk/lambda/access-token}}"

        env_vars: dict[str, str] = {
            "AWS_LAMBDA_EXEC_WRAPPER": wrapper,
            "SPLUNK_REALM": realm,
            "SPLUNK_ACCESS_TOKEN": token_ref,
            "OTEL_SERVICE_NAME": fn,
        }
        if not local:
            env_vars["SPLUNK_LAMBDA_LOCAL_COLLECTOR_ENABLED"] = "false"
            env_vars["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp"
        if xray:
            env_vars["OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION"] = "true"
        if _runtime_family(runtime) == "nodejs":
            env_vars["SPLUNK_TRACE_RESPONSE_HEADER_ENABLED"] = "true"

        env_yaml_lines = []
        for k, v in env_vars.items():
            env_yaml_lines.append(f"          {k}: {v!r}")

        lines += [
            f"# Function: {fn}",
            f"  # Add to your Resources section:",
            f"  {fn}:",
            f"    Type: AWS::Lambda::Function",
            f"    Properties:",
            f"      # ... other properties ...",
            f"      Layers:",
            f"        - {layer_arn}",
            f"      Environment:",
            f"        Variables:",
        ] + env_yaml_lines + ["", ""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handoff scripts.
# ---------------------------------------------------------------------------

def _render_write_token_sh(spec: dict[str, Any]) -> str:
    backend = spec.get("secret_backend", "secretsmanager")
    if backend == "secretsmanager":
        apply_cmd = (
            'aws secretsmanager create-secret \\\n'
            '  --name splunk-lambda-access-token \\\n'
            '  --secret-string "$(cat "${TOKEN_FILE}")"'
        )
        note = "Secret name: splunk-lambda-access-token"
    else:
        apply_cmd = (
            'aws ssm put-parameter \\\n'
            '  --name /splunk/lambda/access-token \\\n'
            '  --value "$(cat "${TOKEN_FILE}")" \\\n'
            '  --type SecureString \\\n'
            '  --overwrite'
        )
        note = "Parameter name: /splunk/lambda/access-token (SecureString)"
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Write the Splunk Observability Cloud access token to {backend}.
# Run this ONCE before applying Lambda function updates.
# The token value never enters shell history; it is read from TOKEN_FILE.
#
# {note}
#
# Usage:
#   bash scripts/write-splunk-token.sh

: "${{TOKEN_FILE:?Set TOKEN_FILE to a chmod-600 file containing the Splunk O11y access token}}"

if [[ ! -f "${{TOKEN_FILE}}" ]]; then
  echo "ERROR: TOKEN_FILE (${{TOKEN_FILE}}) does not exist." >&2
  exit 2
fi

OCTAL=$(python3 -c "import os, stat, sys; print(format(stat.S_IMODE(os.stat(sys.argv[1]).st_mode), '03o'))" "${{TOKEN_FILE}}")
if [[ "${{OCTAL}}" != "600" ]]; then
  echo "ERROR: TOKEN_FILE has loose permissions (${{OCTAL}}); chmod 600 ${{TOKEN_FILE}}" >&2
  exit 2
fi

echo "==> Writing token to {backend}..."
{apply_cmd}
echo "==> Done. Delete ${{TOKEN_FILE}} after confirming the secret is stored."
"""


def _render_handoff_sh(spec: dict[str, Any]) -> str:
    h = spec.get("handoffs", {})
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", "# Cross-skill handoffs", ""]
    wrote_any = False
    if h.get("cloudwatch_metrics"):
        lines.append("# CloudWatch metrics for Lambda namespace")
        lines.append("bash skills/splunk-observability-aws-integration/scripts/setup.sh --render")
        lines.append("")
        wrote_any = True
    if h.get("dashboards"):
        lines.append("# Lambda APM dashboards")
        lines.append("bash skills/splunk-observability-dashboard-builder/scripts/setup.sh --render-lambda-apm-dashboards")
        lines.append("")
        wrote_any = True
    if h.get("detectors"):
        lines.append("# Lambda APM detectors (cold start / error / latency)")
        lines.append("bash skills/splunk-observability-native-ops/scripts/setup.sh --apply autodetect-lambda")
        lines.append("")
        wrote_any = True
    if h.get("logs"):
        lines.append("# Lambda log ingestion via Splunk Connect for OTLP")
        lines.append("bash skills/splunk-connect-for-otlp-setup/scripts/setup.sh --render")
        lines.append("")
        wrote_any = True
    if h.get("gateway_otel_collector"):
        lines.append("# Gateway OTel Collector (send Lambda OTLP to a collector instead of direct ingest)")
        lines.append("# Set local_collector_enabled: false in your spec and point OTEL_EXPORTER_OTLP_ENDPOINT")
        lines.append("# at your collector's OTLP HTTP receiver (default port 4318).")
        lines.append("bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh --render-linux")
        lines.append("")
        wrote_any = True
    if not wrote_any:
        lines.append("echo 'No handoffs requested in spec.'")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SAM renderer.
# ---------------------------------------------------------------------------

def _render_sam(spec: dict[str, Any], manifest: dict[str, Any], metrics_manifest: dict[str, Any], wrappers: dict[str, str]) -> str:
    realm = spec["realm"]
    backend = spec.get("secret_backend", "secretsmanager")
    local = spec.get("local_collector_enabled", True)
    xray = spec.get("xray_coexistence", False)
    use_metrics = spec.get("metrics_extension", False)

    if backend == "secretsmanager":
        token_ref = "{{resolve:secretsmanager:splunk-lambda-access-token:SecretString:::}}"
    else:
        token_ref = "{{resolve:ssm-secure:/splunk/lambda/access-token}}"

    lines = [
        "# AWS SAM template snippet — Splunk Lambda APM layer attachment",
        "# Add the Resources entries below to your SAM template.yaml.",
        "# Transform: AWS::Serverless-2016-10-31 must be at the top of your template.",
        "",
        "Resources:",
    ]

    for tgt in spec.get("targets", []):
        fn = tgt["function_name"]
        region = tgt["region"]
        runtime = tgt["runtime"]
        arch = tgt.get("arch", "x86_64")
        handler_type = tgt.get("handler_type", "default")
        pkg_type = tgt.get("package_type", "zip")
        exec_modes = tgt.get("execution_modes", {})
        prov_concurrency = exec_modes.get("provisioned_concurrency", 0) if exec_modes else 0
        snapstart = exec_modes.get("snapstart", False) if exec_modes else False

        if pkg_type == "image":
            lines.append(f"  # {fn}: container-image function — see container-image/Dockerfile.{runtime.split('.')[0].replace('nodejs', 'node')} for instrumentation snippet.")
            lines.append(f"  # AWS_LAMBDA_EXEC_WRAPPER is NOT honored for container Lambdas; instrument programmatically.")
            lines.append("")
            continue

        try:
            layer_arn = _resolve_layer_arn(manifest, region, arch)
            wrapper = _exec_wrapper(wrappers, runtime, handler_type)
        except RendererError as e:
            lines.append(f"  # ERROR for {fn}: {e}")
            lines.append("")
            continue

        layer_arns = [f'"{layer_arn}"']
        if use_metrics:
            metrics_arn = _resolve_metrics_layer_arn(metrics_manifest, region, arch)
            if metrics_arn:
                layer_arns.append(f'"{metrics_arn}"')

        env_vars: dict[str, str] = {
            "AWS_LAMBDA_EXEC_WRAPPER": wrapper,
            "SPLUNK_REALM": realm,
            "SPLUNK_ACCESS_TOKEN": token_ref,
            "OTEL_SERVICE_NAME": fn,
        }
        if not local:
            env_vars["SPLUNK_LAMBDA_LOCAL_COLLECTOR_ENABLED"] = "false"
            env_vars["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp"
        if xray:
            env_vars["OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION"] = "true"
        if _runtime_family(runtime) == "nodejs":
            env_vars["SPLUNK_TRACE_RESPONSE_HEADER_ENABLED"] = "true"

        safe_name = re.sub(r"[^a-zA-Z0-9]", "", fn.title().replace("-", "").replace("_", ""))

        env_lines = [f"          {k}: {repr(v)}" for k, v in env_vars.items()]

        arch_sam = "arm64" if arch == "arm64" else "x86_64"

        resource_lines = [
            f"  {safe_name}:",
            f"    Type: AWS::Serverless::Function",
            f"    Properties:",
            f"      FunctionName: {fn}",
            f"      Runtime: {runtime}",
            f"      Architectures:",
            f"        - {arch_sam}",
            f"      Layers:",
        ]
        for la in layer_arns:
            resource_lines.append(f"        - {la}")
        resource_lines += [
            f"      Environment:",
            f"        Variables:",
        ] + env_lines

        if snapstart and _runtime_family(runtime) == "java":
            resource_lines += [
                f"      SnapStart:",
                f"        ApplyOn: PublishedVersions",
                f"      # WARNING: Do NOT combine SnapStart with OTEL_JAVA_AGENT_FAST_STARTUP_ENABLED=true",
            ]
        elif snapstart:
            resource_lines.append(f"      # SnapStart is only available for Java runtimes; ignored for {runtime}.")

        if prov_concurrency and int(prov_concurrency) > 0:
            resource_lines += [
                f"      AutoPublishAlias: live",
                f"      ProvisionedConcurrencyConfig:",
                f"        ProvisionedConcurrentExecutions: {int(prov_concurrency)}",
            ]

        lines += resource_lines + [""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CDK renderer (TypeScript + Python snippets).
# ---------------------------------------------------------------------------

def _render_cdk(spec: dict[str, Any], manifest: dict[str, Any], metrics_manifest: dict[str, Any], wrappers: dict[str, str]) -> tuple[str, str]:
    realm = spec["realm"]
    backend = spec.get("secret_backend", "secretsmanager")
    local = spec.get("local_collector_enabled", True)
    xray = spec.get("xray_coexistence", False)
    use_metrics = spec.get("metrics_extension", False)

    ts_lines = [
        "// CDK TypeScript — Splunk Lambda APM layer attachment snippet",
        "// Add to your CDK Stack. Replace placeholder values as needed.",
        "import * as cdk from 'aws-cdk-lib';",
        "import * as lambda from 'aws-cdk-lib/aws-lambda';",
        "import { Construct } from 'constructs';",
        "",
        "export class SplunkLambdaApmStack extends cdk.Stack {",
        "  constructor(scope: Construct, id: string, props?: cdk.StackProps) {",
        "    super(scope, id, props);",
        "",
    ]
    py_lines = [
        "# CDK Python — Splunk Lambda APM layer attachment snippet",
        "from aws_cdk import Stack, aws_lambda as _lambda",
        "from constructs import Construct",
        "",
        "class SplunkLambdaApmStack(Stack):",
        "    def __init__(self, scope: Construct, id: str, **kwargs):",
        "        super().__init__(scope, id, **kwargs)",
        "",
    ]

    for tgt in spec.get("targets", []):
        fn = tgt["function_name"]
        region = tgt["region"]
        runtime = tgt["runtime"]
        arch = tgt.get("arch", "x86_64")
        handler_type = tgt.get("handler_type", "default")
        pkg_type = tgt.get("package_type", "zip")

        if pkg_type == "image":
            ts_lines.append(f"    // {fn}: container-image — instrument programmatically; no layer ARN needed.")
            py_lines.append(f"        # {fn}: container-image — instrument programmatically; no layer ARN needed.")
            continue

        try:
            layer_arn = _resolve_layer_arn(manifest, region, arch)
            wrapper = _exec_wrapper(wrappers, runtime, handler_type)
        except RendererError as e:
            ts_lines.append(f"    // ERROR for {fn}: {e}")
            py_lines.append(f"        # ERROR for {fn}: {e}")
            continue

        metrics_arn = _resolve_metrics_layer_arn(metrics_manifest, region, arch) if use_metrics else None

        safe_ts = re.sub(r"[^a-zA-Z0-9]", "_", fn)
        safe_py = re.sub(r"[^a-zA-Z0-9]", "_", fn)

        env_dict_ts = {
            "AWS_LAMBDA_EXEC_WRAPPER": wrapper,
            "SPLUNK_REALM": realm,
            "OTEL_SERVICE_NAME": fn,
        }
        if not local:
            env_dict_ts["SPLUNK_LAMBDA_LOCAL_COLLECTOR_ENABLED"] = "false"
            env_dict_ts["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp"
        if xray:
            env_dict_ts["OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION"] = "true"
        if _runtime_family(runtime) == "nodejs":
            env_dict_ts["SPLUNK_TRACE_RESPONSE_HEADER_ENABLED"] = "true"

        sm_source = "sm" if backend == "secretsmanager" else "ssm"

        ts_lines += [
            f"    // Function: {fn}",
            f"    const splunkLayer_{safe_ts} = lambda.LayerVersion.fromLayerVersionArn(this, 'SplunkApmLayer{safe_ts}', '{layer_arn}');",
        ]
        if metrics_arn:
            ts_lines.append(f"    const splunkMetricsLayer_{safe_ts} = lambda.LayerVersion.fromLayerVersionArn(this, 'SplunkMetricsLayer{safe_ts}', '{metrics_arn}');")
        ts_layers = f"splunkLayer_{safe_ts}" + (f", splunkMetricsLayer_{safe_ts}" if metrics_arn else "")
        ts_env = ", ".join(f'"{k}": "{v}"' for k, v in env_dict_ts.items())
        ts_lines += [
            f"    // NOTE: Deliver SPLUNK_ACCESS_TOKEN from {sm_source}, not hardcoded:",
            f"    // fn_{safe_ts}.addEnvironment('SPLUNK_ACCESS_TOKEN', secret.secretValue.unsafeUnwrap());",
            f"    // const fn_{safe_ts} = existing lambda Function reference",
            f"    // fn_{safe_ts}.addLayers({ts_layers});",
        ]
        for k, v in env_dict_ts.items():
            ts_lines.append(f"    // fn_{safe_ts}.addEnvironment('{k}', '{v}');")
        ts_lines.append("")

        py_env = ",\n            ".join(f'"{k}": "{v}"' for k, v in env_dict_ts.items())
        py_lines += [
            f"        # Function: {fn}",
            f"        splunk_layer_{safe_py} = _lambda.LayerVersion.from_layer_version_arn(",
            f"            self, 'SplunkApmLayer{safe_py}', '{layer_arn}')",
        ]
        if metrics_arn:
            py_lines += [
                f"        splunk_metrics_layer_{safe_py} = _lambda.LayerVersion.from_layer_version_arn(",
                f"            self, 'SplunkMetricsLayer{safe_py}', '{metrics_arn}')",
            ]
        py_layers = f"splunk_layer_{safe_py}" + (f", splunk_metrics_layer_{safe_py}" if metrics_arn else "")
        py_lines += [
            f"        # fn_{safe_py}.add_layers({py_layers})",
            f"        # NOTE: Deliver SPLUNK_ACCESS_TOKEN from {sm_source}, not hardcoded.",
        ]
        for k, v in env_dict_ts.items():
            py_lines.append(f"        # fn_{safe_py}.add_environment('{k}', '{v}')")
        py_lines.append("")

    ts_lines += ["  }", "}", ""]
    py_lines.append("")
    return "\n".join(ts_lines), "\n".join(py_lines)


# ---------------------------------------------------------------------------
# SAR advisory.
# ---------------------------------------------------------------------------

def _render_sar_readme() -> str:
    return """# Splunk Lambda APM — SAR Advisory

Splunk does **not** publish a Serverless Application Repository (SAR) application
for the OpenTelemetry Lambda layer. SAR is not a supported distribution channel.

## Use the published layer ARNs instead

The correct way to consume the Splunk OTel Lambda layer is via the baked ARN
snapshot in `references/layer-versions.snapshot.json` (publisher `254067382080`).

Run `--list-layer-arns` to display all published ARNs:

```bash
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh --list-layer-arns
```

Use `--refresh-layer-manifest` to fetch the latest versions from
`signalfx/lambda-layer-versions`.

## If you need SAR-style discoverability

Publish the layer to your own AWS account and create a SAR application pointing
at it. Use `aws lambda get-layer-version-by-arn` to download the layer ZIP from
publisher `254067382080`, then `aws lambda publish-layer-version` to re-publish
in your account.
"""


# ---------------------------------------------------------------------------
# Container-image renderer.
# ---------------------------------------------------------------------------

def _render_container_image(spec: dict[str, Any]) -> dict[str, str]:
    realm = spec["realm"]
    local = spec.get("local_collector_enabled", True)
    xray = spec.get("xray_coexistence", False)

    otlp_ep = f"https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp"
    env_note = "# SPLUNK_ACCESS_TOKEN must be injected at runtime via Secrets Manager / SSM env resolver."

    files: dict[str, str] = {}

    for tgt in spec.get("targets", []):
        fn = tgt["function_name"]
        runtime = tgt["runtime"]
        pkg_type = tgt.get("package_type", "zip")
        exec_modes = tgt.get("execution_modes", {})
        snapstart = exec_modes.get("snapstart", False) if exec_modes else False

        if pkg_type != "image":
            continue

        family = _runtime_family(runtime)

        env_block_lines = [
            f'ENV SPLUNK_REALM="{realm}"',
            f'ENV OTEL_SERVICE_NAME="{fn}"',
            f'{env_note}',
        ]
        if not local:
            env_block_lines.append(f'ENV SPLUNK_LAMBDA_LOCAL_COLLECTOR_ENABLED="false"')
            env_block_lines.append(f'ENV OTEL_EXPORTER_OTLP_ENDPOINT="{otlp_ep}"')
        if xray:
            env_block_lines.append(f'ENV OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION="true"')

        env_block = "\n".join(env_block_lines)

        if family == "python":
            # Extract version like "3.11" from "python3.11"
            py_ver = runtime.replace("python", "")
            content = f"""# Dockerfile for Lambda container image — Python {py_ver} + Splunk OTel
# AWS_LAMBDA_EXEC_WRAPPER is NOT honored in container Lambdas.
# Instrument via the splunk-py-trace entrypoint instead.

FROM public.ecr.aws/lambda/python:{py_ver}

# Install Splunk OTel Python distribution
RUN pip install --no-cache-dir splunk-opentelemetry[all]

{env_block}

# Use splunk-py-trace as the entrypoint wrapper
CMD ["splunk-py-trace", "lambda_function.handler"]
"""
        elif family == "nodejs":
            node_ver = runtime.replace("nodejs", "").replace(".x", "")
            content = f"""# Dockerfile for Lambda container image — Node.js {node_ver} + Splunk OTel
# AWS_LAMBDA_EXEC_WRAPPER is NOT honored in container Lambdas.
# Instrument via --require at runtime instead.

FROM public.ecr.aws/lambda/nodejs:{node_ver}

# Install Splunk OTel Node.js distribution
RUN npm install --no-save @splunk/otel

{env_block}
ENV NODE_OPTIONS="--require @splunk/otel/instrument"

CMD ["index.handler"]
"""
        elif family == "java":
            content = f"""# Dockerfile for Lambda container image — Java + Splunk OTel
# AWS_LAMBDA_EXEC_WRAPPER is NOT honored in container Lambdas.
# Instrument via JAVA_TOOL_OPTIONS javaagent instead.

FROM public.ecr.aws/lambda/java:21

# Download the Splunk Java OTel agent
ADD https://github.com/signalfx/splunk-otel-java/releases/latest/download/splunk-otel-javaagent.jar /var/task/splunk-otel-javaagent.jar

{env_block}
ENV JAVA_TOOL_OPTIONS="-javaagent:/var/task/splunk-otel-javaagent.jar"
"""
            if snapstart:
                content += """
# SnapStart note: Do NOT set OTEL_JAVA_AGENT_FAST_STARTUP_ENABLED=true when SnapStart is enabled.
# ENV JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS} -Dotel.javaagent.fast.startup.enabled=false"
"""
            content += """
CMD ["com.example.Handler::handleRequest"]
"""
        else:
            content = f"# No container-image Dockerfile for unsupported runtime '{runtime}'.\n"

        key = f"Dockerfile.{runtime}"
        files[key] = content

    return files


# ---------------------------------------------------------------------------
# Execution-mode validation.
# ---------------------------------------------------------------------------

def _validate_execution_modes(spec: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for tgt in spec.get("targets", []):
        fn = tgt.get("function_name", "?")
        runtime = tgt.get("runtime", "")
        exec_modes = tgt.get("execution_modes") or {}
        if exec_modes.get("lambda_at_edge"):
            raise RendererError(
                f"targets[{fn}] execution_modes.lambda_at_edge=true: Lambda@Edge is not supported. "
                "The Splunk OTel Lambda layer cannot be attached to Lambda@Edge functions. "
                "Remove this target or set lambda_at_edge: false."
            )
        if exec_modes.get("snapstart") and _runtime_family(runtime) != "java":
            warnings.append(
                f"WARN: targets[{fn}] SnapStart is only available for Java runtimes; "
                f"ignored for {runtime}."
            )
        if exec_modes.get("snapstart") and _runtime_family(runtime) == "java":
            warnings.append(
                f"WARN: targets[{fn}] SnapStart + OTel Java agent: "
                "Do NOT set OTEL_JAVA_AGENT_FAST_STARTUP_ENABLED=true when SnapStart is active."
            )
    return warnings


# ---------------------------------------------------------------------------
# Top-level render.
# ---------------------------------------------------------------------------

def render(spec: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    metrics_manifest = _load_metrics_manifest()
    wrappers = _load_wrappers()
    ts = datetime.now(tz=timezone.utc).isoformat()

    # Execution-mode validation (raises on Lambda@Edge, warns on SnapStart).
    exec_mode_warnings = _validate_execution_modes(spec)
    for w in exec_mode_warnings:
        print(w, file=sys.stderr)

    # Numbered plan files.
    plan_contents = {
        "01-overview.md": _render_overview(spec),
        "02-targets.md": _render_targets(spec, manifest),
        "03-layers.md": _render_layers(spec, manifest),
        "04-env.md": _render_env(spec, wrappers),
        "05-validation.md": _render_validation(spec),
    }
    for fname, content in plan_contents.items():
        (output_dir / fname).write_text(content, encoding="utf-8")

    # README.
    n = len(spec.get("targets", []))
    (output_dir / "README.md").write_text(
        f"# AWS Lambda APM — rendered {ts}\n\n"
        f"Realm: {spec['realm']} | Functions: {n}\n\n"
        "## Quick reference\n\n"
        "| File | Purpose |\n|------|--------|\n"
        "| `01-overview.md` | Plan overview and apply command |\n"
        "| `02-targets.md` | Per-function target list |\n"
        "| `03-layers.md` | Layer ARN attachment plan |\n"
        "| `04-env.md` | Environment variable plan |\n"
        "| `05-validation.md` | Validation and smoke test |\n"
        "| `aws-cli/apply-plan.sh` | AWS CLI commands (review before running) |\n"
        "| `terraform/main.tf` | Terraform resource snippets |\n"
        "| `cloudformation/snippets.yaml` | CloudFormation / SAM snippets |\n"
        "| `sam/template.yaml` | AWS SAM template snippet |\n"
        "| `cdk/lambda-apm-stack.ts` | CDK TypeScript snippet |\n"
        "| `cdk/lambda_apm_stack.py` | CDK Python snippet |\n"
        "| `sar/README.md` | SAR advisory (Splunk does not publish SAR) |\n"
        "| `container-image/` | Dockerfile snippets for image-package targets |\n"
        "| `scripts/write-splunk-token.sh` | One-time token write to secret backend |\n"
        "| `coverage-report.json` | Per-section coverage status |\n",
        encoding="utf-8",
    )

    # IAM.
    iam_dir = output_dir / "iam"
    iam_dir.mkdir(exist_ok=True)
    local = spec.get("local_collector_enabled", True)
    if not local:
        iam_policy = _render_iam_ingest_egress(spec)
        (iam_dir / "iam-ingest-egress.json").write_text(
            json.dumps(iam_policy, indent=2), encoding="utf-8"
        )
    else:
        (iam_dir / "iam-not-required.md").write_text(
            "# IAM\n\nNo additional IAM policy is required when `local_collector_enabled=true`.\n"
            "The Lambda Extension (local collector) handles OTLP forwarding internally.\n",
            encoding="utf-8",
        )

    # AWS CLI plan.
    aws_cli_dir = output_dir / "aws-cli"
    aws_cli_dir.mkdir(exist_ok=True)
    cli_plan = _render_aws_cli_plan(spec, manifest, wrappers)
    plan_path = aws_cli_dir / "apply-plan.sh"
    plan_path.write_text(cli_plan, encoding="utf-8")
    plan_path.chmod(0o755)

    # Terraform.
    tf_dir = output_dir / "terraform"
    tf_dir.mkdir(exist_ok=True)
    (tf_dir / "main.tf").write_text(_render_terraform(spec, manifest, wrappers), encoding="utf-8")

    # CloudFormation.
    cfn_dir = output_dir / "cloudformation"
    cfn_dir.mkdir(exist_ok=True)
    (cfn_dir / "snippets.yaml").write_text(_render_cloudformation(spec, manifest, wrappers), encoding="utf-8")

    # SAM.
    sam_dir = output_dir / "sam"
    sam_dir.mkdir(exist_ok=True)
    (sam_dir / "template.yaml").write_text(_render_sam(spec, manifest, metrics_manifest, wrappers), encoding="utf-8")

    # CDK.
    cdk_dir = output_dir / "cdk"
    cdk_dir.mkdir(exist_ok=True)
    cdk_ts, cdk_py = _render_cdk(spec, manifest, metrics_manifest, wrappers)
    (cdk_dir / "lambda-apm-stack.ts").write_text(cdk_ts, encoding="utf-8")
    (cdk_dir / "lambda_apm_stack.py").write_text(cdk_py, encoding="utf-8")

    # SAR advisory.
    sar_dir = output_dir / "sar"
    sar_dir.mkdir(exist_ok=True)
    (sar_dir / "README.md").write_text(_render_sar_readme(), encoding="utf-8")

    # Container-image Dockerfiles.
    has_image_targets = any(t.get("package_type") == "image" for t in spec.get("targets", []))
    if has_image_targets:
        ci_dir = output_dir / "container-image"
        ci_dir.mkdir(exist_ok=True)
        for fname, content in _render_container_image(spec).items():
            (ci_dir / fname).write_text(content, encoding="utf-8")

    # Scripts.
    scripts_dir = output_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    write_token = scripts_dir / "write-splunk-token.sh"
    write_token.write_text(_render_write_token_sh(spec), encoding="utf-8")
    write_token.chmod(0o755)

    handoff = scripts_dir / "handoffs.sh"
    handoff.write_text(_render_handoff_sh(spec), encoding="utf-8")
    handoff.chmod(0o755)

    # Coverage report.
    cov = coverage_for(spec)
    by_status: dict[str, list[str]] = {}
    for k, v in cov.items():
        by_status.setdefault(v, []).append(k)
    coverage_obj = {
        "rendered_at": ts,
        "realm": spec["realm"],
        "total": len(cov),
        "by_status": {s: len(keys) for s, keys in by_status.items()},
        "detail": cov,
    }
    (output_dir / "coverage-report.json").write_text(
        json.dumps(coverage_obj, indent=2), encoding="utf-8"
    )

    return {"coverage_summary": coverage_obj}


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Render Splunk AWS Lambda APM skill assets."
    )
    p.add_argument("--spec", default=str(Path(__file__).resolve().parents[1] / "template.example"))
    p.add_argument("--output-dir", default=str(PROJECT_ROOT / "splunk-observability-aws-lambda-apm-rendered"))
    p.add_argument("--realm", default="")
    p.add_argument("--accept-beta", action="store_true")
    p.add_argument("--json", action="store_true", dest="json_output")
    p.add_argument("--list-runtimes", action="store_true")
    p.add_argument("--list-layer-arns", action="store_true")
    return p


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    manifest = _load_manifest()

    if args.list_runtimes:
        rt = manifest.get("supported_runtimes", {})
        print("Supported runtimes:")
        for family, versions in rt.items():
            if family != "unsupported":
                print(f"  {family}: {', '.join(versions)}")
        print("\nUnsupported (no published layers):")
        for r in rt.get("unsupported", []):
            print(f"  {r}")
        return

    if args.list_layer_arns:
        out: dict[str, Any] = {}
        for arch in ("x86_64", "arm64"):
            out[arch] = {
                region: entry["arn"]
                for region, entry in manifest.get(arch, {}).items()
            }
        if args.json_output:
            print(json.dumps(out, indent=2))
        else:
            for arch, regions in out.items():
                print(f"\n{arch}:")
                for region, arn in sorted(regions.items()):
                    print(f"  {region}: {arn}")
        return

    try:
        text = Path(args.spec).read_text(encoding="utf-8")
        raw = load_yaml_or_json(text, source=args.spec)
    except (YamlCompatError, OSError) as exc:
        print(f"ERROR loading spec: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.realm:
        raw["realm"] = args.realm
    if args.accept_beta:
        raw["accept_beta"] = True

    try:
        spec = validate_spec(raw)
    except RendererError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    try:
        result = render(spec, output_dir)
    except RendererError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        cov = result["coverage_summary"]
        print(f"Rendered {cov['total']} sections to {output_dir}")
        for status, count in sorted(cov["by_status"].items()):
            print(f"  {status}: {count}")


if __name__ == "__main__":
    main()

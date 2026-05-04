"""Render Splunk Observability Kubernetes auto-instrumentation overlay assets.

This renderer is intentionally overlay-only. It never installs the base
splunk-otel-collector chart; it emits Instrumentation CRs, annotation patches,
OBI manifests, runbooks, and gated helper scripts that sit on top of a collector
deployment produced by splunk-observability-otel-collector-setup.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SKILL_NAME = "splunk-observability-k8s-auto-instrumentation-setup"
API_VERSION = f"{SKILL_NAME}/v1"
DEFAULT_OUTPUT_DIR = "splunk-observability-k8s-auto-instrumentation-rendered"
DEFAULT_ENDPOINT = "http://$(SPLUNK_OTEL_AGENT):4317"
DEFAULT_METRICS_ENDPOINT = "http://$(SPLUNK_OTEL_AGENT):9943/v2/datapoint"
DEFAULT_BACKUP_CONFIGMAP = "splunk-otel-auto-instrumentation-annotations-backup"
SUPPORTED_LANGUAGES = {
    "java",
    "nodejs",
    "python",
    "dotnet",
    "go",
    "apache-httpd",
    "nginx",
    "sdk",
}
LANGUAGE_SPEC_KEYS = {
    "java": "java",
    "nodejs": "nodejs",
    "python": "python",
    "dotnet": "dotnet",
    "go": "go",
    "apache-httpd": "apacheHttpd",
    "nginx": "nginx",
}
LANGUAGE_IMAGE_DEFAULTS = {
    "java": "ghcr.io/signalfx/splunk-otel-java:latest",
    "nodejs": "ghcr.io/signalfx/splunk-otel-js:latest",
    "python": "ghcr.io/signalfx/splunk-otel-python:latest",
    "dotnet": "ghcr.io/signalfx/splunk-otel-dotnet:latest",
    "go": "ghcr.io/signalfx/splunk-otel-go:latest",
    "apache-httpd": "ghcr.io/signalfx/splunk-otel-apache-httpd:latest",
    "nginx": "ghcr.io/signalfx/splunk-otel-nginx:latest",
}
AUTO_CLUSTER_DISTRIBUTIONS = {"eks", "eks/auto-mode", "gke", "gke/autopilot", "openshift"}
DIRECT_SECRET_FLAGS = {
    "--access-token",
    "--token",
    "--bearer-token",
    "--api-token",
    "--o11y-token",
    "--sf-token",
    "--hec-token",
    "--platform-hec-token",
    "--org-token",
    "--api-key",
}
TOKEN_SHAPED_RE = re.compile(
    r"(?i)(access[_-]?token|api[_-]?token|bearer[_-]?token|hec[_-]?token|sf[_-]?token)"
    r"\s*[:=]\s*[A-Za-z0-9._-]{20,}"
)


class SpecError(ValueError):
    """Raised for invalid render input."""


def _load_yaml_module():
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
        raise SpecError(
            "PyYAML is required. Install with 'python3 -m pip install -r requirements-agent.txt'."
        ) from exc
    return yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--spec", default="")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--discover-workloads", action="store_true")
    parser.add_argument("--mode", default="render")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--gitops-mode", action="store_true")

    parser.add_argument("--realm", default="")
    parser.add_argument("--cluster-name", default="")
    parser.add_argument("--deployment-environment", default="")
    parser.add_argument("--namespace", default="")
    parser.add_argument("--instrumentation-cr-name", default="")
    parser.add_argument("--distribution", default="")
    parser.add_argument("--base-release", default="")
    parser.add_argument("--base-namespace", default="")

    parser.add_argument("--languages", default="")
    parser.add_argument("--multi-instrumentation", action="store_true")
    parser.add_argument("--profiling-enabled", action="store_true")
    parser.add_argument("--profiling-memory-enabled", action="store_true")
    parser.add_argument("--profiler-call-stack-interval-ms", default="")
    parser.add_argument("--runtime-metrics-enabled", action="store_true")
    parser.add_argument("--propagators", default="")
    parser.add_argument("--sampler", default="")
    parser.add_argument("--sampler-argument", default="")
    parser.add_argument("--agent-endpoint", default="")
    parser.add_argument("--gateway-endpoint", default="")
    parser.add_argument("--per-language-endpoint", action="append", default=[])
    parser.add_argument("--use-labels-for-resource-attributes", action="store_true")
    parser.add_argument("--extra-resource-attr", action="append", default=[])
    parser.add_argument("--extra-env", action="append", default=[])
    parser.add_argument("--resource-limits", action="append", default=[])
    parser.add_argument("--image-pull-secret", default="")
    for lang in ("java", "nodejs", "python", "dotnet", "go", "apache-httpd", "nginx"):
        parser.add_argument(f"--{lang}-image", dest=f"{lang.replace('-', '_')}_image", default="")

    parser.add_argument("--operator-watch-namespaces", default="")
    parser.add_argument("--webhook-cert-mode", default="")
    parser.add_argument("--installation-job-enabled", action="store_true")

    parser.add_argument("--enable-obi", action="store_true")
    parser.add_argument("--obi-namespaces", default="")
    parser.add_argument("--obi-exclude-namespaces", default="")
    parser.add_argument("--obi-version", default="")
    parser.add_argument("--accept-obi-privileged", action="store_true")
    parser.add_argument("--render-openshift-scc", default="")

    parser.add_argument("--annotate-namespace", action="append", default=[])
    parser.add_argument("--annotate-workload", action="append", default=[])
    parser.add_argument("--inventory-file", default="")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--target-all", action="store_true")
    parser.add_argument("--purge-crs", action="store_true")
    parser.add_argument("--detect-vendors", action="store_true")
    parser.add_argument("--exclude-vendor", default="")
    parser.add_argument("--backup-configmap", default="")
    parser.add_argument("--restore-from-backup", action="store_true")
    parser.add_argument("--purge-backup", action="store_true")
    parser.add_argument("--kube-context", default="")
    parser.add_argument("--accept-auto-instrumentation", action="store_true")

    return parser.parse_args()


def split_csv(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(split_csv(item))
        return result
    return [part.strip() for part in str(value).split(",") if part.strip()]


def boolish(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize_language(value: str) -> str:
    lang = value.strip().lower().replace("_", "-")
    aliases = {"node": "nodejs", "javascript": "nodejs", "js": "nodejs", ".net": "dotnet"}
    lang = aliases.get(lang, lang)
    if lang not in SUPPORTED_LANGUAGES:
        raise SpecError(f"Unsupported language {value!r}. Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}")
    return lang


def normalize_kind(value: str) -> str:
    kind = value.strip()
    aliases = {
        "deploy": "Deployment",
        "deployment": "Deployment",
        "deployments": "Deployment",
        "statefulset": "StatefulSet",
        "statefulsets": "StatefulSet",
        "sts": "StatefulSet",
        "daemonset": "DaemonSet",
        "daemonsets": "DaemonSet",
        "ds": "DaemonSet",
    }
    normalized = aliases.get(kind.lower(), kind)
    if normalized not in {"Deployment", "StatefulSet", "DaemonSet"}:
        raise SpecError(f"Unsupported workload kind {value!r}; expected Deployment, StatefulSet, or DaemonSet.")
    return normalized


def load_spec(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"api_version": API_VERSION}
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            yaml = _load_yaml_module()
            data = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001 - rewrap parser details
        raise SpecError(f"Failed to parse spec {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"Spec {path} did not parse to a mapping.")
    api_version = data.get("api_version") or data.get("apiVersion")
    if api_version != API_VERSION:
        raise SpecError(f"Spec api_version must be {API_VERSION!r}; got {api_version!r}.")
    if TOKEN_SHAPED_RE.search(text):
        raise SpecError("Spec appears to contain an inline token-shaped value; use file-based credentials only.")
    return data


def read_yaml_or_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    yaml = _load_yaml_module()
    return yaml.safe_load(text)


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def dump_yaml(payload: Any) -> str:
    yaml = _load_yaml_module()
    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)


def dump_yaml_all(docs: list[dict[str, Any]]) -> str:
    yaml = _load_yaml_module()
    if not docs:
        return "# No resources rendered for this selection.\n"
    return yaml.safe_dump_all(docs, sort_keys=False, default_flow_style=False)


def write_yaml(path: Path, payload: Any) -> None:
    write_text(path, dump_yaml(payload))


def write_yaml_all(path: Path, docs: list[dict[str, Any]]) -> None:
    write_text(path, dump_yaml_all(docs))


def first_value(mapping: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return default


def parse_key_value(value: str, *, label: str) -> tuple[str, str]:
    if "=" not in value:
        raise SpecError(f"{label} must be KEY=VALUE; got {value!r}.")
    key, val = value.split("=", 1)
    key = key.strip()
    if not key:
        raise SpecError(f"{label} has an empty key: {value!r}.")
    return key, val.strip()


def parse_mapping_flags(values: list[str], *, label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        key, val = parse_key_value(item, label=label)
        result[key] = val
    return result


def parse_nested_lang_env(values: list[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for item in values:
        lang, rest = parse_key_value(item, label="--extra-env")
        lang = normalize_language(lang)
        key, val = parse_key_value(rest, label="--extra-env value")
        result.setdefault(lang, {})[key] = val
    return result


def parse_resource_limits(values: list[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for item in values:
        lang, rest = parse_key_value(item, label="--resource-limits")
        lang = normalize_language(lang)
        limits: dict[str, str] = {}
        for part in split_csv(rest):
            key, val = parse_key_value(part, label="--resource-limits value")
            limits[key] = val
        result[lang] = limits
    return result


def parse_namespace_annotation(value: str) -> dict[str, Any]:
    namespace, langs = parse_key_value(value, label="--annotate-namespace")
    return {"namespace": namespace, "languages": [normalize_language(lang) for lang in split_csv(langs)]}


def split_workload_options(raw: str) -> list[str]:
    tokens = [part.strip() for part in raw.split(",") if part.strip()]
    if not tokens:
        return tokens
    result = [tokens[0]]
    option_keys = {"container-names", "dotnet-runtime", "go-target-exe", "cr", "disable", "language"}
    for token in tokens[1:]:
        key = token.split("=", 1)[0].strip()
        if "=" in token and key in option_keys:
            result.append(token)
        else:
            result[-1] = f"{result[-1]},{token}"
    return result


def parse_workload_annotation(value: str) -> dict[str, Any]:
    target, raw_options = parse_key_value(value, label="--annotate-workload")
    parts = target.split("/")
    if len(parts) != 3:
        raise SpecError(
            f"--annotate-workload target must be Kind/namespace/name=language; got {value!r}."
        )
    kind, namespace, name = parts
    tokens = split_workload_options(raw_options)
    if not tokens:
        raise SpecError(f"--annotate-workload missing language: {value!r}.")
    workload: dict[str, Any] = {
        "kind": normalize_kind(kind),
        "namespace": namespace,
        "name": name,
        "language": normalize_language(tokens[0]),
        "container_names": "",
        "dotnet_runtime": "",
        "go_target_exe": "",
        "cr": "",
        "disable": False,
    }
    for token in tokens[1:]:
        key, val = parse_key_value(token, label="--annotate-workload option")
        if key == "container-names":
            workload["container_names"] = val
        elif key == "dotnet-runtime":
            workload["dotnet_runtime"] = val
        elif key == "go-target-exe":
            workload["go_target_exe"] = val
        elif key == "cr":
            workload["cr"] = val
        elif key == "disable":
            workload["disable"] = boolish(val)
        else:
            raise SpecError(f"Unsupported --annotate-workload option {key!r}.")
    return workload


def parse_inventory_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SpecError(f"Inventory file not found: {path}")
    data = read_yaml_or_json(path)
    if isinstance(data, dict):
        rows = data.get("workloads") or data.get("workload_annotations") or []
    elif isinstance(data, list):
        rows = data
    else:
        raise SpecError(f"Inventory file {path} must contain a list or a workloads mapping.")
    workloads: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        language = row.get("language") or row.get("languages") or ""
        if isinstance(language, list):
            language = language[0] if language else ""
        if not language or str(language).lower() in {"", "none", "skip"}:
            continue
        workloads.append(
            {
                "kind": normalize_kind(str(row.get("kind", "Deployment"))),
                "namespace": str(row.get("namespace", "default")),
                "name": str(row.get("name")),
                "language": normalize_language(str(language)),
                "container_names": row.get("container_names") or row.get("containerNames") or "",
                "dotnet_runtime": row.get("dotnet_runtime") or row.get("dotnetRuntime") or "",
                "go_target_exe": row.get("go_target_exe") or row.get("goTargetExe") or "",
                "cr": row.get("cr") or "",
                "disable": boolish(row.get("disable"), False),
            }
        )
    return workloads


def normalize_namespace_annotations(spec_value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(spec_value, dict):
        for namespace, languages in spec_value.items():
            rows.append(
                {
                    "namespace": str(namespace),
                    "languages": [normalize_language(lang) for lang in split_csv(languages)],
                }
            )
    elif isinstance(spec_value, list):
        for row in spec_value:
            if isinstance(row, dict):
                rows.append(
                    {
                        "namespace": str(row.get("namespace")),
                        "languages": [
                            normalize_language(lang)
                            for lang in split_csv(row.get("languages") or row.get("language"))
                        ],
                    }
                )
    return [row for row in rows if row.get("namespace") and row.get("languages")]


def normalize_workload_rows(rows: Any) -> list[dict[str, Any]]:
    workloads: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return workloads
    for row in rows:
        if not isinstance(row, dict):
            continue
        language = row.get("language") or row.get("languages") or ""
        if isinstance(language, list):
            language = language[0] if language else ""
        if not language:
            continue
        workloads.append(
            {
                "kind": normalize_kind(str(row.get("kind", "Deployment"))),
                "namespace": str(row.get("namespace", "default")),
                "name": str(row.get("name")),
                "language": normalize_language(str(language)),
                "container_names": row.get("container_names") or row.get("containerNames") or "",
                "dotnet_runtime": row.get("dotnet_runtime") or row.get("dotnetRuntime") or "",
                "go_target_exe": row.get("go_target_exe") or row.get("goTargetExe") or "",
                "cr": row.get("cr") or "",
                "disable": boolish(row.get("disable"), False),
                "node_selector": row.get("node_selector") or row.get("nodeSelector") or {},
                "metadata": row.get("metadata") or {},
            }
        )
    return workloads


def build_config(args: argparse.Namespace, spec: dict[str, Any], spec_path: Path | None) -> dict[str, Any]:
    base = spec.get("base") if isinstance(spec.get("base"), dict) else {}
    operator = spec.get("operator") if isinstance(spec.get("operator"), dict) else {}
    obi_spec = spec.get("obi") if isinstance(spec.get("obi"), dict) else {}
    vendors = spec.get("vendors") if isinstance(spec.get("vendors"), dict) else {}
    handoffs = spec.get("handoffs") if isinstance(spec.get("handoffs"), dict) else {}

    namespace = args.namespace or first_value(spec, "namespace", default="splunk-otel")
    base_namespace = args.base_namespace or first_value(base, "namespace", default=namespace)
    base_release = args.base_release or first_value(base, "release", default="splunk-otel-collector")
    distribution = args.distribution or first_value(spec, "distribution", default="generic")
    gateway_endpoint = args.gateway_endpoint or first_value(spec, "gateway_endpoint", "gatewayEndpoint", default="")
    agent_endpoint = args.agent_endpoint or first_value(spec, "agent_endpoint", "agentEndpoint", default=DEFAULT_ENDPOINT)
    endpoint = gateway_endpoint or agent_endpoint
    per_language_endpoint = dict(first_value(spec, "per_language_endpoint", "perLanguageEndpoint", default={}) or {})
    per_language_endpoint.update(parse_mapping_flags(args.per_language_endpoint, label="--per-language-endpoint"))

    cli_languages = [normalize_language(lang) for lang in split_csv(args.languages)]
    spec_crs = first_value(spec, "instrumentation_crs", "instrumentationCRs", default=[])
    crs: list[dict[str, Any]] = []
    if isinstance(spec_crs, list) and spec_crs:
        for index, row in enumerate(spec_crs):
            if not isinstance(row, dict):
                continue
            cr_languages = cli_languages or [
                normalize_language(lang) for lang in split_csv(row.get("languages") or spec.get("languages") or [])
            ]
            if not cr_languages:
                cr_languages = ["java"]
            crs.append(
                {
                    "name": (
                        args.instrumentation_cr_name
                        if index == 0 and args.instrumentation_cr_name
                        else str(row.get("name") or args.instrumentation_cr_name or "splunk-otel-auto-instrumentation")
                    ),
                    "namespace": str(row.get("namespace") or namespace),
                    "languages": cr_languages,
                    "endpoint": str(row.get("endpoint") or endpoint),
                    "per_language_endpoint": {
                        **dict(row.get("per_language_endpoint") or row.get("perLanguageEndpoint") or {}),
                        **per_language_endpoint,
                    },
                    "propagators": split_csv(args.propagators) or split_csv(row.get("propagators")) or ["tracecontext", "baggage", "b3"],
                    "sampler": {
                        "type": args.sampler
                        or (row.get("sampler") or {}).get("type")
                        or row.get("sampler_type")
                        or "parentbased_always_on",
                        "argument": args.sampler_argument
                        if args.sampler_argument != ""
                        else (row.get("sampler") or {}).get("argument", row.get("sampler_argument", "")),
                    },
                    "profiling_enabled": args.profiling_enabled or boolish(row.get("profiling_enabled"), False),
                    "profiling_memory_enabled": args.profiling_memory_enabled
                    or boolish(row.get("profiling_memory_enabled"), False),
                    "profiler_call_stack_interval_ms": args.profiler_call_stack_interval_ms
                    or row.get("profiler_call_stack_interval_ms")
                    or "",
                    "runtime_metrics_enabled": args.runtime_metrics_enabled
                    or boolish(row.get("runtime_metrics_enabled"), False),
                    "use_labels_for_resource_attributes": args.use_labels_for_resource_attributes
                    or boolish(row.get("use_labels_for_resource_attributes"), False),
                    "extra_resource_attrs": {
                        **dict(row.get("extra_resource_attrs") or row.get("extraResourceAttrs") or {}),
                        **parse_mapping_flags(args.extra_resource_attr, label="--extra-resource-attr"),
                    },
                    "images": dict(row.get("images") or {}),
                    "extra_env": copy.deepcopy(row.get("extra_env") or row.get("extraEnv") or {}),
                    "resource_limits": copy.deepcopy(row.get("resource_limits") or row.get("resourceLimits") or {}),
                }
            )
    else:
        root_languages = cli_languages or [normalize_language(lang) for lang in split_csv(spec.get("languages"))]
        if not root_languages:
            root_languages = ["java"]
        crs.append(
            {
                "name": args.instrumentation_cr_name or first_value(spec, "instrumentation_cr_name", "instrumentationCrName", default="splunk-otel-auto-instrumentation"),
                "namespace": namespace,
                "languages": root_languages,
                "endpoint": endpoint,
                "per_language_endpoint": per_language_endpoint,
                "propagators": split_csv(args.propagators) or split_csv(spec.get("propagators")) or ["tracecontext", "baggage", "b3"],
                "sampler": {
                    "type": args.sampler
                    or (spec.get("sampler") or {}).get("type")
                    or first_value(spec, "sampler_type", "samplerType", default="parentbased_always_on"),
                    "argument": args.sampler_argument
                    if args.sampler_argument != ""
                    else (spec.get("sampler") or {}).get("argument", first_value(spec, "sampler_argument", "samplerArgument", default="")),
                },
                "profiling_enabled": args.profiling_enabled or boolish(spec.get("profiling_enabled"), False),
                "profiling_memory_enabled": args.profiling_memory_enabled
                or boolish(spec.get("profiling_memory_enabled"), False),
                "profiler_call_stack_interval_ms": args.profiler_call_stack_interval_ms
                or first_value(spec, "profiler_call_stack_interval_ms", "profilerCallStackIntervalMs", default=""),
                "runtime_metrics_enabled": args.runtime_metrics_enabled or boolish(spec.get("runtime_metrics_enabled"), False),
                "use_labels_for_resource_attributes": args.use_labels_for_resource_attributes
                or boolish(spec.get("use_labels_for_resource_attributes"), False),
                "extra_resource_attrs": parse_mapping_flags(args.extra_resource_attr, label="--extra-resource-attr"),
                "images": {},
                "extra_env": {},
                "resource_limits": {},
            }
        )

    cli_images = {
        "java": args.java_image,
        "nodejs": args.nodejs_image,
        "python": args.python_image,
        "dotnet": args.dotnet_image,
        "go": args.go_image,
        "apache-httpd": args.apache_httpd_image,
        "nginx": args.nginx_image,
    }
    cli_env = parse_nested_lang_env(args.extra_env)
    cli_limits = parse_resource_limits(args.resource_limits)
    for cr in crs:
        cr["images"] = {**cr.get("images", {}), **{k: v for k, v in cli_images.items() if v}}
        for lang, values in cli_env.items():
            cr.setdefault("extra_env", {}).setdefault(lang, {}).update(values)
        for lang, values in cli_limits.items():
            cr.setdefault("resource_limits", {})[lang] = values

    namespace_annotations = normalize_namespace_annotations(
        first_value(spec, "namespace_annotations", "namespaceAnnotations", default={})
    )
    namespace_annotations.extend(parse_namespace_annotation(value) for value in args.annotate_namespace)

    workload_annotations = normalize_workload_rows(
        first_value(spec, "workload_annotations", "workloadAnnotations", default=[])
    )
    workload_annotations.extend(parse_workload_annotation(value) for value in args.annotate_workload)
    if args.inventory_file:
        workload_annotations.extend(parse_inventory_file(Path(args.inventory_file).expanduser()))

    image_pull_secret = args.image_pull_secret or first_value(spec, "image_pull_secret", "imagePullSecret", default="")
    multi_instrumentation = (
        args.multi_instrumentation
        or boolish(operator.get("multi_instrumentation"), False)
        or boolish(first_value(spec, "multi_instrumentation", "multiInstrumentation", default=False), False)
    )
    render_scc_default = distribution == "openshift" and (args.enable_obi or boolish(obi_spec.get("enabled"), False))
    render_scc = render_scc_default
    if args.render_openshift_scc != "":
        render_scc = boolish(args.render_openshift_scc)
    elif "render_openshift_scc" in obi_spec:
        render_scc = boolish(obi_spec.get("render_openshift_scc"), render_scc_default)

    config = {
        "api_version": API_VERSION,
        "spec_path": str(spec_path) if spec_path else "",
        "realm": args.realm or first_value(spec, "realm", default=""),
        "cluster_name": args.cluster_name or first_value(spec, "cluster_name", "clusterName", default=""),
        "deployment_environment": args.deployment_environment
        or first_value(spec, "deployment_environment", "deploymentEnvironment", default=""),
        "distribution": distribution,
        "namespace": namespace,
        "base": {"release": base_release, "namespace": base_namespace},
        "instrumentation_crs": crs,
        "operator": {
            "watch_namespaces": split_csv(args.operator_watch_namespaces)
            or split_csv(operator.get("watch_namespaces") or operator.get("watchNamespaces")),
            "webhook_cert_mode": args.webhook_cert_mode or operator.get("webhook_cert_mode") or "auto",
            "installation_job_enabled": args.installation_job_enabled
            or boolish(operator.get("installation_job_enabled"), True),
            "multi_instrumentation": multi_instrumentation,
        },
        "image_pull_secret": image_pull_secret,
        "namespace_annotations": namespace_annotations,
        "workload_annotations": workload_annotations,
        "obi": {
            "enabled": args.enable_obi or boolish(obi_spec.get("enabled"), False),
            "namespaces": split_csv(args.obi_namespaces) or split_csv(obi_spec.get("namespaces")),
            "exclude_namespaces": split_csv(args.obi_exclude_namespaces)
            or split_csv(obi_spec.get("exclude_namespaces") or obi_spec.get("excludeNamespaces"))
            or ["kube-system", "kube-public"],
            "version": args.obi_version or str(obi_spec.get("version") or ""),
            "render_openshift_scc": render_scc,
        },
        "vendors": {
            "detect": args.detect_vendors or boolish(vendors.get("detect"), False),
            "exclude": split_csv(args.exclude_vendor) or split_csv(vendors.get("exclude")),
        },
        "pss_overrides": spec.get("pss_overrides") or spec.get("pssOverrides") or [],
        "handoffs": {
            "base_collector": boolish(handoffs.get("base_collector"), True),
            "native_ops": boolish(handoffs.get("native_ops"), True),
            "dashboard_builder": boolish(handoffs.get("dashboard_builder"), True),
        },
        "backup_configmap": args.backup_configmap or first_value(spec, "backup_configmap", "backupConfigmap", default=DEFAULT_BACKUP_CONFIGMAP),
        "gitops_mode": args.gitops_mode,
        "target": args.target,
        "target_all": args.target_all,
        "purge_crs": args.purge_crs,
        "restore_from_backup": args.restore_from_backup,
        "purge_backup": args.purge_backup,
        "accept_auto_instrumentation": args.accept_auto_instrumentation,
        "accept_obi_privileged": args.accept_obi_privileged,
        "kube_context": args.kube_context,
    }
    return config


def workload_target(workload: dict[str, Any]) -> str:
    return f"{workload['kind']}/{workload['namespace']}/{workload['name']}"


def workload_key(workload: dict[str, Any]) -> str:
    return f"{workload['kind'].lower()}-{workload['namespace']}-{workload['name']}".replace("/", "-")


def annotation_value_for(workload: dict[str, Any]) -> str:
    if boolish(workload.get("disable"), False):
        return "false"
    return str(workload.get("cr") or "true")


def workload_annotations_for(workload: dict[str, Any]) -> dict[str, str]:
    language = normalize_language(str(workload["language"]))
    annotations = {
        f"instrumentation.opentelemetry.io/inject-{language}": annotation_value_for(workload)
    }
    if workload.get("container_names"):
        annotations["instrumentation.opentelemetry.io/container-names"] = str(workload["container_names"])
    if workload.get("dotnet_runtime"):
        annotations["instrumentation.opentelemetry.io/otel-dotnet-auto-runtime"] = str(
            workload["dotnet_runtime"]
        )
    if workload.get("go_target_exe"):
        annotations["instrumentation.opentelemetry.io/otel-go-auto-target-exe"] = str(
            workload["go_target_exe"]
        )
    return annotations


def resource_attr_string(config: dict[str, Any], cr: dict[str, Any]) -> str:
    attrs = {
        "deployment.environment": config["deployment_environment"],
        "k8s.cluster.name": config["cluster_name"],
    }
    attrs.update({str(k): str(v) for k, v in cr.get("extra_resource_attrs", {}).items() if v != ""})
    return ",".join(f"{key}={value}" for key, value in attrs.items() if value)


def env_list(values: dict[str, str]) -> list[dict[str, str]]:
    return [{"name": str(key), "value": str(value)} for key, value in values.items() if value is not None]


def language_env(config: dict[str, Any], cr: dict[str, Any], language: str) -> dict[str, str]:
    endpoint = cr.get("per_language_endpoint", {}).get(language) or cr["endpoint"]
    env = {
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OTEL_RESOURCE_ATTRIBUTES": resource_attr_string(config, cr),
    }
    if language == "go":
        env["OTEL_GO_AUTO_GLOBAL"] = "true"
    if language == "dotnet":
        env["OTEL_DOTNET_AUTO_HOME"] = "/otel-dotnet-auto"
    if cr.get("profiling_enabled") and language in {"java", "nodejs"}:
        env["SPLUNK_PROFILER_ENABLED"] = "true"
        if cr.get("profiling_memory_enabled"):
            env["SPLUNK_PROFILER_MEMORY_ENABLED"] = "true"
        if cr.get("profiler_call_stack_interval_ms"):
            env["SPLUNK_PROFILER_CALL_STACK_INTERVAL"] = str(cr["profiler_call_stack_interval_ms"])
    if cr.get("runtime_metrics_enabled") and language in {"java", "nodejs"}:
        env["SPLUNK_METRICS_ENABLED"] = "true"
        env["SPLUNK_METRICS_ENDPOINT"] = DEFAULT_METRICS_ENDPOINT
    env.update({str(k): str(v) for k, v in (cr.get("extra_env", {}).get(language, {}) or {}).items()})
    return env


def resource_requirements(cr: dict[str, Any], language: str) -> dict[str, Any]:
    limits = cr.get("resource_limits", {}).get(language) or {}
    if not limits:
        return {}
    return {"resourceRequirements": {"limits": {str(k): str(v) for k, v in limits.items()}}}


def instrumentation_cr_doc(config: dict[str, Any], cr: dict[str, Any]) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "exporter": {"endpoint": cr["endpoint"]},
        "propagators": cr["propagators"],
        "sampler": {"type": cr["sampler"]["type"]},
        "env": env_list({"OTEL_RESOURCE_ATTRIBUTES": resource_attr_string(config, cr)}),
    }
    if cr["sampler"].get("argument") not in ("", None):
        spec["sampler"]["argument"] = str(cr["sampler"]["argument"])
    if cr.get("use_labels_for_resource_attributes"):
        spec["defaults"] = {"useLabelsForResourceAttributes": True}
    if config.get("image_pull_secret"):
        spec["imagePullSecrets"] = [{"name": config["image_pull_secret"]}]

    for language in cr["languages"]:
        if language == "sdk":
            continue
        block: dict[str, Any] = {
            "image": cr.get("images", {}).get(language) or LANGUAGE_IMAGE_DEFAULTS[language],
            "env": env_list(language_env(config, cr, language)),
        }
        block.update(resource_requirements(cr, language))
        if language == "apache-httpd":
            block["configPath"] = "/usr/local/apache2/conf"
        if language == "nginx":
            block["configFile"] = "/etc/nginx/nginx.conf"
        spec[LANGUAGE_SPEC_KEYS[language]] = block

    return {
        "apiVersion": "opentelemetry.io/v1alpha1",
        "kind": "Instrumentation",
        "metadata": {"name": cr["name"], "namespace": cr["namespace"]},
        "spec": spec,
    }


def namespace_annotation_docs(config: dict[str, Any]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for row in config["namespace_annotations"]:
        annotations: dict[str, str] = {}
        for language in row["languages"]:
            annotations[f"instrumentation.opentelemetry.io/inject-{language}"] = "true"
        docs.append(
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": row["namespace"], "annotations": annotations},
            }
        )
    return docs


def workload_annotation_docs(config: dict[str, Any]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for workload in config["workload_annotations"]:
        docs.append(
            {
                "apiVersion": "apps/v1",
                "kind": workload["kind"],
                "metadata": {"name": workload["name"], "namespace": workload["namespace"]},
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": workload_annotations_for(workload),
                        }
                    }
                },
            }
        )
    return docs


def backup_configmap_doc(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": config["backup_configmap"],
            "namespace": config["namespace"],
            "labels": {
                "app.kubernetes.io/name": "splunk-otel-auto-instrumentation",
                "app.kubernetes.io/managed-by": SKILL_NAME,
                "splunk.com/ttl": "7d",
            },
        },
        "data": {},
    }


def obi_daemonset_doc(config: dict[str, Any]) -> dict[str, Any]:
    obi = config["obi"]
    image = "ghcr.io/signalfx/splunk-obi"
    if obi.get("version"):
        image = f"{image}:{obi['version']}"
    else:
        image = f"{image}:latest"
    env = {
        "SPLUNK_OBI_NAMESPACE_INCLUDE": ",".join(obi.get("namespaces") or []),
        "SPLUNK_OBI_NAMESPACE_EXCLUDE": ",".join(obi.get("exclude_namespaces") or []),
        "OTEL_EXPORTER_OTLP_ENDPOINT": DEFAULT_ENDPOINT,
        "OTEL_RESOURCE_ATTRIBUTES": f"k8s.cluster.name={config['cluster_name']},deployment.environment={config['deployment_environment']}",
    }
    return {
        "apiVersion": "apps/v1",
        "kind": "DaemonSet",
        "metadata": {"name": "splunk-obi", "namespace": config["namespace"]},
        "spec": {
            "selector": {"matchLabels": {"app.kubernetes.io/name": "splunk-obi"}},
            "template": {
                "metadata": {"labels": {"app.kubernetes.io/name": "splunk-obi"}},
                "spec": {
                    "serviceAccountName": "splunk-obi",
                    "hostPID": True,
                    "containers": [
                        {
                            "name": "obi",
                            "image": image,
                            "securityContext": {"privileged": True},
                            "env": env_list(env),
                            "volumeMounts": [
                                {"name": "kernel-security", "mountPath": "/sys/kernel/security"},
                                {"name": "cgroup", "mountPath": "/sys/fs/cgroup"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "kernel-security", "hostPath": {"path": "/sys/kernel/security"}},
                        {"name": "cgroup", "hostPath": {"path": "/sys/fs/cgroup"}},
                    ],
                },
            },
        },
    }


def openshift_scc_docs(config: dict[str, Any]) -> list[dict[str, Any]]:
    namespace = config["namespace"]
    return [
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "splunk-obi", "namespace": namespace}},
        {
            "apiVersion": "security.openshift.io/v1",
            "kind": "SecurityContextConstraints",
            "metadata": {"name": "splunk-obi-privileged"},
            "allowHostDirVolumePlugin": True,
            "allowHostPID": True,
            "allowPrivilegedContainer": True,
            "allowedCapabilities": ["*"],
            "runAsUser": {"type": "RunAsAny"},
            "seLinuxContext": {"type": "RunAsAny"},
            "fsGroup": {"type": "RunAsAny"},
            "supplementalGroups": {"type": "RunAsAny"},
            "users": [f"system:serviceaccount:{namespace}:splunk-obi"],
            "volumes": ["hostPath", "configMap", "downwardAPI", "emptyDir", "projected", "secret"],
        },
    ]


def target_records(config: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for workload in config["workload_annotations"]:
        records.append(
            {
                "target": workload_target(workload),
                "key": workload_key(workload),
                "kind": workload["kind"],
                "namespace": workload["namespace"],
                "name": workload["name"],
                "language": workload["language"],
                "annotations": workload_annotations_for(workload),
                "cr": workload.get("cr") or "",
            }
        )
    return records


def collect_preflights(config: dict[str, Any], mode: str) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    advisories = [
        "Instrumentation CR image or env changes require a pod restart to take effect.",
        "kubectl rollout restart is idempotent; re-applying annotations safely reruns restarts.",
    ]

    if not config["cluster_name"] and config["distribution"] not in AUTO_CLUSTER_DISTRIBUTIONS:
        errors.append("Missing cluster name: pass --cluster-name or use an auto-detected distribution.")
    if not config["deployment_environment"]:
        errors.append("Missing deployment environment: pass --deployment-environment.")
    if config["distribution"] == "eks/fargate":
        endpoints = [cr.get("endpoint", "") for cr in config["instrumentation_crs"]]
        if all("SPLUNK_OTEL_AGENT" in endpoint for endpoint in endpoints):
            errors.append("EKS Fargate requires --gateway-endpoint; the DaemonSet agent is not available.")

    if len(config["instrumentation_crs"]) > 1 and not config["operator"]["multi_instrumentation"]:
        errors.append("Multiple Instrumentation CRs require --multi-instrumentation.")

    seen_crs: set[tuple[str, str]] = set()
    for cr in config["instrumentation_crs"]:
        key = (cr["namespace"], cr["name"])
        if key in seen_crs:
            errors.append(f"Duplicate Instrumentation CR name: {cr['namespace']}/{cr['name']}.")
        seen_crs.add(key)

    for workload in config["workload_annotations"]:
        if workload["language"] == "go" and not workload.get("go_target_exe"):
            errors.append(f"{workload_target(workload)} uses Go instrumentation but is missing go-target-exe.")
        runtime = str(workload.get("dotnet_runtime") or "").lower()
        metadata_text = json.dumps(workload.get("metadata") or {}, sort_keys=True).lower()
        if workload["language"] == "dotnet" and (
            runtime.startswith("windows-") or ".net framework" in metadata_text or "dotnet framework" in metadata_text
        ):
            errors.append(f"{workload_target(workload)} targets .NET Framework or Windows; Splunk .NET auto-instrumentation is Linux-only.")
        node_selector_text = json.dumps(workload.get("node_selector") or {}, sort_keys=True).lower()
        if workload["language"] == "dotnet" and "arm64" in node_selector_text:
            warnings.append(f"{workload_target(workload)} appears to target arm64; Splunk .NET auto-instrumentation is amd64 only.")
        if workload["language"] in {"go"}:
            for override in config.get("pss_overrides") or []:
                if not isinstance(override, dict):
                    continue
                if override.get("namespace") == workload["namespace"] and str(override.get("enforce", "")).lower() in {"restricted", "baseline"} and not boolish(override.get("acknowledged"), False):
                    errors.append(f"{workload_target(workload)} is in a {override.get('enforce')} PSS namespace; Go instrumentation requires elevated privileges.")

    if config["obi"]["enabled"] and config["distribution"] == "openshift" and not config["obi"]["render_openshift_scc"]:
        errors.append("OpenShift OBI rendering requires openshift-scc-obi.yaml; do not disable --render-openshift-scc.")
    if mode == "apply-annotations" and not config["accept_auto_instrumentation"]:
        errors.append("--apply-annotations requires --accept-auto-instrumentation.")
    if mode == "uninstall-instrumentation" and not config["accept_auto_instrumentation"]:
        errors.append("--uninstall-instrumentation requires --accept-auto-instrumentation.")
    if mode == "apply-instrumentation" and config["obi"]["enabled"] and not config["accept_obi_privileged"]:
        errors.append("--apply-instrumentation with OBI requires --accept-obi-privileged.")
    if mode in {"apply-annotations", "uninstall-instrumentation"} and (config["target"] or config["target_all"]):
        advisories.append("Targeted apply/uninstall consumes metadata.json from the most recent render.")

    if config["distribution"] == "gke/private":
        warnings.append("GKE Private Cluster requires firewall access to the operator webhook on port 9443.")
    if config["distribution"] == "openshift" and not config["obi"]["render_openshift_scc"] and config["obi"]["enabled"]:
        warnings.append("OpenShift OBI needs an SCC binding for privileged eBPF access.")
    if config["operator"]["webhook_cert_mode"] == "external":
        advisories.append("External webhook certificates must be rotated outside this skill.")
    if config["base"]["namespace"] != config["namespace"]:
        warnings.append(
            "Base collector namespace differs from Instrumentation CR namespace; consider a gateway Service DNS endpoint if workloads cannot resolve SPLUNK_OTEL_AGENT."
        )
    if config["vendors"]["detect"]:
        warnings.append(
            "Vendor detection requested; live apply scripts will warn on Datadog/New Relic/AppDynamics/Dynatrace webhook coexistence."
        )
    for vendor in config["vendors"]["exclude"]:
        advisories.append(f"Vendor exclusion requested for {vendor}; see migration-guide.md for env-var cleanup.")

    return errors, warnings, advisories


def preflight_report(errors: list[str], warnings: list[str], advisories: list[str]) -> str:
    lines = ["# Preflight Report", ""]
    verdict = "FAIL" if errors else "PASS"
    lines.append(f"Verdict: **{verdict}**")
    lines.append("")
    for title, items in (("Fail", errors), ("Warn", warnings), ("Advisory", advisories)):
        lines.append(f"## {title}")
        if items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append("- None")
        lines.append("")
    return "\n".join(lines)


def runbook(config: dict[str, Any], errors: list[str]) -> str:
    lines = [
        "# Splunk Observability Kubernetes Auto-Instrumentation Runbook",
        "",
        f"Cluster: `{config['cluster_name'] or '<auto-detect>'}`",
        f"Environment: `{config['deployment_environment'] or '<missing>'}`",
        f"Distribution: `{config['distribution']}`",
        "",
    ]
    if errors:
        lines.extend(
            [
                "## Stop",
                "Preflight found hard errors. Fix `k8s-instrumentation/preflight-report.md` before applying anything.",
                "",
            ]
        )
    lines.extend(
        [
            "## Apply Order",
            "1. Confirm the base Splunk OTel Collector chart is installed with operator and Instrumentation CRDs enabled.",
            "2. Review `k8s-instrumentation/instrumentation-cr.yaml` and `k8s-instrumentation/workload-annotations.yaml`.",
            "3. Apply Instrumentation CRs first: `bash k8s-instrumentation/apply-instrumentation.sh`.",
            "4. Apply workload annotations with an explicit restart gate: `bash k8s-instrumentation/apply-annotations.sh --accept-auto-instrumentation --target-all`.",
            "5. Verify injection: `bash k8s-instrumentation/verify-injection.sh --target <Kind/ns/name>` or run `scripts/validate.sh --live --check-injection` from the skill.",
            "",
            "## Uninstall",
            "Use `bash k8s-instrumentation/uninstall.sh --accept-auto-instrumentation --target <Kind/ns/name>` for selective rollback, or add `--target-all --purge-crs` for full teardown.",
        ]
    )
    return "\n".join(lines) + "\n"


def metadata_payload(
    config: dict[str, Any],
    errors: list[str],
    warnings: list[str],
    advisories: list[str],
    rendered_files: list[str],
    mode: str,
) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    normalized.pop("accept_auto_instrumentation", None)
    normalized.pop("accept_obi_privileged", None)
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest()
    all_languages = sorted({lang for cr in config["instrumentation_crs"] for lang in cr["languages"]})
    return {
        "skill": SKILL_NAME,
        "api_version": API_VERSION,
        "mode": mode,
        "spec_digest": digest,
        "realm": config["realm"],
        "cluster_name": config["cluster_name"],
        "deployment_environment": config["deployment_environment"],
        "distribution": config["distribution"],
        "namespace": config["namespace"],
        "base": config["base"],
        "languages": all_languages,
        "instrumentation_crs": [
            {"name": cr["name"], "namespace": cr["namespace"], "languages": cr["languages"], "endpoint": cr["endpoint"]}
            for cr in config["instrumentation_crs"]
        ],
        "obi_enabled": bool(config["obi"]["enabled"]),
        "backup_configmap": config["backup_configmap"],
        "targets": target_records(config),
        "preflight": {"errors": errors, "warnings": warnings, "advisories": advisories},
        "errors": errors,
        "warnings": warnings,
        "advisories": advisories,
        "rendered_files": rendered_files,
        "gitops_mode": config["gitops_mode"],
    }


def kubectl_prefix(context: str) -> str:
    if context:
        return f"kubectl --context {context}"
    return "kubectl"


def helm_prefix(context: str) -> str:
    if context:
        return f"helm --kube-context {context}"
    return "helm"


def script_header(title: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
OUTPUT_DIR="$(cd "${{SCRIPT_DIR}}/.." && pwd)"
METADATA="${{OUTPUT_DIR}}/metadata.json"

usage() {{
  cat <<'EOF'
{title}

Options:
  --target Kind/namespace/name      Limit to one workload (repeatable where supported)
  --target-all                      Use every workload from metadata.json
  --accept-auto-instrumentation     Required for annotation apply/uninstall restarts
  --accept-obi-privileged           Required when applying OBI
  --purge-crs                       Delete rendered Instrumentation CRs during uninstall
  --purge-backup                    Delete the backup ConfigMap during uninstall
  --kube-context NAME               Use a specific kube context
  --dry-run                         Print commands without running them
  --help                            Show this help
EOF
}}

require_metadata() {{
  [[ -f "${{METADATA}}" ]] || {{ echo "ERROR: metadata.json not found. Run --render first." >&2; exit 1; }}
}}

run_cmd() {{
  if [[ "${{DRY_RUN:-false}}" == "true" ]]; then
    printf 'DRY RUN:'
    printf ' %q' "$@"
    printf '\\n'
  else
    "$@"
  fi
}}
"""


def apply_instrumentation_script(config: dict[str, Any]) -> str:
    return script_header("Apply Splunk OTel Instrumentation CRs and optional OBI assets") + f"""
DRY_RUN=false
ACCEPT_OBI=false
KUBE_CONTEXT="{config.get('kube_context', '')}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --accept-obi-privileged) ACCEPT_OBI=true; shift ;;
    --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done
require_metadata
OBI_ENABLED="$(python3 - "$METADATA" <<'PY'
import json, sys
print(str(json.load(open(sys.argv[1])).get("obi_enabled", False)).lower())
PY
)"
if [[ "${{OBI_ENABLED}}" == "true" && "${{ACCEPT_OBI}}" != "true" ]]; then
  echo "ERROR: OBI uses privileged eBPF access; rerun with --accept-obi-privileged." >&2
  exit 1
fi
KUBECTL=(kubectl)
HELM=(helm)
if [[ -n "${{KUBE_CONTEXT}}" ]]; then
  KUBECTL+=(--context "${{KUBE_CONTEXT}}")
  HELM+=(--kube-context "${{KUBE_CONTEXT}}")
fi
BASE_NAMESPACE="{config['base']['namespace']}"
BASE_RELEASE="{config['base']['release']}"
if [[ "${{DRY_RUN}}" != "true" ]]; then
  "${{KUBECTL[@]}}" get crd instrumentations.opentelemetry.io >/dev/null
  if ! "${{HELM[@]}}" list -n "${{BASE_NAMESPACE}}" -q | grep -qx "${{BASE_RELEASE}}"; then
    echo "ERROR: Base Splunk OTel Collector helm release not found: ${{BASE_NAMESPACE}}/${{BASE_RELEASE}}." >&2
    echo "Run splunk-observability-otel-collector-setup before applying this overlay." >&2
    exit 1
  fi
fi
if [[ -f "${{SCRIPT_DIR}}/openshift-scc-obi.yaml" ]]; then
  run_cmd "${{KUBECTL[@]}}" apply -f "${{SCRIPT_DIR}}/openshift-scc-obi.yaml"
fi
run_cmd "${{KUBECTL[@]}}" apply -f "${{SCRIPT_DIR}}/instrumentation-cr.yaml"
if [[ -f "${{SCRIPT_DIR}}/obi-daemonset.yaml" ]]; then
  run_cmd "${{KUBECTL[@]}}" apply -f "${{SCRIPT_DIR}}/obi-daemonset.yaml"
fi
if [[ "${{DRY_RUN}}" != "true" ]]; then
  echo "Waiting for an OpenTelemetry operator webhook endpoint on port 9443..."
  for _ in $(seq 1 30); do
    if "${{KUBECTL[@]}}" get endpoints -A 2>/dev/null | grep -q '9443'; then
      echo "Webhook endpoint detected."
      exit 0
    fi
    sleep 2
  done
  echo "WARN: webhook endpoint on port 9443 was not observed; inspect operator logs before annotating workloads." >&2
fi
"""


def apply_annotations_script(config: dict[str, Any]) -> str:
    head = script_header("Apply Splunk OTel auto-instrumentation workload annotations")
    prelude = (
        f'\nDRY_RUN=false\nACCEPT=false\nTARGET_ALL=false\n'
        f'KUBE_CONTEXT="{config.get("kube_context", "")}"\n'
        f'BACKUP_NAME="{config["backup_configmap"]}"\n'
        f'BACKUP_NAMESPACE="{config["namespace"]}"\n'
    )
    body = r"""TARGETS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --accept-auto-instrumentation) ACCEPT=true; shift ;;
    --target) TARGETS+=("$2"); shift 2 ;;
    --target-all) TARGET_ALL=true; shift ;;
    --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done
require_metadata
if [[ "${ACCEPT}" != "true" ]]; then
  echo "ERROR: --accept-auto-instrumentation is required because this restarts pods." >&2
  exit 1
fi
if [[ "${TARGET_ALL}" != "true" && ${#TARGETS[@]} -eq 0 ]]; then
  echo "ERROR: pass --target Kind/namespace/name (repeatable) or --target-all." >&2
  exit 1
fi
KUBECTL=(kubectl)
if [[ -n "${KUBE_CONTEXT}" ]]; then KUBECTL+=(--context "${KUBE_CONTEXT}"); fi
run_cmd "${KUBECTL[@]}" apply -f "${SCRIPT_DIR}/annotation-backup-configmap.yaml"
TARGET_JSON="$(python3 - "$METADATA" "${TARGET_ALL}" "${TARGETS[@]+"${TARGETS[@]}"}" <<'PY'
import json, sys
meta = json.load(open(sys.argv[1]))
target_all = sys.argv[2] == "true"
requested = {token for token in sys.argv[3:] if token}
records = meta.get("targets", [])
if requested:
    records = [r for r in records if r.get("target") in requested]
elif not target_all:
    records = []
print(json.dumps(records))
PY
)"
while IFS=$'\t' read -r kind namespace name key patch; do
  [[ -n "${kind}" ]] || continue
  if [[ "${DRY_RUN}" != "true" ]]; then
    # Capture current pod-template annotations as a real JSON object so the
    # backup ConfigMap stores a value uninstall.sh can decode for restore.
    # `kubectl get -o jsonpath` emits Go map syntax, so use -o json + python.
    current_json="$("${KUBECTL[@]}" -n "${namespace}" get "${kind}" "${name}" -o json 2>/dev/null \
      | python3 -c 'import json,sys
try:
    obj = json.load(sys.stdin)
    annotations = (((obj or {}).get("spec") or {}).get("template") or {}).get("metadata", {}).get("annotations") or {}
except Exception:
    annotations = {}
print(json.dumps(annotations))' || echo '{}')"
    if ! "${KUBECTL[@]}" -n "${BACKUP_NAMESPACE}" get configmap "${BACKUP_NAME}" -o "jsonpath={.data.${key}}" >/dev/null 2>&1; then
      backup_patch="$(python3 - "${key}" "${current_json}" <<'PY'
import json, sys
key = sys.argv[1]
prior = sys.argv[2].strip() or "{}"
# Validate that the prior payload is JSON; fall back to empty object on failure.
try:
    json.loads(prior)
except Exception:
    prior = "{}"
print(json.dumps({"data": {key: prior}}))
PY
)"
      "${KUBECTL[@]}" -n "${BACKUP_NAMESPACE}" patch configmap "${BACKUP_NAME}" --type merge -p "${backup_patch}" >/dev/null
    fi
  fi
  run_cmd "${KUBECTL[@]}" -n "${namespace}" patch "${kind}" "${name}" --type strategic -p "${patch}"
  run_cmd "${KUBECTL[@]}" -n "${namespace}" rollout restart "${kind}/${name}"
  if [[ "${DRY_RUN}" != "true" ]]; then
    "${KUBECTL[@]}" -n "${namespace}" rollout status "${kind}/${name}"
  fi
done < <(python3 - "$TARGET_JSON" <<'PY'
import json, sys
for row in json.loads(sys.argv[1]):
    patch = {"spec": {"template": {"metadata": {"annotations": row["annotations"]}}}}
    print("\t".join([row["kind"], row["namespace"], row["name"], row["key"], json.dumps(patch)]))
PY
)
"""
    return head + prelude + body


def uninstall_script(config: dict[str, Any]) -> str:
    cr_delete_lines = "\n".join(
        f'  run_cmd "${{KUBECTL[@]}}" -n "{cr["namespace"]}" delete otelinst "{cr["name"]}" --ignore-not-found'
        for cr in config["instrumentation_crs"]
    )
    head = script_header("Uninstall Splunk OTel auto-instrumentation annotations and CRs")
    prelude = (
        f'\nDRY_RUN=false\nACCEPT=false\nTARGET_ALL=false\nPURGE_CRS=false\nPURGE_BACKUP=false\n'
        f'KUBE_CONTEXT="{config.get("kube_context", "")}"\n'
        f'CR_NAMESPACE="{config["namespace"]}"\n'
        f'BACKUP_NAMESPACE="{config["namespace"]}"\n'
        f'BACKUP_NAME="{config["backup_configmap"]}"\n'
    )
    body = r"""TARGETS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --accept-auto-instrumentation) ACCEPT=true; shift ;;
    --target) TARGETS+=("$2"); shift 2 ;;
    --target-all) TARGET_ALL=true; shift ;;
    --purge-crs) PURGE_CRS=true; shift ;;
    --purge-backup) PURGE_BACKUP=true; shift ;;
    --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done
require_metadata
if [[ "${ACCEPT}" != "true" ]]; then
  echo "ERROR: --accept-auto-instrumentation is required because this restarts pods." >&2
  exit 1
fi
if [[ "${TARGET_ALL}" != "true" && ${#TARGETS[@]} -eq 0 ]]; then
  echo "ERROR: pass --target Kind/namespace/name (repeatable) or --target-all." >&2
  exit 1
fi
KUBECTL=(kubectl)
if [[ -n "${KUBE_CONTEXT}" ]]; then KUBECTL+=(--context "${KUBE_CONTEXT}"); fi
TARGET_JSON="$(python3 - "$METADATA" "${TARGET_ALL}" "${TARGETS[@]+"${TARGETS[@]}"}" <<'PY'
import json, sys
meta = json.load(open(sys.argv[1]))
target_all = sys.argv[2] == "true"
requested = {token for token in sys.argv[3:] if token}
records = meta.get("targets", [])
if requested:
    records = [r for r in records if r.get("target") in requested]
elif not target_all:
    records = []
print(json.dumps(records))
PY
)"
while IFS=$'\t' read -r kind namespace name language key; do
  [[ -n "${kind}" ]] || continue
  # Best-effort restore: read the prior pod-template annotations from the
  # backup ConfigMap so we can return any pre-existing values (e.g. a
  # container-names annotation the operator set before instrumentation).
  # If the backup key is missing, fall back to nulling only the inject-*
  # annotations we may have written.
  prior_json='{}'
  if [[ "${DRY_RUN}" != "true" ]]; then
    prior_json="$("${KUBECTL[@]}" -n "${BACKUP_NAMESPACE}" get configmap "${BACKUP_NAME}" -o "jsonpath={.data.${key}}" 2>/dev/null || true)"
    [[ -n "${prior_json}" ]] || prior_json='{}'
  fi
  patch="$(python3 - "${language}" "${prior_json}" <<'PY'
import json, sys
lang = sys.argv[1]
prior_text = (sys.argv[2] or "").strip() or "{}"
try:
    prior = json.loads(prior_text)
    if not isinstance(prior, dict):
        prior = {}
except Exception:
    prior = {}
managed_keys = [
    "instrumentation.opentelemetry.io/inject-" + lang,
    "instrumentation.opentelemetry.io/container-names",
    "instrumentation.opentelemetry.io/otel-dotnet-auto-runtime",
    "instrumentation.opentelemetry.io/otel-go-auto-target-exe",
]
annotations = {key: prior[key] if key in prior else None for key in managed_keys}
print(json.dumps({"spec": {"template": {"metadata": {"annotations": annotations}}}}))
PY
)"
  run_cmd "${KUBECTL[@]}" -n "${namespace}" patch "${kind}" "${name}" --type strategic -p "${patch}"
  run_cmd "${KUBECTL[@]}" -n "${namespace}" rollout restart "${kind}/${name}"
  if [[ "${DRY_RUN}" != "true" ]]; then
    "${KUBECTL[@]}" -n "${namespace}" rollout status "${kind}/${name}"
  fi
done < <(python3 - "$TARGET_JSON" <<'PY'
import json, sys
for row in json.loads(sys.argv[1]):
    print("\t".join([row["kind"], row["namespace"], row["name"], row["language"], row["key"]]))
PY
)
"""
    tail = (
        f'if [[ "${{PURGE_CRS}}" == "true" ]]; then\n{cr_delete_lines}\nfi\n'
        f'if [[ "${{PURGE_BACKUP}}" == "true" ]]; then\n'
        f'  run_cmd "${{KUBECTL[@]}}" -n "${{CR_NAMESPACE}}" delete configmap "${{BACKUP_NAME}}" --ignore-not-found\n'
        f'fi\n'
    )
    return head + prelude + body + tail


def verify_injection_script(config: dict[str, Any]) -> str:
    return script_header("Verify Splunk OTel auto-instrumentation injection for a target workload") + """
DRY_RUN=false
TARGET=""
KUBE_CONTEXT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done
require_metadata
[[ -n "${TARGET}" ]] || { echo "ERROR: --target Kind/namespace/name is required." >&2; exit 1; }
KUBECTL=(kubectl)
if [[ -n "${KUBE_CONTEXT}" ]]; then KUBECTL+=(--context "${KUBE_CONTEXT}"); fi
IFS=/ read -r kind namespace name <<<"${TARGET}"
echo "Workload annotations:"
"${KUBECTL[@]}" -n "${namespace}" get "${kind}" "${name}" -o jsonpath='{.spec.template.metadata.annotations}' || true
echo
echo "Sample pods with OpenTelemetry init containers:"
# Resolve the workload's actual matchLabels selector and use it to scope the
# pod query. Falls back to listing all pods in the namespace when the
# selector cannot be resolved (e.g. the workload was just deleted).
selector_label="$("${KUBECTL[@]}" -n "${namespace}" get "${kind}" "${name}" -o json 2>/dev/null | python3 -c 'import json,sys
try:
    obj = json.load(sys.stdin)
    labels = (((obj or {}).get("spec") or {}).get("selector") or {}).get("matchLabels") or {}
    print(",".join(f"{k}={v}" for k, v in sorted(labels.items())))
except Exception:
    print("")' || echo "")"
if [[ -n "${selector_label}" ]]; then
  pods_json="$("${KUBECTL[@]}" -n "${namespace}" get pods -l "${selector_label}" -o json)"
else
  pods_json="$("${KUBECTL[@]}" -n "${namespace}" get pods -o json)"
fi
printf '%s\\n' "${pods_json}" | python3 -c 'import json,sys
data = json.load(sys.stdin)
for p in data.get("items", []):
    init_containers = (p.get("spec") or {}).get("initContainers") or []
    if any(c.get("name") == "opentelemetry-auto-instrumentation" for c in init_containers):
        print(p["metadata"]["name"])' || true
"""


def status_script(config: dict[str, Any]) -> str:
    return script_header("Show Splunk OTel auto-instrumentation status") + """
KUBE_CONTEXT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done
KUBECTL=(kubectl)
if [[ -n "${KUBE_CONTEXT}" ]]; then KUBECTL+=(--context "${KUBE_CONTEXT}"); fi
echo "Instrumentation CRs:"
"${KUBECTL[@]}" get otelinst -A || true
echo
echo "Mutating webhooks:"
"${KUBECTL[@]}" get mutatingwebhookconfiguration | grep -E 'opentelemetry|otel|splunk' || true
echo
echo "Pods with OpenTelemetry init containers:"
# Avoid nested-quote f-strings so this works on Python 3.9 / 3.11 (PEP 701
# is only available from 3.12+). Plain string concatenation is portable.
"${KUBECTL[@]}" get pods -A -o json | python3 -c 'import json,sys
data = json.load(sys.stdin)
for p in data.get("items", []):
    init_containers = (p.get("spec") or {}).get("initContainers") or []
    if any(c.get("name") == "opentelemetry-auto-instrumentation" for c in init_containers):
        meta = p.get("metadata") or {}
        print((meta.get("namespace") or "") + "/" + (meta.get("name") or ""))' || true
"""


def list_instrumented_script(config: dict[str, Any]) -> str:
    return script_header("List workloads rendered for Splunk OTel auto-instrumentation") + """
require_metadata
python3 - "$METADATA" <<'PY'
import json, sys
meta = json.load(open(sys.argv[1]))
print("TARGET\\tLANGUAGE\\tCR")
for row in meta.get("targets", []):
    print(f"{row['target']}\\t{row['language']}\\t{row.get('cr') or '<default>'}")
PY
"""


def handoff_collector(config: dict[str, Any]) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

echo "Run the base collector setup first if the Instrumentation CRD is absent:"
echo "bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh --render-k8s --realm {config['realm'] or '<realm>'} --cluster-name {config['cluster_name'] or '<cluster>'} --distribution {config['distribution']} --with-operator --with-instrumentation"
"""


def handoff_native_ops(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_version": "splunk-observability-native-ops/v1",
        "realm": config["realm"],
        "operations": [
            {
                "kind": "detector",
                "name": "Auto-instrumented services reporting errors",
                "programText": "A = traces.count(filter=filter('sf_environment', '%s')).publish()" % config["deployment_environment"],
                "description": "Starter detector for services onboarded through Kubernetes auto-instrumentation.",
            }
        ],
    }


def handoff_dashboard_builder(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_version": "splunk-observability-dashboard-builder/v1",
        "realm": config["realm"],
        "dashboard_group": "Kubernetes Auto-Instrumentation",
        "dashboards": [
            {
                "name": "Auto-instrumented APM topology",
                "description": "Starter dashboard for workloads annotated by splunk-observability-k8s-auto-instrumentation-setup.",
                "filters": {
                    "k8s.cluster.name": config["cluster_name"],
                    "deployment.environment": config["deployment_environment"],
                },
            }
        ],
    }


def render_all(config: dict[str, Any], output_dir: Path, mode: str) -> tuple[dict[str, Any], int]:
    errors, warnings, advisories = collect_preflights(config, mode)
    k8s_dir = output_dir / "k8s-instrumentation"
    rendered: list[str] = []

    cr_docs = [instrumentation_cr_doc(config, cr) for cr in config["instrumentation_crs"]]
    namespace_docs = namespace_annotation_docs(config)
    workload_docs = workload_annotation_docs(config)
    backup_doc = backup_configmap_doc(config)
    obi_docs = [obi_daemonset_doc(config)] if config["obi"]["enabled"] else []
    scc_docs = openshift_scc_docs(config) if config["obi"]["enabled"] and config["obi"]["render_openshift_scc"] and config["distribution"] == "openshift" else []

    files: list[tuple[Path, str | Any, str]] = [
        (k8s_dir / "instrumentation-cr.yaml", cr_docs, "yaml_all"),
        (k8s_dir / "namespace-annotations.yaml", namespace_docs, "yaml_all"),
        (k8s_dir / "workload-annotations.yaml", workload_docs, "yaml_all"),
        (k8s_dir / "annotation-backup-configmap.yaml", backup_doc, "yaml"),
        (k8s_dir / "preflight-report.md", preflight_report(errors, warnings, advisories), "text"),
        (output_dir / "runbook.md", runbook(config, errors), "text"),
    ]
    if obi_docs:
        files.append((k8s_dir / "obi-daemonset.yaml", obi_docs, "yaml_all"))
    if scc_docs:
        files.append((k8s_dir / "openshift-scc-obi.yaml", scc_docs, "yaml_all"))
    if config["handoffs"]["base_collector"]:
        files.append((output_dir / "handoff-collector.sh", handoff_collector(config), "script"))
    if config["handoffs"]["native_ops"]:
        files.append((output_dir / "handoff-native-ops.spec.yaml", handoff_native_ops(config), "yaml"))
    if config["handoffs"]["dashboard_builder"]:
        files.append((output_dir / "handoff-dashboard-builder.spec.yaml", handoff_dashboard_builder(config), "yaml"))
    # Read-only diagnostic scripts are always rendered; even in --gitops-mode
    # the operator wants status / verify / drift-audit helpers that do not touch
    # the cluster in a mutating way.
    files.extend(
        [
            (k8s_dir / "verify-injection.sh", verify_injection_script(config), "script"),
            (k8s_dir / "status.sh", status_script(config), "script"),
            (k8s_dir / "list-instrumented.sh", list_instrumented_script(config), "script"),
        ]
    )
    # Mutating scripts are skipped in --gitops-mode; the operator's CD system
    # is responsible for apply / uninstall in that model.
    if not config["gitops_mode"]:
        files.extend(
            [
                (k8s_dir / "apply-instrumentation.sh", apply_instrumentation_script(config), "script"),
                (k8s_dir / "apply-annotations.sh", apply_annotations_script(config), "script"),
                (k8s_dir / "uninstall.sh", uninstall_script(config), "script"),
            ]
        )

    for path, content, kind in files:
        rel = path.relative_to(output_dir).as_posix()
        rendered.append(rel)
        if kind == "yaml_all":
            write_yaml_all(path, content)  # type: ignore[arg-type]
        elif kind == "yaml":
            write_yaml(path, content)
        elif kind == "script":
            write_text(path, str(content), executable=True)
        else:
            write_text(path, str(content))

    metadata = metadata_payload(config, errors, warnings, advisories, rendered, mode)
    write_json(output_dir / "metadata.json", metadata)
    return metadata, 2 if errors else 0


def discover_workloads(config: dict[str, Any], output_dir: Path, *, dry_run: bool) -> tuple[dict[str, Any], int]:
    discovery_dir = output_dir / "discovery"
    workloads: list[dict[str, Any]] = []
    kubectl_path = shutil.which("kubectl")
    helm_path = shutil.which("helm")
    probe = {
        "kubectl_available": bool(kubectl_path),
        "helm_available": bool(helm_path),
        "helm_release_present": False,
        "instrumentation_crd_present": False,
        "warnings": [],
    }
    kubectl = ["kubectl"]
    helm = ["helm"]
    if config.get("kube_context"):
        kubectl.extend(["--context", config["kube_context"]])
        helm.extend(["--kube-context", config["kube_context"]])
    if kubectl_path:
        try:
            result = subprocess.run(
                kubectl + ["get", "deploy,sts,ds", "-A", "-o", "json"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout or "{}")
                for item in data.get("items", []):
                    workloads.append(
                        {
                            "kind": item.get("kind", ""),
                            "namespace": item.get("metadata", {}).get("namespace", "default"),
                            "name": item.get("metadata", {}).get("name", ""),
                            "language": "",
                            "container_names": "",
                            "go_target_exe": "",
                            "dotnet_runtime": "",
                            "cr": "",
                        }
                    )
            else:
                probe["warnings"].append(result.stderr.strip() or "kubectl workload discovery failed.")
        except Exception as exc:  # noqa: BLE001
            probe["warnings"].append(f"kubectl workload discovery failed: {exc}")
        try:
            crd = subprocess.run(
                kubectl + ["get", "crd", "instrumentations.opentelemetry.io"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            probe["instrumentation_crd_present"] = crd.returncode == 0
        except Exception as exc:  # noqa: BLE001
            probe["warnings"].append(f"CRD probe failed: {exc}")
    else:
        probe["warnings"].append("kubectl not found on PATH; wrote an empty starter inventory.")
    if helm_path:
        try:
            helm_result = subprocess.run(
                helm + ["list", "-n", config["base"]["namespace"], "-q"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            probe["helm_release_present"] = config["base"]["release"] in (helm_result.stdout or "").splitlines()
        except Exception as exc:  # noqa: BLE001
            probe["warnings"].append(f"helm probe failed: {exc}")

    payload = {"api_version": API_VERSION, "workloads": workloads}
    result = {"discovery": payload, "base_collector_probe": probe}
    if not dry_run:
        discovery_dir.mkdir(parents=True, exist_ok=True)
        write_yaml(discovery_dir / "workloads.yaml", payload)
        write_json(discovery_dir / "base-collector-probe.json", probe)
    return result, 0


def explain(config: dict[str, Any], mode: str) -> str:
    lines = [
        "Splunk Observability Kubernetes Auto-Instrumentation plan",
        f"  Mode: {mode}",
        f"  Output directory: {DEFAULT_OUTPUT_DIR}",
        f"  Realm: {config['realm'] or '<missing>'}",
        f"  Cluster: {config['cluster_name'] or '<auto/missing>'}",
        f"  Environment: {config['deployment_environment'] or '<missing>'}",
        f"  Distribution: {config['distribution']}",
        f"  Instrumentation CRs: {len(config['instrumentation_crs'])}",
        f"  Workload annotations: {len(config['workload_annotations'])}",
        f"  Namespace annotations: {len(config['namespace_annotations'])}",
        f"  OBI enabled: {str(config['obi']['enabled']).lower()}",
        f"  GitOps mode: {str(config['gitops_mode']).lower()}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    for arg in sys.argv[1:]:
        if arg.split("=", 1)[0] in DIRECT_SECRET_FLAGS:
            print(
                f"ERROR: Direct secret flag {arg.split('=', 1)[0]} is not allowed; use the base collector file-based credential flow.",
                file=sys.stderr,
            )
            return 1
    args = parse_args()
    spec_path = Path(args.spec).expanduser().resolve() if args.spec else None
    try:
        spec = load_spec(spec_path)
        config = build_config(args, spec, spec_path)
    except SpecError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir).expanduser().resolve()
    mode = "discover-workloads" if args.discover_workloads else args.mode
    if args.explain:
        print(explain(config, mode), end="")
        return 0
    if mode == "discover-workloads":
        payload, code = discover_workloads(config, output_dir, dry_run=args.dry_run)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif args.dry_run:
            print(f"DRY RUN: would write discovery assets under {output_dir / 'discovery'}")
        return code

    errors, warnings, advisories = collect_preflights(config, mode)
    rendered_preview = [
        "k8s-instrumentation/instrumentation-cr.yaml",
        "k8s-instrumentation/workload-annotations.yaml",
        "k8s-instrumentation/annotation-backup-configmap.yaml",
        "metadata.json",
    ]
    if args.dry_run:
        payload = metadata_payload(config, errors, warnings, advisories, rendered_preview, mode)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(preflight_report(errors, warnings, advisories))
            print(f"DRY RUN: would write rendered assets under {output_dir}")
        return 2 if errors else 0

    metadata, code = render_all(config, output_dir, mode)
    if args.json:
        print(json.dumps(metadata, indent=2, sort_keys=True))
    else:
        print(f"Rendered {len(metadata['rendered_files'])} files under {output_dir}")
        if metadata["errors"]:
            print("Preflight verdict: FAIL", file=sys.stderr)
        elif metadata["warnings"]:
            print("Preflight verdict: PASS with warnings")
        else:
            print("Preflight verdict: PASS")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

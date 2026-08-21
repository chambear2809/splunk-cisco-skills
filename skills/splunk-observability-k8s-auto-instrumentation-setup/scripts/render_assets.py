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
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SKILL_NAME = "splunk-observability-k8s-auto-instrumentation-setup"
API_VERSION = f"{SKILL_NAME}/v1"
DEFAULT_OUTPUT_DIR = "splunk-observability-k8s-auto-instrumentation-rendered"
DEFAULT_ENDPOINT = "http://$(SPLUNK_OTEL_AGENT):4317"
DEFAULT_METRICS_ENDPOINT = "http://$(SPLUNK_OTEL_AGENT):9943/v2/datapoint"
DEFAULT_BACKUP_CONFIGMAP = "splunk-otel-auto-instrumentation-annotations-backup"
DISCOVERY_COMMAND_TIMEOUT_SECONDS = 5
# Two vendor statements apply at different layers, so state both rather than
# collapsing them: the chart is production tested (chart README "Current
# Status"), while Operator-related features carry an alpha/experimental notice
# (chart values.yaml). This overlay depends on the Operator the base chart
# deploys, so the caveat applies here too. Keep this text identical to the copy
# in splunk-observability-otel-collector-setup; the two skills are required to
# agree. Sources are recorded in that skill's references/sources.md.
OPERATOR_MATURITY_ADVISORY = (
    "Auto-instrumentation is a supported capability on a production-tested chart, but the chart's "
    "bundled OpenTelemetry Operator packaging carries the vendor's alpha/experimental notice: "
    "breaking changes or outright replacement are reserved, and Operator subchart upgrades can "
    "change injected instrumentation even when your values are unchanged. The chart is the "
    "supported route for injection-based auto-instrumentation, so treat this as a stability "
    "caveat, not a reason to avoid it: keep the chart version pinned exactly, review the Operator "
    "subchart release notes before every upgrade, and diff rendered manifests. To avoid the "
    "Operator dependency entirely, instrument each language runtime directly instead of by "
    "injection."
)
SUPPORTED_LANGUAGES = {
    "java",
    "nodejs",
    "python",
    "dotnet",
    "go",
    "apache-httpd",
    "nginx",
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
# These exact manifest digests are shared with the base Collector skill's
# chart-0.158.0 supply-chain audit. Do not replace them with tags: even a
# concrete-looking registry tag is mutable. Nginx intentionally has no default
# because this repository has no audited Nginx image digest yet.
LANGUAGE_IMAGE_DEFAULTS: dict[str, str | None] = {
    "java": (
        "ghcr.io/signalfx/splunk-otel-java/splunk-otel-java@"
        "sha256:812ad3b45675ef90043020c10e9ed21a3f11ba0903a848e78e3fe71654ae622c"
    ),
    "nodejs": (
        "ghcr.io/signalfx/splunk-otel-js/splunk-otel-js@"
        "sha256:55f93be18e545d98a981bba124fe94a02fdbbb88f1fc471aa08793f7ccba4d78"
    ),
    "python": (
        "quay.io/signalfx/splunk-otel-instrumentation-python@"
        "sha256:d488c507e0cacc64b81423b96f6e53b30f2602a0e4bcc614658182f6aa13d5b4"
    ),
    "dotnet": (
        "ghcr.io/signalfx/splunk-otel-dotnet/splunk-otel-dotnet@"
        "sha256:1b8d96528c8138ef40a20fa0a58db423d653a9bcb7e1fa0fa5ecb83293b8e5bc"
    ),
    "go": (
        "ghcr.io/open-telemetry/opentelemetry-go-instrumentation/autoinstrumentation-go@"
        "sha256:664715c04cb854ffdbb920ea1289a86b0717f39e46b18e6584caa9e1f2e4d83f"
    ),
    "apache-httpd": (
        "ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-apache-httpd@"
        "sha256:a86df0699bf53228588d8e08dbd95e763b7bb377a02fe1d9e68806ef954d04f8"
    ),
    "nginx": None,
}
DIGEST_IMAGE_RE = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")
DNS_LABEL_RE = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")
DNS_SUBDOMAIN_RE = re.compile(
    r"(?=.{1,253}\Z)[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?"
)
SUPPORTED_REALMS = {"us0", "us1", "us2", "us3", "us2-gcp", "au0", "eu0", "eu1", "eu2", "jp0", "sg0"}
SUPPORTED_PROPAGATORS = {
    "tracecontext",
    "baggage",
    "b3",
    "b3multi",
    "jaeger",
    "xray",
    "ottrace",
    "none",
}
SUPPORTED_SAMPLERS = {
    "always_on",
    "always_off",
    "traceidratio",
    "parentbased_always_on",
    "parentbased_always_off",
    "parentbased_traceidratio",
    "jaeger_remote",
    "xray",
}
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
    r"(?i)(access[_-]?token|api[_-]?key|api[_-]?token|authorization|bearer(?:[_-]?token)?|"
    r"hec[_-]?token|org[_-]?token|password|passwd|secret|sf[_-]?token|x-sf-token)"
    r"\s*[:=]\s*[^\s,;}]{4,}"
)
SECRET_KEY_RE = re.compile(
    r"(?i)(access[_-]?token|api[_-]?key|api[_-]?token|authorization|bearer|"
    r"credential|hec(?:[_-]?token)?|org[_-]?token|password|passwd|secret|sf[_-]?token|token)"
)
SECRET_VALUE_RE = re.compile(
    r"(?i)(?:authorization|bearer|x-sf-token)\s*[:= ]\s*\S+|"
    r"(?:access[_-]?token|api[_-]?key|api[_-]?token|hec[_-]?token|password|secret|token)="
)
SAFE_SECRET_REFERENCE_KEYS = {"image_pull_secret", "imagePullSecret", "imagePullSecrets"}


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
    parser.add_argument("--operation-dry-run", action="store_true", help=argparse.SUPPRESS)
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
    parser.add_argument("--multi-instrumentation", action="store_true", help=argparse.SUPPRESS)
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

    parser.add_argument("--operator-watch-namespaces", default="", help=argparse.SUPPRESS)
    parser.add_argument("--webhook-cert-mode", default="", help=argparse.SUPPRESS)
    parser.add_argument("--installation-job-enabled", default="", help=argparse.SUPPRESS)

    parser.add_argument("--enable-obi", action="store_true")
    parser.add_argument("--obi-namespaces", default="")
    parser.add_argument("--obi-exclude-namespaces", default="")
    parser.add_argument("--obi-version", default="")
    parser.add_argument("--obi-image", default="")
    parser.add_argument("--accept-obi-privileged", action="store_true")
    parser.add_argument("--render-openshift-scc", default="")

    parser.add_argument("--annotate-namespace", action="append", default=[])
    parser.add_argument("--annotate-workload", action="append", default=[])
    parser.add_argument("--inventory-file", default="")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--target-all", action="store_true")
    parser.add_argument("--purge-crs", action="store_true")
    parser.add_argument("--purge-obi", action="store_true")
    parser.add_argument("--detect-vendors", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--exclude-vendor", default="", help=argparse.SUPPRESS)
    parser.add_argument("--backup-configmap", default="")
    parser.add_argument("--restore-from-backup", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--purge-backup", action="store_true")
    parser.add_argument("--kube-context", default="")
    parser.add_argument("--allow-current-context", action="store_true")
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


def cli_bool(value: str, *, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise SpecError(f"{label} must be true or false; got {value!r}.")


def normalize_language(value: str) -> str:
    lang = value.strip().lower().replace("_", "-")
    aliases = {"node": "nodejs", "javascript": "nodejs", "js": "nodejs", ".net": "dotnet"}
    lang = aliases.get(lang, lang)
    if lang not in SUPPORTED_LANGUAGES:
        raise SpecError(f"Unsupported language {value!r}. Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}")
    return lang


def normalize_image_overrides(value: Any) -> dict[str, str]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise SpecError("Instrumentation CR images must be a language-to-image mapping.")
    result: dict[str, str] = {}
    for raw_language, raw_image in value.items():
        language = normalize_language(str(raw_language))
        image = str(raw_image or "").strip()
        if not image:
            raise SpecError(f"Instrumentation image override for {language} is empty.")
        result[language] = image
    return result


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
    reject_secret_values(data, path="spec")
    return data


def reject_secret_values(value: Any, *, path: str) -> None:
    """Reject credential material and credential-shaped configuration recursively.

    The sole exception is the name of an existing Kubernetes image-pull Secret.
    This renderer never reads or renders the Secret's data.
    """

    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            if key not in SAFE_SECRET_REFERENCE_KEYS and SECRET_KEY_RE.search(key):
                raise SpecError(
                    f"{child_path} is a secret-like key; credential values are not accepted by this skill."
                )
            reject_secret_values(child, path=child_path)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            reject_secret_values(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and (TOKEN_SHAPED_RE.search(value) or SECRET_VALUE_RE.search(value)):
        raise SpecError(
            f"{path} contains a secret-like value; use the base collector's file-backed credential flow."
        )


def validate_dns_label(value: Any, *, label: str) -> str:
    text = str(value or "")
    if not DNS_LABEL_RE.fullmatch(text):
        raise SpecError(f"{label} must be a Kubernetes DNS-1123 label (1-63 characters); got {text!r}.")
    return text


def validate_dns_subdomain(value: Any, *, label: str) -> str:
    text = str(value or "")
    if not DNS_SUBDOMAIN_RE.fullmatch(text) or any(
        not DNS_LABEL_RE.fullmatch(part) for part in text.split(".")
    ):
        raise SpecError(
            f"{label} must be a Kubernetes DNS-1123 subdomain (1-253 characters); got {text!r}."
        )
    return text


def validate_endpoint(value: Any, *, label: str) -> str:
    endpoint = str(value or "").strip()
    if not endpoint or endpoint != str(value):
        raise SpecError(f"{label} must be a nonempty URL without surrounding whitespace.")
    if TOKEN_SHAPED_RE.search(endpoint) or SECRET_VALUE_RE.search(endpoint):
        raise SpecError(f"{label} contains credential material; OTLP URLs must be credential-free.")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise SpecError(f"{label} is not a valid OTLP URL: {exc}.") from exc
    if parsed.scheme not in {"http", "https"}:
        raise SpecError(f"{label} must use http or https.")
    if parsed.username is not None or parsed.password is not None:
        raise SpecError(f"{label} must not contain userinfo or credentials.")
    if parsed.query or parsed.fragment:
        raise SpecError(f"{label} must not contain a query string or fragment.")
    if not parsed.hostname or port is None:
        raise SpecError(f"{label} must include a host and explicit port.")
    hostname = parsed.hostname
    if hostname != "$(splunk_otel_agent)" and not (
        DNS_SUBDOMAIN_RE.fullmatch(hostname)
        and all(DNS_LABEL_RE.fullmatch(part) for part in hostname.split("."))
    ):
        # Permit IP literals while rejecting shell syntax and malformed names.
        try:
            import ipaddress

            ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise SpecError(f"{label} has an invalid or unsafe host {hostname!r}.") from exc
    return endpoint


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
        if key in result:
            raise SpecError(f"{label} repeats key {key!r}.")
        result[key] = val
    return result


def parse_nested_lang_env(values: list[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for item in values:
        lang, rest = parse_key_value(item, label="--extra-env")
        lang = normalize_language(lang)
        key, val = parse_key_value(rest, label="--extra-env value")
        if SECRET_KEY_RE.search(key) or TOKEN_SHAPED_RE.search(val) or SECRET_VALUE_RE.search(val):
            raise SpecError(
                f"--extra-env {lang}={key}=... is secret-like; credential values are not accepted."
            )
        if key in result.setdefault(lang, {}):
            raise SpecError(f"--extra-env repeats {lang} key {key!r}.")
        result[lang][key] = val
    return result


def parse_resource_limits(values: list[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for item in values:
        lang, rest = parse_key_value(item, label="--resource-limits")
        lang = normalize_language(lang)
        limits: dict[str, str] = {}
        for part in split_csv(rest):
            key, val = parse_key_value(part, label="--resource-limits value")
            if key not in {"cpu", "memory"}:
                raise SpecError(f"--resource-limits supports only cpu and memory; got {key!r}.")
            if key in limits:
                raise SpecError(f"--resource-limits repeats {lang} key {key!r}.")
            if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eEinumkKMGTP]*[-+]?[0-9]*)?", val):
                raise SpecError(f"--resource-limits {lang} {key} has invalid Kubernetes quantity {val!r}.")
            limits[key] = val
        if lang in result:
            raise SpecError(f"--resource-limits repeats language {lang!r}.")
        result[lang] = limits
    return result


def string_mapping(value: Any, *, label: str) -> dict[str, str]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise SpecError(f"{label} must be a mapping.")
    result: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(item, (dict, list, tuple, set)) or item is None:
            raise SpecError(f"{label}.{key} must be a scalar value.")
        result[str(key)] = str(item).lower() if isinstance(item, bool) else str(item)
    return result


def language_nested_mapping(value: Any, *, label: str) -> dict[str, dict[str, str]]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise SpecError(f"{label} must be a language-to-mapping object.")
    result: dict[str, dict[str, str]] = {}
    for raw_language, raw_mapping in value.items():
        language = normalize_language(str(raw_language))
        result[language] = string_mapping(raw_mapping, label=f"{label}.{language}")
    return result


def language_string_mapping(value: Any, *, label: str) -> dict[str, str]:
    mapping = string_mapping(value, label=label)
    result: dict[str, str] = {}
    for raw_language, item in mapping.items():
        language = normalize_language(raw_language)
        if language in result:
            raise SpecError(f"{label} repeats normalized language {language!r}.")
        result[language] = item
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
    root_sampler = spec.get("sampler") or {}
    if not isinstance(root_sampler, dict):
        raise SpecError("sampler must be an object.")

    namespace = args.namespace or first_value(spec, "namespace", default="splunk-otel")
    base_namespace = args.base_namespace or first_value(base, "namespace", default=namespace)
    base_release = args.base_release or first_value(base, "release", default="splunk-otel-collector")
    distribution = args.distribution or first_value(spec, "distribution", default="generic")
    gateway_endpoint = args.gateway_endpoint or first_value(spec, "gateway_endpoint", "gatewayEndpoint", default="")
    agent_endpoint = args.agent_endpoint or first_value(spec, "agent_endpoint", "agentEndpoint", default=DEFAULT_ENDPOINT)
    endpoint = gateway_endpoint or agent_endpoint
    per_language_endpoint = language_string_mapping(
        first_value(spec, "per_language_endpoint", "perLanguageEndpoint", default={}),
        label="per_language_endpoint",
    )
    per_language_endpoint.update(parse_mapping_flags(args.per_language_endpoint, label="--per-language-endpoint"))

    cli_languages = [normalize_language(lang) for lang in split_csv(args.languages)]
    spec_crs = first_value(spec, "instrumentation_crs", "instrumentationCRs", default=[])
    if (
        args.instrumentation_cr_name
        and isinstance(spec_crs, list)
        and len([row for row in spec_crs if isinstance(row, dict)]) > 1
    ):
        raise SpecError(
            "--instrumentation-cr-name is valid only with one Instrumentation CR; "
            "name each CR independently in the multi-CR spec."
        )
    crs: list[dict[str, Any]] = []
    if isinstance(spec_crs, list) and spec_crs:
        for index, row in enumerate(spec_crs):
            if not isinstance(row, dict):
                raise SpecError(f"instrumentation_crs[{index}] must be an object.")
            row_sampler = row.get("sampler") or {}
            if not isinstance(row_sampler, dict):
                raise SpecError(f"instrumentation_crs[{index}].sampler must be an object.")
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
                    # An explicit CLI namespace is a global override. This is
                    # intentionally different from an omitted flag, which
                    # preserves each CR's spec namespace.
                    "namespace": str(args.namespace or row.get("namespace") or namespace),
                    "languages": cr_languages,
                    "endpoint": str(row.get("endpoint") or endpoint),
                    "per_language_endpoint": {
                        **language_string_mapping(
                            row.get("per_language_endpoint") or row.get("perLanguageEndpoint") or {},
                            label=f"instrumentation_crs[{index}].per_language_endpoint",
                        ),
                        **per_language_endpoint,
                    },
                    "propagators": split_csv(args.propagators) or split_csv(row.get("propagators")) or ["tracecontext", "baggage", "b3"],
                    "sampler": {
                        "type": args.sampler
                        or row_sampler.get("type")
                        or row.get("sampler_type")
                        or "parentbased_always_on",
                        "argument": args.sampler_argument
                        if args.sampler_argument != ""
                        else row_sampler.get("argument", row.get("sampler_argument", "")),
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
                        **string_mapping(
                            row.get("extra_resource_attrs") or row.get("extraResourceAttrs") or {},
                            label=f"instrumentation_crs[{index}].extra_resource_attrs",
                        ),
                        **parse_mapping_flags(args.extra_resource_attr, label="--extra-resource-attr"),
                    },
                    "images": normalize_image_overrides(row.get("images")),
                    "extra_env": language_nested_mapping(
                        row.get("extra_env") or row.get("extraEnv") or {},
                        label=f"instrumentation_crs[{index}].extra_env",
                    ),
                    "resource_limits": language_nested_mapping(
                        row.get("resource_limits") or row.get("resourceLimits") or {},
                        label=f"instrumentation_crs[{index}].resource_limits",
                    ),
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
                    or root_sampler.get("type")
                    or first_value(spec, "sampler_type", "samplerType", default="parentbased_always_on"),
                    "argument": args.sampler_argument
                    if args.sampler_argument != ""
                    else root_sampler.get("argument", first_value(spec, "sampler_argument", "samplerArgument", default="")),
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
    unsupported_operator_controls: list[str] = []
    for key in (
        "watch_namespaces",
        "watchNamespaces",
        "webhook_cert_mode",
        "webhookCertMode",
        "installation_job_enabled",
        "installationJobEnabled",
        "multi_instrumentation",
        "multiInstrumentation",
    ):
        if key in operator:
            unsupported_operator_controls.append(f"operator.{key}")
    if args.operator_watch_namespaces:
        unsupported_operator_controls.append("--operator-watch-namespaces")
    if args.webhook_cert_mode:
        unsupported_operator_controls.append("--webhook-cert-mode")
    if args.installation_job_enabled:
        unsupported_operator_controls.append("--installation-job-enabled")
    if args.multi_instrumentation:
        unsupported_operator_controls.append("--multi-instrumentation")
    if first_value(spec, "multi_instrumentation", "multiInstrumentation", default=None) is not None:
        unsupported_operator_controls.append("multi_instrumentation")
    render_scc_default = distribution == "openshift" and (args.enable_obi or boolish(obi_spec.get("enabled"), False))
    render_scc = render_scc_default
    if args.render_openshift_scc != "":
        render_scc = cli_bool(args.render_openshift_scc, label="--render-openshift-scc")
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
            "unsupported_controls": sorted(set(unsupported_operator_controls)),
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
            "image": args.obi_image or str(obi_spec.get("image") or ""),
            "render_openshift_scc": render_scc,
        },
        "vendors": {
            "detect": args.detect_vendors or boolish(vendors.get("detect"), False),
            "exclude": split_csv(args.exclude_vendor) or split_csv(vendors.get("exclude")),
            "requested": bool(vendors) or args.detect_vendors or bool(args.exclude_vendor),
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
        "purge_obi": args.purge_obi,
        "restore_from_backup": args.restore_from_backup,
        "purge_backup": args.purge_backup,
        "accept_auto_instrumentation": args.accept_auto_instrumentation,
        "accept_obi_privileged": args.accept_obi_privileged,
        "operation_dry_run": args.operation_dry_run,
        "kube_context": args.kube_context,
        "allow_current_context": args.allow_current_context,
    }
    reject_secret_values(config, path="render configuration")
    return config


def workload_target(workload: dict[str, Any]) -> str:
    return f"{workload['kind']}/{workload['namespace']}/{workload['name']}"


def workload_key(workload: dict[str, Any]) -> str:
    target = workload_target(workload)
    return f"snapshot-{hashlib.sha256(target.encode('utf-8')).hexdigest()[:20]}"


def bounded_k8s_name(value: str, limit: int) -> str:
    """Mirror the base Collector renderer's collision-resistant name bound."""

    if len(value) <= limit:
        return value.rstrip("-")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{value[: limit - len(digest) - 1].rstrip('-')}-{digest}"


def operator_resource_names(release: str, namespace: str) -> dict[str, str]:
    raw = release if "operator" in release else f"{release}-operator"
    operator_name = bounded_k8s_name(raw, 31)
    return {
        "namespace": namespace,
        "deployment_name": operator_name,
        "webhook_configuration_name": f"{operator_name}-mutation",
        "webhook_service_name": f"{operator_name}-webhook",
    }


def default_cr_reference(config: dict[str, Any]) -> str:
    cr = config["instrumentation_crs"][0]
    return f"{cr['namespace']}/{cr['name']}"


def annotation_value_for(config: dict[str, Any], workload: dict[str, Any]) -> str:
    if boolish(workload.get("disable"), False):
        return "false"
    # Always render an explicit namespace/name binding. A bare "true" makes
    # the Operator search the workload namespace and silently misses the
    # default splunk-otel CR for the common cross-namespace topology.
    return str(workload.get("cr") or default_cr_reference(config))


def workload_annotations_for(config: dict[str, Any], workload: dict[str, Any]) -> dict[str, str]:
    language = normalize_language(str(workload["language"]))
    annotations = {
        f"instrumentation.opentelemetry.io/inject-{language}": annotation_value_for(config, workload)
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


def instrumentation_image(cr: dict[str, Any], language: str) -> str:
    override = str((cr.get("images") or {}).get(language) or "").strip()
    default = LANGUAGE_IMAGE_DEFAULTS[language]
    if override:
        return override
    if default:
        return default
    # collect_preflights reports the actionable error. Keeping an explicit
    # marker in a failed review packet is safer than substituting a mutable tag.
    return "UNRESOLVED-AUDITED-IMAGE"


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
        block: dict[str, Any] = {
            "image": instrumentation_image(cr, language),
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
        "metadata": {
            "name": cr["name"],
            "namespace": cr["namespace"],
            "labels": {
                "app.kubernetes.io/name": "splunk-otel-auto-instrumentation",
                "app.kubernetes.io/managed-by": SKILL_NAME,
            },
        },
        "spec": spec,
    }


def namespace_annotation_docs(config: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, str]] = {}
    for row in config["namespace_annotations"]:
        annotations = grouped.setdefault(str(row["namespace"]), {})
        for language in row["languages"]:
            annotations[f"instrumentation.opentelemetry.io/inject-{language}"] = default_cr_reference(
                config
            )
    docs: list[dict[str, Any]] = []
    for namespace, annotations in grouped.items():
        docs.append(
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": namespace, "annotations": annotations},
            }
        )
    return docs


def namespace_target_records(config: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for document in namespace_annotation_docs(config):
        metadata = document["metadata"]
        annotations = metadata["annotations"]
        languages = sorted(
            key.rsplit("inject-", 1)[1]
            for key in annotations
            if key.startswith("instrumentation.opentelemetry.io/inject-")
        )
        namespace = str(metadata["name"])
        records.append(
            {
                "target": f"Namespace/{namespace}",
                "namespace": namespace,
                "languages": languages,
                "annotations": annotations,
            }
        )
    return records


def workload_annotation_docs(config: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, str]] = {}
    for workload in config["workload_annotations"]:
        identity = (
            str(workload["kind"]),
            str(workload["namespace"]),
            str(workload["name"]),
        )
        annotations = grouped.setdefault(identity, {})
        for key, value in workload_annotations_for(config, workload).items():
            # collect_preflights reports conflicting values. Retain the first
            # value so a failed review packet never silently chooses the last
            # duplicate row.
            annotations.setdefault(key, value)
    docs: list[dict[str, Any]] = []
    for (kind, namespace, name), annotations in grouped.items():
        docs.append(
            {
                "apiVersion": "apps/v1",
                "kind": kind,
                "metadata": {"name": name, "namespace": namespace},
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": annotations,
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


def obi_service_account_doc(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {
            "name": "splunk-obi",
            "namespace": config["namespace"],
            "labels": {
                "app.kubernetes.io/name": "splunk-obi",
                "app.kubernetes.io/managed-by": SKILL_NAME,
            },
        },
    }


def obi_daemonset_doc(config: dict[str, Any]) -> dict[str, Any]:
    obi = config["obi"]
    image = str(obi.get("image") or "UNRESOLVED-AUDITED-OBI-IMAGE")
    env = {
        "SPLUNK_OBI_NAMESPACE_INCLUDE": ",".join(obi.get("namespaces") or []),
        "SPLUNK_OBI_NAMESPACE_EXCLUDE": ",".join(obi.get("exclude_namespaces") or []),
        "OTEL_EXPORTER_OTLP_ENDPOINT": DEFAULT_ENDPOINT,
        "OTEL_RESOURCE_ATTRIBUTES": f"k8s.cluster.name={config['cluster_name']},deployment.environment={config['deployment_environment']}",
    }
    labels = {
        "app.kubernetes.io/name": "splunk-obi",
        "app.kubernetes.io/managed-by": SKILL_NAME,
    }
    return {
        "apiVersion": "apps/v1",
        "kind": "DaemonSet",
        "metadata": {
            "name": "splunk-obi",
            "namespace": config["namespace"],
            "labels": labels,
        },
        "spec": {
            "selector": {"matchLabels": {"app.kubernetes.io/name": "splunk-obi"}},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "serviceAccountName": "splunk-obi",
                    "hostPID": True,
                    "nodeSelector": {"kubernetes.io/os": "linux"},
                    "tolerations": [{"operator": "Exists"}],
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
        {
            "apiVersion": "security.openshift.io/v1",
            "kind": "SecurityContextConstraints",
            "metadata": {
                "name": "splunk-obi-privileged",
                "labels": {
                    "app.kubernetes.io/name": "splunk-obi",
                    "app.kubernetes.io/managed-by": SKILL_NAME,
                },
            },
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


def obi_documents(config: dict[str, Any]) -> list[dict[str, Any]]:
    if not config["obi"]["enabled"]:
        return []
    return [obi_service_account_doc(config), obi_daemonset_doc(config)]


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
                "annotations": workload_annotations_for(config, workload),
                "cr": ""
                if boolish(workload.get("disable"), False)
                else annotation_value_for(config, workload),
            }
        )
    return records


def collect_preflights(config: dict[str, Any], mode: str) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    advisories = [
        OPERATOR_MATURITY_ADVISORY,
        "Instrumentation CR image or env changes require a pod restart to take effect.",
        "Re-running annotation apply/uninstall intentionally starts another workload rollout.",
    ]

    if not config["realm"]:
        errors.append("Missing Splunk Observability realm: pass --realm.")
    elif config["realm"] not in SUPPORTED_REALMS:
        errors.append(
            f"Unsupported Splunk Observability realm {config['realm']!r}; use a documented realm identifier."
        )
    if not config["cluster_name"]:
        errors.append(
            "Missing cluster name: pass --cluster-name explicitly; this offline renderer does not auto-detect cluster identity."
        )
    if not config["deployment_environment"]:
        errors.append("Missing deployment environment: pass --deployment-environment.")
    for value, label in (
        (config["cluster_name"], "cluster name"),
        (config["deployment_environment"], "deployment environment"),
    ):
        text = str(value or "")
        if text and (
            text != text.strip()
            or any(character.isspace() for character in text)
            or any(character in text for character in (",", "=", "\r", "\n", "\x00"))
        ):
            errors.append(f"{label.capitalize()} contains characters unsafe for OTEL_RESOURCE_ATTRIBUTES.")
    for value, label, validator in (
        (config["namespace"], "overlay namespace", validate_dns_label),
        (config["base"]["namespace"], "base collector namespace", validate_dns_label),
        (config["base"]["release"], "base collector release", validate_dns_label),
        (config["backup_configmap"], "backup ConfigMap name", validate_dns_subdomain),
    ):
        try:
            validator(value, label=label)
        except SpecError as exc:
            errors.append(str(exc))
    if config.get("image_pull_secret"):
        try:
            validate_dns_subdomain(config["image_pull_secret"], label="image pull Secret name")
        except SpecError as exc:
            errors.append(str(exc))
    if config["operator"].get("unsupported_controls"):
        errors.append(
            "Operator installation controls are owned by splunk-observability-otel-collector-setup and "
            "cannot be applied by this overlay; remove: "
            + ", ".join(config["operator"]["unsupported_controls"])
            + "."
        )
    if config["vendors"].get("requested"):
        errors.append(
            "Vendor detection/exclusion is not implemented by this offline overlay; remove vendors/"
            "--detect-vendors/--exclude-vendor and perform the documented manual coexistence audit."
        )
    if config.get("restore_from_backup"):
        errors.append(
            "--restore-from-backup is not a standalone overlay control; use uninstall with explicit targets, which always requires the owned transactional snapshot."
        )
    if config["distribution"] == "eks/fargate":
        endpoints = [cr.get("endpoint", "") for cr in config["instrumentation_crs"]]
        if all("SPLUNK_OTEL_AGENT" in endpoint for endpoint in endpoints):
            errors.append("EKS Fargate requires --gateway-endpoint; the DaemonSet agent is not available.")

    seen_crs: set[tuple[str, str]] = set()
    cr_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for cr in config["instrumentation_crs"]:
        key = (cr["namespace"], cr["name"])
        if key in seen_crs:
            errors.append(f"Duplicate Instrumentation CR name: {cr['namespace']}/{cr['name']}.")
        seen_crs.add(key)
        cr_by_identity[key] = cr
        if not cr["languages"] or len(cr["languages"]) != len(set(cr["languages"])):
            errors.append(
                f"Instrumentation CR {cr['namespace']}/{cr['name']} has no languages or repeats a language."
            )
        try:
            validate_dns_label(cr["namespace"], label="Instrumentation CR namespace")
            validate_dns_subdomain(cr["name"], label="Instrumentation CR name")
        except SpecError as exc:
            errors.append(str(exc))
        try:
            validate_endpoint(cr["endpoint"], label=f"Instrumentation CR {cr['namespace']}/{cr['name']} endpoint")
            for language, endpoint in (cr.get("per_language_endpoint") or {}).items():
                normalize_language(str(language))
                validate_endpoint(
                    endpoint,
                    label=f"Instrumentation CR {cr['namespace']}/{cr['name']} {language} endpoint",
                )
        except SpecError as exc:
            errors.append(str(exc))
        propagators = [str(value) for value in cr.get("propagators") or []]
        if (
            not propagators
            or len(propagators) != len(set(propagators))
            or any(value not in SUPPORTED_PROPAGATORS for value in propagators)
            or ("none" in propagators and len(propagators) != 1)
        ):
            errors.append(
                f"Instrumentation CR {cr['namespace']}/{cr['name']} has invalid, duplicate, or incompatible propagators."
            )
        sampler_type = str((cr.get("sampler") or {}).get("type") or "")
        sampler_argument = str((cr.get("sampler") or {}).get("argument") or "")
        if sampler_type not in SUPPORTED_SAMPLERS:
            errors.append(
                f"Instrumentation CR {cr['namespace']}/{cr['name']} has unsupported sampler {sampler_type!r}."
            )
        ratio_samplers = {"traceidratio", "parentbased_traceidratio"}
        if sampler_type in ratio_samplers:
            try:
                ratio = float(sampler_argument)
                if not 0.0 <= ratio <= 1.0:
                    raise ValueError
            except ValueError:
                errors.append(
                    f"Instrumentation CR {cr['namespace']}/{cr['name']} sampler {sampler_type} requires an argument from 0 through 1."
                )
        elif sampler_argument and sampler_type not in {"jaeger_remote"}:
            errors.append(
                f"Instrumentation CR {cr['namespace']}/{cr['name']} sampler {sampler_type} does not accept an argument."
            )
        for attribute_key, attribute_value in (cr.get("extra_resource_attrs") or {}).items():
            key_text, value_text = str(attribute_key), str(attribute_value)
            if (
                not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", key_text)
                or any(character in value_text for character in (",", "=", "\r", "\n", "\x00"))
            ):
                errors.append(
                    f"Instrumentation CR {cr['namespace']}/{cr['name']} has an unsafe resource attribute {key_text!r}."
                )
        for language in cr["languages"]:
            image = instrumentation_image(cr, language)
            if image == "UNRESOLVED-AUDITED-IMAGE":
                errors.append(
                    f"No repository-audited default image exists for {language}; provide "
                    f"instrumentation_crs[].images.{language} or --{language}-image with an @sha256 digest."
                )
            elif not DIGEST_IMAGE_RE.fullmatch(image):
                errors.append(
                    f"Instrumentation image for {cr['namespace']}/{cr['name']} language {language} "
                    "must be pinned by an immutable @sha256 digest."
                )
        unused_images = sorted(set(cr.get("images") or {}) - set(cr["languages"]))
        if unused_images:
            errors.append(
                f"Instrumentation CR {cr['namespace']}/{cr['name']} has image overrides for "
                f"languages it does not enable: {', '.join(unused_images)}."
            )
        for mapping_name in ("per_language_endpoint", "extra_env", "resource_limits"):
            unused = sorted(set(cr.get(mapping_name) or {}) - set(cr["languages"]))
            if unused:
                errors.append(
                    f"Instrumentation CR {cr['namespace']}/{cr['name']} has {mapping_name} entries for disabled languages: {', '.join(unused)}."
                )
        for language, limits in (cr.get("resource_limits") or {}).items():
            if any(key not in {"cpu", "memory"} for key in limits):
                errors.append(
                    f"Instrumentation CR {cr['namespace']}/{cr['name']} {language} resource limits support only cpu and memory."
                )
            for resource, quantity in limits.items():
                if not re.fullmatch(
                    r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eEinumkKMGTP]*[-+]?[0-9]*)?",
                    str(quantity),
                ):
                    errors.append(
                        f"Instrumentation CR {cr['namespace']}/{cr['name']} {language} {resource} has invalid Kubernetes quantity {quantity!r}."
                    )
        if cr.get("profiling_memory_enabled") and not cr.get("profiling_enabled"):
            errors.append(
                f"Instrumentation CR {cr['namespace']}/{cr['name']} enables memory profiling without profiling."
            )
        interval = str(cr.get("profiler_call_stack_interval_ms") or "")
        if interval:
            if not cr.get("profiling_enabled"):
                errors.append(
                    f"Instrumentation CR {cr['namespace']}/{cr['name']} sets a profiler interval while profiling is disabled."
                )
            try:
                interval_value = int(interval)
                if not 1 <= interval_value <= 60000:
                    raise ValueError
            except ValueError:
                errors.append(
                    f"Instrumentation CR {cr['namespace']}/{cr['name']} profiler interval must be an integer from 1 through 60000 ms."
                )

    default_cr = config["instrumentation_crs"][0]
    seen_targets: set[tuple[str, str, str, str]] = set()
    grouped_annotations: dict[tuple[str, str, str], dict[str, str]] = {}
    for workload in config["workload_annotations"]:
        target_key = (
            workload["kind"],
            workload["namespace"],
            workload["name"],
            workload["language"],
        )
        if target_key in seen_targets:
            errors.append(
                f"Duplicate workload/language target: {workload_target(workload)}={workload['language']}."
            )
        seen_targets.add(target_key)
        try:
            validate_dns_label(workload["namespace"], label=f"{workload_target(workload)} namespace")
            validate_dns_subdomain(workload["name"], label=f"{workload_target(workload)} name")
        except SpecError as exc:
            errors.append(str(exc))
        workload_identity = (
            str(workload["kind"]),
            str(workload["namespace"]),
            str(workload["name"]),
        )
        merged = grouped_annotations.setdefault(workload_identity, {})
        for annotation_key, annotation_value in workload_annotations_for(config, workload).items():
            if annotation_key in merged and merged[annotation_key] != annotation_value:
                errors.append(
                    f"{workload_target(workload)} has conflicting values for managed annotation {annotation_key}."
                )
            merged[annotation_key] = annotation_value
        if not boolish(workload.get("disable"), False):
            binding = str(workload.get("cr") or f"{default_cr['namespace']}/{default_cr['name']}")
            binding_parts = binding.split("/")
            bound_cr = cr_by_identity.get(tuple(binding_parts)) if len(binding_parts) == 2 else None
            if bound_cr is None:
                errors.append(
                    f"{workload_target(workload)} references missing Instrumentation CR {binding!r}."
                )
            elif workload["language"] not in bound_cr["languages"]:
                errors.append(
                    f"{workload_target(workload)} binds {workload['language']} to {binding}, "
                    "but that Instrumentation CR does not enable the language."
                )
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

    for row in config["namespace_annotations"]:
        namespace = str(row["namespace"])
        try:
            validate_dns_label(namespace, label="Namespace annotation target")
        except SpecError as exc:
            errors.append(str(exc))
        for language in row["languages"]:
            if language not in default_cr["languages"]:
                errors.append(
                    f"Namespace {namespace} binds {language} to default Instrumentation CR "
                    f"{default_cr['namespace']}/{default_cr['name']}, but that CR does not enable the language."
                )

    if config["obi"]["enabled"] and config["distribution"] == "openshift" and not config["obi"]["render_openshift_scc"]:
        errors.append("OpenShift OBI rendering requires openshift-scc-obi.yaml; do not disable --render-openshift-scc.")
    if config["obi"]["enabled"]:
        for namespace in [
            *(config["obi"].get("namespaces") or []),
            *(config["obi"].get("exclude_namespaces") or []),
        ]:
            try:
                validate_dns_label(namespace, label="OBI namespace selector")
            except SpecError as exc:
                errors.append(str(exc))
        if config["obi"].get("version"):
            errors.append(
                "--obi-version and obi.version are tag-only inputs and are not accepted for production; "
                "use --obi-image with a reviewed @sha256 digest."
            )
        obi_image = str(config["obi"].get("image") or "")
        if not obi_image:
            errors.append(
                "No repository-audited OBI container default exists; --enable-obi requires "
                "--obi-image with a reviewed @sha256 digest."
            )
        elif not DIGEST_IMAGE_RE.fullmatch(obi_image):
            errors.append("OBI image must be pinned by an immutable @sha256 digest.")
    if (
        mode == "apply-instrumentation"
        and not config["operation_dry_run"]
        and not config["accept_auto_instrumentation"]
    ):
        errors.append(
            "--apply-instrumentation requires --accept-auto-instrumentation because CR changes "
            "can alter already-annotated workloads on their next pod creation or restart."
        )
    if mode == "apply-annotations" and not config["accept_auto_instrumentation"]:
        errors.append("--apply-annotations requires --accept-auto-instrumentation.")
    if mode == "uninstall-instrumentation" and not config["accept_auto_instrumentation"]:
        errors.append("--uninstall-instrumentation requires --accept-auto-instrumentation.")
    if mode == "apply-instrumentation" and config["obi"]["enabled"] and not config["accept_obi_privileged"]:
        errors.append("--apply-instrumentation with OBI requires --accept-obi-privileged.")
    if (
        mode in {"apply-instrumentation", "apply-annotations", "uninstall-instrumentation"}
        and not config["operation_dry_run"]
        and not config["kube_context"]
        and not config["allow_current_context"]
    ):
        errors.append(
            f"--{mode} requires --kube-context CTX or the explicit --allow-current-context acknowledgement."
        )
    if config["kube_context"] and config["allow_current_context"]:
        errors.append("--kube-context conflicts with --allow-current-context.")
    if mode in {"apply-annotations", "uninstall-instrumentation"} and (config["target"] or config["target_all"]):
        advisories.append("Targeted apply/uninstall consumes metadata.json from the most recent render.")

    if config["distribution"] == "gke/private":
        warnings.append("GKE Private Cluster requires firewall access to the operator webhook on port 9443.")
    if config["distribution"] == "openshift" and not config["obi"]["render_openshift_scc"] and config["obi"]["enabled"]:
        warnings.append("OpenShift OBI needs an SCC binding for privileged eBPF access.")
    if config["base"]["namespace"] != config["namespace"]:
        warnings.append(
            "Base collector namespace differs from Instrumentation CR namespace; consider a gateway Service DNS endpoint if workloads cannot resolve SPLUNK_OTEL_AGENT."
        )
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
        f"Cluster: `{config['cluster_name'] or '<missing>'}`",
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
            "5. Verify injection: `bash k8s-instrumentation/verify-injection.sh --target <Kind/ns/name>` or run the skill's narrow `scripts/validate.sh --check-injection` diagnostic. Use `scripts/validate.sh --live --check-apm <service>` for the complete production gate.",
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
    cr_lookup = {
        f"{cr['namespace']}/{cr['name']}": cr for cr in config["instrumentation_crs"]
    }
    apm_services: list[dict[str, str]] = []
    seen_apm: set[tuple[str, str]] = set()
    for target in target_records(config):
        if not target.get("cr"):
            continue
        cr = cr_lookup.get(str(target["cr"])) or {}
        language = str(target["language"])
        env = (cr.get("extra_env") or {}).get(language) or {}
        attributes = cr.get("extra_resource_attrs") or {}
        service = str(env.get("OTEL_SERVICE_NAME") or attributes.get("service.name") or target["name"])
        key = (str(target["target"]), service)
        if key in seen_apm:
            continue
        seen_apm.add(key)
        apm_services.append(
            {
                "service": service,
                "target": str(target["target"]),
                "realm": str(config["realm"]),
                "cluster_name": str(config["cluster_name"]),
                "deployment_environment": str(config["deployment_environment"]),
            }
        )
    scc_documents = (
        openshift_scc_docs(config)
        if config["obi"]["enabled"]
        and config["obi"]["render_openshift_scc"]
        and config["distribution"] == "openshift"
        else []
    )
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
        "operator_resources": operator_resource_names(
            str(config["base"]["release"]), str(config["base"]["namespace"])
        ),
        "languages": all_languages,
        "instrumentation_crs": [
            {"name": cr["name"], "namespace": cr["namespace"], "languages": cr["languages"], "endpoint": cr["endpoint"]}
            for cr in config["instrumentation_crs"]
        ],
        "instrumentation_documents": [
            instrumentation_cr_doc(config, cr) for cr in config["instrumentation_crs"]
        ],
        "obi_enabled": bool(config["obi"]["enabled"]),
        "obi_contract": {
            "enabled": bool(config["obi"]["enabled"]),
            "namespace": config["namespace"],
            "documents": obi_documents(config),
            "scc_documents": scc_documents,
            "minimum_kernel": "5.8.0",
            "supported_architectures": ["amd64", "arm64"],
        },
        "backup_configmap": config["backup_configmap"],
        "targets": target_records(config),
        "namespace_targets": namespace_target_records(config),
        "apm_services": apm_services,
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
  --target TARGET                   Kind/namespace/name; audits also accept Namespace/name
  --target-all                      Use every workload from metadata.json
  --accept-auto-instrumentation     Required for live CR/annotation apply and uninstall
  --accept-obi-privileged           Required when applying OBI
  --purge-crs                       Delete rendered Instrumentation CRs during uninstall
  --purge-obi                       Verify ownership then delete rendered OBI resources
  --purge-backup                    Delete the backup ConfigMap during uninstall
  --kube-context NAME               Use a specific kube context
  --allow-current-context           Explicitly acknowledge kubectl's current context
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
    operator = operator_resource_names(
        str(config["base"]["release"]), str(config["base"]["namespace"])
    )
    manifest_args = ['--manifest "${SCRIPT_DIR}/instrumentation-cr.yaml"']
    if config["obi"]["enabled"] and config["obi"]["render_openshift_scc"] and config["distribution"] == "openshift":
        manifest_args.insert(0, '--manifest "${SCRIPT_DIR}/openshift-scc-obi.yaml"')
    if config["obi"]["enabled"]:
        manifest_args.append('--manifest "${SCRIPT_DIR}/obi-daemonset.yaml"')
    manifest_arg_text = " ".join(manifest_args)
    return script_header("Apply Splunk OTel Instrumentation CRs and optional OBI assets") + f"""
DRY_RUN=false
ACCEPT_OBI=false
ACCEPT_AUTO=false
ALLOW_CURRENT_CONTEXT=false
KUBE_CONTEXT={shlex.quote(str(config.get('kube_context') or ''))}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --accept-auto-instrumentation) ACCEPT_AUTO=true; shift ;;
    --accept-obi-privileged) ACCEPT_OBI=true; shift ;;
    --allow-current-context) ALLOW_CURRENT_CONTEXT=true; shift ;;
    --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done
require_metadata
if [[ -n "${{KUBE_CONTEXT}}" && "${{ALLOW_CURRENT_CONTEXT}}" == "true" ]]; then
  echo "ERROR: --kube-context conflicts with --allow-current-context." >&2
  exit 1
fi
if [[ "${{DRY_RUN}}" != "true" && -z "${{KUBE_CONTEXT}}" && "${{ALLOW_CURRENT_CONTEXT}}" != "true" ]]; then
  echo "ERROR: pass --kube-context CTX or explicitly acknowledge --allow-current-context." >&2
  exit 1
fi
if [[ "${{DRY_RUN}}" != "true" && "${{ACCEPT_AUTO}}" != "true" ]]; then
  echo "ERROR: --accept-auto-instrumentation is required because Instrumentation CR changes can affect annotated workloads." >&2
  exit 1
fi
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
if [[ "${{DRY_RUN}}" == "true" ]]; then
  echo "DRY RUN: would preflight exact ownership for every managed SCC, Instrumentation, ServiceAccount, and DaemonSet before race-safe create/replace."
else
  LIFECYCLE_CONTEXT_ARGS=()
  if [[ -n "${{KUBE_CONTEXT}}" ]]; then LIFECYCLE_CONTEXT_ARGS+=(--kube-context "${{KUBE_CONTEXT}}"); fi
  python3 "${{SCRIPT_DIR}}/managed-resource-lifecycle.py" --mode apply \
    {manifest_arg_text} \
    "${{LIFECYCLE_CONTEXT_ARGS[@]+"${{LIFECYCLE_CONTEXT_ARGS[@]}}"}}"
fi
if [[ "${{DRY_RUN}}" != "true" ]]; then
  WEBHOOK_NAMESPACE={shlex.quote(operator['namespace'])}
  WEBHOOK_SERVICE={shlex.quote(operator['webhook_service_name'])}
  echo "Waiting for ${{WEBHOOK_NAMESPACE}}/${{WEBHOOK_SERVICE}} on ready 9443/TCP route evidence..."
  route_source=""
  for _ in $(seq 1 30); do
    use_endpoints=false
    if slices_json="$("${{KUBECTL[@]}}" -n "${{WEBHOOK_NAMESPACE}}" get endpointslice \
      -l "kubernetes.io/service-name=${{WEBHOOK_SERVICE}}" -o json 2>/dev/null)"; then
      if python3 - "endpointslice" "${{WEBHOOK_NAMESPACE}}" "${{WEBHOOK_SERVICE}}" 3<<<"${{slices_json}}" <<'PY'
import json, os, sys
kind, namespace, service = sys.argv[1:]
with os.fdopen(3, encoding="utf-8") as handle:
    payload = json.load(handle)
items = payload.get("items")
if payload.get("kind") not in {{"EndpointSliceList", "List"}} or not isinstance(items, list):
    raise SystemExit(1)
if not items:
    raise SystemExit(3)
for item in items:
    metadata = item.get("metadata") or {{}}
    if (
        item.get("apiVersion") != "discovery.k8s.io/v1"
        or item.get("kind") != "EndpointSlice"
        or metadata.get("namespace") != namespace
        or (metadata.get("labels") or {{}}).get("kubernetes.io/service-name") != service
    ):
        raise SystemExit(1)
ready = any(
    any(
        endpoint.get("conditions", {{}}).get("ready") is True
        and endpoint.get("conditions", {{}}).get("terminating") is not True
        and bool(endpoint.get("addresses"))
        for endpoint in (item.get("endpoints") or [])
    )
    and any(
        port.get("name") in (None, "", "webhook-server")
        and port.get("protocol", "TCP") == "TCP"
        and port.get("port") == 9443
        for port in (item.get("ports") or [])
    )
    for item in items
)
raise SystemExit(0 if ready else 1)
PY
      then
        route_source="endpointslice"
        break
      else
        slice_status=$?
        if [[ ${{slice_status}} -eq 3 ]]; then use_endpoints=true; fi
      fi
    else
      use_endpoints=true
    fi
    if [[ "${{use_endpoints}}" == "true" ]] \
      && endpoints_json="$("${{KUBECTL[@]}}" -n "${{WEBHOOK_NAMESPACE}}" get endpoints "${{WEBHOOK_SERVICE}}" -o json 2>/dev/null)" \
      && python3 - "endpoints" "${{WEBHOOK_NAMESPACE}}" "${{WEBHOOK_SERVICE}}" 3<<<"${{endpoints_json}}" <<'PY'
import json, os, sys
_, namespace, service = sys.argv[1:]
with os.fdopen(3, encoding="utf-8") as handle:
    payload = json.load(handle)
metadata = payload.get("metadata") or {{}}
if (
    payload.get("kind") != "Endpoints"
    or metadata.get("namespace") != namespace
    or metadata.get("name") != service
):
    raise SystemExit(1)
ready = any(
    bool(subset.get("addresses"))
    and any(
        port.get("name") in (None, "", "webhook-server")
        and port.get("protocol", "TCP") == "TCP"
        and port.get("port") == 9443
        for port in (subset.get("ports") or [])
    )
    for subset in (payload.get("subsets") or [])
)
raise SystemExit(0 if ready else 1)
PY
    then
      route_source="endpoints"
      break
    fi
    sleep 2
  done
  if [[ -z "${{route_source}}" ]]; then
    echo "ERROR: exact Operator webhook Service did not become route-ready on 9443/TCP." >&2
    exit 1
  fi
  echo "Webhook route ready via ${{route_source}}."
fi
"""


def apply_annotations_script(config: dict[str, Any]) -> str:
    head = script_header("Apply Splunk OTel auto-instrumentation workload annotations")
    prelude = (
        f'\nDRY_RUN=false\nACCEPT=false\nTARGET_ALL=false\nALLOW_CURRENT_CONTEXT=false\n'
        f'KUBE_CONTEXT={shlex.quote(str(config.get("kube_context") or ""))}\n'
    )
    body = r"""TARGETS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --accept-auto-instrumentation) ACCEPT=true; shift ;;
    --target) TARGETS+=("$2"); shift 2 ;;
    --target-all) TARGET_ALL=true; shift ;;
    --allow-current-context) ALLOW_CURRENT_CONTEXT=true; shift ;;
    --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done
require_metadata
if [[ -n "${KUBE_CONTEXT}" && "${ALLOW_CURRENT_CONTEXT}" == "true" ]]; then
  echo "ERROR: --kube-context conflicts with --allow-current-context." >&2
  exit 1
fi
if [[ "${DRY_RUN}" != "true" && -z "${KUBE_CONTEXT}" && "${ALLOW_CURRENT_CONTEXT}" != "true" ]]; then
  echo "ERROR: pass --kube-context CTX or explicitly acknowledge --allow-current-context." >&2
  exit 1
fi
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
SELECTION_ARGS=()
if [[ "${TARGET_ALL}" == "true" ]]; then SELECTION_ARGS+=(--target-all); fi
for target in "${TARGETS[@]+"${TARGETS[@]}"}"; do SELECTION_ARGS+=(--target "${target}"); done
CONTEXT_ARGS=()
if [[ -n "${KUBE_CONTEXT}" ]]; then CONTEXT_ARGS+=(--kube-context "${KUBE_CONTEXT}"); fi
if [[ "${DRY_RUN}" != "true" ]]; then
  PLAN_JSON="$(python3 "${SCRIPT_DIR}/annotation-backup.py" \
    --mode capture --metadata "${METADATA}" \
    "${CONTEXT_ARGS[@]+"${CONTEXT_ARGS[@]}"}" \
    "${SELECTION_ARGS[@]+"${SELECTION_ARGS[@]}"}")"
else
  echo "DRY RUN: would transactionally capture and verify every selected managed annotation before patching."
  PLAN_JSON="$(python3 "${SCRIPT_DIR}/annotation-backup.py" \
    --mode apply-plan --metadata "${METADATA}" \
    "${SELECTION_ARGS[@]+"${SELECTION_ARGS[@]}"}")"
fi
while IFS=$'\t' read -r kind namespace name patch; do
  [[ -n "${kind}" ]] || continue
  run_cmd "${KUBECTL[@]}" -n "${namespace}" patch "${kind}" "${name}" --type strategic -p "${patch}"
  run_cmd "${KUBECTL[@]}" -n "${namespace}" rollout restart "${kind}/${name}"
  if [[ "${DRY_RUN}" != "true" ]]; then
    "${KUBECTL[@]}" -n "${namespace}" rollout status "${kind}/${name}"
  fi
done < <(python3 - "$PLAN_JSON" <<'PY'
import json, sys
for row in json.loads(sys.argv[1]):
    print("\t".join([row["kind"], row["namespace"], row["name"], json.dumps(row["patch"])]))
PY
)
"""
    return head + prelude + body


def uninstall_script(config: dict[str, Any]) -> str:
    head = script_header("Uninstall Splunk OTel auto-instrumentation annotations and CRs")
    prelude = (
        f'\nDRY_RUN=false\nACCEPT=false\nTARGET_ALL=false\nPURGE_CRS=false\nPURGE_OBI=false\nPURGE_BACKUP=false\nALLOW_CURRENT_CONTEXT=false\n'
        f'KUBE_CONTEXT={shlex.quote(str(config.get("kube_context") or ""))}\n'
    )
    body = r"""TARGETS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --accept-auto-instrumentation) ACCEPT=true; shift ;;
    --target) TARGETS+=("$2"); shift 2 ;;
    --target-all) TARGET_ALL=true; shift ;;
    --purge-crs) PURGE_CRS=true; shift ;;
    --purge-obi) PURGE_OBI=true; shift ;;
    --purge-backup) PURGE_BACKUP=true; shift ;;
    --allow-current-context) ALLOW_CURRENT_CONTEXT=true; shift ;;
    --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done
require_metadata
if [[ -n "${KUBE_CONTEXT}" && "${ALLOW_CURRENT_CONTEXT}" == "true" ]]; then
  echo "ERROR: --kube-context conflicts with --allow-current-context." >&2
  exit 1
fi
if [[ "${DRY_RUN}" != "true" && -z "${KUBE_CONTEXT}" && "${ALLOW_CURRENT_CONTEXT}" != "true" ]]; then
  echo "ERROR: pass --kube-context CTX or explicitly acknowledge --allow-current-context." >&2
  exit 1
fi
if [[ "${ACCEPT}" != "true" ]]; then
  echo "ERROR: --accept-auto-instrumentation is required because this restarts pods." >&2
  exit 1
fi
if [[ "${TARGET_ALL}" != "true" && ${#TARGETS[@]} -eq 0 \
  && "${PURGE_CRS}" != "true" && "${PURGE_OBI}" != "true" && "${PURGE_BACKUP}" != "true" ]]; then
  echo "ERROR: select workload targets or an explicit --purge-* operation." >&2
  exit 1
fi
KUBECTL=(kubectl)
if [[ -n "${KUBE_CONTEXT}" ]]; then KUBECTL+=(--context "${KUBE_CONTEXT}"); fi
if [[ "${TARGET_ALL}" == "true" || ${#TARGETS[@]} -gt 0 ]]; then
  SELECTION_ARGS=()
  if [[ "${TARGET_ALL}" == "true" ]]; then SELECTION_ARGS+=(--target-all); fi
  for target in "${TARGETS[@]+"${TARGETS[@]}"}"; do SELECTION_ARGS+=(--target "${target}"); done
  CONTEXT_ARGS=()
  if [[ -n "${KUBE_CONTEXT}" ]]; then CONTEXT_ARGS+=(--kube-context "${KUBE_CONTEXT}"); fi
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "DRY RUN: would require a complete, owned rollback snapshot before restoring selected workloads."
  else
    PLAN_JSON="$(python3 "${SCRIPT_DIR}/annotation-backup.py" \
      --mode restore-plan --metadata "${METADATA}" \
      "${CONTEXT_ARGS[@]+"${CONTEXT_ARGS[@]}"}" \
      "${SELECTION_ARGS[@]+"${SELECTION_ARGS[@]}"}")"
    while IFS=$'\t' read -r kind namespace name patch; do
      [[ -n "${kind}" ]] || continue
      "${KUBECTL[@]}" -n "${namespace}" patch "${kind}" "${name}" --type strategic -p "${patch}"
      "${KUBECTL[@]}" -n "${namespace}" rollout restart "${kind}/${name}"
      "${KUBECTL[@]}" -n "${namespace}" rollout status "${kind}/${name}"
    done < <(python3 - "$PLAN_JSON" <<'PY'
import json, sys
for row in json.loads(sys.argv[1]):
    print("\t".join([row["kind"], row["namespace"], row["name"], json.dumps(row["patch"])]))
PY
)
  fi
fi
"""
    # The empty interpolation makes this one f-string while doubled braces emit
    # the literal Bash parameter-expansion syntax used by the rendered helper.
    tail = f"""{''}if [[ "${{PURGE_CRS}}" == "true" ]]; then
  if [[ "${{DRY_RUN}}" == "true" ]]; then
    echo "DRY RUN: would verify exact Instrumentation ownership then delete with UID/resourceVersion preconditions."
  else
    CR_CONTEXT_ARGS=()
    if [[ -n "${{KUBE_CONTEXT}}" ]]; then CR_CONTEXT_ARGS+=(--kube-context "${{KUBE_CONTEXT}}"); fi
    python3 "${{SCRIPT_DIR}}/managed-resource-lifecycle.py" --mode delete --manifest "${{SCRIPT_DIR}}/instrumentation-cr.yaml" "${{CR_CONTEXT_ARGS[@]+"${{CR_CONTEXT_ARGS[@]}}"}}"
  fi
fi
if [[ "${{PURGE_OBI}}" == "true" ]]; then
  if [[ "${{DRY_RUN}}" == "true" ]]; then
    echo "DRY RUN: would verify exact OBI ownership/config then delete DaemonSet, optional SCC, and ServiceAccount."
  else
    OBI_CONTEXT_ARGS=()
    if [[ -n "${{KUBE_CONTEXT}}" ]]; then OBI_CONTEXT_ARGS+=(--kube-context "${{KUBE_CONTEXT}}"); fi
    python3 "${{SCRIPT_DIR}}/obi-lifecycle.py" --mode purge --metadata "${{METADATA}}" "${{OBI_CONTEXT_ARGS[@]+"${{OBI_CONTEXT_ARGS[@]}}"}}"
  fi
fi
if [[ "${{PURGE_BACKUP}}" == "true" ]]; then
  if [[ "${{DRY_RUN}}" == "true" ]]; then
    echo "DRY RUN: would require every owned snapshot before deleting the backup ConfigMap."
  else
    BACKUP_CONTEXT_ARGS=()
    if [[ -n "${{KUBE_CONTEXT}}" ]]; then BACKUP_CONTEXT_ARGS+=(--kube-context "${{KUBE_CONTEXT}}"); fi
    python3 "${{SCRIPT_DIR}}/annotation-backup.py" --mode purge --metadata "${{METADATA}}" --target-all "${{BACKUP_CONTEXT_ARGS[@]+"${{BACKUP_CONTEXT_ARGS[@]}}"}}"
  fi
fi
"""
    return head + prelude + body + tail


def verify_injection_script(config: dict[str, Any]) -> str:
    return script_header("Verify Splunk OTel auto-instrumentation injection for rendered workloads") + f"""
TARGET_ALL=false
TARGETS=()
ALLOW_CURRENT_CONTEXT=false
KUBE_CONTEXT={shlex.quote(str(config.get('kube_context') or ''))}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) [[ $# -ge 2 ]] || {{ echo "ERROR: --target requires a value." >&2; exit 1; }}; TARGETS+=("$2"); shift 2 ;;
    --target-all) TARGET_ALL=true; shift ;;
    --allow-current-context) ALLOW_CURRENT_CONTEXT=true; shift ;;
    --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done
require_metadata
if [[ "${{TARGET_ALL}}" == "true" && ${{#TARGETS[@]}} -gt 0 ]]; then
  echo "ERROR: --target and --target-all are mutually exclusive." >&2
  exit 1
fi
if [[ "${{TARGET_ALL}}" != "true" && ${{#TARGETS[@]}} -eq 0 ]]; then
  echo "ERROR: pass --target Kind/namespace/name or --target-all." >&2
  exit 1
fi
if [[ -n "${{KUBE_CONTEXT}}" && "${{ALLOW_CURRENT_CONTEXT}}" == "true" ]]; then
  echo "ERROR: --kube-context conflicts with --allow-current-context." >&2
  exit 1
fi
if [[ -z "${{KUBE_CONTEXT}}" && "${{ALLOW_CURRENT_CONTEXT}}" != "true" ]]; then
  echo "ERROR: pass --kube-context CTX or explicitly acknowledge --allow-current-context." >&2
  exit 1
fi
command -v python3 >/dev/null 2>&1 || {{ echo "ERROR: python3 is required." >&2; exit 1; }}
command -v kubectl >/dev/null 2>&1 || {{ echo "ERROR: kubectl is required." >&2; exit 1; }}
AUDIT_ARGS=(--output-dir "${{OUTPUT_DIR}}")
if [[ -n "${{KUBE_CONTEXT}}" ]]; then AUDIT_ARGS+=(--kube-context "${{KUBE_CONTEXT}}"); fi
if [[ "${{ALLOW_CURRENT_CONTEXT}}" == "true" ]]; then AUDIT_ARGS+=(--allow-current-context); fi
if [[ "${{TARGET_ALL}}" == "true" ]]; then AUDIT_ARGS+=(--target-all); fi
for target in "${{TARGETS[@]+"${{TARGETS[@]}}"}}"; do
  AUDIT_ARGS+=(--target "${{target}}")
done
python3 "${{SCRIPT_DIR}}/injection-audit.py" "${{AUDIT_ARGS[@]}}"
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
    return script_header("Audit and list workloads rendered for Splunk OTel auto-instrumentation") + f"""
KUBE_CONTEXT={shlex.quote(str(config.get('kube_context') or ''))}
ALLOW_CURRENT_CONTEXT=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kube-context) [[ $# -ge 2 ]] || {{ echo "ERROR: --kube-context requires a value." >&2; exit 1; }}; KUBE_CONTEXT="$2"; shift 2 ;;
    --allow-current-context) ALLOW_CURRENT_CONTEXT=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done
require_metadata
if [[ -n "${{KUBE_CONTEXT}}" && "${{ALLOW_CURRENT_CONTEXT}}" == "true" ]]; then
  echo "ERROR: --kube-context conflicts with --allow-current-context." >&2
  exit 1
fi
if [[ -z "${{KUBE_CONTEXT}}" && "${{ALLOW_CURRENT_CONTEXT}}" != "true" ]]; then
  echo "ERROR: pass --kube-context CTX or explicitly acknowledge --allow-current-context." >&2
  exit 1
fi
command -v python3 >/dev/null 2>&1 || {{ echo "ERROR: python3 is required." >&2; exit 1; }}
command -v kubectl >/dev/null 2>&1 || {{ echo "ERROR: kubectl is required." >&2; exit 1; }}
AUDIT_ARGS=(--output-dir "${{OUTPUT_DIR}}" --target-all)
if [[ -n "${{KUBE_CONTEXT}}" ]]; then AUDIT_ARGS+=(--kube-context "${{KUBE_CONTEXT}}"); fi
if [[ "${{ALLOW_CURRENT_CONTEXT}}" == "true" ]]; then AUDIT_ARGS+=(--allow-current-context); fi
python3 "${{SCRIPT_DIR}}/injection-audit.py" "${{AUDIT_ARGS[@]}}"
python3 - "${{METADATA}}" <<'PY'
import json, sys
meta = json.load(open(sys.argv[1]))
print("TARGET\\tLANGUAGE\\tCR")
for row in meta.get("targets", []):
    print(f"{{row['target']}}\\t{{row['language']}}\\t{{row.get('cr') or '<default>'}}")
for row in meta.get("namespace_targets", []):
    bindings = sorted(set((row.get("annotations") or {{}}).values()))
    print(f"{{row['target']}}\\t{{','.join(row.get('languages') or [])}}\\t{{','.join(bindings)}}")
PY
"""


def handoff_collector(config: dict[str, Any]) -> str:
    command = (
        "bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh "
        f"--render-k8s --realm {config['realm'] or '<realm>'} "
        f"--cluster-name {config['cluster_name'] or '<cluster>'} "
        f"--distribution {config['distribution']}"
    )
    return f"""#!/usr/bin/env bash
set -euo pipefail

echo "Run the base collector setup first if the Instrumentation CRD is absent:"
printf '%s\n' {shlex.quote(command)}
echo "The base collector includes Operator CRDs unless --skip-operator-crds is set; then return to this skill for Instrumentation CRs and workload annotations."
"""


def handoff_native_ops(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_version": "splunk-observability-native-ops/v1",
        "realm": config["realm"],
        "operations": [
            {
                "kind": "detector",
                "name": "Auto-instrumented services reporting errors",
                "programText": "A = traces.count(filter=filter('sf_environment', %s)).publish()"
                % json.dumps(config["deployment_environment"]),
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
    obi_docs = obi_documents(config)
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
            (
                k8s_dir / "injection-audit.py",
                Path(__file__).with_name("injection_audit.py").read_text(encoding="utf-8"),
                "script",
            ),
            (
                k8s_dir / "annotation-backup.py",
                Path(__file__).with_name("annotation_backup.py").read_text(encoding="utf-8"),
                "script",
            ),
            (
                k8s_dir / "obi-lifecycle.py",
                Path(__file__).with_name("obi_lifecycle.py").read_text(encoding="utf-8"),
                "script",
            ),
            (
                k8s_dir / "managed-resource-lifecycle.py",
                Path(__file__).with_name("managed_resource_lifecycle.py").read_text(encoding="utf-8"),
                "script",
            ),
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

    def run_discovery_probe(command: list[str], label: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                command,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=DISCOVERY_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            probe["warnings"].append(
                f"{label} timed out after {DISCOVERY_COMMAND_TIMEOUT_SECONDS}s; continuing with empty discovery data."
            )
        except Exception as exc:  # noqa: BLE001
            probe["warnings"].append(f"{label} failed: {exc}")
        return None

    if kubectl_path:
        result = run_discovery_probe(
            kubectl + ["get", "deploy,sts,ds", "-A", "-o", "json"],
            "kubectl workload discovery",
        )
        if result is not None:
            if result.returncode == 0:
                try:
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
                except Exception as exc:  # noqa: BLE001
                    probe["warnings"].append(f"kubectl workload discovery failed: {exc}")
            else:
                probe["warnings"].append(result.stderr.strip() or "kubectl workload discovery failed.")
        crd = run_discovery_probe(
            kubectl + ["get", "crd", "instrumentations.opentelemetry.io"],
            "kubectl CRD probe",
        )
        if crd is not None:
            probe["instrumentation_crd_present"] = crd.returncode == 0
    else:
        probe["warnings"].append("kubectl not found on PATH; wrote an empty starter inventory.")
    if helm_path:
        helm_result = run_discovery_probe(
            helm + ["list", "-n", config["base"]["namespace"], "-q"],
            "helm release probe",
        )
        if helm_result is not None:
            probe["helm_release_present"] = config["base"]["release"] in (helm_result.stdout or "").splitlines()

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
        f"  Cluster: {config['cluster_name'] or '<missing>'}",
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

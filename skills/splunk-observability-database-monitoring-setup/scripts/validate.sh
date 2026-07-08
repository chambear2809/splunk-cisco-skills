#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-database-monitoring-rendered"
LIVE=false
LIVE_SINCE="5m"
API=false
COLLECTOR_VALIDATE=false
API_LOOKBACK_SECONDS="600"
API_METRICS=()
API_FILTERS=()

usage() {
    cat <<'EOF'
Splunk Observability Database Monitoring validation

Usage:
  bash skills/splunk-observability-database-monitoring-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR          Rendered output directory
  --live                    Run scoped, read-only Kubernetes checks
  --live-since DURATION     Collector log lookback (default: 5m)
  --collector-validate      Validate config with collector image 0.155.0
  --api                     Require current DBMon metrics in Observability
  --api-metric NAME         Ad-hoc metric to require; repeatable and requires --api-filter.
  --api-filter KEY=VALUE    SignalFlow filter; repeatable and never inferred
  --api-lookback-seconds N  SignalFlow lookback (default: 600)
  --help                    Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --live-since) require_arg "$1" "$#" || exit 1; LIVE_SINCE="$2"; shift 2 ;;
        --collector-validate) COLLECTOR_VALIDATE=true; shift ;;
        --api) API=true; shift ;;
        --api-metric) require_arg "$1" "$#" || exit 1; API_METRICS+=("$2"); shift 2 ;;
        --api-filter) require_arg "$1" "$#" || exit 1; API_FILTERS+=("$2"); shift 2 ;;
        --api-lookback-seconds)
            require_arg "$1" "$#" || exit 1; API_LOOKBACK_SECONDS="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [[ ! -d "${OUTPUT_DIR}" ]]; then log "ERROR: ${OUTPUT_DIR} not found."; exit 1; fi
if ! [[ "${API_LOOKBACK_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
    log "ERROR: --api-lookback-seconds must be a positive integer."
    exit 1
fi

PYTHONPATH="${PROJECT_ROOT}/skills/shared/lib" python3 - "${OUTPUT_DIR}" <<'PY'
from __future__ import annotations

import json
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

from yaml_compat import load_yaml_or_json

out = Path(sys.argv[1])
metadata_path = out / "metadata.json"
if not metadata_path.is_file():
    raise SystemExit(f"ERROR: Missing {metadata_path}")
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
if not isinstance(metadata, dict):
    raise SystemExit("ERROR: metadata.json must contain an object.")
if metadata.get("collector_version") not in {"v0.155.0", "0.155.0"}:
    raise SystemExit("ERROR: DBMon production output must pin collector v0.155.0.")
if metadata.get("chart_version") != "0.155.0":
    raise SystemExit("ERROR: DBMon production output must pin chart 0.155.0.")
realm = str(metadata.get("realm") or "")
if realm not in {"us0", "us1", "eu0", "eu1", "eu2", "au0", "jp0", "sg0"}:
    raise SystemExit(f"ERROR: metadata.json contains unsupported DBMon realm {realm!r}.")
kube_context = str(metadata.get("collector_kube_context") or "")
sizing = metadata.get("sizing_evidence") or {}
if set(sizing) != {
    "peak_cpu_cores",
    "peak_memory_mib",
    "reference",
    "reviewed_at",
    "reviewed_by",
    "target_count",
}:
    raise SystemExit("ERROR: metadata.json sizing_evidence schema is incomplete.")
if (
    int(metadata.get("collector_memory_mib") or 0) < int(sizing["peak_memory_mib"])
    or int(sizing["target_count"]) < int(metadata.get("target_count") or 0)
):
    raise SystemExit("ERROR: rendered collector sizing is below its reviewed evidence.")
cpu_limit = str(metadata.get("collector_cpu_limit") or "")
try:
    cpu_cores = int(cpu_limit[:-1]) / 1000 if cpu_limit.endswith("m") else float(cpu_limit)
except ValueError as exc:
    raise SystemExit("ERROR: metadata collector_cpu_limit is invalid.") from exc
if cpu_cores < float(sizing["peak_cpu_cores"]):
    raise SystemExit("ERROR: rendered collector CPU is below its reviewed evidence.")

targets = metadata.get("targets") or []
if not isinstance(targets, list) or not targets:
    raise SystemExit("ERROR: metadata.json has no DBMon targets.")
allowed_types = {"postgresql", "sqlserver", "oracledb", "mysql", "mariadb"}
target_types = {item.get("type") for item in targets if isinstance(item, dict)}
if not target_types <= allowed_types:
    raise SystemExit(f"ERROR: metadata contains unsupported engines: {sorted(target_types - allowed_types)}")
validation_metrics = metadata.get("validation_metrics") or []
if not isinstance(validation_metrics, list) or not validation_metrics:
    raise SystemExit("ERROR: metadata.json must list validation_metrics.")
validation_probes = metadata.get("validation_probes") or []
if not isinstance(validation_probes, list) or len(validation_probes) != len(targets):
    raise SystemExit("ERROR: metadata.json must contain one validation_probe per target.")
target_identity = {
    item.get("name"): item.get("receiver_id") for item in targets if isinstance(item, dict)
}
target_records = {
    item.get("name"): item for item in targets if isinstance(item, dict)
}
probe_targets = set()
for probe in validation_probes:
    if not isinstance(probe, dict) or set(probe) != {"target", "receiver_id", "metric", "filters"}:
        raise SystemExit("ERROR: metadata.json contains a malformed validation_probe.")
    target_name = probe.get("target")
    if target_name in probe_targets or target_identity.get(target_name) != probe.get("receiver_id"):
        raise SystemExit("ERROR: metadata validation_probe target identity is duplicate or invalid.")
    if (
        probe.get("metric") not in validation_metrics
        or probe.get("metric") != (target_records.get(target_name) or {}).get("validation_metric")
    ):
        raise SystemExit("ERROR: metadata validation_probe metric is not bound to its target.")
    filters = probe.get("filters")
    if not isinstance(filters, list) or not filters:
        raise SystemExit("ERROR: every metadata validation_probe requires target filters.")
    for item in filters:
        if not isinstance(item, dict) or set(item) != {"key", "value"} or not item["key"] or not item["value"]:
            raise SystemExit("ERROR: metadata validation_probe contains a malformed filter.")
    probe_targets.add(target_name)
if probe_targets != set(target_identity):
    raise SystemExit("ERROR: metadata validation_probes do not cover every target.")

coverage_path = out / "coverage.json"
product_validation_path = out / "validation/product-validation.md"
apm_path = out / "apm/query-correlation.md"
for required in (coverage_path, product_validation_path, apm_path):
    if not required.is_file():
        raise SystemExit(f"ERROR: Missing product coverage artifact {required}")
coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
scrape_owner = metadata.get("scrape_owner")
if scrape_owner not in {"kubernetes", "linux", "windows"}:
    raise SystemExit("ERROR: metadata.json must declare one scrape_owner runtime.")
if coverage.get("scrape_owner") != scrape_owner:
    raise SystemExit("ERROR: coverage.json scrape_owner does not match metadata.")
if sorted(coverage.get("engines") or []) != sorted(target_types):
    raise SystemExit("ERROR: coverage.json engine inventory does not match metadata.")
coverage_targets = coverage.get("targets") or []
if sorted(item.get("name") for item in coverage_targets) != sorted(
    item.get("name") for item in targets
):
    raise SystemExit("ERROR: coverage.json target inventory does not match metadata.")
required_product_keys = {
    "overview_queries_samples_metrics_dependencies_metadata",
    "stored_procedures",
    "apm_correlation",
    "ai_assistant",
}
if set((coverage.get("product") or {})) != required_product_keys:
    raise SystemExit("ERROR: coverage.json is missing a DBMon product completion surface.")
for target in targets:
    runbook = out / "prerequisites" / f"{target['name']}.md"
    if not runbook.is_file():
        raise SystemExit(f"ERROR: Missing database prerequisite runbook {runbook}")

# Search for values that are likely real credentials, while allowing the explicit
# placeholder-only Kubernetes Secret stubs and env templates.
secretish = re.compile(
    r"(INLINE_SHOULD_NOT_LEAK|AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._-]{20,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|SuperSecretPassword)",
    re.IGNORECASE,
)
for path in out.rglob("*"):
    if path.is_symlink():
        raise SystemExit(f"ERROR: Rendered output must not contain symlinks: {path}")
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if secretish.search(text):
            raise SystemExit(f"ERROR: Rendered file appears to contain secret material: {path}")

receiver_prefixes = ("postgresql/", "sqlserver/", "oracledb/", "mysql/")
expected_receiver_ids = sorted(
    str(item.get("receiver_id")) for item in targets if isinstance(item, dict)
)
target_by_receiver = {
    str(item.get("receiver_id")): item for item in targets if isinstance(item, dict)
}


def db_receiver_ids(config: dict[str, Any]) -> list[str]:
    receivers = config.get("receivers") or {}
    if not isinstance(receivers, dict):
        raise SystemExit("ERROR: Collector receivers must be a mapping.")
    return sorted(str(key) for key in receivers if str(key).startswith(receiver_prefixes))


def assert_exporter(config: dict[str, Any], source: Path) -> None:
    exporters = config.get("exporters") or {}
    if "otlphttp/dbmon" in exporters:
        raise SystemExit(f"ERROR: {source} uses removed exporter ID otlphttp/dbmon.")
    dbmon = exporters.get("otlp_http/dbmon") or {}
    endpoint = dbmon.get("logs_endpoint", "")
    expected_endpoint = f"https://ingest.{realm}.observability.splunkcloud.com/v3/event"
    if endpoint != expected_endpoint:
        raise SystemExit(f"ERROR: {source} has wrong DBMon logs_endpoint: {endpoint!r}")
    headers = dbmon.get("headers") or {}
    if headers.get("X-splunk-instrumentation-library") != "dbmon":
        raise SystemExit(f"ERROR: {source} is missing the DBMon instrumentation header.")
    token = headers.get("X-SF-Token")
    if not isinstance(token, str) or not re.fullmatch(r"\$\{env:[A-Z][A-Z0-9_]*\}", token):
        raise SystemExit(f"ERROR: {source} DBMon exporter token must be an env reference.")
    queue = dbmon.get("sending_queue") or {}
    batch = queue.get("batch") or {}
    expected = {"flush_timeout": "15s", "max_size": 10485760, "sizer": "bytes"}
    if batch != expected:
        raise SystemExit(f"ERROR: {source} must use the documented DBMon queue batch contract.")
    signalfx = exporters.get("signalfx/dbmon") or {}
    if signalfx.get("realm") != realm or signalfx.get("access_token") != token:
        raise SystemExit(
            f"ERROR: {source} must use an isolated signalfx/dbmon exporter with the "
            "same env-backed token and audited realm."
        )


def assert_dbmon_config(config: dict[str, Any], source: Path) -> None:
    receivers = db_receiver_ids(config)
    if not receivers:
        raise SystemExit(f"ERROR: {source} has no DBMon receiver IDs.")
    if receivers != expected_receiver_ids:
        raise SystemExit(
            f"ERROR: {source} receiver IDs do not match metadata: {receivers!r} != "
            f"{expected_receiver_ids!r}."
        )
    for receiver_id in receivers:
        receiver = (config.get("receivers") or {}).get(receiver_id) or {}
        target = target_by_receiver[receiver_id]
        for field in ("username", "password", "datasource"):
            if field in receiver and not re.fullmatch(
                r"\$\{env:[A-Z][A-Z0-9_]*\}", str(receiver[field])
            ):
                raise SystemExit(
                    f"ERROR: {source} {receiver_id}.{field} must be an env reference."
                )
        query_settings = receiver.get("query_sample_collection") or {}
        max_rows = query_settings.get("max_rows_per_query")
        if isinstance(max_rows, bool) or not isinstance(max_rows, int) or not 1 <= max_rows <= 100:
            raise SystemExit(
                f"ERROR: {source} {receiver_id} must cap query samples at 1..100 rows."
            )
        events = receiver.get("events") or {}
        expected_events = target.get("events") or {}
        for event_name, metadata_name in (
            ("db.server.query_sample", "query_sample"),
            ("db.server.top_query", "top_query"),
        ):
            if (events.get(event_name) or {}).get("enabled") is not expected_events.get(metadata_name):
                raise SystemExit(f"ERROR: {source} {receiver_id} event settings differ from metadata.")
        target_type = target.get("type")
        if target_type in {"postgresql", "mysql", "mariadb"}:
            tls = receiver.get("tls") or {}
            if tls.get("insecure") is not False or tls.get("insecure_skip_verify") is not False:
                raise SystemExit(
                    f"ERROR: {source} {receiver_id} must require TLS and certificate verification."
                )
        elif "tls" in receiver:
            raise SystemExit(
                f"ERROR: {source} {receiver_id} cannot use a generic TLS block; use datasource TLS."
            )
        if target_type in {"sqlserver", "oracledb"}:
            mode = target.get("connection_mode")
            if mode == "datasource" and "datasource" not in receiver:
                raise SystemExit(f"ERROR: {source} {receiver_id} must use an env-backed datasource.")
            if mode == "direct" and not isinstance(target.get("transport_exception"), dict):
                raise SystemExit(
                    f"ERROR: {source} {receiver_id} direct transport lacks reviewed exception evidence."
                )
        if target_type in {"mysql", "mariadb"}:
            attrs = receiver.get("resource_attributes") or {}
            if (attrs.get("mysql.instance.endpoint") or {}).get("enabled") is not True:
                raise SystemExit(
                    f"ERROR: {source} {receiver_id} must emit mysql.instance.endpoint."
                )
        if target_type == "sqlserver" and target.get("platform") in {
            "azure-managed-instance",
            "azure-sql-database",
        }:
            metrics = receiver.get("metrics") or {}
            if (metrics.get("sqlserver.database.count") or {}).get("enabled") is not False:
                raise SystemExit(
                    f"ERROR: {source} {receiver_id} must disable unsupported Azure database.count."
                )
        if target_type == "oracledb":
            expected_wait = bool(expected_events.get("session_wait_sample"))
            actual_wait = (events.get("db.server.session.wait_sample") or {}).get("enabled")
            if actual_wait is not expected_wait:
                raise SystemExit(
                    f"ERROR: {source} {receiver_id} session-wait event differs from metadata."
                )
    assert_exporter(config, source)

    processors_config = config.get("processors") or {}
    limiter = processors_config.get("memory_limiter/dbmon") or {}
    expected_limit = max(128, int(int(metadata["collector_memory_mib"]) * 0.8))
    if limiter.get("check_interval") != "2s" or limiter.get("limit_mib") != expected_limit:
        raise SystemExit(f"ERROR: {source} has an invalid DBMon-owned memory limiter.")
    if processors_config.get("batch/dbmon") != {}:
        raise SystemExit(f"ERROR: {source} must define the isolated batch/dbmon processor.")
    detection = processors_config.get("resourcedetection/dbmon") or {}
    if detection.get("detectors") != ["system"]:
        raise SystemExit(f"ERROR: {source} has an invalid DBMon resource detector.")

    pipelines = ((config.get("service") or {}).get("pipelines") or {})
    if not isinstance(pipelines, dict):
        raise SystemExit(f"ERROR: {source} service.pipelines must be a mapping.")
    metric_pipelines = {
        name: value
        for name, value in pipelines.items()
        if name in {"metrics/dbmon", "metrics/dbmon_core", "metrics/dbmon_mysql"}
    }
    log_pipelines = {
        name: value
        for name, value in pipelines.items()
        if name in {"logs/dbmon", "logs/dbmon_core", "logs/dbmon_mysql"}
    }
    if not metric_pipelines or not log_pipelines:
        raise SystemExit(f"ERROR: {source} is missing DBMon metrics or logs pipelines.")
    if "metrics" in pipelines:
        raise SystemExit(f"ERROR: {source} DBMon fragment must not replace the chart metrics pipeline.")

    metric_receivers: list[str] = []
    log_receivers: list[str] = []
    for name, pipeline in metric_pipelines.items():
        current = list((pipeline or {}).get("receivers") or [])
        metric_receivers.extend(current)
        processors = list((pipeline or {}).get("processors") or [])
        expected = (
            ["memory_limiter/dbmon", "batch/dbmon", "resourcedetection/dbmon", "resource/mysql_service_instance_id"]
            if name.endswith("dbmon_mysql") or (name == "metrics/dbmon" and all(item.startswith("mysql/") for item in current))
            else ["memory_limiter/dbmon", "batch/dbmon"]
        )
        if processors != expected:
            raise SystemExit(f"ERROR: {source} {name} processors are {processors!r}, expected {expected!r}.")
        if list((pipeline or {}).get("exporters") or []) != ["signalfx/dbmon"]:
            raise SystemExit(f"ERROR: {source} {name} must export only through signalfx/dbmon.")
    for name, pipeline in log_pipelines.items():
        current = list((pipeline or {}).get("receivers") or [])
        log_receivers.extend(current)
        processors = list((pipeline or {}).get("processors") or [])
        expected = (
            ["memory_limiter/dbmon", "batch/dbmon", "resource/mysql_service_instance_id"]
            if name.endswith("dbmon_mysql") or (name == "logs/dbmon" and all(item.startswith("mysql/") for item in current))
            else ["memory_limiter/dbmon", "batch/dbmon"]
        )
        if processors != expected:
            raise SystemExit(f"ERROR: {source} {name} processors are {processors!r}, expected {expected!r}.")
        if list((pipeline or {}).get("exporters") or []) != ["otlp_http/dbmon"]:
            raise SystemExit(f"ERROR: {source} {name} must export only through otlp_http/dbmon.")

    if sorted(metric_receivers) != receivers or len(metric_receivers) != len(set(metric_receivers)):
        raise SystemExit(f"ERROR: {source} must assign each DB receiver to one DBMon metrics pipeline.")
    if sorted(log_receivers) != receivers or len(log_receivers) != len(set(log_receivers)):
        raise SystemExit(f"ERROR: {source} must assign each DB receiver to one DBMon logs pipeline.")


def contains_db_receiver(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).startswith(receiver_prefixes) or contains_db_receiver(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(contains_db_receiver(item) for item in value)
    return False


overlay_path = out / "k8s/values.dbmon.clusterreceiver.yaml"
linux_path = out / "linux/collector-dbmon.yaml"
windows_path = out / "windows/collector-dbmon.yaml"
if not any(path.is_file() for path in (overlay_path, linux_path, windows_path)):
    raise SystemExit("ERROR: Missing Kubernetes, Linux, and Windows DBMon collector outputs.")
owner_path = {
    "kubernetes": overlay_path,
    "linux": linux_path,
    "windows": windows_path,
}[scrape_owner]
if not owner_path.is_file():
    raise SystemExit(f"ERROR: scrape_owner {scrape_owner!r} has no rendered platform output.")

if overlay_path.is_file():
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,252}", kube_context):
        raise SystemExit("ERROR: Kubernetes output requires a reviewed collector_kube_context.")
    overlay = load_yaml_or_json(overlay_path.read_text(encoding="utf-8"), source=str(overlay_path))
    if not isinstance(overlay, dict):
        raise SystemExit("ERROR: Kubernetes overlay must be a mapping.")
    forbidden = {"clusterName", "distribution"} & set(overlay)
    if forbidden:
        raise SystemExit(f"ERROR: DBMon overlay must not own chart identity keys: {sorted(forbidden)}")
    splunk_o11y = overlay.get("splunkObservability") or {}
    if isinstance(splunk_o11y, dict) and ({"realm", "accessToken"} & set(splunk_o11y)):
        raise SystemExit("ERROR: DBMon overlay must not replace chart-owned realm or accessToken.")
    cluster = overlay.get("clusterReceiver") or {}
    if not cluster.get("enabled"):
        raise SystemExit("ERROR: Kubernetes overlay must enable clusterReceiver.")
    if "replicas" in cluster:
        raise SystemExit("ERROR: clusterReceiver.replicas is not valid in chart 0.155.0 values.")
    resources = cluster.get("resources") or {}
    expected_memory = f"{metadata['collector_memory_mib']}Mi"
    if (resources.get("limits") or {}).get("memory") != expected_memory:
        raise SystemExit("ERROR: clusterReceiver memory limit does not match audited sizing.")
    if (resources.get("requests") or {}).get("memory") != expected_memory:
        raise SystemExit("ERROR: clusterReceiver memory request does not match audited sizing.")
    if (resources.get("requests") or {}).get("cpu") != (resources.get("limits") or {}).get("cpu"):
        raise SystemExit("ERROR: clusterReceiver CPU request and limit must match audited sizing.")
    if (resources.get("limits") or {}).get("cpu") != metadata["collector_cpu_limit"]:
        raise SystemExit("ERROR: clusterReceiver CPU does not match reviewed sizing evidence.")
    if contains_db_receiver(overlay.get("agent") or {}):
        raise SystemExit("ERROR: Kubernetes overlay must not place DB receivers under agent.")
    extra_envs = cluster.get("extraEnvs") or []
    env_names: list[str] = []
    for entry in extra_envs:
        if not isinstance(entry, dict) or set(entry) != {"name", "valueFrom"}:
            raise SystemExit("ERROR: DBMon clusterReceiver.extraEnvs must use only name/valueFrom.")
        name = str(entry.get("name") or "")
        secret_ref = (entry.get("valueFrom") or {}).get("secretKeyRef") or {}
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name) or not secret_ref.get("name") or not secret_ref.get("key"):
            raise SystemExit("ERROR: DBMon extraEnvs contains an invalid Secret reference.")
        env_names.append(name)
    if len(env_names) != len(set(env_names)):
        raise SystemExit("ERROR: DBMon clusterReceiver.extraEnvs contains duplicate names.")
    image = ((overlay.get("image") or {}).get("otelcol") or {})
    if image.get("repository") != "quay.io/signalfx/splunk-otel-collector":
        raise SystemExit("ERROR: Kubernetes overlay must pin the official collector repository.")
    if image.get("tag") != "0.155.0@sha256:df3c302ca23928d7fb5031e52a174b253b44b14c325bbad9fe4dcab36b7e8efa":
        raise SystemExit("ERROR: Kubernetes overlay must pin the audited collector manifest digest.")
    cluster_config = cluster.get("config") or {}
    assert_dbmon_config(cluster_config, overlay_path)
    k8s_token = (((cluster_config.get("exporters") or {}).get("otlp_http/dbmon") or {}).get("headers") or {}).get("X-SF-Token")
    if k8s_token != "${env:SPLUNK_OBSERVABILITY_ACCESS_TOKEN}":
        raise SystemExit("ERROR: Kubernetes DBMon must reuse the base chart token environment.")
    for required in (
        out / "scripts/apply-dbmon-overlay.sh",
        out / "scripts/rollback-dbmon-k8s.sh",
    ):
        if not required.is_file():
            raise SystemExit(f"ERROR: Missing production action helper {required}")
    overlay_digest = hashlib.sha256(overlay_path.read_bytes()).hexdigest()
    apply_text = (out / "scripts/apply-dbmon-overlay.sh").read_text(encoding="utf-8")
    if overlay_digest not in apply_text:
        raise SystemExit("ERROR: Kubernetes apply helper is not bound to this reviewed overlay.")
    k8s_contract = (
        "ACCEPT_K8S_APPLY",
        "XDG_STATE_HOME:-${HOME:?HOME is required}/.local/state",
        "CHART_SHA256=",
        "previous_manifest_sha256",
        "APPLY_TRANSACTION_ID",
        "fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)",
        "Recreate",
    )
    if any(marker not in apply_text for marker in k8s_contract):
        raise SystemExit("ERROR: Kubernetes apply helper is missing a production transaction guard.")

for path in (linux_path, windows_path):
    if path.is_file():
        config = load_yaml_or_json(path.read_text(encoding="utf-8"), source=str(path))
        if not isinstance(config, dict):
            raise SystemExit(f"ERROR: {path} must contain a mapping.")
        assert_dbmon_config(config, path)
        host_token = (((config.get("exporters") or {}).get("otlp_http/dbmon") or {}).get("headers") or {}).get("X-SF-Token")
        if host_token != "${env:SPLUNK_ACCESS_TOKEN}":
            raise SystemExit(f"ERROR: {path} must use SPLUNK_ACCESS_TOKEN from the guarded host env file.")
        signalfx = (config.get("exporters") or {}).get("signalfx/dbmon") or {}
        if signalfx.get("access_token") != "${env:SPLUNK_ACCESS_TOKEN}" or signalfx.get("realm") != realm:
            raise SystemExit(f"ERROR: {path} has an invalid SignalFx exporter token or realm.")
        fragment_path = path.with_name("collector-dbmon.fragment.yaml")
        if not fragment_path.is_file():
            raise SystemExit(f"ERROR: Missing applied host fragment {fragment_path}")
        fragment = load_yaml_or_json(
            fragment_path.read_text(encoding="utf-8"), source=str(fragment_path)
        )
        if not isinstance(fragment, dict):
            raise SystemExit(f"ERROR: {fragment_path} must contain a mapping.")
        assert_dbmon_config(fragment, fragment_path)
        fragment_token = (((fragment.get("exporters") or {}).get("otlp_http/dbmon") or {}).get("headers") or {}).get("X-SF-Token")
        if fragment_token != "${env:SPLUNK_ACCESS_TOKEN}":
            raise SystemExit(f"ERROR: {fragment_path} has an invalid DBMon token reference.")
        for key in ("receivers", "service"):
            if fragment.get(key) != config.get(key):
                raise SystemExit(f"ERROR: {fragment_path} {key} differs from the validated standalone config.")
        env_template = path.with_name("dbmon.env.template")
        if not env_template.is_file():
            raise SystemExit(f"ERROR: Missing guarded host environment template {env_template}")
        env_text = env_template.read_text(encoding="utf-8")
        memory_match = re.search(r"^SPLUNK_MEMORY_LIMIT_MIB=([0-9]+)$", env_text, re.MULTILINE)
        if not memory_match or int(memory_match.group(1)) < int(metadata["collector_memory_mib"]):
            raise SystemExit(f"ERROR: {env_template} does not enforce collector memory sizing.")
        if path == linux_path and not re.search(r"^SPLUNK_ACCESS_TOKEN=$", env_text, re.MULTILINE):
            raise SystemExit(f"ERROR: {env_template} must contain a blank access-token handoff.")

if linux_path.is_file():
    for required in (
        out / "scripts/apply-dbmon-linux.sh",
        out / "scripts/rollback-dbmon-linux.sh",
        out / "scripts/secure-env.py",
        out / "scripts/audit-base-config.py",
    ):
        if not required.is_file():
            raise SystemExit(f"ERROR: Missing production action helper {required}")
    fragment_path = out / "linux/collector-dbmon.fragment.yaml"
    fragment_digest = hashlib.sha256(fragment_path.read_bytes()).hexdigest()
    linux_apply_text = (out / "scripts/apply-dbmon-linux.sh").read_text(encoding="utf-8")
    if fragment_digest not in linux_apply_text:
        raise SystemExit("ERROR: Linux apply helper is not bound to this reviewed fragment.")
    linux_contract = (
        "ACCEPT_LINUX_APPLY",
        'OTELCOL="/usr/bin/otelcol"',
        '"state_version": 2',
        '"phase": "preparing"',
        'state["phase"] = "applying"',
        "rollback-dbmon-linux.sh",
        "fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)",
        "--synthetic-secrets",
        "cgroup_path.relative_to(mount_root)",
        "memory.limit_in_bytes",
        "cpu.cfs_quota_us",
        "cpuset.cpus.effective",
    )
    if any(marker not in linux_apply_text for marker in linux_contract):
        raise SystemExit("ERROR: Linux apply helper is missing a production transaction guard.")
    linux_rollback_text = (out / "scripts/rollback-dbmon-linux.sh").read_text(
        encoding="utf-8"
    )
    rollback_contract = (
        '"preparing", "applying", "restoring", "validated", "finalizing"',
        'state["phase"] = "finalizing"',
        "finish_without_restore finalizing",
        'state["restore_paths"]',
    )
    if any(marker not in linux_rollback_text for marker in rollback_contract):
        raise SystemExit("ERROR: Linux rollback helper is missing a resumable transaction guard.")

if windows_path.is_file():
    for required in (
        out / "scripts/apply-dbmon-windows.ps1",
        out / "scripts/rollback-dbmon-windows.ps1",
    ):
        if not required.is_file():
            raise SystemExit(f"ERROR: Missing production action helper {required}")

print("Splunk Observability Database Monitoring rendered assets passed static validation.")
PY

if [[ "${COLLECTOR_VALIDATE}" == "true" ]]; then
    cleanup_temporary_config() {
        local status=$?
        if [[ -n "${temporary_config:-}" ]]; then
            rm -f -- "${temporary_config}" || true
            temporary_config=""
        fi
        return "${status}"
    }
    runtime=""
    if command -v docker >/dev/null 2>&1; then runtime="docker"; fi
    if [[ -z "${runtime}" ]] && command -v podman >/dev/null 2>&1; then runtime="podman"; fi
    if [[ -z "${runtime}" ]]; then
        log "ERROR: --collector-validate requires docker or podman."
        exit 1
    fi
    config_path="${OUTPUT_DIR}/linux/collector-dbmon.yaml"
    if [[ ! -f "${config_path}" ]]; then config_path="${OUTPUT_DIR}/windows/collector-dbmon.yaml"; fi
    temporary_config=""
    if [[ ! -f "${config_path}" && -f "${OUTPUT_DIR}/k8s/values.dbmon.clusterreceiver.yaml" ]]; then
        temporary_config="$(mktemp)"
        trap cleanup_temporary_config EXIT
        PYTHONPATH="${PROJECT_ROOT}/skills/shared/lib" python3 - \
            "${OUTPUT_DIR}/k8s/values.dbmon.clusterreceiver.yaml" "${temporary_config}" <<'PY'
import json
import sys
from yaml_compat import load_yaml_or_json

with open(sys.argv[1], encoding="utf-8") as handle:
    values = load_yaml_or_json(handle.read(), source=sys.argv[1])
config = (values.get("clusterReceiver") or {}).get("config") or {}
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    json.dump(config, handle, sort_keys=True)
    handle.write("\n")
PY
        config_path="${temporary_config}"
    fi
    if [[ ! -f "${config_path}" ]]; then
        log "ERROR: --collector-validate requires a rendered collector config."
        exit 1
    fi
    collector_memory_mib="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["collector_memory_mib"])' "${OUTPUT_DIR}/metadata.json")"
    env_args=(-e "SPLUNK_MEMORY_LIMIT_MIB=${collector_memory_mib}")
    while IFS= read -r env_name; do
        [[ -n "${env_name}" ]] && env_args+=(-e "${env_name}=dbmon-static-validation")
    done < <(grep -Eo '\$\{env:[A-Z][A-Z0-9_]*\}' "${config_path}" | sed -E 's/^\$\{env:|\}$//g' | sort -u)
    log "  Validating DBMon config with quay.io/signalfx/splunk-otel-collector:0.155.0"
    "${runtime}" run --rm --network=none \
        -v "${config_path}:/etc/otel/collector/dbmon.yaml:ro" \
        "${env_args[@]}" \
        --entrypoint /otelcol \
        --pull=always \
        quay.io/signalfx/splunk-otel-collector:0.155.0@sha256:df3c302ca23928d7fb5031e52a174b253b44b14c325bbad9fe4dcab36b7e8efa \
        validate --config=/etc/otel/collector/dbmon.yaml
    cleanup_temporary_config
fi

if [[ "${LIVE}" == "true" ]]; then
    [[ -f "${OUTPUT_DIR}/k8s/values.dbmon.clusterreceiver.yaml" ]] || {
        log "ERROR: --live Kubernetes validation requires rendered outputs.kubernetes."; exit 1;
    }
    command -v kubectl >/dev/null 2>&1 || { log "ERROR: kubectl not on PATH."; exit 1; }
    IFS=$'\t' read -r namespace release version kube_context scrape_owner component_pattern < <(python3 - "${OUTPUT_DIR}/metadata.json" <<'PY'
import json, re, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    d = json.load(stream)
components = [
    *(re.escape(str(item["receiver_id"])) for item in d["targets"]),
    r"otlp_http/dbmon",
    r"signalfx/dbmon",
    r"logs/dbmon(_core|_mysql)?",
    r"metrics/dbmon(_core|_mysql)?",
]
print("\t".join((
    d["collector_namespace"],
    d["collector_release_name"],
    str(d["collector_version"]).lstrip("v"),
    d["collector_kube_context"],
    d["scrape_owner"],
    "|".join(components),
)))
PY
    )
    [[ "${scrape_owner}" == "kubernetes" ]] || {
        log "ERROR: --live Kubernetes validation is valid only for a packet whose scrape_owner is kubernetes."
        exit 1
    }
    actual_context="$(kubectl config current-context)"
    [[ "${actual_context}" == "${kube_context}" ]] || {
        log "ERROR: active kube context ${actual_context:-<none>} does not match reviewed context ${kube_context}."
        exit 1
    }
    KUBECTL=(kubectl --context "${kube_context}")
    selector="app=splunk-otel-collector,component=otel-k8s-cluster-receiver,release=${release}"
    log "  Checking DBMon cluster receiver in ${namespace} for release ${release}."
    deployments_json="$("${KUBECTL[@]}" get deployments -n "${namespace}" -l "${selector}" -o json)"
    DEPLOYMENTS_JSON="${deployments_json}" python3 - <<'PY'
import json, os
items = json.loads(os.environ["DEPLOYMENTS_JSON"]).get("items") or []
if len(items) != 1:
    raise SystemExit(f"ERROR: Expected one scoped DBMon Deployment, found {len(items)}.")
if items[0].get("spec", {}).get("replicas") != 1:
    raise SystemExit("ERROR: DBMon cluster-receiver desired replicas must equal one.")
PY
    pods_json="$("${KUBECTL[@]}" get pods -n "${namespace}" -l "${selector}" -o json)"
    pod_runtime="$(PODS_JSON="${pods_json}" python3 - "${version}" <<'PY'
import json, os, sys
expected = sys.argv[1]
d = json.loads(os.environ["PODS_JSON"])
items = d.get("items") or []
if len(items) != 1:
    raise SystemExit(f"ERROR: Expected one scoped DBMon cluster-receiver pod, found {len(items)}.")
pod = items[0]
conditions = {c.get("type"): c.get("status") for c in pod.get("status", {}).get("conditions", [])}
if conditions.get("Ready") != "True":
    raise SystemExit("ERROR: Scoped DBMon cluster-receiver pod is not Ready.")
containers = [
    c for c in pod.get("spec", {}).get("containers", []) if c.get("name") == "otel-collector"
]
audited = (
    "quay.io/signalfx/splunk-otel-collector:0.155.0@"
    "sha256:df3c302ca23928d7fb5031e52a174b253b44b14c325bbad9fe4dcab36b7e8efa"
)
if expected != "0.155.0" or len(containers) != 1 or containers[0].get("image") != audited:
    raise SystemExit("ERROR: Scoped named DBMon collector is not the audited image reference.")
statuses = [
    c for c in pod.get("status", {}).get("containerStatuses", []) if c.get("name") == "otel-collector"
]
allowed_digests = {
    "sha256:df3c302ca23928d7fb5031e52a174b253b44b14c325bbad9fe4dcab36b7e8efa",
    "sha256:4e2c6177302abd3c1146388d4aaf7c1ef9a2f91e0a2aad98e8662b4c559cb15c",
    "sha256:cad9da35f789acae44643db6773059f732e10befcf899bba511122c733271332",
    "sha256:77c6fc369e34127d3a3cc20cfc35bfe28aca717150cae1630faa0330410f7a15",
}
if len(statuses) != 1 or not statuses[0].get("ready") or statuses[0].get("imageID", "").rsplit("@", 1)[-1] not in allowed_digests:
    raise SystemExit("ERROR: Scoped named DBMon collector is not ready at the audited manifest or a platform digest.")
restart_count = statuses[0].get("restartCount")
if isinstance(restart_count, bool) or not isinstance(restart_count, int) or restart_count < 0:
    raise SystemExit("ERROR: Scoped named DBMon collector has an invalid restart count.")
print(f'{pod["metadata"]["name"]}\t{restart_count}')
PY
    )"
    IFS=$'\t' read -r pod_name restart_count <<<"${pod_runtime}"
    if (( restart_count > 1 )); then
        log "ERROR: Scoped DBMon collector restarted more than once; Kubernetes retains only one previous-container log, so the requested validation window cannot be proven complete. Replace the pod and rerun validation."
        exit 1
    fi

    cleanup_live_logs() {
        local status=$?
        if [[ -n "${live_log_dir:-}" ]]; then
            rm -rf -- "${live_log_dir}" || true
            live_log_dir=""
        fi
        return "${status}"
    }
    live_log_dir="$(mktemp -d)"
    trap cleanup_live_logs EXIT
    chmod 700 "${live_log_dir}"
    current_log="$(mktemp "${live_log_dir}/current.XXXXXX")"
    chmod 600 "${current_log}"
    if ! "${KUBECTL[@]}" logs -n "${namespace}" "${pod_name}" -c otel-collector \
        --since="${LIVE_SINCE}" --tail=-1 --limit-bytes=10485761 \
        >"${current_log}" 2>/dev/null; then
        log "ERROR: Could not read scoped DBMon collector logs; output suppressed because it may contain database material."
        exit 1
    fi
    current_bytes="$(wc -c <"${current_log}" | tr -d '[:space:]')"
    if (( current_bytes > 10485760 )); then
        log "ERROR: Scoped current DBMon collector logs exceed the 10 MiB validation bound; narrow --live-since and retry."
        exit 1
    fi

    previous_log=""
    if (( restart_count > 0 )); then
        previous_log="$(mktemp "${live_log_dir}/previous.XXXXXX")"
        chmod 600 "${previous_log}"
        if ! "${KUBECTL[@]}" logs -n "${namespace}" "${pod_name}" -c otel-collector --previous \
            --since="${LIVE_SINCE}" --tail=-1 --limit-bytes=10485761 \
            >"${previous_log}" 2>/dev/null; then
            log "ERROR: Scoped DBMon collector restarted, but previous-container logs are unavailable; raw output is suppressed."
            exit 1
        fi
        previous_bytes="$(wc -c <"${previous_log}" | tr -d '[:space:]')"
        if (( previous_bytes > 10485760 )); then
            log "ERROR: Scoped previous DBMon collector logs exceed the 10 MiB validation bound; narrow --live-since and retry."
            exit 1
        fi
    fi

    combined_log="$(mktemp "${live_log_dir}/combined.XXXXXX")"
    relevant_log="$(mktemp "${live_log_dir}/relevant.XXXXXX")"
    actionable_log="$(mktemp "${live_log_dir}/actionable.XXXXXX")"
    chmod 600 "${combined_log}" "${relevant_log}" "${actionable_log}"
    cat -- "${current_log}" >"${combined_log}"
    if [[ -n "${previous_log}" ]]; then
        printf '\n' >>"${combined_log}"
        cat -- "${previous_log}" >>"${combined_log}"
    fi
    grep -E "${component_pattern}" "${combined_log}" >"${relevant_log}" || true
    grep -Eiv 'postgresqlreceiver@v[0-9.]+/(client|scraper)\.go:[0-9]+[[:space:]]+failed to explain (statement|query)' \
        "${relevant_log}" >"${actionable_log}" || true
    hard_fatal='unauthorized|forbidden|(^|[^0-9])(401|403|429)([^0-9]|$)|too many requests|resource.?exhausted|rate.?limit|throttl|queue.*full|dropp?(ed|ing).*(telemetry|data)|authentication failed|password authentication failed|access denied|login failed|connection refused|connection reset|broken pipe|bad connection|unexpected EOF|server closed the connection|connection (was )?closed|no such host|no route to host|i/o timeout|x509:|certificate.*(invalid|unknown)|failed to export|export(ing)? (failed|failure)|error exporting|unable to export'
    fatal='(^|[[:space:]"=:])(error|fatal)([[:space:]"=:]|$)|(level|severity)["= :]+(error|fatal)|unauthorized|forbidden|(^|[^0-9])(401|403|429)([^0-9]|$)|too many requests|resource.?exhausted|rate.?limit|throttl|queue.*full|dropp?(ed|ing).*(telemetry|data)|authentication failed|access denied|login failed|permission denied|operation not permitted|connection refused|deadline exceeded|no such host|no route to host|i/o timeout|x509:|certificate.*(invalid|unknown)|failed to (start|export|fetch|collect|scrape|connect|query)|export(ing)? (failed|failure)|error (exporting|scraping|reading|collecting|querying)|unable to (export|connect|collect|query)|cannot start|invalid configuration|duplicate scraper|ORA-[0-9]+'
    if grep -Eiq "${hard_fatal}" "${relevant_log}" \
        || grep -Eiq "${fatal}" "${actionable_log}"; then
        log "ERROR: Recent scoped DBMon collector logs contain a critical failure; raw lines are suppressed because they may contain database material."
        exit 1
    fi
    relevant_count="$(awk 'NF {count++} END {print count+0}' "${relevant_log}")"
    cleanup_live_logs
    trap - EXIT
    log "  Scoped runtime validation passed (${relevant_count} DBMon-scoped log lines reviewed; raw content suppressed)."
fi

if [[ "${API}" == "true" ]]; then
    load_observability_cloud_settings
    if [[ -n "${SPLUNK_O11Y_REALM:-}" ]]; then export SPLUNK_O11Y_REALM; fi
    if [[ -n "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then export SPLUNK_O11Y_TOKEN_FILE; fi
    probe_args=(
        --metadata "${OUTPUT_DIR}/metadata.json"
        --lookback-seconds "${API_LOOKBACK_SECONDS}"
    )
    for metric in "${API_METRICS[@]}"; do probe_args+=(--metric "${metric}"); done
    for filter in "${API_FILTERS[@]}"; do probe_args+=(--filter "${filter}"); done
    python3 "${SCRIPT_DIR}/api_probe.py" "${probe_args[@]}"
fi

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-database-monitoring-rendered"
LIVE=false
LIVE_SINCE="2m"
API=false
API_METRIC="postgresql.database.count"
API_LOOKBACK_SECONDS="600"

usage() {
    cat <<'EOF'
Splunk Observability Database Monitoring validation

Usage:
  bash skills/splunk-observability-database-monitoring-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --live             Run read-only kubectl probes when available
  --live-since DURATION
                     Log lookback for --live DBMon error checks (default: 2m)
  --api              Run read-only Splunk Observability API probes
  --api-metric NAME  DBMon metric to query (default: postgresql.database.count)
  --api-lookback-seconds N
                     SignalFlow lookback window for --api (default: 600)
  --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --live-since) require_arg "$1" "$#" || exit 1; LIVE_SINCE="$2"; shift 2 ;;
        --api) API=true; shift ;;
        --api-metric) require_arg "$1" "$#" || exit 1; API_METRIC="$2"; shift 2 ;;
        --api-lookback-seconds) require_arg "$1" "$#" || exit 1; API_LOOKBACK_SECONDS="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [[ ! -d "${OUTPUT_DIR}" ]]; then log "ERROR: ${OUTPUT_DIR} not found."; exit 1; fi

PYTHONPATH="${PROJECT_ROOT}/skills/shared/lib" python3 - "${OUTPUT_DIR}" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

from yaml_compat import load_yaml_or_json

out = Path(sys.argv[1])

required = [
    out / "metadata.json",
    out / "references/gateway-routing.sqlserver.md",
]
for path in required:
    if not path.is_file():
        raise SystemExit(f"ERROR: Missing {path}")

overlay_path = out / "k8s/values.dbmon.clusterreceiver.yaml"
merged_path = out / "k8s/values.dbmon.merged.yaml"
linux_path = out / "linux/collector-dbmon.yaml"
if not overlay_path.is_file() and not linux_path.is_file():
    raise SystemExit("ERROR: Missing both Kubernetes and Linux DBMon collector outputs.")

secretish = re.compile(
    r"(INLINE_SHOULD_NOT_LEAK|AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._-]{20,}|"
    r"your-splunk-access-token|secure-password|SuperSecretPassword)",
    re.IGNORECASE,
)
for path in out.rglob("*"):
    if path.is_file() and secretish.search(path.read_text(encoding="utf-8")):
        raise SystemExit(f"ERROR: Rendered file appears to contain secret material: {path}")

def assert_dbmon_config(config: dict, source: Path) -> None:
    receivers = config.get("receivers") or {}
    receiver_ids = [
        key for key in receivers if key.startswith(("postgresql/", "sqlserver/", "oracledb/"))
    ]
    if not receiver_ids:
        raise SystemExit(f"ERROR: {source} has no DBMon receiver IDs.")
    if any(key.startswith(("mysql", "mariadb")) for key in receivers):
        raise SystemExit(f"ERROR: {source} contains unsupported MySQL/MariaDB receiver.")

    exporters = config.get("exporters") or {}
    dbmon = exporters.get("otlphttp/dbmon") or {}
    endpoint = dbmon.get("logs_endpoint", "")
    if not endpoint.startswith("https://ingest.") or not endpoint.endswith(
        ".observability.splunkcloud.com/v3/event"
    ):
        raise SystemExit(f"ERROR: {source} has wrong DBMon logs_endpoint: {endpoint!r}")
    headers = dbmon.get("headers") or {}
    if headers.get("X-splunk-instrumentation-library") != "dbmon":
        raise SystemExit(f"ERROR: {source} missing X-splunk-instrumentation-library: dbmon")
    if headers.get("X-SF-Token") != "${env:SPLUNK_ACCESS_TOKEN}":
        raise SystemExit(f"ERROR: {source} must use env placeholder for X-SF-Token.")

    pipelines = ((config.get("service") or {}).get("pipelines") or {})
    metrics = pipelines.get("metrics") or {}
    logs = pipelines.get("logs/dbmon") or {}
    if not metrics or not logs:
        raise SystemExit(f"ERROR: {source} must define metrics and logs/dbmon pipelines.")
    for receiver_id in receiver_ids:
        if receiver_id not in metrics.get("receivers", []):
            raise SystemExit(f"ERROR: {source} metrics pipeline missing {receiver_id}.")
        if receiver_id not in logs.get("receivers", []):
            raise SystemExit(f"ERROR: {source} logs/dbmon pipeline missing {receiver_id}.")
    if metrics.get("processors") != logs.get("processors"):
        raise SystemExit(f"ERROR: {source} metrics and logs/dbmon processors must match.")
    if logs.get("exporters") != ["otlphttp/dbmon"]:
        raise SystemExit(f"ERROR: {source} logs/dbmon must export only via otlphttp/dbmon.")

def contains_db_receiver(value) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).startswith(("postgresql/", "sqlserver/", "oracledb/")):
                return True
            if contains_db_receiver(child):
                return True
    if isinstance(value, list):
        return any(contains_db_receiver(item) for item in value)
    return False

def assert_k8s_values(path: Path) -> None:
    overlay = load_yaml_or_json(path.read_text(encoding="utf-8"), source=str(path))
    cluster = overlay.get("clusterReceiver") or {}
    if not cluster.get("enabled"):
        raise SystemExit("ERROR: Kubernetes overlay must enable clusterReceiver.")
    if cluster.get("replicas") != 1:
        raise SystemExit("ERROR: Kubernetes overlay must set clusterReceiver.replicas: 1.")
    if contains_db_receiver(overlay.get("agent") or {}):
        raise SystemExit("ERROR: Kubernetes overlay must not place DB receivers under agent.")
    assert_dbmon_config(cluster.get("config") or {}, path)

if overlay_path.is_file():
    assert_k8s_values(overlay_path)

if merged_path.is_file():
    assert_k8s_values(merged_path)

if linux_path.is_file():
    linux = load_yaml_or_json(linux_path.read_text(encoding="utf-8"), source=str(linux_path))
    assert_dbmon_config(linux, linux_path)

print("Splunk Observability Database Monitoring rendered assets passed static validation.")
PY

if [[ "${LIVE}" == "true" ]]; then
    log "  --live: read-only probe requested."
    if ! command -v kubectl >/dev/null 2>&1; then
        log "  ERROR: kubectl not on PATH."
        exit 1
    fi
    K8S_CLUSTER_RECEIVER_SELECTOR='app=splunk-otel-collector,component in (otel-k8s-cluster-receiver,k8s-cluster-receiver)'
    log "  Splunk OTel cluster receiver pods:"
    kubectl get pods -A -l "${K8S_CLUSTER_RECEIVER_SELECTOR}" 2>&1 | head -5 || true
    CLUSTER_RECEIVER_PODS="$(
        kubectl get pods -A -l "${K8S_CLUSTER_RECEIVER_SELECTOR}" \
            -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\n"}{end}' 2>&1
    )"
    if [[ -z "${CLUSTER_RECEIVER_PODS}" ]]; then
        log "  ERROR: No Splunk OTel cluster receiver pods found."
        exit 1
    fi
    log "  Recent DBMon collector log lines (${LIVE_SINCE}):"
    DBMON_LOG_LINES="$(
        while IFS=$'\t' read -r pod_namespace pod_name; do
            if [[ -n "${pod_namespace}" && -n "${pod_name}" ]]; then
                kubectl logs -n "${pod_namespace}" "${pod_name}" --since="${LIVE_SINCE}" --tail=500 2>&1
            fi
        done <<< "${CLUSTER_RECEIVER_PODS}" \
            | grep -Ei 'dbmon|postgresql|sqlserver|oracledb|unauthorized|authentication|operation not permitted|logs/dbmon|scraper|error|warn' \
            | head -40 || true
    )"
    if [[ -n "${DBMON_LOG_LINES}" ]]; then
        printf '%s\n' "${DBMON_LOG_LINES}"
        if printf '%s\n' "${DBMON_LOG_LINES}" | grep -Eiq 'error|warn|failed|unauthorized|authentication|operation not permitted'; then
            log "  ERROR: Recent DBMon collector log lines include errors."
            exit 1
        fi
    else
        log "  No recent DBMon warning/error log lines found."
    fi
fi

if [[ "${API}" == "true" ]]; then
    log "  --api: probing Splunk Observability metric catalog and SignalFlow."
    load_observability_cloud_settings
    if [[ -n "${SPLUNK_O11Y_REALM:-}" ]]; then
        export SPLUNK_O11Y_REALM
    fi
    if [[ -n "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then
        export SPLUNK_O11Y_TOKEN_FILE
    fi
    python3 "${SCRIPT_DIR}/api_probe.py" \
        --metadata "${OUTPUT_DIR}/metadata.json" \
        --metric "${API_METRIC}" \
        --lookback-seconds "${API_LOOKBACK_SECONDS}"
fi

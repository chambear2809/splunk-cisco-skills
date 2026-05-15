#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/galileo-platform-rendered"

usage() {
    cat <<'EOF'
Galileo Platform Setup validation

Usage:
  bash skills/galileo-platform-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ ! -d "${OUTPUT_DIR}" ]]; then
    log "ERROR: Rendered output directory not found: ${OUTPUT_DIR}"
    exit 1
fi

check_file() {
    local path="$1"
    [[ -f "${path}" ]] || { log "ERROR: Missing ${path}"; exit 1; }
}

check_exec() {
    local path="$1"
    [[ -x "${path}" ]] || { log "ERROR: Missing executable ${path}"; exit 1; }
}

check_file "${OUTPUT_DIR}/apply-plan.json"
check_file "${OUTPUT_DIR}/coverage-report.json"
check_file "${OUTPUT_DIR}/handoff.md"
check_file "${OUTPUT_DIR}/readiness/readiness-report.json"
check_exec "${OUTPUT_DIR}/readiness/healthcheck.sh"
check_file "${OUTPUT_DIR}/runtime/python-opentelemetry-env.sh"
check_file "${OUTPUT_DIR}/runtime/python-galileo-protect.py"
check_file "${OUTPUT_DIR}/evaluate/evaluate-assets.yaml"
check_file "${OUTPUT_DIR}/splunk-platform/hec-event-sample.json"
check_file "${OUTPUT_DIR}/splunk-platform/export-records-request.json"
check_file "${OUTPUT_DIR}/otel/collector-galileo-fanout.yaml"
check_exec "${OUTPUT_DIR}/scripts/apply-readiness.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-observe-export.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-observe-runtime.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-protect-runtime.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-evaluate-assets.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-splunk-hec.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-splunk-otlp.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-otel-collector.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-dashboards.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-detectors.sh"

python3 - "${OUTPUT_DIR}/apply-plan.json" "${OUTPUT_DIR}/coverage-report.json" <<'PY'
import json
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
coverage = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
sections = {item["name"]: item for item in plan["sections"]}
required = {
    "readiness": "galileo-platform-setup",
    "observe-export": "galileo-platform-setup",
    "observe-runtime": "galileo-platform-setup",
    "protect-runtime": "galileo-platform-setup",
    "evaluate-assets": "galileo-platform-setup",
    "splunk-hec": "splunk-hec-service-setup",
    "splunk-otlp": "splunk-connect-for-otlp-setup",
    "otel-collector": "splunk-observability-otel-collector-setup",
    "dashboards": "splunk-observability-dashboard-builder",
    "detectors": "splunk-observability-native-ops",
}
missing = set(required) - set(sections)
if missing:
    raise SystemExit(f"missing apply sections: {sorted(missing)}")
for section, target in required.items():
    if sections[section]["delegates_to"] != target:
        raise SystemExit(f"{section} delegates to {sections[section]['delegates_to']}, expected {target}")
if plan.get("secret_files") is None:
    raise SystemExit("apply plan missing secret_files")
if coverage.get("secret_values_rendered") is not False:
    raise SystemExit("coverage report must assert secret_values_rendered=false")
request = json.loads(Path(sys.argv[1]).with_name("splunk-platform").joinpath("export-records-request.json").read_text(encoding="utf-8"))
if request.get("export_format") != "jsonl":
    raise SystemExit("export_records request must default to jsonl")
for key in ("root_type", "redact", "log_stream_id", "experiment_id", "metrics_testing_id"):
    if key not in request:
        raise SystemExit(f"export_records request missing {key}")
PY

if grep -RIl . "${OUTPUT_DIR}" | xargs grep -E -- 'Authorization:[[:space:]]*(Splunk|Bearer)[[:space:]]+[A-Za-z0-9._=-]{12,}' >/dev/null 2>&1; then
    log "ERROR: Rendered output appears to contain a concrete authorization secret."
    exit 1
fi

log "Galileo Platform Setup rendered assets passed static validation."

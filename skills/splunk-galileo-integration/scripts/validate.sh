#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-galileo-rendered"

usage() {
    cat <<'EOF'
Splunk Galileo Integration validation

Usage:
  bash skills/splunk-galileo-integration/scripts/validate.sh [options]

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
check_file "${OUTPUT_DIR}/runtime/python-opentelemetry-env.sh"
check_file "${OUTPUT_DIR}/splunk-platform/hec-event-sample.json"
check_file "${OUTPUT_DIR}/otel/collector-galileo-fanout.yaml"
check_exec "${OUTPUT_DIR}/scripts/apply-hec-service.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-hec-export.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-otlp-input.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-otel-collector.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-python-runtime.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-kubernetes-runtime.sh"
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
    "hec-service": "splunk-hec-service-setup",
    "hec-export": "splunk-galileo-integration",
    "otlp-input": "splunk-connect-for-otlp-setup",
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
PY

if grep -RIl . "${OUTPUT_DIR}" | xargs grep -E -- 'Authorization:[[:space:]]*(Splunk|Bearer)[[:space:]]+[A-Za-z0-9._=-]{12,}' >/dev/null 2>&1; then
    log "ERROR: Rendered output appears to contain a concrete authorization secret."
    exit 1
fi

log "Splunk Galileo Integration rendered assets passed static validation."

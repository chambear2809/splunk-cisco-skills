#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/galileo-agent-control-rendered"

usage() {
    cat <<'EOF'
Galileo Agent Control Setup validation

Usage:
  bash skills/galileo-agent-control-setup/scripts/validate.sh [options]

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

check_file "${OUTPUT_DIR}/metadata.json"
check_file "${OUTPUT_DIR}/apply-plan.json"
check_file "${OUTPUT_DIR}/coverage-report.json"
check_file "${OUTPUT_DIR}/handoff.md"
check_file "${OUTPUT_DIR}/server/docker-compose.env.example"
check_file "${OUTPUT_DIR}/server/external-server-readiness.md"
check_file "${OUTPUT_DIR}/auth/agent-control-auth.env.example"
check_file "${OUTPUT_DIR}/controls/policy-templates.json"
check_file "${OUTPUT_DIR}/runtime/python-control.py"
check_file "${OUTPUT_DIR}/runtime/typescript-control.ts"
check_file "${OUTPUT_DIR}/sinks/otel-sink.env"
check_file "${OUTPUT_DIR}/sinks/splunk-hec-sink.py"
check_file "${OUTPUT_DIR}/sinks/splunk-hec-event-sample.json"
check_file "${OUTPUT_DIR}/dashboards/agent-control-dashboard.yaml"
check_file "${OUTPUT_DIR}/detectors/agent-control-detectors.yaml"

for script in \
    apply-server.sh \
    apply-auth.sh \
    apply-controls.sh \
    apply-python-runtime.sh \
    apply-typescript-runtime.sh \
    apply-otel-sink.sh \
    apply-splunk-sink.sh \
    apply-splunk-hec.sh \
    apply-otel-collector.sh \
    apply-dashboards.sh \
    apply-detectors.sh \
    apply-selected.sh
do
    check_exec "${OUTPUT_DIR}/scripts/${script}"
done

python3 - "${OUTPUT_DIR}/apply-plan.json" "${OUTPUT_DIR}/coverage-report.json" "${OUTPUT_DIR}/controls/policy-templates.json" <<'PY'
import json
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
coverage = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
controls = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
sections = {item["name"]: item for item in plan["sections"]}
required = {
    "server": "galileo-agent-control-setup",
    "auth": "galileo-agent-control-setup",
    "controls": "galileo-agent-control-setup",
    "python-runtime": "galileo-agent-control-setup",
    "typescript-runtime": "galileo-agent-control-setup",
    "otel-sink": "galileo-agent-control-setup",
    "splunk-sink": "galileo-agent-control-setup",
    "splunk-hec": "splunk-hec-service-setup",
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
if coverage.get("secret_values_rendered") is not False:
    raise SystemExit("coverage report must assert secret_values_rendered=false")
if not controls.get("controls"):
    raise SystemExit("control policy template is empty")
PY

python3 -m py_compile \
    "${OUTPUT_DIR}/runtime/python-control.py" \
    "${OUTPUT_DIR}/sinks/splunk-hec-sink.py"

if grep -RIl . "${OUTPUT_DIR}" | xargs grep -E -- 'Authorization:[[:space:]]*(Splunk|Bearer)[[:space:]]+[A-Za-z0-9._=-]{12,}' >/dev/null 2>&1; then
    log "ERROR: Rendered output appears to contain a concrete authorization secret."
    exit 1
fi

log "Galileo Agent Control Setup rendered assets passed static validation."

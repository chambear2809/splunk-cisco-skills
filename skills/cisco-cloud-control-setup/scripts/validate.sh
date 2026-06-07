#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/cisco-cloud-control-rendered"

usage() {
    cat <<'EOF'
Cisco Cloud Control Setup validation

Usage:
  bash skills/cisco-cloud-control-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --help             Show this help

This validator checks artifacts produced by setup.sh --render, the delegated
--execute plan, and static coverage/metadata needed before live validation.
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

check_md_dir() {
    local path="$1" label="$2"
    [[ -d "${path}" ]] || { log "ERROR: Missing ${label} directory ${path}"; exit 1; }
    if ! find "${path}" -type f -name '*.md' -print -quit | grep -q .; then
        log "ERROR: ${label} directory has no Markdown artifacts: ${path}"
        exit 1
    fi
}

for rel in \
    metadata.json \
    apply-plan.json \
    coverage-report.json \
    coverage-report.md \
    doctor-report.md \
    handoff.md \
    platform/feature-coverage.md \
    platform/product-integration-matrix.md \
    platform/admin-readiness.md \
    api/cloud-control-api-boundary.md \
    api/workflows-api-readiness.md \
    data-fabric/handoff.md \
    studio/mcp-connector-plan.md \
    observability/cloud-control-dashboard.yaml \
    observability/cloud-control-native-ops.yaml
do
    check_file "${OUTPUT_DIR}/${rel}"
done

check_md_dir "${OUTPUT_DIR}/studio/agent-blueprints" "agent blueprint"
check_md_dir "${OUTPUT_DIR}/studio/app-builder-briefs" "app builder brief"
check_md_dir "${OUTPUT_DIR}/ai-canvas/board-templates" "AI Canvas board template"

for section in \
    data-fabric \
    mcp \
    agent-observability \
    observability-content \
    domain-readiness \
    cloud-control-studio \
    ai-canvas
do
    check_exec "${OUTPUT_DIR}/scripts/execute-${section}.sh"
done
check_exec "${OUTPUT_DIR}/scripts/execute-selected.sh"

python3 - "${OUTPUT_DIR}/coverage-report.json" "${OUTPUT_DIR}/apply-plan.json" "${OUTPUT_DIR}/metadata.json" <<'PY'
import json
import sys
from pathlib import Path

allowed_statuses = {
    "delegated_apply",
    "render",
    "ui_handoff",
    "ca_handoff",
    "validate",
    "not_applicable",
}
coverage = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
plan = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
metadata = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))

rows = coverage.get("coverage")
if not isinstance(rows, list) or not rows:
    raise SystemExit("coverage-report.json must contain non-empty coverage rows")
required = {"key", "area", "status", "owner", "source_url", "apply_boundary"}
for index, row in enumerate(rows):
    missing = required - set(row)
    if missing:
        raise SystemExit(f"coverage row {index} missing {sorted(missing)}")
    if row["status"] not in allowed_statuses:
        raise SystemExit(f"coverage row {index} has unsupported status {row['status']}")
if coverage.get("secret_values_rendered") is not False:
    raise SystemExit("coverage report must assert secret_values_rendered=false")
if metadata.get("secret_values_rendered") is not False:
    raise SystemExit("metadata must assert secret_values_rendered=false")

sections = {section.get("name") for section in plan.get("sections", [])}
expected = {
    "data-fabric",
    "mcp",
    "agent-observability",
    "observability-content",
    "domain-readiness",
    "cloud-control-studio",
    "ai-canvas",
}
if sections != expected:
    raise SystemExit(f"apply-plan sections mismatch: {sorted(sections)}")
for section in plan.get("sections", []):
    commands = section.get("commands", [])
    if not isinstance(commands, list):
        raise SystemExit(f"{section.get('name')} commands must be a list")
    for command in commands:
        if not isinstance(command, list) or not command:
            raise SystemExit(f"{section.get('name')} command must be a non-empty argv list")
PY

if grep -RIE -- '(Authorization:[[:space:]]*(Splunk|Bearer)[[:space:]]+[A-Za-z0-9._=-]{12,}|DIRECT_SECRET|SHOULD_NOT_RENDER)' "${OUTPUT_DIR}" >/dev/null 2>&1; then
    log "ERROR: Rendered output appears to contain a concrete secret."
    exit 1
fi

log "Cisco Cloud Control Setup rendered assets passed static validation."

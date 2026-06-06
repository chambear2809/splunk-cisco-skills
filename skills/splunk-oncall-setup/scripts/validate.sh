#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="${PYTHON:-python3}"
fi

SPEC="${SKILL_DIR}/templates/oncall.example.json"
OUTPUT_DIR=""
JSON_OUTPUT=false

usage() {
    cat <<'EOF'
Splunk On-Call validation

Usage:
  bash skills/splunk-oncall-setup/scripts/validate.sh [options]

Options:
  --spec PATH         YAML or JSON On-Call spec to validate
  --output-dir DIR    Optional rendered output directory to validate
  --json              Emit JSON output
  --help              Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --spec) [[ $# -ge 2 ]] || { echo "ERROR: --spec requires a value" >&2; exit 1; }; SPEC="$2"; shift 2 ;;
        --output-dir|--rendered-dir) [[ $# -ge 2 ]] || { echo "ERROR: $1 requires a value" >&2; exit 1; }; OUTPUT_DIR="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

args=(--spec "${SPEC}")
[[ -n "${OUTPUT_DIR}" ]] && args+=(--output-dir "${OUTPUT_DIR}")
[[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
"${PYTHON_BIN}" "${SCRIPT_DIR}/validate_oncall.py" "${args[@]}"

#!/usr/bin/env bash
set -euo pipefail

require_arg() {
    local flag="$1"
    local remaining="$2"
    if [[ "${remaining}" -lt 2 ]]; then
        echo "ERROR: Option '${flag}' requires a value." >&2
        exit 1
    fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-claude-code-instrumentation-rendered"
JSON_OUTPUT=false
COLLECTOR_CONFIG=""

usage() {
    cat <<'EOF'
Validate rendered Splunk Observability Claude Code instrumentation output.

Usage:
  validate.sh [--output-dir DIR] [--collector-config PATH] [--json]
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#"; OUTPUT_DIR="$2"; shift 2 ;;
        --collector-config) require_arg "$1" "$#"; COLLECTOR_CONFIG="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

args=(--validate --output-dir "${OUTPUT_DIR}")
if [[ -n "${COLLECTOR_CONFIG}" ]]; then
    args+=(--collector-config "${COLLECTOR_CONFIG}")
fi
if [[ "${JSON_OUTPUT}" == true ]]; then
    args+=(--json)
fi

exec python3 "${PROJECT_ROOT}/skills/shared/coding_agent_o11y/claude_code.py" "${args[@]}"

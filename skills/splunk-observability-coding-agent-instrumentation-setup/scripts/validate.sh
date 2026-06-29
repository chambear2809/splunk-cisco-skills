#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-coding-agent-instrumentation-rendered"
JSON_OUTPUT=false

usage() {
    cat <<'EOF'
Validate rendered coding-agent O11y parent-router output.

Usage:
  validate.sh [--output-dir DIR] [--json]
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

args=(--validate --output-dir "${OUTPUT_DIR}")
if [[ "${JSON_OUTPUT}" == true ]]; then
    args+=(--json)
fi

exec python3 "${PROJECT_ROOT}/skills/shared/coding_agent_o11y/parent.py" "${args[@]}"


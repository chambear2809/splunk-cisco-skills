#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCTOR="${SCRIPT_DIR}/doctor.py"

JSON_OUTPUT=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Admin Doctor Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --json
  --help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --json) JSON_OUTPUT=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

args=(--phase validate)
[[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
python3 "${DOCTOR}" "${args[@]}"

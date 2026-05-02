#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DEFAULT_RENDER_DIR_NAME="splunk-workload-management-rendered"
OUTPUT_DIR=""
JSON_OUTPUT=false
LIVE=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Workload Management Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --output-dir PATH
  --live
  --json
  --help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

json_array() {
    python3 - "$@" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1:]), end="")
PY
}

if [[ -n "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
else
    OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
fi

render_dir="${OUTPUT_DIR}/workload-management"
required=(README.md metadata.json workload_pools.conf workload_rules.conf workload_policy.conf preflight.sh apply.sh status.sh)
missing=()
for file in "${required[@]}"; do
    [[ -f "${render_dir}/${file}" ]] || missing+=("${file}")
done

ok=true
(( ${#missing[@]} == 0 )) || ok=false

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    printf '{"target":"workload-management","render_dir":"%s","ok":%s,"missing":%s}\n' "${render_dir}" "${ok}" "$(json_array "${missing[@]}")"
else
    if [[ "${ok}" == "true" ]]; then
        log "Rendered workload management assets are present under ${render_dir}."
    else
        log "ERROR: Missing rendered workload management assets under ${render_dir}: ${missing[*]}"
    fi
fi

[[ "${ok}" == "true" ]] || exit 1

if [[ "${LIVE}" == "true" ]]; then
    (cd "${render_dir}" && ./status.sh)
fi

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DEFAULT_RENDER_DIR_NAME="splunk-dashboard-studio-rendered"
OUTPUT_DIR=""
JSON_OUTPUT=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Dashboard Studio Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --output-dir PATH
  --json
  --help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
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

render_dir="${OUTPUT_DIR}/dashboard-studio"
required=(README.md metadata.json dashboard.json view.xml)
missing=()
for file in "${required[@]}"; do
    [[ -f "${render_dir}/${file}" ]] || missing+=("${file}")
done

ok=true
(( ${#missing[@]} == 0 )) || ok=false

if [[ -f "${render_dir}/view.xml" ]]; then
    if ! grep -q 'version="2"' "${render_dir}/view.xml"; then
        missing+=("view.xml version=2")
        ok=false
    fi
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    printf '{"target":"dashboard-studio","render_dir":"%s","ok":%s,"missing":%s}\n' "${render_dir}" "${ok}" "$(json_array "${missing[@]}")"
else
    if [[ "${ok}" == "true" ]]; then
        log "Rendered Dashboard Studio assets are present under ${render_dir}."
    else
        log "ERROR: Missing Dashboard Studio assets under ${render_dir}: ${missing[*]}"
    fi
fi

[[ "${ok}" == "true" ]] || exit 1

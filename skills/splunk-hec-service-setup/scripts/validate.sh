#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DEFAULT_RENDER_DIR_NAME="splunk-hec-service-rendered"
PLATFORM="enterprise"
OUTPUT_DIR=""
JSON_OUTPUT=false
LIVE=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk HEC Service Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --platform enterprise|cloud
  --output-dir PATH
  --live
  --json
  --help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) require_arg "$1" $# || exit 1; PLATFORM="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

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

validate_choice "${PLATFORM}" enterprise cloud

if [[ -n "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
else
    OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
fi

render_dir="${OUTPUT_DIR}/hec-service"
required=(README.md metadata.json inputs.conf.template acs-hec-token.json acs-hec-token-bulk.json preflight.sh apply-enterprise-files.sh apply-cloud-acs.sh status-enterprise.sh status-cloud-acs.sh)
missing=()
for file in "${required[@]}"; do
    [[ -f "${render_dir}/${file}" ]] || missing+=("${file}")
done

ok=true
(( ${#missing[@]} == 0 )) || ok=false

if [[ -f "${render_dir}/inputs.conf.template" ]]; then
    if ! grep -q "__HEC_TOKEN_FROM_FILE__" "${render_dir}/inputs.conf.template"; then
        missing+=("inputs.conf.template placeholder")
        ok=false
    fi
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    printf '{"target":"hec-service","platform":"%s","render_dir":"%s","ok":%s,"missing":%s}\n' "${PLATFORM}" "${render_dir}" "${ok}" "$(json_array "${missing[@]}")"
else
    if [[ "${ok}" == "true" ]]; then
        log "Rendered HEC service assets are present under ${render_dir}."
    else
        log "ERROR: Missing or invalid HEC service assets under ${render_dir}: ${missing[*]}"
    fi
fi

[[ "${ok}" == "true" ]] || exit 1

if [[ "${LIVE}" == "true" ]]; then
    if [[ "${PLATFORM}" == "enterprise" ]]; then
        (cd "${render_dir}" && ./status-enterprise.sh)
    else
        (cd "${render_dir}" && ./status-cloud-acs.sh)
    fi
fi

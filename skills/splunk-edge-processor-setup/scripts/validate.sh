#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DEFAULT_RENDER_DIR_NAME="splunk-edge-processor-rendered"
OUTPUT_DIR=""
LIVE=false
JSON_OUTPUT=false
EP_TENANT_URL=""
EP_API_TOKEN_FILE_ARG=""
EP_NAME=""
EP_API_BASE_ARG=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Edge Processor Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --output-dir PATH
  --ep-tenant-url URL                (only required for --live)
  --ep-api-token-file PATH           (only required for --live)
  --ep-name NAME                     (only required for --live)
  --ep-api-base URL                  (required for --live; control-plane REST base)
  --live
  --json
  --help

NOTE: Without --live this script is a structural check only — it confirms
that the rendered files are present and well-formed. With --live it runs
the rendered validate.sh which calls the EP control-plane REST API. The
rendered validator will skip the live REST checks if EP_API_BASE is unset
even when --live is passed, so --live now also requires --ep-api-base.

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --ep-tenant-url) require_arg "$1" $# || exit 1; EP_TENANT_URL="$2"; shift 2 ;;
        --ep-api-token-file) require_arg "$1" $# || exit 1; EP_API_TOKEN_FILE_ARG="$2"; shift 2 ;;
        --ep-name) require_arg "$1" $# || exit 1; EP_NAME="$2"; shift 2 ;;
        --ep-api-base) require_arg "$1" $# || exit 1; EP_API_BASE_ARG="$2"; shift 2 ;;
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

if [[ -n "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
else
    OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
fi

required=(README.md metadata.json validate.sh control-plane/apply-objects.sh handoffs/acs-allowlist.json)
missing=()
for file in "${required[@]}"; do
    [[ -f "${OUTPUT_DIR}/${file}" ]] || missing+=("${file}")
done

if (( ${#missing[@]} > 0 )); then
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        python3 - "${OUTPUT_DIR}" "${missing[@]}" <<'PY'
import json, sys
print(json.dumps({"status": "FAIL", "render_dir": sys.argv[1], "missing": sys.argv[2:]}))
PY
    else
        echo "FAIL: Missing rendered files in ${OUTPUT_DIR}: ${missing[*]}" >&2
    fi
    exit 1
fi

if [[ "${LIVE}" == "true" ]]; then
    missing_live=()
    [[ -z "${EP_TENANT_URL}" ]] && missing_live+=("--ep-tenant-url")
    [[ -z "${EP_API_TOKEN_FILE_ARG}" ]] && missing_live+=("--ep-api-token-file")
    [[ -z "${EP_NAME}" ]] && missing_live+=("--ep-name")
    [[ -z "${EP_API_BASE_ARG}" ]] && missing_live+=("--ep-api-base")
    if (( ${#missing_live[@]} > 0 )); then
        log "ERROR: --live requires: ${missing_live[*]}."
        log "  --ep-api-base must point at the EP control-plane REST base for your tenant"
        log "  (e.g. https://api.<region>.splunkcloud.com/<tenant>/edge-processor/v1)."
        log "  Without it the rendered validate.sh exits PASS (offline) without hitting the API."
        exit 1
    fi
    export EP_API_TOKEN_FILE="${EP_API_TOKEN_FILE_ARG}"
    export EP_API_BASE="${EP_API_BASE_ARG}"
    (cd "${OUTPUT_DIR}" && ./validate.sh)
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    python3 - "${OUTPUT_DIR}" "${required[@]}" <<'PY'
import json, sys
print(json.dumps({"status": "PASS", "render_dir": sys.argv[1], "files": sys.argv[2:]}))
PY
else
    echo "PASS: ${#required[@]} rendered files present in ${OUTPUT_DIR}"
fi

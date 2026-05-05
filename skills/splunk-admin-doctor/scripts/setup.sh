#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DOCTOR="${SCRIPT_DIR}/doctor.py"
DEFAULT_RENDER_DIR_NAME="splunk-admin-doctor-rendered"

PHASE="doctor"
PLATFORM="auto"
TARGET_SEARCH_HEAD=""
SPLUNK_URI=""
SPLUNK_HOME_VALUE="/opt/splunk"
OUTPUT_DIR=""
EVIDENCE_FILE=""
FIXES=""
JSON_OUTPUT=false
STRICT=false
DRY_RUN=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Admin Doctor + Fixes

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase doctor|fix-plan|apply|validate|status
  --platform auto|cloud|enterprise
  --target-search-head HOSTNAME
  --splunk-uri URI
  --splunk-home PATH
  --output-dir PATH
  --evidence-file PATH
  --fixes FIX_ID[,FIX_ID]
  --json
  --strict
  --dry-run
  --help

Examples:
  $(basename "$0") --phase doctor --platform enterprise --splunk-home /opt/splunk
  $(basename "$0") --phase fix-plan --evidence-file skills/splunk-admin-doctor/fixtures/enterprise_unhealthy.json
  $(basename "$0") --phase apply --fixes SAD-CONNECTIVITY-REST-DENIED --dry-run --json

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --platform) require_arg "$1" $# || exit 1; PLATFORM="$2"; shift 2 ;;
        --target-search-head) require_arg "$1" $# || exit 1; TARGET_SEARCH_HEAD="$2"; shift 2 ;;
        --splunk-uri) require_arg "$1" $# || exit 1; SPLUNK_URI="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --evidence-file) require_arg "$1" $# || exit 1; EVIDENCE_FILE="$2"; shift 2 ;;
        --fixes) require_arg "$1" $# || exit 1; FIXES="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --strict) STRICT=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
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

validate_args() {
    validate_choice "${PHASE}" doctor fix-plan apply validate status
    validate_choice "${PLATFORM}" auto cloud enterprise
    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
    if [[ "${PHASE}" == "apply" && -z "${FIXES}" && "${DRY_RUN}" != "true" ]]; then
        log "ERROR: --phase apply requires --fixes FIX_ID[,FIX_ID]."
        exit 1
    fi
}

build_args() {
    DOCTOR_ARGS=(
        --phase "${PHASE}"
        --platform "${PLATFORM}"
        --target-search-head "${TARGET_SEARCH_HEAD}"
        --splunk-uri "${SPLUNK_URI}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --output-dir "${OUTPUT_DIR}"
    )
    [[ -n "${EVIDENCE_FILE}" ]] && DOCTOR_ARGS+=(--evidence-file "${EVIDENCE_FILE}")
    [[ -n "${FIXES}" ]] && DOCTOR_ARGS+=(--fixes "${FIXES}")
    [[ "${JSON_OUTPUT}" == "true" ]] && DOCTOR_ARGS+=(--json)
    [[ "${STRICT}" == "true" ]] && DOCTOR_ARGS+=(--strict)
    [[ "${DRY_RUN}" == "true" ]] && DOCTOR_ARGS+=(--dry-run)
    return 0
}

main() {
    validate_args
    build_args
    python3 "${DOCTOR}" "${DOCTOR_ARGS[@]}"
}

main "$@"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DOCTOR="${SCRIPT_DIR}/doctor.py"
DEFAULT_RENDER_DIR_NAME="splunk-data-source-readiness-doctor-rendered"

PHASE="doctor"
PLATFORM="auto"
TARGETS="es,itsi,ari"
TARGET_SEARCH_HEAD=""
SPLUNK_URI=""
OUTPUT_DIR=""
EVIDENCE_FILE=""
COLLECTOR_RESULTS_FILE=""
REGISTRY_FILE=""
SOURCE_PACKS_FILE=""
SOURCE_PACK=""
SESSION_KEY_FILE=""
NO_VERIFY_TLS=false
MAX_ROWS=""
MAX_SEARCHES=""
COLLECT_TIMEOUT_SECONDS=""
FIXES=""
JSON_OUTPUT=false
STRICT=false
DRY_RUN=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Data Source Readiness Doctor

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase doctor|fix-plan|apply|validate|status|source-packs|collect|synthesize
  --platform auto|cloud|enterprise
  --targets es,itsi,ari
  --target-search-head HOSTNAME
  --splunk-uri URI
  --output-dir PATH
  --evidence-file PATH
  --collector-results-file PATH
  --registry-file PATH
  --source-packs-file PATH
  --source-pack PACK_ID[,PACK_ID]
  --session-key-file PATH
  --no-verify-tls
  --max-rows N
  --max-searches N
  --collect-timeout-seconds N
  --fixes FIX_ID[,FIX_ID]
  --json
  --strict
  --dry-run
  --help

Examples:
  $(basename "$0") --phase doctor --evidence-file skills/splunk-data-source-readiness-doctor/fixtures/comprehensive_unready.json
  $(basename "$0") --phase source-packs --json
  $(basename "$0") --phase collect --source-pack aws_cloudtrail --evidence-file evidence.json
  $(basename "$0") --phase synthesize --evidence-file evidence.json --collector-results-file live-collector-results.redacted.json
  $(basename "$0") --phase fix-plan --targets es,itsi --evidence-file evidence.json
  $(basename "$0") --phase apply --fixes DSRD-CIM-TAG-EVENTTYPE-GAP --dry-run --json

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --platform) require_arg "$1" $# || exit 1; PLATFORM="$2"; shift 2 ;;
        --targets) require_arg "$1" $# || exit 1; TARGETS="$2"; shift 2 ;;
        --target-search-head) require_arg "$1" $# || exit 1; TARGET_SEARCH_HEAD="$2"; shift 2 ;;
        --splunk-uri) require_arg "$1" $# || exit 1; SPLUNK_URI="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --evidence-file) require_arg "$1" $# || exit 1; EVIDENCE_FILE="$2"; shift 2 ;;
        --collector-results-file) require_arg "$1" $# || exit 1; COLLECTOR_RESULTS_FILE="$2"; shift 2 ;;
        --registry-file) require_arg "$1" $# || exit 1; REGISTRY_FILE="$2"; shift 2 ;;
        --source-packs-file) require_arg "$1" $# || exit 1; SOURCE_PACKS_FILE="$2"; shift 2 ;;
        --source-pack) require_arg "$1" $# || exit 1; SOURCE_PACK="$2"; shift 2 ;;
        --session-key-file) require_arg "$1" $# || exit 1; SESSION_KEY_FILE="$2"; shift 2 ;;
        --no-verify-tls) NO_VERIFY_TLS=true; shift ;;
        --max-rows) require_arg "$1" $# || exit 1; MAX_ROWS="$2"; shift 2 ;;
        --max-searches) require_arg "$1" $# || exit 1; MAX_SEARCHES="$2"; shift 2 ;;
        --collect-timeout-seconds) require_arg "$1" $# || exit 1; COLLECT_TIMEOUT_SECONDS="$2"; shift 2 ;;
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
    validate_choice "${PHASE}" doctor fix-plan apply validate status source-packs collect synthesize
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
        --targets "${TARGETS}"
        --target-search-head "${TARGET_SEARCH_HEAD}"
        --splunk-uri "${SPLUNK_URI}"
        --output-dir "${OUTPUT_DIR}"
    )
    [[ -n "${EVIDENCE_FILE}" ]] && DOCTOR_ARGS+=(--evidence-file "${EVIDENCE_FILE}")
    [[ -n "${COLLECTOR_RESULTS_FILE}" ]] && DOCTOR_ARGS+=(--collector-results-file "${COLLECTOR_RESULTS_FILE}")
    [[ -n "${REGISTRY_FILE}" ]] && DOCTOR_ARGS+=(--registry-file "${REGISTRY_FILE}")
    [[ -n "${SOURCE_PACKS_FILE}" ]] && DOCTOR_ARGS+=(--source-packs-file "${SOURCE_PACKS_FILE}")
    [[ -n "${SOURCE_PACK}" ]] && DOCTOR_ARGS+=(--source-pack "${SOURCE_PACK}")
    [[ -n "${SESSION_KEY_FILE}" ]] && DOCTOR_ARGS+=(--session-key-file "${SESSION_KEY_FILE}")
    [[ "${NO_VERIFY_TLS}" == "true" ]] && DOCTOR_ARGS+=(--no-verify-tls)
    [[ -n "${MAX_ROWS}" ]] && DOCTOR_ARGS+=(--max-rows "${MAX_ROWS}")
    [[ -n "${MAX_SEARCHES}" ]] && DOCTOR_ARGS+=(--max-searches "${MAX_SEARCHES}")
    [[ -n "${COLLECT_TIMEOUT_SECONDS}" ]] && DOCTOR_ARGS+=(--collect-timeout-seconds "${COLLECT_TIMEOUT_SECONDS}")
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

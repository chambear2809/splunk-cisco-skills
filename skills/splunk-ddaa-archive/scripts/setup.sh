#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-ddaa-archive-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
OUTPUT_DIR=""
STACK=""
INDEX=""
DATATYPE="event"
SEARCHABLE_DAYS=""
ARCHIVAL_RETENTION_DAYS=""
MAX_DATA_SIZE_MB=""
OPERATION="enable"
TOKEN_FILE="/tmp/acs_token"
ACS_BASE="https://admin.splunk.com"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Cloud DDAA Archive Lifecycle

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|apply|status|restore|audit
  --dry-run
  --json
  --output-dir PATH
  --stack NAME            (required)
  --index NAME            (required)
  --datatype event|metric
  --searchable-days N     (required)
  --archival-retention-days N  (required; total retention, must exceed searchable-days)
  --max-data-size-mb N
  --operation enable|update|create|plan
  --token-file PATH       (ACS token file; never the token value)
  --acs-base URL
  --help
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --stack) require_arg "$1" $# || exit 1; STACK="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --datatype) require_arg "$1" $# || exit 1; DATATYPE="$2"; shift 2 ;;
        --searchable-days) require_arg "$1" $# || exit 1; SEARCHABLE_DAYS="$2"; shift 2 ;;
        --archival-retention-days) require_arg "$1" $# || exit 1; ARCHIVAL_RETENTION_DAYS="$2"; shift 2 ;;
        --max-data-size-mb) require_arg "$1" $# || exit 1; MAX_DATA_SIZE_MB="$2"; shift 2 ;;
        --operation) require_arg "$1" $# || exit 1; OPERATION="$2"; shift 2 ;;
        --token-file) require_arg "$1" $# || exit 1; TOKEN_FILE="$2"; shift 2 ;;
        --acs-base) require_arg "$1" $# || exit 1; ACS_BASE="$2"; shift 2 ;;
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

require_value() {
    local name="$1" value="$2"
    if [[ -z "${value}" ]]; then
        log "ERROR: ${name} is required."
        exit 1
    fi
}

validate_args() {
    validate_choice "${PHASE}" render apply status restore audit
    validate_choice "${DATATYPE}" event metric
    validate_choice "${OPERATION}" enable update create plan
    require_value "--stack" "${STACK}"
    require_value "--index" "${INDEX}"
    require_value "--searchable-days" "${SEARCHABLE_DAYS}"
    require_value "--archival-retention-days" "${ARCHIVAL_RETENTION_DAYS}"
    if [[ "${JSON_OUTPUT}" == "true" && "${PHASE}" != "render" && "${DRY_RUN}" != "true" ]]; then
        log "ERROR: --json is supported only for render-only or --dry-run workflows."
        exit 1
    fi
    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
}

build_renderer_args() {
    RENDER_ARGS=(
        --output-dir "${OUTPUT_DIR}"
        --stack "${STACK}"
        --index "${INDEX}"
        --datatype "${DATATYPE}"
        --searchable-days "${SEARCHABLE_DAYS}"
        --archival-retention-days "${ARCHIVAL_RETENTION_DAYS}"
        --max-data-size-mb "${MAX_DATA_SIZE_MB}"
        --operation "${OPERATION}"
        --token-file "${TOKEN_FILE}"
        --acs-base "${ACS_BASE}"
    )
}

render_dir() {
    printf '%s/ddaa' "${OUTPUT_DIR}"
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

run_rendered_script() {
    local script_name="$1" dir
    dir="$(render_dir)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./${script_name})"
        return 0
    fi
    if [[ ! -x "${dir}/${script_name}" ]]; then
        log "ERROR: Rendered script is missing or not executable: ${dir}/${script_name}"
        exit 1
    fi
    (cd "${dir}" && "./${script_name}")
}

main() {
    validate_args
    build_renderer_args
    if [[ "${DRY_RUN}" == "true" ]]; then
        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            exec python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
        fi
        python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
        exit 0
    fi
    case "${PHASE}" in
        render) render_assets ;;
        apply) render_assets; run_rendered_script enable-ddaa.sh ;;
        status) render_assets; run_rendered_script status.sh ;;
        restore) render_assets; run_rendered_script restore.sh ;;
        audit) render_assets; run_rendered_script audit.sh ;;
    esac
}

main "$@"

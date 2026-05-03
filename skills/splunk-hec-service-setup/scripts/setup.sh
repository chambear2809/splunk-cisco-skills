#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-hec-service-rendered"

PLATFORM="enterprise"
PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
APP_NAME="splunk_httpinput"
TOKEN_NAME="cisco_skills_hec"
DESCRIPTION="Managed by splunk-hec-service-setup"
DEFAULT_INDEX="main"
ALLOWED_INDEXES="main"
SOURCE=""
SOURCETYPE=""
PORT="8088"
ENABLE_SSL="true"
GLOBAL_DISABLED="false"
TOKEN_DISABLED="false"
USE_ACK="false"
S2S_INDEXES_VALIDATION="disabled_for_internal"
TOKEN_FILE=""
WRITE_TOKEN_FILE=""
RESTART_SPLUNK="true"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk HEC Service Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --platform enterprise|cloud
  --phase render|preflight|apply|status|all
  --apply
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --app-name NAME
  --token-name NAME
  --description TEXT
  --default-index NAME
  --allowed-indexes CSV
  --source VALUE
  --sourcetype VALUE
  --port PORT
  --enable-ssl true|false
  --global-disabled true|false
  --token-disabled true|false
  --use-ack true|false
  --s2s-indexes-validation disabled|disabled_for_internal|enabled_for_all
  --token-file PATH
  --write-token-file PATH
  --restart-splunk true|false
  --help

Examples:
  $(basename "$0") --platform enterprise --token-name app_hec --default-index app --allowed-indexes app
  $(basename "$0") --platform enterprise --phase apply --token-file /tmp/app_hec_token
  $(basename "$0") --platform cloud --phase apply --write-token-file /tmp/app_hec_token

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) require_arg "$1" $# || exit 1; PLATFORM="$2"; shift 2 ;;
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --token-name) require_arg "$1" $# || exit 1; TOKEN_NAME="$2"; shift 2 ;;
        --description) require_arg "$1" $# || exit 1; DESCRIPTION="$2"; shift 2 ;;
        --default-index) require_arg "$1" $# || exit 1; DEFAULT_INDEX="$2"; shift 2 ;;
        --allowed-indexes) require_arg "$1" $# || exit 1; ALLOWED_INDEXES="$2"; shift 2 ;;
        --source) require_arg "$1" $# || exit 1; SOURCE="$2"; shift 2 ;;
        --sourcetype) require_arg "$1" $# || exit 1; SOURCETYPE="$2"; shift 2 ;;
        --port) require_arg "$1" $# || exit 1; PORT="$2"; shift 2 ;;
        --enable-ssl) require_arg "$1" $# || exit 1; ENABLE_SSL="$2"; shift 2 ;;
        --global-disabled) require_arg "$1" $# || exit 1; GLOBAL_DISABLED="$2"; shift 2 ;;
        --token-disabled) require_arg "$1" $# || exit 1; TOKEN_DISABLED="$2"; shift 2 ;;
        --use-ack) require_arg "$1" $# || exit 1; USE_ACK="$2"; shift 2 ;;
        --s2s-indexes-validation) require_arg "$1" $# || exit 1; S2S_INDEXES_VALIDATION="$2"; shift 2 ;;
        --token-file) require_arg "$1" $# || exit 1; TOKEN_FILE="$2"; shift 2 ;;
        --write-token-file) require_arg "$1" $# || exit 1; WRITE_TOKEN_FILE="$2"; shift 2 ;;
        --restart-splunk) require_arg "$1" $# || exit 1; RESTART_SPLUNK="$2"; shift 2 ;;
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
    validate_choice "${PLATFORM}" enterprise cloud
    validate_choice "${PHASE}" render preflight apply status all
    validate_choice "${ENABLE_SSL}" true false
    validate_choice "${GLOBAL_DISABLED}" true false
    validate_choice "${TOKEN_DISABLED}" true false
    validate_choice "${USE_ACK}" true false
    validate_choice "${S2S_INDEXES_VALIDATION}" disabled disabled_for_internal enabled_for_all
    validate_choice "${RESTART_SPLUNK}" true false
    if [[ "${JSON_OUTPUT}" == "true" && "${DRY_RUN}" != "true" && ( "${PHASE}" != "render" || "${APPLY}" == "true" ) ]]; then
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
        --platform "${PLATFORM}"
        --output-dir "${OUTPUT_DIR}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --app-name "${APP_NAME}"
        --token-name "${TOKEN_NAME}"
        --description "${DESCRIPTION}"
        --default-index "${DEFAULT_INDEX}"
        --allowed-indexes "${ALLOWED_INDEXES}"
        --source "${SOURCE}"
        --sourcetype "${SOURCETYPE}"
        --port "${PORT}"
        --enable-ssl "${ENABLE_SSL}"
        --global-disabled "${GLOBAL_DISABLED}"
        --token-disabled "${TOKEN_DISABLED}"
        --use-ack "${USE_ACK}"
        --s2s-indexes-validation "${S2S_INDEXES_VALIDATION}"
        --token-file "${TOKEN_FILE}"
        --write-token-file "${WRITE_TOKEN_FILE}"
        --restart-splunk "${RESTART_SPLUNK}"
    )
}

render_dir() {
    printf '%s/hec-service' "${OUTPUT_DIR}"
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

apply_script() {
    if [[ "${PLATFORM}" == "enterprise" ]]; then
        printf '%s' "apply-enterprise-files.sh"
    else
        printf '%s' "apply-cloud-acs.sh"
    fi
}

status_script() {
    if [[ "${PLATFORM}" == "enterprise" ]]; then
        printf '%s' "status-enterprise.sh"
    else
        printf '%s' "status-cloud-acs.sh"
    fi
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
        render)
            render_assets
            if [[ "${APPLY}" == "true" ]]; then
                run_rendered_script "$(apply_script)"
            fi
            ;;
        preflight) render_assets; run_rendered_script preflight.sh ;;
        apply) render_assets; run_rendered_script "$(apply_script)" ;;
        status) run_rendered_script "$(status_script)" ;;
        all) render_assets; run_rendered_script preflight.sh; run_rendered_script "$(apply_script)"; run_rendered_script "$(status_script)" ;;
    esac
}

main "$@"

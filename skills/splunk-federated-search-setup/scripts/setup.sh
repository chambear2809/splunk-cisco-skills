#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-federated-search-rendered"

MODE="standard"
PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
APPLY_TARGET="search-head"
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
APP_NAME="ZZZ_cisco_skills_federated_search"
PROVIDER_NAME="remote_provider"
REMOTE_HOST_PORT=""
SERVICE_ACCOUNT=""
PASSWORD_FILE=""
APP_CONTEXT="search"
USE_FSH_KNOWLEDGE_OBJECTS="false"
FEDERATED_INDEX_NAME="remote_main"
DATASET_TYPE="index"
DATASET_NAME="main"
SHC_REPLICATION="true"
MAX_PREVIEW_GENERATION_DURATION="0"
MAX_PREVIEW_GENERATION_INPUTCOUNT="0"
RESTART_SPLUNK="true"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Federated Search Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --mode standard|transparent
  --phase render|preflight|apply|status|all
  --apply
  --apply-target search-head|shc-deployer
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --app-name NAME
  --provider-name NAME
  --remote-host-port HOST:PORT
  --service-account USER
  --password-file PATH
  --app-context APP
  --use-fsh-knowledge-objects true|false
  --federated-index-name NAME
  --dataset-type index|metricindex|savedsearch|lastjob|datamodel
  --dataset-name NAME
  --shc-replication true|false
  --max-preview-generation-duration SECONDS
  --max-preview-generation-inputcount ROWS
  --restart-splunk true|false
  --help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode) require_arg "$1" $# || exit 1; MODE="$2"; shift 2 ;;
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --apply-target) require_arg "$1" $# || exit 1; APPLY_TARGET="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --provider-name) require_arg "$1" $# || exit 1; PROVIDER_NAME="$2"; shift 2 ;;
        --remote-host-port) require_arg "$1" $# || exit 1; REMOTE_HOST_PORT="$2"; shift 2 ;;
        --service-account) require_arg "$1" $# || exit 1; SERVICE_ACCOUNT="$2"; shift 2 ;;
        --password-file) require_arg "$1" $# || exit 1; PASSWORD_FILE="$2"; shift 2 ;;
        --app-context) require_arg "$1" $# || exit 1; APP_CONTEXT="$2"; shift 2 ;;
        --use-fsh-knowledge-objects) require_arg "$1" $# || exit 1; USE_FSH_KNOWLEDGE_OBJECTS="$2"; shift 2 ;;
        --federated-index-name) require_arg "$1" $# || exit 1; FEDERATED_INDEX_NAME="$2"; shift 2 ;;
        --dataset-type) require_arg "$1" $# || exit 1; DATASET_TYPE="$2"; shift 2 ;;
        --dataset-name) require_arg "$1" $# || exit 1; DATASET_NAME="$2"; shift 2 ;;
        --shc-replication) require_arg "$1" $# || exit 1; SHC_REPLICATION="$2"; shift 2 ;;
        --max-preview-generation-duration) require_arg "$1" $# || exit 1; MAX_PREVIEW_GENERATION_DURATION="$2"; shift 2 ;;
        --max-preview-generation-inputcount) require_arg "$1" $# || exit 1; MAX_PREVIEW_GENERATION_INPUTCOUNT="$2"; shift 2 ;;
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
    validate_choice "${MODE}" standard transparent
    validate_choice "${PHASE}" render preflight apply status all
    validate_choice "${APPLY_TARGET}" search-head shc-deployer
    validate_choice "${USE_FSH_KNOWLEDGE_OBJECTS}" true false
    validate_choice "${DATASET_TYPE}" index metricindex savedsearch lastjob datamodel
    validate_choice "${SHC_REPLICATION}" true false
    validate_choice "${RESTART_SPLUNK}" true false
    if [[ -z "${REMOTE_HOST_PORT}" || -z "${SERVICE_ACCOUNT}" ]]; then
        log "ERROR: --remote-host-port and --service-account are required."
        exit 1
    fi
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
        --mode "${MODE}"
        --output-dir "${OUTPUT_DIR}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --app-name "${APP_NAME}"
        --provider-name "${PROVIDER_NAME}"
        --remote-host-port "${REMOTE_HOST_PORT}"
        --service-account "${SERVICE_ACCOUNT}"
        --password-file "${PASSWORD_FILE}"
        --app-context "${APP_CONTEXT}"
        --use-fsh-knowledge-objects "${USE_FSH_KNOWLEDGE_OBJECTS}"
        --federated-index-name "${FEDERATED_INDEX_NAME}"
        --dataset-type "${DATASET_TYPE}"
        --dataset-name "${DATASET_NAME}"
        --shc-replication "${SHC_REPLICATION}"
        --max-preview-generation-duration "${MAX_PREVIEW_GENERATION_DURATION}"
        --max-preview-generation-inputcount "${MAX_PREVIEW_GENERATION_INPUTCOUNT}"
        --restart-splunk "${RESTART_SPLUNK}"
    )
}

render_dir() {
    printf '%s/federated-search' "${OUTPUT_DIR}"
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" "${extra_args[@]}"
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
    if [[ "${APPLY_TARGET}" == "shc-deployer" ]]; then
        printf '%s' "apply-shc-deployer.sh"
    else
        printf '%s' "apply-search-head.sh"
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
        status) run_rendered_script status.sh ;;
        all) render_assets; run_rendered_script preflight.sh; run_rendered_script "$(apply_script)"; run_rendered_script status.sh ;;
    esac
}

main "$@"

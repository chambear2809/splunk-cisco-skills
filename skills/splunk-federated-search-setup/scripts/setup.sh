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
FEDERATED_SEARCH_ENABLED="true"
SPEC_PATH=""
PROVIDER_FRAGMENTS=()
FEDERATED_INDEX_FRAGMENTS=()
GLOBAL_TOGGLE=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Federated Search Setup

Usage: $(basename "$0") [OPTIONS]

Spec input (preferred for multi-provider deployments):
  --spec PATH                 YAML or JSON spec describing all providers and indexes
                              (see skills/splunk-federated-search-setup/template.example)

Repeated CLI flags (multi-provider without YAML):
  --provider 'type=splunk,name=remote_prod,mode=standard,host_port=h:p,...'
  --federated-index 'name=remote_main,provider=remote_prod,dataset_type=index,dataset_name=main'

Single-provider back-compat flags:
  --mode standard|transparent
  --remote-host-port HOST:PORT
  --service-account USER
  --password-file PATH
  --provider-name NAME
  --app-context APP
  --use-fsh-knowledge-objects true|false
  --federated-index-name NAME
  --dataset-type index|metricindex|savedsearch|lastjob|datamodel|glue_table
  --dataset-name NAME

Workflow:
  --phase render|preflight|apply|status|all|global-toggle
  --apply
  --apply-target search-head|shc-deployer|rest
  --global-toggle enable|disable
                              For --phase global-toggle, choose direction.
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --app-name NAME
  --shc-replication true|false
  --max-preview-generation-duration SECONDS
  --max-preview-generation-inputcount ROWS
  --restart-splunk true|false
  --federated-search-enabled true|false
                              Captured in metadata.json; toggle via --phase global-toggle.
  --help

REST apply (--apply-target rest) reads:
  SPLUNK_REST_URI=https://<sh>:8089
  SPLUNK_REST_USER=admin
  SPLUNK_REST_PASSWORD_FILE=/path/to/admin_pw   # chmod 600, no newline
  SPLUNK_VERIFY_SSL=true|false                  # default true (canonical)
                                                # Legacy alias: SPLUNK_REST_VERIFY_SSL (still honored)

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
        --federated-search-enabled) require_arg "$1" $# || exit 1; FEDERATED_SEARCH_ENABLED="$2"; shift 2 ;;
        --spec) require_arg "$1" $# || exit 1; SPEC_PATH="$2"; shift 2 ;;
        --provider) require_arg "$1" $# || exit 1; PROVIDER_FRAGMENTS+=("$2"); shift 2 ;;
        --federated-index) require_arg "$1" $# || exit 1; FEDERATED_INDEX_FRAGMENTS+=("$2"); shift 2 ;;
        --global-toggle) require_arg "$1" $# || exit 1; GLOBAL_TOGGLE="$2"; shift 2 ;;
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
    validate_choice "${PHASE}" render preflight apply status all global-toggle
    validate_choice "${APPLY_TARGET}" search-head shc-deployer rest
    validate_choice "${USE_FSH_KNOWLEDGE_OBJECTS}" true false
    validate_choice "${DATASET_TYPE}" index metricindex savedsearch lastjob datamodel glue_table
    validate_choice "${SHC_REPLICATION}" true false
    validate_choice "${RESTART_SPLUNK}" true false
    validate_choice "${FEDERATED_SEARCH_ENABLED}" true false
    if [[ "${PHASE}" == "global-toggle" && -z "${GLOBAL_TOGGLE}" ]]; then
        log "ERROR: --phase global-toggle requires --global-toggle enable|disable."
        exit 1
    fi
    if [[ -n "${GLOBAL_TOGGLE}" ]]; then
        validate_choice "${GLOBAL_TOGGLE}" enable disable
    fi
    # When neither --spec nor any --provider fragments are given, the
    # back-compat single-provider path requires --remote-host-port and
    # --service-account just like before.
    if [[ -z "${SPEC_PATH}" && ${#PROVIDER_FRAGMENTS[@]} -eq 0 ]]; then
        if [[ -z "${REMOTE_HOST_PORT}" || -z "${SERVICE_ACCOUNT}" ]]; then
            log "ERROR: --remote-host-port and --service-account are required for the single-provider back-compat flow."
            log "       Use --spec PATH or --provider 'type=splunk,name=...' for the multi-provider flow."
            exit 1
        fi
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
        --output-dir "${OUTPUT_DIR}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --app-name "${APP_NAME}"
        --mode "${MODE}"
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
        --federated-search-enabled "${FEDERATED_SEARCH_ENABLED}"
    )
    if [[ -n "${SPEC_PATH}" ]]; then
        RENDER_ARGS+=(--spec "${SPEC_PATH}")
    fi
    local fragment
    for fragment in "${PROVIDER_FRAGMENTS[@]}"; do
        RENDER_ARGS+=(--provider "${fragment}")
    done
    for fragment in "${FEDERATED_INDEX_FRAGMENTS[@]}"; do
        RENDER_ARGS+=(--federated-index "${fragment}")
    done
}

render_dir() {
    printf '%s/federated-search' "${OUTPUT_DIR}"
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
    case "${APPLY_TARGET}" in
        shc-deployer) printf '%s' "apply-shc-deployer.sh" ;;
        rest) printf '%s' "apply-rest.sh" ;;
        *) printf '%s' "apply-search-head.sh" ;;
    esac
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
        status) render_assets; run_rendered_script status.sh ;;
        global-toggle)
            render_assets
            if [[ "${GLOBAL_TOGGLE}" == "enable" ]]; then
                run_rendered_script global-enable.sh
            else
                run_rendered_script global-disable.sh
            fi
            ;;
        all)
            render_assets
            run_rendered_script preflight.sh
            run_rendered_script "$(apply_script)"
            run_rendered_script status.sh
            ;;
    esac
}

main "$@"

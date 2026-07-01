#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-cim-data-model-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
APP_NAME="Splunk_SA_CIM"
DATAMODEL=""
ALLOW_CUSTOM_DATAMODEL="false"
ACCELERATION="unset"
EARLIEST_TIME="-7d"
BACKFILL_TIME=""
MAX_CONCURRENT=""
MANUAL_REBUILDS="unset"
CRON_SCHEDULE=""
CONSTRAIN_INDEXES=""
EVENTTYPE_NAME=""
EVENTTYPE_SEARCH=""
TAGS=""
ACCEPT_ACCELERATION=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk CIM Data Model Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|apply|status|all
  --apply
  --dry-run
  --json
  --output-dir PATH
  --app-name NAME                 (default Splunk_SA_CIM)
  --datamodel NAME                (required; CIM model id or custom)
  --allow-custom-datamodel true|false
  --acceleration true|false|unset   (false disables; unset leaves it unmanaged)
  --earliest-time SPL_TIME        (acceleration summary range)
  --backfill-time SPL_TIME
  --max-concurrent N
  --manual-rebuilds true|false|unset
  --cron-schedule CRON
  --constrain-indexes CSV         (writes cim_<model>_indexes macro)
  --eventtype-name NAME
  --eventtype-search SPL
  --tags CSV                      (CIM tags attached to the eventtype)
  --accept-acceleration           (required to enable acceleration live)
  --help

Examples:
  $(basename "$0") --datamodel Network_Traffic --acceleration true --earliest-time -7d
  $(basename "$0") --phase apply --datamodel Network_Traffic --acceleration true --accept-acceleration
  $(basename "$0") --phase apply --datamodel Authentication --eventtype-name cisco_ise_auth \\
    --eventtype-search 'sourcetype=cisco:ise:syslog' --tags authentication

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --datamodel) require_arg "$1" $# || exit 1; DATAMODEL="$2"; shift 2 ;;
        --allow-custom-datamodel) require_arg "$1" $# || exit 1; ALLOW_CUSTOM_DATAMODEL="$2"; shift 2 ;;
        --acceleration) require_arg "$1" $# || exit 1; ACCELERATION="$2"; shift 2 ;;
        --earliest-time) require_arg "$1" $# || exit 1; EARLIEST_TIME="$2"; shift 2 ;;
        --backfill-time) require_arg "$1" $# || exit 1; BACKFILL_TIME="$2"; shift 2 ;;
        --max-concurrent) require_arg "$1" $# || exit 1; MAX_CONCURRENT="$2"; shift 2 ;;
        --manual-rebuilds) require_arg "$1" $# || exit 1; MANUAL_REBUILDS="$2"; shift 2 ;;
        --cron-schedule) require_arg "$1" $# || exit 1; CRON_SCHEDULE="$2"; shift 2 ;;
        --constrain-indexes) require_arg "$1" $# || exit 1; CONSTRAIN_INDEXES="$2"; shift 2 ;;
        --eventtype-name) require_arg "$1" $# || exit 1; EVENTTYPE_NAME="$2"; shift 2 ;;
        --eventtype-search) require_arg "$1" $# || exit 1; EVENTTYPE_SEARCH="$2"; shift 2 ;;
        --tags) require_arg "$1" $# || exit 1; TAGS="$2"; shift 2 ;;
        --accept-acceleration) ACCEPT_ACCELERATION=true; shift ;;
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
    validate_choice "${PHASE}" render preflight apply status all
    validate_choice "${ALLOW_CUSTOM_DATAMODEL}" true false
    validate_choice "${ACCELERATION}" true false unset
    validate_choice "${MANUAL_REBUILDS}" true false unset
    if [[ -z "${DATAMODEL}" ]]; then
        log "ERROR: --datamodel is required."
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
        --output-dir "${OUTPUT_DIR}"
        --app-name "${APP_NAME}"
        --datamodel "${DATAMODEL}"
        --allow-custom-datamodel "${ALLOW_CUSTOM_DATAMODEL}"
        --acceleration "${ACCELERATION}"
        --earliest-time "${EARLIEST_TIME}"
        --backfill-time "${BACKFILL_TIME}"
        --max-concurrent "${MAX_CONCURRENT}"
        --manual-rebuilds "${MANUAL_REBUILDS}"
        --cron-schedule "${CRON_SCHEDULE}"
        --constrain-indexes "${CONSTRAIN_INDEXES}"
        --eventtype-name "${EVENTTYPE_NAME}"
        --eventtype-search "${EVENTTYPE_SEARCH}"
        --tags "${TAGS}"
    )
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

apply_live() {
    if [[ "${ACCELERATION}" == "unset" && -z "${CONSTRAIN_INDEXES}" && -z "${EVENTTYPE_NAME}" ]]; then
        log "ERROR: apply requested no acceleration, macro, or eventtype/tag mutation."
        exit 2
    fi
    if [[ "${ACCELERATION}" == "true" && "${ACCEPT_ACCELERATION}" != "true" ]]; then
        log "ERROR: Data model acceleration consumes resources. Re-run with --accept-acceleration."
        exit 1
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would write CIM governance to app ${APP_NAME} via REST (datamodels/macros/eventtypes/tags)."
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    local sk
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
    if ! rest_check_app "${sk}" "${SPLUNK_URI}" "${APP_NAME}"; then
        log "ERROR: App '${APP_NAME}' not found. Install the Splunk CIM add-on (Splunk_SA_CIM, Splunkbase 1621) before applying governance."
        exit 1
    fi
    if [[ "${ACCELERATION}" == "true" ]]; then
        local body="acceleration=1"
        body="${body}&$(form_urlencode_pairs acceleration.earliest_time "${EARLIEST_TIME}")"
        [[ -n "${BACKFILL_TIME}" ]] && body="${body}&$(form_urlencode_pairs acceleration.backfill_time "${BACKFILL_TIME}")"
        [[ -n "${MAX_CONCURRENT}" ]] && body="${body}&$(form_urlencode_pairs acceleration.max_concurrent "${MAX_CONCURRENT}")"
        [[ "${MANUAL_REBUILDS}" != "unset" ]] && body="${body}&$(form_urlencode_pairs acceleration.manual_rebuilds "${MANUAL_REBUILDS}")"
        [[ -n "${CRON_SCHEDULE}" ]] && body="${body}&$(form_urlencode_pairs acceleration.cron_schedule "${CRON_SCHEDULE}")"
        if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "datamodels" "${DATAMODEL}" "${body}"; then
            log "ERROR: Failed to set acceleration for data model '${DATAMODEL}'."
            exit 1
        fi
        log "Acceleration enabled for ${DATAMODEL} (earliest ${EARLIEST_TIME})."
    elif [[ "${ACCELERATION}" == "false" ]]; then
        if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "datamodels" "${DATAMODEL}" "acceleration=0"; then
            log "ERROR: Failed to disable acceleration for data model '${DATAMODEL}'."
            exit 1
        fi
        log "Acceleration disabled for ${DATAMODEL}."
    fi
    if [[ -n "${CONSTRAIN_INDEXES}" ]]; then
        local idx_def parts
        IFS=',' read -ra parts <<<"${CONSTRAIN_INDEXES}"
        idx_def=""
        local idx
        for idx in "${parts[@]}"; do
            idx="$(echo "${idx}" | tr -d '[:space:]')"
            [[ -z "${idx}" ]] && continue
            if [[ ! "${idx}" =~ ^[A-Za-z0-9_-]{1,80}$ ]]; then
                log "ERROR: invalid index name '${idx}'."
                exit 1
            fi
            [[ -n "${idx_def}" ]] && idx_def="${idx_def} OR "
            idx_def="${idx_def}index=${idx}"
        done
        local macro_body
        macro_body=$(form_urlencode_pairs definition "(${idx_def})" iseval "0")
        if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "macros" "cim_${DATAMODEL}_indexes" "${macro_body}"; then
            log "ERROR: Failed to write macro cim_${DATAMODEL}_indexes."
            exit 1
        fi
        log "Index-constraint macro cim_${DATAMODEL}_indexes written."
    fi
    if [[ -n "${EVENTTYPE_NAME}" ]]; then
        local et_body
        et_body=$(form_urlencode_pairs search "${EVENTTYPE_SEARCH}")
        if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "eventtypes" "${EVENTTYPE_NAME}" "${et_body}"; then
            log "ERROR: Failed to write eventtype ${EVENTTYPE_NAME}."
            exit 1
        fi
        log "Eventtype ${EVENTTYPE_NAME} written."
        if [[ -n "${TAGS}" ]]; then
            local tag_body tparts t
            tag_body=""
            IFS=',' read -ra tparts <<<"${TAGS}"
            for t in "${tparts[@]}"; do
                t="$(echo "${t}" | tr -d '[:space:]')"
                [[ -z "${t}" ]] && continue
                [[ -n "${tag_body}" ]] && tag_body="${tag_body}&"
                tag_body="${tag_body}$(form_urlencode_pairs "${t}" "enabled")"
            done
            if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "tags" "eventtype=${EVENTTYPE_NAME}" "${tag_body}"; then
                log "ERROR: Failed to write tags for eventtype ${EVENTTYPE_NAME}."
                exit 1
            fi
            log "CIM tags written for eventtype ${EVENTTYPE_NAME}."
        fi
    fi
    log "$(log_platform_restart_guidance "CIM data model or knowledge object changes")"
}

run_validate() {
    local dir="${OUTPUT_DIR}/cim"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./validate-tstats.sh)"
        return 0
    fi
    (cd "${dir}" && ./validate-tstats.sh)
}

main() {
    validate_args
    build_renderer_args
    if [[ "${DRY_RUN}" == "true" ]]; then
        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
        else
            python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
            [[ "${PHASE}" == "apply" || "${PHASE}" == "all" ]] && apply_live
        fi
        exit 0
    fi
    case "${PHASE}" in
        render)
            render_assets
            [[ "${APPLY}" == "true" ]] && apply_live
            ;;
        preflight) render_assets ;;
        apply) render_assets; apply_live ;;
        status) render_assets; run_validate ;;
        all) render_assets; apply_live; run_validate ;;
    esac
}

main "$@"

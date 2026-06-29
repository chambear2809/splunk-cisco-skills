#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-knowledge-objects-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
APP_NAME="search"
OBJECT_KIND=""
NAME=""
SEARCH=""
IS_SCHEDULED="false"
CRON_SCHEDULE=""
DISPATCH_EARLIEST_TIME=""
DISPATCH_LATEST_TIME=""
ALERT_TYPE=""
ALERT_CONDITION=""
ACTIONS=""
DEFINITION=""
ARGS=""
ISEVAL="0"
LOOKUP_TYPE="csv"
LOOKUP_FILENAME=""
COLLECTION=""
FIELDS_LIST=""
CSV_HEADERS=""
AUTO_LOOKUP_SOURCETYPE=""
LOOKUP_INPUT_FIELDS=""
LOOKUP_OUTPUT_FIELDS=""
EVENTTYPE_SEARCH=""
TAGS=""
SHARING="app"
OWNER="nobody"
READ_ROLES=""
WRITE_ROLES=""
ACCEPT_GLOBAL_SHARING=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Knowledge Objects Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|apply|status|all
  --apply | --dry-run | --json
  --output-dir PATH
  --app-name NAME
  --object-kind savedsearch|macro|lookup|eventtype|tag   (required)
  --name NAME
  --search SPL                 (savedsearch)
  --is-scheduled true|false
  --cron-schedule CRON
  --dispatch-earliest-time SPL_TIME
  --dispatch-latest-time SPL_TIME
  --alert-type TYPE
  --alert-condition SPL
  --actions CSV                (e.g. email,webhook)
  --definition SPL             (macro)
  --args CSV
  --iseval 0|1
  --lookup-type csv|kvstore
  --lookup-filename FILE.csv
  --collection NAME            (kvstore lookup)
  --fields-list CSV
  --csv-headers CSV
  --auto-lookup-sourcetype ST  (bind automatic lookup in props.conf)
  --lookup-input-fields CSV
  --lookup-output-fields CSV
  --eventtype-search SPL
  --tags CSV
  --sharing user|app|global
  --owner USER
  --read-roles CSV
  --write-roles CSV
  --accept-global-sharing      (required to apply sharing=global)
  --help

Examples:
  $(basename "$0") --object-kind macro --name net_idx --definition 'index IN (a,b)'
  $(basename "$0") --phase apply --object-kind savedsearch --name "Daily Count" \\
    --search 'index=main | stats count' --is-scheduled true --cron-schedule '0 6 * * *' --app-name search

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
        --object-kind) require_arg "$1" $# || exit 1; OBJECT_KIND="$2"; shift 2 ;;
        --name) require_arg "$1" $# || exit 1; NAME="$2"; shift 2 ;;
        --search) require_arg "$1" $# || exit 1; SEARCH="$2"; shift 2 ;;
        --is-scheduled) require_arg "$1" $# || exit 1; IS_SCHEDULED="$2"; shift 2 ;;
        --cron-schedule) require_arg "$1" $# || exit 1; CRON_SCHEDULE="$2"; shift 2 ;;
        --dispatch-earliest-time) require_arg "$1" $# || exit 1; DISPATCH_EARLIEST_TIME="$2"; shift 2 ;;
        --dispatch-latest-time) require_arg "$1" $# || exit 1; DISPATCH_LATEST_TIME="$2"; shift 2 ;;
        --alert-type) require_arg "$1" $# || exit 1; ALERT_TYPE="$2"; shift 2 ;;
        --alert-condition) require_arg "$1" $# || exit 1; ALERT_CONDITION="$2"; shift 2 ;;
        --actions) require_arg "$1" $# || exit 1; ACTIONS="$2"; shift 2 ;;
        --definition) require_arg "$1" $# || exit 1; DEFINITION="$2"; shift 2 ;;
        --args) require_arg "$1" $# || exit 1; ARGS="$2"; shift 2 ;;
        --iseval) require_arg "$1" $# || exit 1; ISEVAL="$2"; shift 2 ;;
        --lookup-type) require_arg "$1" $# || exit 1; LOOKUP_TYPE="$2"; shift 2 ;;
        --lookup-filename) require_arg "$1" $# || exit 1; LOOKUP_FILENAME="$2"; shift 2 ;;
        --collection) require_arg "$1" $# || exit 1; COLLECTION="$2"; shift 2 ;;
        --fields-list) require_arg "$1" $# || exit 1; FIELDS_LIST="$2"; shift 2 ;;
        --csv-headers) require_arg "$1" $# || exit 1; CSV_HEADERS="$2"; shift 2 ;;
        --auto-lookup-sourcetype) require_arg "$1" $# || exit 1; AUTO_LOOKUP_SOURCETYPE="$2"; shift 2 ;;
        --lookup-input-fields) require_arg "$1" $# || exit 1; LOOKUP_INPUT_FIELDS="$2"; shift 2 ;;
        --lookup-output-fields) require_arg "$1" $# || exit 1; LOOKUP_OUTPUT_FIELDS="$2"; shift 2 ;;
        --eventtype-search) require_arg "$1" $# || exit 1; EVENTTYPE_SEARCH="$2"; shift 2 ;;
        --tags) require_arg "$1" $# || exit 1; TAGS="$2"; shift 2 ;;
        --sharing) require_arg "$1" $# || exit 1; SHARING="$2"; shift 2 ;;
        --owner) require_arg "$1" $# || exit 1; OWNER="$2"; shift 2 ;;
        --read-roles) require_arg "$1" $# || exit 1; READ_ROLES="$2"; shift 2 ;;
        --write-roles) require_arg "$1" $# || exit 1; WRITE_ROLES="$2"; shift 2 ;;
        --accept-global-sharing) ACCEPT_GLOBAL_SHARING=true; shift ;;
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
    [[ -n "${OBJECT_KIND}" ]] || { log "ERROR: --object-kind is required."; exit 1; }
    validate_choice "${OBJECT_KIND}" savedsearch macro lookup eventtype tag
    validate_choice "${SHARING}" user app global
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
        --object-kind "${OBJECT_KIND}"
        --name "${NAME}"
        --search "${SEARCH}"
        --is-scheduled "${IS_SCHEDULED}"
        --cron-schedule "${CRON_SCHEDULE}"
        --dispatch-earliest-time "${DISPATCH_EARLIEST_TIME}"
        --dispatch-latest-time "${DISPATCH_LATEST_TIME}"
        --alert-type "${ALERT_TYPE}"
        --alert-condition "${ALERT_CONDITION}"
        --actions "${ACTIONS}"
        --definition "${DEFINITION}"
        --args "${ARGS}"
        --iseval "${ISEVAL}"
        --lookup-type "${LOOKUP_TYPE}"
        --lookup-filename "${LOOKUP_FILENAME}"
        --collection "${COLLECTION}"
        --fields-list "${FIELDS_LIST}"
        --csv-headers "${CSV_HEADERS}"
        --auto-lookup-sourcetype "${AUTO_LOOKUP_SOURCETYPE}"
        --lookup-input-fields "${LOOKUP_INPUT_FIELDS}"
        --lookup-output-fields "${LOOKUP_OUTPUT_FIELDS}"
        --eventtype-search "${EVENTTYPE_SEARCH}"
        --tags "${TAGS}"
        --sharing "${SHARING}"
        --owner "${OWNER}"
        --read-roles "${READ_ROLES}"
        --write-roles "${WRITE_ROLES}"
    )
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

conf_name() {
    case "${OBJECT_KIND}" in
        savedsearch) printf '%s' "savedsearches" ;;
        macro) printf '%s' "macros" ;;
        lookup) printf '%s' "transforms" ;;
        eventtype) printf '%s' "eventtypes" ;;
        tag) printf '%s' "tags" ;;
    esac
}

stanza_name() {
    case "${OBJECT_KIND}" in
        tag) printf 'eventtype=%s' "${NAME}" ;;
        macro)
            if [[ -n "${ARGS}" && "${NAME}" != *"("* ]]; then
                local count
                count=$(awk -F',' '{print NF}' <<<"${ARGS}")
                printf '%s(%s)' "${NAME}" "${count}"
            else
                printf '%s' "${NAME}"
            fi
            ;;
        *) printf '%s' "${NAME}" ;;
    esac
}

build_body() {
    case "${OBJECT_KIND}" in
        savedsearch)
            BODY=$(form_urlencode_pairs search "${SEARCH}")
            [[ "${IS_SCHEDULED}" == "true" ]] && BODY="${BODY}&$(form_urlencode_pairs enableSched 1)"
            [[ -n "${CRON_SCHEDULE}" ]] && BODY="${BODY}&$(form_urlencode_pairs cron_schedule "${CRON_SCHEDULE}")"
            [[ -n "${DISPATCH_EARLIEST_TIME}" ]] && BODY="${BODY}&$(form_urlencode_pairs dispatch.earliest_time "${DISPATCH_EARLIEST_TIME}")"
            [[ -n "${DISPATCH_LATEST_TIME}" ]] && BODY="${BODY}&$(form_urlencode_pairs dispatch.latest_time "${DISPATCH_LATEST_TIME}")"
            [[ -n "${ALERT_TYPE}" ]] && BODY="${BODY}&$(form_urlencode_pairs alert_type "${ALERT_TYPE}")"
            [[ -n "${ALERT_CONDITION}" ]] && BODY="${BODY}&$(form_urlencode_pairs alert_condition "${ALERT_CONDITION}")"
            if [[ -n "${ACTIONS}" ]]; then
                local _action _action_parts
                IFS=',' read -ra _action_parts <<<"${ACTIONS}"
                for _action in "${_action_parts[@]}"; do
                    _action="$(echo "${_action}" | tr -d '[:space:]')"
                    [[ -z "${_action}" ]] && continue
                    BODY="${BODY}&$(form_urlencode_pairs "action.${_action}" 1)"
                done
                BODY="${BODY}&$(form_urlencode_pairs actions "${ACTIONS//,/, }")"
            fi
            ;;
        macro)
            BODY=$(form_urlencode_pairs definition "${DEFINITION}" iseval "${ISEVAL}")
            [[ -n "${ARGS}" ]] && BODY="${BODY}&$(form_urlencode_pairs args "${ARGS//,/, }")"
            ;;
        lookup)
            if [[ "${LOOKUP_TYPE}" == "csv" ]]; then
                BODY=$(form_urlencode_pairs filename "${LOOKUP_FILENAME}")
            else
                BODY=$(form_urlencode_pairs external_type "kvstore" collection "${COLLECTION}")
            fi
            [[ -n "${FIELDS_LIST}" ]] && BODY="${BODY}&$(form_urlencode_pairs fields_list "${FIELDS_LIST//,/, }")"
            ;;
        eventtype)
            BODY=$(form_urlencode_pairs search "${EVENTTYPE_SEARCH}")
            ;;
        tag)
            BODY=""
            local t parts
            IFS=',' read -ra parts <<<"${TAGS}"
            for t in "${parts[@]}"; do
                t="$(echo "${t}" | tr -d '[:space:]')"
                [[ -z "${t}" ]] && continue
                [[ -n "${BODY}" ]] && BODY="${BODY}&"
                BODY="${BODY}$(form_urlencode_pairs "${t}" enabled)"
            done
            ;;
    esac
}

apply_live() {
    if [[ "${SHARING}" == "global" && "${ACCEPT_GLOBAL_SHARING}" != "true" ]]; then
        log "ERROR: sharing=global is broad. Re-run with --accept-global-sharing."
        exit 1
    fi
    local conf stanza
    conf="$(conf_name)"
    stanza="$(stanza_name)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would write conf-${conf}/[${stanza}] in app ${APP_NAME} and set ACL sharing=${SHARING} owner=${OWNER}."
        if [[ "${OBJECT_KIND}" == "lookup" && -n "${AUTO_LOOKUP_SOURCETYPE}" ]]; then
            log "DRY RUN: would also bind LOOKUP-${NAME} on source type ${AUTO_LOOKUP_SOURCETYPE} (props.conf)."
        fi
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    local sk
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
    build_body
    if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "${conf}" "${stanza}" "${BODY}"; then
        log "ERROR: Failed to write ${OBJECT_KIND} '${stanza}' to conf-${conf}."
        exit 1
    fi
    log "Wrote ${OBJECT_KIND} '${stanza}' to app ${APP_NAME}."
    apply_acl "${sk}" "${conf}" "${stanza}"
    apply_auto_lookup_props "${sk}"
    log "$(log_platform_restart_guidance "knowledge object changes")"
}

# Bind an automatic lookup in props.conf when --auto-lookup-sourcetype is set.
# Mirrors render_props() so the live apply matches the rendered props.conf.
apply_auto_lookup_props() {
    local sk="$1"
    [[ "${OBJECT_KIND}" == "lookup" && -n "${AUTO_LOOKUP_SOURCETYPE}" ]] || return 0
    local spec="${NAME}" item parts
    if [[ -n "${LOOKUP_INPUT_FIELDS}" ]]; then
        IFS=',' read -ra parts <<<"${LOOKUP_INPUT_FIELDS}"
        for item in "${parts[@]}"; do
            item="$(echo "${item}" | tr -d '[:space:]')"
            [[ -n "${item}" ]] && spec="${spec} ${item}"
        done
    fi
    if [[ -n "${LOOKUP_OUTPUT_FIELDS}" ]]; then
        spec="${spec} OUTPUT"
        IFS=',' read -ra parts <<<"${LOOKUP_OUTPUT_FIELDS}"
        for item in "${parts[@]}"; do
            item="$(echo "${item}" | tr -d '[:space:]')"
            [[ -n "${item}" ]] && spec="${spec} ${item}"
        done
    fi
    local pbody
    pbody=$(form_urlencode_pairs "LOOKUP-${NAME}" "${spec}")
    if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "props" "${AUTO_LOOKUP_SOURCETYPE}" "${pbody}"; then
        log "ERROR: Failed to bind LOOKUP-${NAME} on ${AUTO_LOOKUP_SOURCETYPE} (props.conf)."
        exit 1
    fi
    log "Bound automatic lookup LOOKUP-${NAME} on source type ${AUTO_LOOKUP_SOURCETYPE} (props.conf)."
}

apply_acl() {
    local sk="$1" conf="$2" stanza="$3"
    local acl_body encoded_stanza
    acl_body=$(form_urlencode_pairs sharing "${SHARING}" owner "${OWNER}")
    local role
    if [[ -n "${READ_ROLES}" ]]; then
        IFS=',' read -ra _read <<<"${READ_ROLES}"
        for role in "${_read[@]}"; do
            role="$(echo "${role}" | tr -d '[:space:]')"
            [[ -n "${role}" ]] && acl_body="${acl_body}&$(form_urlencode_pairs perms.read "${role}")"
        done
    fi
    if [[ -n "${WRITE_ROLES}" ]]; then
        IFS=',' read -ra _write <<<"${WRITE_ROLES}"
        for role in "${_write[@]}"; do
            role="$(echo "${role}" | tr -d '[:space:]')"
            [[ -n "${role}" ]] && acl_body="${acl_body}&$(form_urlencode_pairs perms.write "${role}")"
        done
    fi
    encoded_stanza=$(_urlencode "${stanza}")
    local http_code resp
    resp=$(splunk_curl_post "${sk}" "${acl_body}" \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/configs/conf-${conf}/${encoded_stanza}/acl" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        200|201) log "ACL set: sharing=${SHARING}, owner=${OWNER}." ;;
        *) log "WARNING: ACL update returned HTTP ${http_code}; review object permissions manually." ;;
    esac
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
        status) render_assets ;;
        all) render_assets; apply_live ;;
    esac
}

main "$@"

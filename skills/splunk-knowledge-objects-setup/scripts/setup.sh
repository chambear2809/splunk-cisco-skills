#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
STATE_HELPER="${SCRIPT_DIR}/transaction_state.py"
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
STATE_DIR=""
TXN_DIR=""
EVENTS_FILE=""
DESIRED_BODY_FILE=""
PROPS_BODY_FILE=""
PRE_OBJECT_CODE=""
PRE_ACL_CODE=""
PRE_PROPS_CODE="not-requested"
ROLLBACK_STATUS="not-required"
TRANSACTION_MUTATED=false
TRANSACTION_FINISHED=false
TRANSACTION_ROLLBACK_ACTIVE=false
TRANSACTION_SK=""
TRANSACTION_CONF=""
TRANSACTION_STANZA=""
MANUAL_CLEANUP_REQUIRED=false
MANUAL_CLEANUP_PATH=""

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

Live phases:
  preflight  Authenticates and snapshots the real object, ACL, and optional
             automatic-lookup endpoint without mutating them.
  status     Queries live content and ACL state and exits nonzero on drift.
  apply/all  Preflight, apply content+ACL, and verify. Failed mutations are
             retained for reviewed recovery with private
             before/current evidence under knowledge-objects/state/.

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
    if [[ ! "${APP_NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$ ]]; then
        log "ERROR: --app-name must start with a letter or number and use at most 128 safe characters."
        exit 1
    fi
    if [[ ! "${OWNER}" =~ ^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$ ]]; then
        log "ERROR: --owner must be a 1-128 character Splunk username using letters, numbers, dot, underscore, @, or hyphen."
        exit 1
    fi
    if [[ "${NAME}" == "." || "${NAME}" == ".." ]]; then
        log "ERROR: --name must not be a dot path segment."
        exit 1
    fi
    if [[ "${AUTO_LOOKUP_SOURCETYPE}" == "." || "${AUTO_LOOKUP_SOURCETYPE}" == ".." ]]; then
        log "ERROR: --auto-lookup-sourcetype must not be a dot path segment."
        exit 1
    fi
    if [[ "${SHARING}" == "user" && "${OWNER}" == "nobody" ]]; then
        log "ERROR: sharing=user requires an explicit user owner, not nobody."
        exit 1
    fi
    if [[ "${SHARING}" != "user" && "${OWNER}" != "nobody" ]]; then
        log "ERROR: app/global knowledge objects must use --owner nobody."
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

prepare_state_dir() {
    STATE_DIR="${OUTPUT_DIR}/knowledge-objects/state"
    if [[ -L "${STATE_DIR}" ]]; then
        log "ERROR: Refusing symlink transaction-state directory: ${STATE_DIR}"
        return 1
    fi
    mkdir -p "${STATE_DIR}"
    [[ -d "${STATE_DIR}" ]] || { log "ERROR: Transaction-state path is not a directory: ${STATE_DIR}"; return 1; }
    chmod 700 "${STATE_DIR}"
}

begin_transaction() {
    prepare_state_dir || return 1
    TXN_DIR="$(mktemp -d "${STATE_DIR}/.transaction.XXXXXX")"
    chmod 700 "${TXN_DIR}"
    EVENTS_FILE="${TXN_DIR}/events.jsonl"
    : > "${EVENTS_FILE}"
    chmod 600 "${EVENTS_FILE}"
    DESIRED_BODY_FILE="${TXN_DIR}/desired-object.form"
    PROPS_BODY_FILE="${TXN_DIR}/desired-props.form"
    TRANSACTION_MUTATED=false
    TRANSACTION_FINISHED=false
    TRANSACTION_ROLLBACK_ACTIVE=false
    MANUAL_CLEANUP_REQUIRED=false
    MANUAL_CLEANUP_PATH=""
    trap 'transaction_exit_handler $?' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
}

transaction_exit_handler() {
    local exit_code="$1"
    trap - EXIT INT TERM
    if [[ "${TRANSACTION_MUTATED:-false}" == "true" \
        && "${TRANSACTION_FINISHED:-false}" != "true" \
        && "${TRANSACTION_ROLLBACK_ACTIVE:-false}" != "true" \
        && -n "${TRANSACTION_SK:-}" ]]; then
        TRANSACTION_ROLLBACK_ACTIVE=true
        record_event "unexpected-exit" "failed" "The process exited after mutation and before verified completion; read-only failure reconciliation started." || true
        rollback_transaction "${TRANSACTION_SK}" "${TRANSACTION_CONF}" "${TRANSACTION_STANZA}" || true
        rm -f -- "${STATE_DIR}/live-status.json"
        write_transaction_evidence "failed" "unexpected-exit" "${ROLLBACK_STATUS}" \
            "${STATE_DIR}/apply-evidence.json" || true
        log "ERROR: Apply exited unexpectedly after mutation. Evidence: ${STATE_DIR}/apply-evidence.json"
    fi
    cleanup_transaction
    exit "${exit_code}"
}

cleanup_transaction() {
    if [[ -n "${TXN_DIR:-}" && -d "${TXN_DIR}" ]]; then
        rm -rf -- "${TXN_DIR}"
    fi
    TXN_DIR=""
}

record_event() {
    python3 "${STATE_HELPER}" event \
        --events "${EVENTS_FILE}" --step "$1" --status "$2" --detail "$3"
}

ensure_manual_cleanup_dir() {
    local candidate
    if [[ -n "${MANUAL_CLEANUP_PATH}" ]]; then
        [[ -d "${MANUAL_CLEANUP_PATH}" && ! -L "${MANUAL_CLEANUP_PATH}" ]]
        return
    fi
    candidate="${STATE_DIR}/manual-cleanup-$(date -u '+%Y%m%dT%H%M%SZ')-$$"
    if [[ -e "${candidate}" || -L "${candidate}" ]]; then
        log "ERROR: Refusing existing manual-cleanup evidence path: ${candidate}"
        return 1
    fi
    mkdir -m 700 -- "${candidate}" || return 1
    [[ -d "${candidate}" && ! -L "${candidate}" ]] || return 1
    MANUAL_CLEANUP_PATH="${candidate}"
}

preserve_private_snapshot() {
    local label="$1" source="$2"
    [[ -f "${source}" ]] || return 0
    ensure_manual_cleanup_dir || return 1
    python3 "${STATE_HELPER}" publish-raw \
        --source "${source}" --output "${MANUAL_CLEANUP_PATH}/${label}"
}

require_manual_cleanup() {
    local target="$1"
    MANUAL_CLEANUP_REQUIRED=true
    ensure_manual_cleanup_dir || return 1
    log "MANUAL RECOVERY REQUIRED: retained failed ${target}; automatic restore and DELETE are disabled because Splunk exposes no verified conditional write/delete contract."
    log "Review private before/current evidence under ${MANUAL_CLEANUP_PATH}, fetch the exact live stanza and ACL again, confirm no concurrent owner changed them, then reconcile through the supported Splunk UI/REST workflow."
}

object_endpoint() {
    local conf="$1" stanza="$2"
    printf '%s/servicesNS/%s/%s/configs/conf-%s/%s' \
        "${SPLUNK_URI}" "$(_urlencode "$(namespace_owner)")" "$(_urlencode "${APP_NAME}")" \
        "$(_urlencode "${conf}")" "$(_urlencode "${stanza}")"
}

props_endpoint() {
    printf '%s/servicesNS/nobody/%s/configs/conf-props/%s' \
        "${SPLUNK_URI}" "$(_urlencode "${APP_NAME}")" "$(_urlencode "${AUTO_LOOKUP_SOURCETYPE}")"
}

namespace_owner() {
    if [[ "${SHARING}" == "user" ]]; then
        printf '%s' "${OWNER}"
    else
        printf '%s' "nobody"
    fi
}

set_conf_body() {
    local sk="$1" namespace="$2" conf="$3" stanza="$4" body="$5"
    local endpoint collection create_body resp http_code
    endpoint="${SPLUNK_URI}/servicesNS/$(_urlencode "${namespace}")/$(_urlencode "${APP_NAME}")/configs/conf-$(_urlencode "${conf}")/$(_urlencode "${stanza}")"
    collection="${SPLUNK_URI}/servicesNS/$(_urlencode "${namespace}")/$(_urlencode "${APP_NAME}")/configs/conf-$(_urlencode "${conf}")"
    resp=$(splunk_curl_post "${sk}" "${body}" "${endpoint}" -w '\n%{http_code}' 2>/dev/null) || return 1
    http_code=$(echo "${resp}" | tail -1)
    [[ "${http_code}" == "200" ]] && return 0
    [[ "${http_code}" == "404" ]] || return 1
    create_body=$(form_urlencode_pairs name "${stanza}") || return 1
    [[ -z "${body}" ]] || create_body="${create_body}&${body}"
    resp=$(splunk_curl_post "${sk}" "${create_body}" "${collection}" -w '\n%{http_code}' 2>/dev/null) || return 1
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        200|201) return 0 ;;
        *) return 1 ;;
    esac
}

# Capture a response body and print only its HTTP status. The caller supplies a
# private transaction path; raw live config never becomes console output.
capture_endpoint() {
    local sk="$1" url="$2" destination="$3"
    local response code
    response="$(mktemp "${TXN_DIR}/.response.XXXXXX")"
    chmod 600 "${response}"
    if ! splunk_curl "${sk}" "${url}?output_mode=json" -w '\n%{http_code}' > "${response}" 2>/dev/null; then
        : > "${destination}"
        rm -f -- "${response}"
        printf '%s' "000"
        return 0
    fi
    code="$(tail -n 1 "${response}")"
    [[ "${code}" =~ ^[0-9]{3}$ ]] || code="000"
    sed '$d' "${response}" > "${destination}"
    chmod 600 "${destination}"
    rm -f -- "${response}"
    printf '%s' "${code}"
}

write_transaction_evidence() {
    local result="$1" failure_step="$2" rollback="$3" destination="$4"
    local existed=false
    [[ "${PRE_OBJECT_CODE}" == "200" ]] && existed=true
    python3 "${STATE_HELPER}" evidence \
        --events "${EVENTS_FILE}" --output "${destination}" \
        --result "${result}" --failure-step "${failure_step}" --rollback "${rollback}" \
        --app "${APP_NAME}" --kind "${OBJECT_KIND}" --name "$(stanza_name)" \
        --object-existed "${existed}" \
        --manual-cleanup-required "${MANUAL_CLEANUP_REQUIRED}" \
        --manual-cleanup-path "${MANUAL_CLEANUP_PATH}"
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
    return 0
}

build_auto_lookup_body() {
    PROPS_BODY=""
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
    PROPS_BODY=$(form_urlencode_pairs "LOOKUP-${NAME}" "${spec}")
    return 0
}

build_acl_body() {
    ACL_BODY=$(form_urlencode_pairs sharing "${SHARING}" owner "${OWNER}")
    local role
    if [[ -n "${READ_ROLES}" ]]; then
        IFS=',' read -ra _read <<<"${READ_ROLES}"
        for role in "${_read[@]}"; do
            role="$(echo "${role}" | tr -d '[:space:]')"
            [[ -n "${role}" ]] && ACL_BODY="${ACL_BODY}&$(form_urlencode_pairs perms.read "${role}")"
        done
    fi
    if [[ -n "${WRITE_ROLES}" ]]; then
        IFS=',' read -ra _write <<<"${WRITE_ROLES}"
        for role in "${_write[@]}"; do
            role="$(echo "${role}" | tr -d '[:space:]')"
            [[ -n "${role}" ]] && ACL_BODY="${ACL_BODY}&$(form_urlencode_pairs perms.write "${role}")"
        done
    fi
    return 0
}

post_acl_body() {
    local sk="$1" conf="$2" stanza="$3" acl_body="$4"
    local http_code resp
    resp=$(splunk_curl_post "${sk}" "${acl_body}" \
        "$(object_endpoint "${conf}" "${stanza}")/acl" \
        -w '\n%{http_code}' 2>/dev/null) || return 1
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        200|201) return 0 ;;
        *) return 1 ;;
    esac
}

capture_preflight_state() {
    local sk="$1" conf="$2" stanza="$3"
    local allow_bundle="${4:-false}" code context_json
    if [[ "${allow_bundle}" != "true" ]] && deployment_should_manage_search_config_via_bundle; then
        log "ERROR: Transactional content+ACL apply is not supported through an SHC deployer bundle."
        log "       This skill does not render local.meta or a bulk SHC bundle."
        log "HANDOFF: prepare a reviewed, deployer-owned app bundle through a supported SHC deployment workflow."
        record_event "delivery-plane" "failed" "Bundle-managed target refused before mutation because REST ACL governance cannot be atomic with a deployer write."
        return 1
    fi

    code="$(capture_endpoint "${sk}" "${SPLUNK_URI}/services/apps/local/$(_urlencode "${APP_NAME}")" "${TXN_DIR}/app.json")"
    if [[ "${code}" != "200" ]]; then
        record_event "app-access" "failed" "Target app was not readable during preflight (HTTP ${code})."
        log "ERROR: Target app ${APP_NAME} is not readable (HTTP ${code}); refusing mutation."
        return 1
    fi
    record_event "app-access" "passed" "Target app is readable."

    code="$(capture_endpoint "${sk}" "${SPLUNK_URI}/services/authentication/current-context" "${TXN_DIR}/context.json")"
    if [[ "${code}" != "200" ]] || ! context_json="$(python3 "${STATE_HELPER}" context --snapshot "${TXN_DIR}/context.json" 2>/dev/null)"; then
        record_event "authenticated-context" "failed" "Authenticated context/capabilities were not readable."
        log "ERROR: Could not read authenticated Splunk context; refusing mutation."
        return 1
    fi
    [[ -n "${context_json}" ]] || return 1
    record_event "authenticated-context" "passed" "Authenticated context and capabilities were captured."

    code="$(capture_endpoint "${sk}" \
        "${SPLUNK_URI}/servicesNS/$(_urlencode "$(namespace_owner)")/$(_urlencode "${APP_NAME}")/configs/conf-$(_urlencode "${conf}")" \
        "${TXN_DIR}/collection.json")"
    if [[ "${code}" != "200" ]]; then
        record_event "conf-access" "failed" "Target conf collection was not readable (HTTP ${code})."
        log "ERROR: conf-${conf} is not readable in app ${APP_NAME} (HTTP ${code}); refusing mutation."
        return 1
    fi
    record_event "conf-access" "passed" "Target conf collection is readable."

    PRE_OBJECT_CODE="$(capture_endpoint "${sk}" "$(object_endpoint "${conf}" "${stanza}")" "${TXN_DIR}/before-object.json")"
    case "${PRE_OBJECT_CODE}" in
        200) record_event "object-snapshot" "passed" "Existing object was snapshotted before mutation." ;;
        404) record_event "object-snapshot" "passed" "Target object does not exist; a failed create will be retained for reviewed recovery because conditional delete is unavailable." ;;
        *)
            record_event "object-snapshot" "failed" "Object snapshot failed (HTTP ${PRE_OBJECT_CODE})."
            log "ERROR: Could not snapshot target object (HTTP ${PRE_OBJECT_CODE}); refusing mutation."
            return 1
            ;;
    esac

    PRE_ACL_CODE="404"
    : > "${TXN_DIR}/before-acl.json"
    if [[ "${PRE_OBJECT_CODE}" == "200" ]]; then
        PRE_ACL_CODE="$(capture_endpoint "${sk}" "$(object_endpoint "${conf}" "${stanza}")/acl" "${TXN_DIR}/before-acl.json")"
        if [[ "${PRE_ACL_CODE}" != "200" ]]; then
            record_event "acl-snapshot" "failed" "Existing ACL snapshot failed (HTTP ${PRE_ACL_CODE})."
            log "ERROR: Could not snapshot existing ACL (HTTP ${PRE_ACL_CODE}); refusing mutation."
            return 1
        fi
        record_event "acl-snapshot" "passed" "Existing ACL was snapshotted before mutation."
    else
        record_event "acl-snapshot" "passed" "No pre-existing object ACL was present."
    fi

    PRE_PROPS_CODE="not-requested"
    : > "${TXN_DIR}/before-props.json"
    if [[ -n "${PROPS_BODY}" ]]; then
        PRE_PROPS_CODE="$(capture_endpoint "${sk}" "$(props_endpoint)" "${TXN_DIR}/before-props.json")"
        case "${PRE_PROPS_CODE}" in
            200|404) record_event "props-snapshot" "passed" "Automatic-lookup props state was snapshotted before mutation." ;;
            *)
                record_event "props-snapshot" "failed" "Automatic-lookup props snapshot failed (HTTP ${PRE_PROPS_CODE})."
                log "ERROR: Could not snapshot automatic-lookup props state (HTTP ${PRE_PROPS_CODE}); refusing mutation."
                return 1
                ;;
        esac
    fi
}

evaluate_live_state() {
    local sk="$1" conf="$2" stanza="$3" prefix="$4" output="$5"
    local object_code acl_code props_code="not-requested"
    local -a props_args=()
    object_code="$(capture_endpoint "${sk}" "$(object_endpoint "${conf}" "${stanza}")" "${TXN_DIR}/${prefix}-object.json")"
    acl_code="404"
    : > "${TXN_DIR}/${prefix}-acl.json"
    if [[ "${object_code}" == "200" ]]; then
        acl_code="$(capture_endpoint "${sk}" "$(object_endpoint "${conf}" "${stanza}")/acl" "${TXN_DIR}/${prefix}-acl.json")"
    fi
    if [[ -n "${PROPS_BODY}" ]]; then
        props_code="$(capture_endpoint "${sk}" "$(props_endpoint)" "${TXN_DIR}/${prefix}-props.json")"
        props_args=(
            --props-file "${TXN_DIR}/${prefix}-props.json"
            --props-code "${props_code}"
            --props-body-file "${PROPS_BODY_FILE}"
        )
    fi
    python3 "${STATE_HELPER}" status \
        --object-file "${TXN_DIR}/${prefix}-object.json" --object-code "${object_code}" \
        --acl-file "${TXN_DIR}/${prefix}-acl.json" --acl-code "${acl_code}" \
        --desired-body-file "${DESIRED_BODY_FILE}" \
        --acl-plan "${OUTPUT_DIR}/knowledge-objects/acl-plan.json" \
        ${props_args[@]+"${props_args[@]}"} --output "${output}"
}

claim_new_object_state() {
    local sk="$1" conf="$2" stanza="$3" object_code acl_code
    object_code="$(capture_endpoint "${sk}" "$(object_endpoint "${conf}" "${stanza}")" "${TXN_DIR}/owned-object.json")"
    if [[ "${object_code}" != "200" ]]; then
        record_event "object-ownership-snapshot" "failed" "The new object could not be read back completely (HTTP ${object_code})."
        return 1
    fi
    if ! python3 "${STATE_HELPER}" claim-config \
        --snapshot "${TXN_DIR}/owned-object.json" --desired-body-file "${DESIRED_BODY_FILE}" >/dev/null; then
        record_event "object-ownership-snapshot" "failed" "The new object contained missing, mismatched, or unexpected mutable fields."
        return 1
    fi
    acl_code="$(capture_endpoint "${sk}" "$(object_endpoint "${conf}" "${stanza}")/acl" "${TXN_DIR}/owned-acl.json")"
    if [[ "${acl_code}" != "200" ]]; then
        record_event "object-ownership-snapshot" "failed" "The new object's initial ACL could not be read back (HTTP ${acl_code})."
        return 1
    fi
    record_event "object-ownership-snapshot" "passed" "Captured the complete transaction-created object and its initial ACL before governance mutation."
}

claim_new_props_state() {
    local sk="$1" props_code
    props_code="$(capture_endpoint "${sk}" "$(props_endpoint)" "${TXN_DIR}/owned-props.json")"
    if [[ "${props_code}" != "200" ]]; then
        record_event "props-ownership-snapshot" "failed" "The new automatic-lookup stanza could not be read back completely (HTTP ${props_code})."
        return 1
    fi
    if ! python3 "${STATE_HELPER}" claim-config \
        --snapshot "${TXN_DIR}/owned-props.json" --desired-body-file "${PROPS_BODY_FILE}" >/dev/null; then
        record_event "props-ownership-snapshot" "failed" "The new automatic-lookup stanza contained missing, mismatched, or unexpected mutable fields."
        return 1
    fi
    record_event "props-ownership-snapshot" "passed" "Captured the complete transaction-created automatic-lookup stanza."
}

# Bind an automatic lookup in props.conf when requested. Failures return to the
# transaction coordinator so it can reconcile instead of exiting mid-apply.
apply_auto_lookup_props() {
    local sk="$1"
    [[ -n "${PROPS_BODY}" ]] || return 0
    if ! set_conf_body "${sk}" "nobody" "props" "${AUTO_LOOKUP_SOURCETYPE}" "${PROPS_BODY}"; then
        log "ERROR: Failed to bind LOOKUP-${NAME} on ${AUTO_LOOKUP_SOURCETYPE} (props.conf)."
        return 1
    fi
    log "Bound automatic lookup LOOKUP-${NAME} on source type ${AUTO_LOOKUP_SOURCETYPE} (props.conf)."
}

apply_acl() {
    local sk="$1" conf="$2" stanza="$3"
    if post_acl_body "${sk}" "${conf}" "${stanza}" "${ACL_BODY}"; then
        log "ACL set: sharing=${SHARING}, owner=${OWNER}."
        return 0
    fi
    log "ERROR: ACL update failed; starting read-only failure reconciliation."
    return 1
}

rollback_config_target() {
    local sk="$1" label="$2" endpoint="$3" before_code="$4" before_file="$5"
    local desired_file="$6" owned_file="${7:-}"
    local current_file current_code classification
    current_file="${TXN_DIR}/rollback-${label}-current.json"
    current_code="$(capture_endpoint "${sk}" "${endpoint}" "${current_file}")"
    if [[ "${before_code}" == "404" ]]; then
        if [[ "${current_code}" == "404" ]]; then
            record_event "rollback-${label}" "unchanged" "No transaction-created ${label} remains."
            return 0
        fi
        require_manual_cleanup "${label}" || true
        preserve_private_snapshot "${label}-before.raw" "${before_file}" || true
        preserve_private_snapshot "${label}-current.raw" "${current_file}" || true
        preserve_private_snapshot "${label}-post-write.raw" "${owned_file}" || true
        record_event "rollback-${label}" "refused" "The transaction-created ${label} was retained for reviewed recovery; automatic whole-stanza DELETE is disabled because state can change after read-back."
        return 1
    fi
    classification="$(python3 "${STATE_HELPER}" classify-config \
        --before-file "${before_file}" --before-code "${before_code}" \
        --current-file "${current_file}" --current-code "${current_code}" \
        --desired-body-file "${desired_file}" 2>/dev/null || printf '%s' conflict)"
    case "${classification}" in
        unchanged)
            record_event "rollback-${label}" "unchanged" "The ${label} still matches its pre-transaction state."
            return 0
            ;;
        restore|conflict)
            require_manual_cleanup "${label}" || true
            preserve_private_snapshot "${label}-before.raw" "${before_file}" || true
            preserve_private_snapshot "${label}-current.raw" "${current_file}" || true
            preserve_private_snapshot "${label}-post-write.raw" "${owned_file}" || true
            record_event "rollback-${label}" "refused" "The failed ${label} state was retained for reviewed recovery (${classification}). Automatic restore POST is disabled because state can change after read-back."
            return 1
            ;;
        *)
            require_manual_cleanup "${label}" || true
            preserve_private_snapshot "${label}-before.raw" "${before_file}" || true
            preserve_private_snapshot "${label}-current.raw" "${current_file}" || true
            preserve_private_snapshot "${label}-post-write.raw" "${owned_file}" || true
            record_event "rollback-${label}" "refused" "Unreadable or unrecognized ${label} state was retained; automatic restore POST is disabled."
            return 1
            ;;
    esac
}

rollback_new_object() {
    local sk="$1" conf="$2" stanza="$3"
    local current_object current_acl object_code acl_code="not-read"
    current_object="${TXN_DIR}/rollback-object-current.json"
    object_code="$(capture_endpoint "${sk}" "$(object_endpoint "${conf}" "${stanza}")" "${current_object}")"
    if [[ "${object_code}" == "404" ]]; then
        record_event "rollback-object" "unchanged" "No transaction-created object remains."
        return 0
    fi
    current_acl="${TXN_DIR}/rollback-object-current-acl.json"
    : > "${current_acl}"
    chmod 600 "${current_acl}"
    if [[ "${object_code}" == "200" ]]; then
        acl_code="$(capture_endpoint "${sk}" "$(object_endpoint "${conf}" "${stanza}")/acl" "${current_acl}")"
    fi
    require_manual_cleanup "knowledge object ${APP_NAME}/${stanza}" || true
    preserve_private_snapshot "object-before.raw" "${TXN_DIR}/before-object.json" || true
    preserve_private_snapshot "object-current.raw" "${current_object}" || true
    preserve_private_snapshot "object-post-write.raw" "${TXN_DIR}/owned-object.json" || true
    preserve_private_snapshot "acl-before.raw" "${TXN_DIR}/before-acl.json" || true
    preserve_private_snapshot "acl-current.raw" "${current_acl}" || true
    preserve_private_snapshot "acl-post-write.raw" "${TXN_DIR}/owned-acl.json" || true
    record_event "rollback-object" "refused" "The transaction-created object was retained for reviewed recovery; automatic DELETE is disabled because object or ACL state can change after read-back (object HTTP ${object_code}, ACL HTTP ${acl_code})."
    return 1
}

rollback_existing_acl() {
    local sk="$1" conf="$2" stanza="$3"
    local current_file current_code classification
    current_file="${TXN_DIR}/rollback-acl-current.json"
    current_code="$(capture_endpoint "${sk}" "$(object_endpoint "${conf}" "${stanza}")/acl" "${current_file}")"
    if [[ "${current_code}" != "200" ]]; then
        require_manual_cleanup "knowledge-object ACL" || true
        preserve_private_snapshot "acl-before.raw" "${TXN_DIR}/before-acl.json" || true
        preserve_private_snapshot "acl-current.raw" "${current_file}" || true
        record_event "rollback-acl" "refused" "Current ACL was not readable during failure reconciliation (HTTP ${current_code}); automatic restore POST is disabled."
        return 1
    fi
    classification="$(python3 "${STATE_HELPER}" classify-acl \
        --before-file "${TXN_DIR}/before-acl.json" --current-file "${current_file}" \
        --expected-plan "${OUTPUT_DIR}/knowledge-objects/acl-plan.json" 2>/dev/null || printf '%s' conflict)"
    case "${classification}" in
        unchanged)
            record_event "rollback-acl" "unchanged" "ACL already matched its pre-transaction state."
            return 0
            ;;
        restore|conflict)
            require_manual_cleanup "knowledge-object ACL" || true
            preserve_private_snapshot "acl-before.raw" "${TXN_DIR}/before-acl.json" || true
            preserve_private_snapshot "acl-current.raw" "${current_file}" || true
            record_event "rollback-acl" "refused" "The failed ACL state was retained for reviewed recovery (${classification}). Automatic restore POST is disabled because state can change after read-back."
            return 1
            ;;
        *)
            require_manual_cleanup "knowledge-object ACL" || true
            preserve_private_snapshot "acl-before.raw" "${TXN_DIR}/before-acl.json" || true
            preserve_private_snapshot "acl-current.raw" "${current_file}" || true
            record_event "rollback-acl" "refused" "Unreadable or unrecognized ACL state was retained; automatic restore POST is disabled."
            return 1
            ;;
    esac
}

preserve_recovery_context() {
    [[ "${MANUAL_CLEANUP_REQUIRED}" == "true" ]] || return 0
    preserve_private_snapshot "object-before.raw" "${TXN_DIR}/before-object.json" || true
    preserve_private_snapshot "object-current.raw" "${TXN_DIR}/rollback-object-current.json" || true
    preserve_private_snapshot "acl-before.raw" "${TXN_DIR}/before-acl.json" || true
    if [[ -f "${TXN_DIR}/rollback-acl-current.json" ]]; then
        preserve_private_snapshot "acl-current.raw" "${TXN_DIR}/rollback-acl-current.json" || true
    else
        preserve_private_snapshot "acl-current.raw" "${TXN_DIR}/rollback-object-current-acl.json" || true
    fi
    if [[ -n "${PROPS_BODY}" ]]; then
        preserve_private_snapshot "automatic-lookup-before.raw" "${TXN_DIR}/before-props.json" || true
        preserve_private_snapshot "automatic-lookup-current.raw" \
            "${TXN_DIR}/rollback-automatic-lookup-current.json" || true
    fi
}

rollback_transaction() {
    local sk="$1" conf="$2" stanza="$3" complete=true
    if [[ -n "${PROPS_BODY}" ]]; then
        local owned_props=""
        [[ -f "${TXN_DIR}/owned-props.json" ]] && owned_props="${TXN_DIR}/owned-props.json"
        rollback_config_target "${sk}" "automatic-lookup" "$(props_endpoint)" \
            "${PRE_PROPS_CODE}" "${TXN_DIR}/before-props.json" "${PROPS_BODY_FILE}" \
            "${owned_props}" || complete=false
    fi
    if [[ "${PRE_OBJECT_CODE}" == "404" ]]; then
        rollback_new_object "${sk}" "${conf}" "${stanza}" || complete=false
    else
        rollback_config_target "${sk}" "object" "$(object_endpoint "${conf}" "${stanza}")" \
            "${PRE_OBJECT_CODE}" \
            "${TXN_DIR}/before-object.json" "${DESIRED_BODY_FILE}" || complete=false
        rollback_existing_acl "${sk}" "${conf}" "${stanza}" || complete=false
    fi
    preserve_recovery_context
    if [[ "${complete}" == "true" ]]; then
        ROLLBACK_STATUS="complete"
        log "Failure reconciliation confirmed that no failed mutation remains."
        return 0
    fi
    ROLLBACK_STATUS="partial"
    log "ERROR: Failed state was retained for reviewed recovery; automatic restore/delete is disabled."
    return 1
}

transaction_failed() {
    local sk="$1" conf="$2" stanza="$3" failure_step="$4" detail="$5"
    record_event "${failure_step}" "failed" "${detail}"
    rollback_transaction "${sk}" "${conf}" "${stanza}" || true
    rm -f -- "${STATE_DIR}/live-status.json"
    write_transaction_evidence "failed" "${failure_step}" "${ROLLBACK_STATUS}" \
        "${STATE_DIR}/apply-evidence.json" || log "ERROR: Could not write transaction evidence."
    TRANSACTION_FINISHED=true
    log "ERROR: Knowledge-object apply failed at ${failure_step}. Evidence: ${STATE_DIR}/apply-evidence.json"
    return 1
}

prepare_transaction_forms() {
    build_body
    build_auto_lookup_body
    build_acl_body
    printf '%s' "${BODY}" > "${DESIRED_BODY_FILE}"
    printf '%s' "${PROPS_BODY}" > "${PROPS_BODY_FILE}"
    chmod 600 "${DESIRED_BODY_FILE}" "${PROPS_BODY_FILE}"
    return 0
}

run_live_preflight() {
    local conf stanza sk
    conf="$(conf_name)"
    stanza="$(stanza_name)"
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; return 1; }
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; return 1; }
    begin_transaction
    prepare_transaction_forms
    if ! capture_preflight_state "${sk}" "${conf}" "${stanza}"; then
        write_transaction_evidence "failed" "preflight" "not-required" \
            "${STATE_DIR}/preflight-evidence.json" || true
        log "ERROR: Live preflight failed before mutation. Evidence: ${STATE_DIR}/preflight-evidence.json"
        return 1
    fi
    record_event "preflight" "passed" "All live read-only preflight checks passed."
    write_transaction_evidence "succeeded" "" "not-required" "${STATE_DIR}/preflight-evidence.json"
    log "Live preflight passed. Evidence: ${STATE_DIR}/preflight-evidence.json"
}

run_live_status() {
    local conf stanza sk status_file
    conf="$(conf_name)"
    stanza="$(stanza_name)"
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; return 1; }
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; return 1; }
    begin_transaction
    prepare_transaction_forms
    if ! capture_preflight_state "${sk}" "${conf}" "${stanza}" true; then
        log "ERROR: Live status could not query the target endpoints."
        return 1
    fi
    status_file="${STATE_DIR}/live-status.json"
    if evaluate_live_state "${sk}" "${conf}" "${stanza}" "status" "${status_file}"; then
        log "Live knowledge-object content and ACLs match the rendered intent. Evidence: ${status_file}"
        return 0
    fi
    log "ERROR: Live knowledge-object content or ACLs do not match rendered intent. Evidence: ${status_file}"
    return 1
}

apply_live() {
    if [[ "${SHARING}" == "global" && "${ACCEPT_GLOBAL_SHARING}" != "true" ]]; then
        log "ERROR: sharing=global is broad. Re-run with --accept-global-sharing."
        return 1
    fi
    local conf stanza sk post_status
    conf="$(conf_name)"
    stanza="$(stanza_name)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would preflight, write conf-${conf}/[${stanza}], set ACL sharing=${SHARING} owner=${OWNER}, and verify; failures retain state for reviewed recovery."
        if [[ "${OBJECT_KIND}" == "lookup" && -n "${AUTO_LOOKUP_SOURCETYPE}" ]]; then
            log "DRY RUN: would include LOOKUP-${NAME} on source type ${AUTO_LOOKUP_SOURCETYPE} in the same verified apply."
        fi
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; return 1; }
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; return 1; }
    begin_transaction
    prepare_transaction_forms
    rm -f -- "${STATE_DIR}/live-status.json"
    if ! capture_preflight_state "${sk}" "${conf}" "${stanza}"; then
        write_transaction_evidence "failed" "preflight" "not-required" \
            "${STATE_DIR}/apply-evidence.json" || true
        log "ERROR: Apply was refused before mutation. Evidence: ${STATE_DIR}/apply-evidence.json"
        return 1
    fi
    record_event "preflight" "passed" "All live read-only preflight checks passed."

    TRANSACTION_SK="${sk}"
    TRANSACTION_CONF="${conf}"
    TRANSACTION_STANZA="${stanza}"
    TRANSACTION_MUTATED=true

    if ! set_conf_body "${sk}" "$(namespace_owner)" "${conf}" "${stanza}" "${BODY}"; then
        transaction_failed "${sk}" "${conf}" "${stanza}" "content-write" \
            "Splunk rejected the object content write." || true
        return 1
    fi
    record_event "content-write" "passed" "Knowledge-object content write returned success."
    log "Wrote ${OBJECT_KIND} '${stanza}' to app ${APP_NAME}."
    if [[ "${PRE_OBJECT_CODE}" == "404" ]] && ! claim_new_object_state "${sk}" "${conf}" "${stanza}"; then
        transaction_failed "${sk}" "${conf}" "${stanza}" "object-ownership-snapshot" \
            "The complete post-write object/ACL state could not be attributed to this transaction." || true
        return 1
    fi

    if ! apply_acl "${sk}" "${conf}" "${stanza}"; then
        transaction_failed "${sk}" "${conf}" "${stanza}" "acl-write" \
            "Splunk rejected the requested owner/sharing ACL." || true
        return 1
    fi
    record_event "acl-write" "passed" "Requested owner and sharing ACL returned success."

    if ! apply_auto_lookup_props "${sk}"; then
        transaction_failed "${sk}" "${conf}" "${stanza}" "automatic-lookup-write" \
            "Splunk rejected the optional automatic-lookup binding." || true
        return 1
    fi
    [[ -z "${PROPS_BODY}" ]] || record_event "automatic-lookup-write" "passed" "Automatic-lookup binding returned success."
    if [[ -n "${PROPS_BODY}" && "${PRE_PROPS_CODE}" == "404" ]] && ! claim_new_props_state "${sk}"; then
        transaction_failed "${sk}" "${conf}" "${stanza}" "props-ownership-snapshot" \
            "The complete post-write automatic-lookup state could not be attributed to this transaction." || true
        return 1
    fi

    post_status="${TXN_DIR}/post-apply-status.json"
    if ! evaluate_live_state "${sk}" "${conf}" "${stanza}" "post-apply" "${post_status}"; then
        transaction_failed "${sk}" "${conf}" "${stanza}" "post-apply-verification" \
            "A live read-back did not match the requested content and ACL." || true
        return 1
    fi
    record_event "post-apply-verification" "passed" "Live content, ACL, and optional automatic lookup match the request."
    write_transaction_evidence "succeeded" "" "not-required" "${STATE_DIR}/apply-evidence.json"
    python3 "${STATE_HELPER}" publish --source "${post_status}" --output "${STATE_DIR}/live-status.json"
    TRANSACTION_FINISHED=true
    log "Transactional apply verified. Evidence: ${STATE_DIR}/apply-evidence.json"
    log "$(log_platform_restart_guidance "knowledge object changes")"
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
        preflight) render_assets; run_live_preflight ;;
        apply) render_assets; apply_live ;;
        status) render_assets; run_live_status ;;
        all) render_assets; apply_live ;;
    esac
}

main "$@"

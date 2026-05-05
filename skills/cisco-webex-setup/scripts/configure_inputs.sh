#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="ta_cisco_webex_add_on_for_splunk"

ACCOUNT=""
INPUT_TYPE=""
INPUT_NAME=""
INDEX=""
INTERVAL="3600"
START_TIME=""
END_TIME=""
SITE_URL=""
ACCOUNT_REGION=""
LOCATIONS=""
WEBEX_ENDPOINT=""
WEBEX_BASE_URL="webexapis.com"
METHOD="GET"
QUERY_PARAMS=""
REQUEST_BODY=""
ORG_ID=""
CONTACT_CENTER_REGION=""
QUERY_TEMPLATE="AAR"
SK=""

usage() {
    cat >&2 <<EOF
Configure Webex Add-on inputs.

Usage: $(basename "$0") --account NAME --input-type TYPE [OPTIONS]

Input types:
  core, meetings, meetings_summary_report, admin_audit_events,
  security_audit_events, meeting_qualities, detailed_call_history,
  generic_endpoint, contact_center_search

Options:
  --name NAME
  --index INDEX
  --interval SECONDS_OR_CRON
  --start-time UTC                 Format: YYYY-MM-DDTHH:MM:SSZ
  --end-time UTC                   Format: YYYY-MM-DDTHH:MM:SSZ
  --site-url URL                   Required for meeting summary in some orgs
  --account-region REGION          Detailed call history region
  --locations CSV                  Detailed call history locations
  --webex-endpoint PATH            Generic endpoint path without leading slash
  --webex-base-url HOST            Generic endpoint base API URL (default: webexapis.com)
  --method METHOD                  Generic endpoint HTTP method (default: GET)
  --query-params STRING            Generic endpoint query params
  --request-body JSON              Generic endpoint request body
  --org-id ID                      Webex Contact Center org ID
  --webex-contact-center-region R  Webex Contact Center region
  --query-template AAR|ASR|CAR|CSR Contact Center template (default: AAR)
  --help
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --account) require_arg "$1" $# || exit 1; ACCOUNT="$2"; shift 2 ;;
        --input-type) require_arg "$1" $# || exit 1; INPUT_TYPE="$2"; shift 2 ;;
        --name) require_arg "$1" $# || exit 1; INPUT_NAME="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --interval) require_arg "$1" $# || exit 1; INTERVAL="$2"; shift 2 ;;
        --start-time) require_arg "$1" $# || exit 1; START_TIME="$2"; shift 2 ;;
        --end-time) require_arg "$1" $# || exit 1; END_TIME="$2"; shift 2 ;;
        --site-url) require_arg "$1" $# || exit 1; SITE_URL="$2"; shift 2 ;;
        --account-region) require_arg "$1" $# || exit 1; ACCOUNT_REGION="$2"; shift 2 ;;
        --locations) require_arg "$1" $# || exit 1; LOCATIONS="$2"; shift 2 ;;
        --webex-endpoint) require_arg "$1" $# || exit 1; WEBEX_ENDPOINT="$2"; shift 2 ;;
        --webex-base-url) require_arg "$1" $# || exit 1; WEBEX_BASE_URL="$2"; shift 2 ;;
        --method) require_arg "$1" $# || exit 1; METHOD="$2"; shift 2 ;;
        --query-params) require_arg "$1" $# || exit 1; QUERY_PARAMS="$2"; shift 2 ;;
        --request-body) require_arg "$1" $# || exit 1; REQUEST_BODY="$2"; shift 2 ;;
        --org-id) require_arg "$1" $# || exit 1; ORG_ID="$2"; shift 2 ;;
        --webex-contact-center-region) require_arg "$1" $# || exit 1; CONTACT_CENTER_REGION="$2"; shift 2 ;;
        --query-template) require_arg "$1" $# || exit 1; QUERY_TEMPLATE="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "${ACCOUNT}" || -z "${INPUT_TYPE}" ]]; then
    log "ERROR: --account and --input-type are required."
    exit 1
fi

validate_timestamp() {
    local value="$1" label="$2"
    [[ -z "${value}" ]] && return 0
    if [[ ! "${value}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; then
        log "ERROR: ${label} must use YYYY-MM-DDTHH:MM:SSZ."
        exit 1
    fi
}

validate_timestamp "${START_TIME}" "--start-time"
validate_timestamp "${END_TIME}" "--end-time"

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

default_index_for_type() {
    case "$1" in
        detailed_call_history) printf '%s' "wxc" ;;
        contact_center_search) printf '%s' "wxcc" ;;
        *) printf '%s' "wx" ;;
    esac
}

default_name_for_type() {
    case "$1" in
        meetings) printf '%s' "${ACCOUNT}_meetings" ;;
        meetings_summary_report) printf '%s' "${ACCOUNT}_meeting_summary_report" ;;
        admin_audit_events) printf '%s' "${ACCOUNT}_admin_audit_events" ;;
        security_audit_events) printf '%s' "${ACCOUNT}_security_audit_events" ;;
        meeting_qualities) printf '%s' "${ACCOUNT}_meeting_qualities" ;;
        detailed_call_history) printf '%s' "${ACCOUNT}_detailed_call_history" ;;
        generic_endpoint) printf '%s' "${ACCOUNT}_generic_endpoint" ;;
        contact_center_search) printf '%s' "${ACCOUNT}_contact_center_${QUERY_TEMPLATE}" ;;
        *) printf '%s' "${ACCOUNT}_${1}" ;;
    esac
}

create_one() {
    local kind="$1" name="$2" index="$3" body
    case "${kind}" in
        meetings_summary_report|admin_audit_events|security_audit_events|meeting_qualities|detailed_call_history|contact_center_search)
            [[ -n "${START_TIME}" ]] || { log "ERROR: ${kind} requires --start-time."; exit 1; }
            ;;
    esac
    body=$(form_urlencode_pairs \
        global_account "${ACCOUNT}" \
        index "${index}" \
        interval "${INTERVAL}" \
        disabled "0") || exit 1
    [[ -n "${START_TIME}" ]] && body="${body}&$(form_urlencode_pairs start_time "${START_TIME}")"
    [[ -n "${END_TIME}" ]] && body="${body}&$(form_urlencode_pairs end_time "${END_TIME}")"

    case "${kind}" in
        meetings_summary_report)
            [[ -n "${SITE_URL}" ]] || { log "ERROR: meetings_summary_report requires --site-url."; exit 1; }
            body="${body}&$(form_urlencode_pairs site_url "${SITE_URL}")"
            ;;
        detailed_call_history)
            [[ -n "${ACCOUNT_REGION}" ]] && body="${body}&$(form_urlencode_pairs account_region "${ACCOUNT_REGION}")"
            if [[ -n "${LOCATIONS}" ]]; then
                log "WARNING: The package validator for detailed-call-history locations is narrow; verify this value if creation fails."
                body="${body}&$(form_urlencode_pairs locations "${LOCATIONS}")"
            fi
            ;;
        generic_endpoint)
            [[ -n "${WEBEX_ENDPOINT}" ]] || { log "ERROR: generic_endpoint requires --webex-endpoint."; exit 1; }
            [[ "${WEBEX_ENDPOINT}" != /* ]] || { log "ERROR: --webex-endpoint must not start with '/'."; exit 1; }
            body="${body}&$(form_urlencode_pairs webex_endpoint "${WEBEX_ENDPOINT}" webex_base_url "${WEBEX_BASE_URL}" method "${METHOD}")"
            [[ -n "${QUERY_PARAMS}" ]] && body="${body}&$(form_urlencode_pairs query_params "${QUERY_PARAMS}")"
            [[ -n "${REQUEST_BODY}" ]] && body="${body}&$(form_urlencode_pairs request_body "${REQUEST_BODY}")"
            ;;
        contact_center_search)
            [[ -n "${ORG_ID}" && -n "${CONTACT_CENTER_REGION}" ]] || {
                log "ERROR: contact_center_search requires --org-id and --webex-contact-center-region."
                exit 1
            }
            case "${QUERY_TEMPLATE}" in
                AAR|ASR|CAR|CSR) ;;
                *) log "ERROR: --query-template must be AAR, ASR, CAR, or CSR."; exit 1 ;;
            esac
            body="${body}&$(form_urlencode_pairs org_id "${ORG_ID}" webex_contact_center_region "${CONTACT_CENTER_REGION}" query_template "${QUERY_TEMPLATE}")"
            ;;
    esac

    if rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "webex_${kind}" "${name}" "${body}"; then
        log "Configured webex_${kind}://${name} -> index=${index}"
    else
        log "ERROR: Failed to configure webex_${kind}://${name}."
        exit 1
    fi
}

create_requested() {
    local type="$1" name index
    name="${INPUT_NAME:-$(default_name_for_type "${type}")}"
    index="${INDEX:-$(default_index_for_type "${type}")}"
    create_one "${type}" "${name}" "${index}"
}

case "${INPUT_TYPE}" in
    core)
        for item in meetings admin_audit_events security_audit_events meeting_qualities meetings_summary_report detailed_call_history; do
            INPUT_NAME=""
            create_requested "${item}"
        done
        ;;
    meetings|meetings_summary_report|admin_audit_events|security_audit_events|meeting_qualities|detailed_call_history|generic_endpoint|contact_center_search)
        create_requested "${INPUT_TYPE}"
        ;;
    *)
        log "ERROR: Unsupported --input-type '${INPUT_TYPE}'."
        exit 1
        ;;
esac

log "Webex input configuration complete."

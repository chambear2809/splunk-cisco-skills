#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="ta_cisco_webex_add_on_for_splunk"

ACCT_NAME=""
ENDPOINT="webexapis.com"
IS_GOV_ACCOUNT=""
GOV_API_REFERENCE_LINK=""
CLIENT_ID=""
CLIENT_SECRET=""
REDIRECT_URL=""
SCOPE=""
ACCESS_TOKEN=""
REFRESH_TOKEN=""
INSTANCE_URL=""
LOGLEVEL=""
PROXY_ENABLED=""
PROXY_TYPE=""
PROXY_URL=""
PROXY_PORT=""
PROXY_USERNAME=""
PROXY_PASSWORD=""
PROXY_RDNS=""
CREATE_DEFAULTS=false
START_TIME=""
SITE_URL=""
SK=""

usage() {
    cat >&2 <<EOF
Configure a Webex OAuth account for the Webex Add-on for Splunk.

Usage: $(basename "$0") [OPTIONS]

Required:
  --name NAME
  --client-id ID
  --client-secret-file FILE
  --scope SCOPES

Optional:
  --endpoint HOST                     Default: webexapis.com
  --redirect-url URL
  --is-gov-account true|false
  --gov-api-reference-link URL
  --instance-url URL
  --access-token-file FILE
  --refresh-token-file FILE
  --loglevel LEVEL                    DEBUG, INFO, WARN, ERROR
  --proxy-enabled true|false
  --proxy-type http|socks4|socks5
  --proxy-url HOST
  --proxy-port PORT
  --proxy-username USER
  --proxy-password-file FILE
  --proxy-rdns true|false
  --create-defaults                  Create the core input set after account creation
  --start-time UTC                   Start time for default inputs
  --site-url URL                     Site URL for default meeting summary report input
  --help
EOF
    exit "${1:-0}"
}

truthy() {
    case "${1,,}" in
        1|true|yes|y|on) return 0 ;;
        *) return 1 ;;
    esac
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) require_arg "$1" $# || exit 1; ACCT_NAME="$2"; shift 2 ;;
        --endpoint) require_arg "$1" $# || exit 1; ENDPOINT="$2"; shift 2 ;;
        --is-gov-account) require_arg "$1" $# || exit 1; IS_GOV_ACCOUNT="$2"; shift 2 ;;
        --gov-api-reference-link) require_arg "$1" $# || exit 1; GOV_API_REFERENCE_LINK="$2"; shift 2 ;;
        --client-id) require_arg "$1" $# || exit 1; CLIENT_ID="$2"; shift 2 ;;
        --client-secret|--client-secret=*) reject_secret_arg "${1%%=*}" "--client-secret-file" || exit 1 ;;
        --client-secret-file) require_arg "$1" $# || exit 1; CLIENT_SECRET="$(read_secret_file "$2")"; shift 2 ;;
        --redirect-url) require_arg "$1" $# || exit 1; REDIRECT_URL="$2"; shift 2 ;;
        --scope) require_arg "$1" $# || exit 1; SCOPE="$2"; shift 2 ;;
        --access-token|--access-token=*) reject_secret_arg "${1%%=*}" "--access-token-file" || exit 1 ;;
        --access-token-file) require_arg "$1" $# || exit 1; ACCESS_TOKEN="$(read_secret_file "$2")"; shift 2 ;;
        --refresh-token|--refresh-token=*) reject_secret_arg "${1%%=*}" "--refresh-token-file" || exit 1 ;;
        --refresh-token-file) require_arg "$1" $# || exit 1; REFRESH_TOKEN="$(read_secret_file "$2")"; shift 2 ;;
        --instance-url) require_arg "$1" $# || exit 1; INSTANCE_URL="$2"; shift 2 ;;
        --loglevel) require_arg "$1" $# || exit 1; LOGLEVEL="$2"; shift 2 ;;
        --proxy-enabled) require_arg "$1" $# || exit 1; PROXY_ENABLED="$2"; shift 2 ;;
        --proxy-type) require_arg "$1" $# || exit 1; PROXY_TYPE="$2"; shift 2 ;;
        --proxy-url) require_arg "$1" $# || exit 1; PROXY_URL="$2"; shift 2 ;;
        --proxy-port) require_arg "$1" $# || exit 1; PROXY_PORT="$2"; shift 2 ;;
        --proxy-username) require_arg "$1" $# || exit 1; PROXY_USERNAME="$2"; shift 2 ;;
        --proxy-password|--proxy-password=*) reject_secret_arg "${1%%=*}" "--proxy-password-file" || exit 1 ;;
        --proxy-password-file) require_arg "$1" $# || exit 1; PROXY_PASSWORD="$(read_secret_file "$2")"; shift 2 ;;
        --proxy-rdns) require_arg "$1" $# || exit 1; PROXY_RDNS="$2"; shift 2 ;;
        --create-defaults) CREATE_DEFAULTS=true; shift ;;
        --start-time) require_arg "$1" $# || exit 1; START_TIME="$2"; shift 2 ;;
        --site-url) require_arg "$1" $# || exit 1; SITE_URL="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "${ACCT_NAME}" || -z "${CLIENT_ID}" || -z "${CLIENT_SECRET}" || -z "${SCOPE}" ]]; then
    log "ERROR: --name, --client-id, --client-secret-file, and --scope are required."
    exit 1
fi
if [[ -n "${LOGLEVEL}" ]]; then
    case "${LOGLEVEL}" in
        DEBUG|INFO|WARN|ERROR) ;;
        *) log "ERROR: --loglevel must be DEBUG, INFO, WARN, or ERROR."; exit 1 ;;
    esac
fi
if [[ -n "${PROXY_TYPE}" ]]; then
    case "${PROXY_TYPE}" in
        http|socks4|socks5) ;;
        *) log "ERROR: --proxy-type must be http, socks4, or socks5."; exit 1 ;;
    esac
fi
if [[ -n "${PROXY_ENABLED}" ]] && truthy "${PROXY_ENABLED}"; then
    [[ -n "${PROXY_URL}" && -n "${PROXY_PORT}" ]] || {
        log "ERROR: --proxy-url and --proxy-port are required when --proxy-enabled is true."
        exit 1
    }
fi
if [[ "${CREATE_DEFAULTS}" == "true" && ( -z "${START_TIME}" || -z "${SITE_URL}" ) ]]; then
    log "ERROR: --create-defaults requires --start-time and --site-url for package-required Webex inputs."
    exit 1
fi

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
    log "ERROR: ${APP_NAME} is not installed."
    exit 1
fi

fields=(
    endpoint "${ENDPOINT}"
    client_id "${CLIENT_ID}"
    client_secret "${CLIENT_SECRET}"
    scope "${SCOPE}"
)
[[ -n "${IS_GOV_ACCOUNT}" ]] && fields+=(is_gov_account "${IS_GOV_ACCOUNT}")
[[ -n "${GOV_API_REFERENCE_LINK}" ]] && fields+=(gov_api_reference_link "${GOV_API_REFERENCE_LINK}")
[[ -n "${REDIRECT_URL}" ]] && fields+=(redirect_url "${REDIRECT_URL}")
[[ -n "${ACCESS_TOKEN}" ]] && fields+=(access_token "${ACCESS_TOKEN}")
[[ -n "${REFRESH_TOKEN}" ]] && fields+=(refresh_token "${REFRESH_TOKEN}")
[[ -n "${INSTANCE_URL}" ]] && fields+=(instance_url "${INSTANCE_URL}")

create_body=$(form_urlencode_pairs name "${ACCT_NAME}" "${fields[@]}") || exit 1
update_body=$(form_urlencode_pairs "${fields[@]}") || exit 1
endpoint_url="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/ta_cisco_webex_add_on_for_splunk_account"
http_code=$(rest_create_or_update_account "${SK}" "${endpoint_url}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
log "Configured Webex account '${ACCT_NAME}' (HTTP ${http_code})."

if [[ -n "${LOGLEVEL}" ]]; then
    body=$(form_urlencode_pairs loglevel "${LOGLEVEL}") || exit 1
    rest_set_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "ta_cisco_webex_add_on_for_splunk_settings" "logging" "${body}" \
        || { log "ERROR: Failed to configure Webex logging settings."; exit 1; }
    log "Updated Webex logging level."
fi

if [[ -n "${PROXY_ENABLED}${PROXY_TYPE}${PROXY_URL}${PROXY_PORT}${PROXY_USERNAME}${PROXY_PASSWORD}${PROXY_RDNS}" ]]; then
    settings=()
    [[ -n "${PROXY_ENABLED}" ]] && settings+=(proxy_enabled "${PROXY_ENABLED}")
    [[ -n "${PROXY_TYPE}" ]] && settings+=(proxy_type "${PROXY_TYPE}")
    [[ -n "${PROXY_URL}" ]] && settings+=(proxy_url "${PROXY_URL}")
    [[ -n "${PROXY_PORT}" ]] && settings+=(proxy_port "${PROXY_PORT}")
    [[ -n "${PROXY_USERNAME}" ]] && settings+=(proxy_username "${PROXY_USERNAME}")
    [[ -n "${PROXY_PASSWORD}" ]] && settings+=(proxy_password "${PROXY_PASSWORD}")
    [[ -n "${PROXY_RDNS}" ]] && settings+=(proxy_rdns "${PROXY_RDNS}")
    body=$(form_urlencode_pairs "${settings[@]}") || exit 1
    rest_set_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "ta_cisco_webex_add_on_for_splunk_settings" "proxy" "${body}" \
        || { log "ERROR: Failed to configure Webex proxy settings."; exit 1; }
    log "Updated Webex proxy settings."
fi

if [[ "${CREATE_DEFAULTS}" == "true" ]]; then
    cmd=(bash "${SCRIPT_DIR}/configure_inputs.sh" --account "${ACCT_NAME}" --input-type core)
    [[ -n "${START_TIME}" ]] && cmd+=(--start-time "${START_TIME}")
    [[ -n "${SITE_URL}" ]] && cmd+=(--site-url "${SITE_URL}")
    "${cmd[@]}"
fi

log "Webex account configuration complete."

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_cisco-ucs"
NAME=""
SERVER_URL=""
ACCOUNT_NAME=""
PASSWORD=""
DESCRIPTION=""
DISABLE_SSL_VERIFICATION="false"
CREATE_DEFAULT_TASK=false
INDEX="cisco_ucs"

usage() {
    cat >&2 <<EOF
Configure a Cisco UCS Manager server record.

Usage: $(basename "$0") [OPTIONS]

Required:
  --name NAME
  --server-url HOST
  --account-name USER
  --password-file FILE

Optional:
  --description TEXT
  --disable-ssl-verification
  --create-default-task
  --index INDEX
  --help
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) require_arg "$1" $# || exit 1; NAME="$2"; shift 2 ;;
        --server-url) require_arg "$1" $# || exit 1; SERVER_URL="$2"; shift 2 ;;
        --account-name) require_arg "$1" $# || exit 1; ACCOUNT_NAME="$2"; shift 2 ;;
        --password|--password=*) reject_secret_arg "${1%%=*}" "--password-file" || exit 1 ;;
        --password-file) require_arg "$1" $# || exit 1; PASSWORD="$(read_secret_file "$2")"; shift 2 ;;
        --description) require_arg "$1" $# || exit 1; DESCRIPTION="$2"; shift 2 ;;
        --disable-ssl-verification) DISABLE_SSL_VERIFICATION="true"; shift ;;
        --create-default-task) CREATE_DEFAULT_TASK=true; shift ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "${NAME}" || -z "${SERVER_URL}" || -z "${ACCOUNT_NAME}" || -z "${PASSWORD}" ]]; then
    log "ERROR: --name, --server-url, --account-name, and --password-file are required."
    exit 1
fi

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
    log "ERROR: ${APP_NAME} is not installed."
    exit 1
fi

create_body=$(form_urlencode_pairs \
    name "${NAME}" \
    server_url "${SERVER_URL}" \
    account_name "${ACCOUNT_NAME}" \
    account_password "${PASSWORD}" \
    description "${DESCRIPTION}" \
    disable_ssl_verification "${DISABLE_SSL_VERIFICATION}") || exit 1
update_body=$(form_urlencode_pairs \
    server_url "${SERVER_URL}" \
    account_name "${ACCOUNT_NAME}" \
    account_password "${PASSWORD}" \
    description "${DESCRIPTION}" \
    disable_ssl_verification "${DISABLE_SSL_VERIFICATION}") || exit 1

endpoint_url="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/splunk_ta_cisco_ucs_servers"
http_code=$(rest_create_or_update_account "${SK}" "${endpoint_url}" "${NAME}" "${create_body}" "${update_body}") || exit 1
log "Configured UCS Manager '${NAME}' (HTTP ${http_code})."

if [[ "${CREATE_DEFAULT_TASK}" == "true" ]]; then
    bash "${SCRIPT_DIR}/configure_task.sh" \
        --name "${NAME}_all" \
        --servers "${NAME}" \
        --templates "UCS_Fault,UCS_Inventory,UCS_Performance" \
        --index "${INDEX}"
fi

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_Cisco_Intersight"
SETUP_SCRIPT="${SCRIPT_DIR}/setup.sh"

ACCT_NAME=""
HOSTNAME="intersight.com"
CLIENT_ID=""
CLIENT_SECRET=""
CREATE_DEFAULTS="false"
SET_VERIFY_SSL=""

usage() {
    cat <<EOF
Configure a Cisco Intersight account via Splunk REST API.

Usage: $(basename "$0") [OPTIONS]

Required:
  --name NAME                Account name (stanza identifier)
  --client-id ID             Intersight OAuth2 Client ID
  --client-secret-file FILE  Read client secret from FILE

Optional:
  --hostname HOST            Intersight hostname (default: intersight.com)
  --create-defaults          Enable the default input set after account creation
  --no-verify-ssl            Disable TLS verification on the Intersight
                             connection (sets ssl_validation=false in
                             Splunk_TA_Cisco_Intersight_settings [verify_ssl]).
                             Use this for on-prem Intersight Virtual Appliance
                             deployments with self-signed certificates.
  --verify-ssl               Re-enable TLS verification on the connection.

Splunk credentials are read from the project-root credentials file (falls back to ~/.splunk/credentials) automatically.
Set SPLUNK_URI for remote Splunk (default: https://localhost:8089).
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) require_arg "$1" $# || exit 1; ACCT_NAME="$2"; shift 2 ;;
        --hostname) require_arg "$1" $# || exit 1; HOSTNAME="$2"; shift 2 ;;
        --client-id) require_arg "$1" $# || exit 1; CLIENT_ID="$2"; shift 2 ;;
        --client-secret) require_arg "$1" $# || exit 1; reject_secret_arg "$1" "--client-secret-file" || exit 1 ;;
        --client-secret-file) require_arg "$1" $# || exit 1; CLIENT_SECRET=$(read_secret_file "$2"); shift 2 ;;
        --create-defaults) CREATE_DEFAULTS="true"; shift ;;
        --no-verify-ssl) SET_VERIFY_SSL="false"; shift ;;
        --verify-ssl) SET_VERIFY_SSL="true"; shift ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "${ACCT_NAME}" || -z "${CLIENT_ID}" || -z "${CLIENT_SECRET}" ]]; then
    log "ERROR: --name, --client-id, and --client-secret-file are required"
    exit 1
fi

load_splunk_credentials

SK=$(get_session_key "${SPLUNK_URI}")

log "Authenticated to Splunk REST API."

if [[ -n "${SET_VERIFY_SSL}" ]]; then
    # The Intersight TA stores its TLS-validation flag in
    # Splunk_TA_Cisco_Intersight_settings.conf under stanza [verify_ssl] with
    # key `ssl_validation` (per the published vendor reference). Lowercase
    # true/false matches the documented vendor default.
    if rest_set_verify_ssl "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "Splunk_TA_Cisco_Intersight_settings" "verify_ssl" "${SET_VERIFY_SSL}" "ssl_validation"; then
        log "Set ssl_validation=${SET_VERIFY_SSL} in Splunk_TA_Cisco_Intersight_settings.conf [verify_ssl]."
    else
        log "ERROR: Failed to set ssl_validation in Splunk_TA_Cisco_Intersight_settings.conf."
        exit 1
    fi
fi

local_endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/Splunk_TA_Cisco_Intersight_account"
log "Creating Intersight account '${ACCT_NAME}' (hostname: ${HOSTNAME})..."

create_body=$(form_urlencode_pairs \
    name "${ACCT_NAME}" \
    intersight_hostname "${HOSTNAME}" \
    client_id "${CLIENT_ID}" \
    client_secret "${CLIENT_SECRET}") || exit 1
update_body=$(form_urlencode_pairs \
    intersight_hostname "${HOSTNAME}" \
    client_id "${CLIENT_ID}" \
    client_secret "${CLIENT_SECRET}") || exit 1

http_code=$(rest_create_or_update_account "${SK}" "${local_endpoint}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
log "  SUCCESS: Intersight account '${ACCT_NAME}' configured (HTTP ${http_code})"

if [[ "${CREATE_DEFAULTS}" == "true" ]]; then
    log "Enabling default Intersight inputs for account '${ACCT_NAME}'..."
    bash "${SETUP_SCRIPT}" --enable-inputs --account "${ACCT_NAME}" --index "intersight" --input-type all
fi

log "Account configuration complete."

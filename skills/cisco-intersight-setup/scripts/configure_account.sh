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

usage() {
    cat <<EOF
Configure a Cisco Intersight account via Splunk REST API.

Usage: $(basename "$0") [OPTIONS]

Required:
  --name NAME                Account name (stanza identifier)
  --client-id ID             Intersight OAuth2 Client ID
  --client-secret SECRET     Intersight OAuth2 Client Secret
  --client-secret-file FILE  Read client secret from FILE

Optional:
  --hostname HOST            Intersight hostname (default: intersight.com)
  --create-defaults          Enable the default input set after account creation

Splunk credentials are read from the project-root credentials file (falls back to ~/.splunk/credentials) automatically.
Set SPLUNK_URI for remote Splunk (default: https://localhost:8089).
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) ACCT_NAME="$2"; shift 2 ;;
        --hostname) HOSTNAME="$2"; shift 2 ;;
        --client-id) CLIENT_ID="$2"; shift 2 ;;
        --client-secret) CLIENT_SECRET="$2"; shift 2 ;;
        --client-secret-file) CLIENT_SECRET=$(read_secret_file "$2"); shift 2 ;;
        --create-defaults) CREATE_DEFAULTS="true"; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if [[ -z "${ACCT_NAME}" || -z "${CLIENT_ID}" || -z "${CLIENT_SECRET}" ]]; then
    log "ERROR: --name, --client-id, and --client-secret (or --client-secret-file) are required"
    exit 1
fi

load_splunk_credentials

SK=$(get_session_key "${SPLUNK_URI}")

log "Authenticated to Splunk REST API."

local_endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/Splunk_TA_Cisco_Intersight_account"
log "Creating Intersight account '${ACCT_NAME}' (hostname: ${HOSTNAME})..."

body=""
update_body=""
http_code=""
body=$(form_urlencode_pairs \
    name "${ACCT_NAME}" \
    intersight_hostname "${HOSTNAME}" \
    client_id "${CLIENT_ID}" \
    client_secret "${CLIENT_SECRET}") || exit 1
resp=$(splunk_curl_post "${SK}" \
    "${body}" \
    "${local_endpoint}" -w '\n%{http_code}' 2>/dev/null)
http_code=$(echo "${resp}" | tail -1)
resp_body=$(printf '%s\n' "${resp}" | sed '$d')

if [[ "${http_code}" == "201" || "${http_code}" == "200" ]]; then
    log "  SUCCESS: Account '${ACCT_NAME}' created (HTTP ${http_code})"
elif [[ "${http_code}" == "409" ]] || { [[ "${http_code}" == "400" ]] && echo "${resp_body}" | grep -q 'Conflict'; }; then
    log "  Account already exists. Updating..."
    update_body=$(form_urlencode_pairs \
        intersight_hostname "${HOSTNAME}" \
        client_id "${CLIENT_ID}" \
        client_secret "${CLIENT_SECRET}") || exit 1
    resp=$(splunk_curl_post "${SK}" \
        "${update_body}" \
        "${local_endpoint}/${ACCT_NAME}" -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    if [[ "${http_code}" == "200" ]]; then
        log "  SUCCESS: Account '${ACCT_NAME}' updated (HTTP ${http_code})"
    else
        log "  ERROR: Update returned HTTP ${http_code}"
        sanitize_response "${resp}"
        exit 1
    fi
else
    log "  ERROR: HTTP ${http_code}"
    sanitize_response "${resp}"
    exit 1
fi

if [[ "${CREATE_DEFAULTS}" == "true" ]]; then
    log "Enabling default Intersight inputs for account '${ACCT_NAME}'..."
    bash "${SETUP_SCRIPT}" --enable-inputs --account "${ACCT_NAME}" --index "intersight" --input-type all
fi

log "Account configuration complete."

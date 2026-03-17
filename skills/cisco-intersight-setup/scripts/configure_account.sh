#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_Cisco_Intersight"

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
  --create-defaults          Create default inputs during account creation

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

create_default_val="0"
if [[ "${CREATE_DEFAULTS}" == "true" ]]; then
    create_default_val="1"
fi

http_code=""
resp=$(splunk_curl_post "${SK}" \
    "name=${ACCT_NAME}&intersight_hostname=${HOSTNAME}&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&create_default_inputs=${create_default_val}" \
    "${local_endpoint}" -w '\n%{http_code}' 2>/dev/null)
http_code=$(echo "${resp}" | tail -1)

if [[ "${http_code}" == "201" || "${http_code}" == "200" ]]; then
    log "  SUCCESS: Account '${ACCT_NAME}' created (HTTP ${http_code})"
elif [[ "${http_code}" == "409" ]]; then
    log "  Account already exists. Updating..."
    resp=$(splunk_curl_post "${SK}" \
        "intersight_hostname=${HOSTNAME}&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&create_default_inputs=${create_default_val}" \
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

log "Account configuration complete."

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_Talos_Intelligence"
ACCOUNT_NAME="Talos_Intelligence_Service"
SERVICE_ACCOUNT=""

usage() {
    cat >&2 <<EOF
Advanced diagnostic helper: configure Talos service account material.

Usage: $(basename "$0") --service-account-file FILE [--name NAME]

Normally Splunk Cloud provisions this certificate/private-key material. Use this
only when explicitly diagnosing a missing service account, and keep the PEM in a
local secret file.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) require_arg "$1" $# || exit 1; ACCOUNT_NAME="$2"; shift 2 ;;
        --service-account|--service-account=*) reject_secret_arg "${1%%=*}" "--service-account-file" || exit 1 ;;
        --service-account-file) require_arg "$1" $# || exit 1; SERVICE_ACCOUNT="$(read_secret_file "$2")"; shift 2 ;;
        --help|-h) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

[[ -n "${SERVICE_ACCOUNT}" ]] || { log "ERROR: --service-account-file is required."; exit 1; }

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

create_body=$(form_urlencode_pairs name "${ACCOUNT_NAME}" service_account "${SERVICE_ACCOUNT}") || exit 1
update_body=$(form_urlencode_pairs service_account "${SERVICE_ACCOUNT}") || exit 1
endpoint_url="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/Splunk_TA_Talos_Intelligence_account"
http_code=$(rest_create_or_update_account "${SK}" "${endpoint_url}" "${ACCOUNT_NAME}" "${create_body}" "${update_body}") || exit 1
log "Configured Talos service account '${ACCOUNT_NAME}' (HTTP ${http_code})."

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_AppDynamics"
SETUP_SCRIPT="${SCRIPT_DIR}/setup.sh"

ACCT_NAME=""
CONTROLLER_URL=""
CLIENT_NAME=""
CLIENT_SECRET=""
CREATE_INPUTS=""
INDEX="appdynamics"

usage() {
    cat <<EOF
Configure an AppDynamics controller connection via Splunk REST API.

Usage: $(basename "$0") [OPTIONS]

Required:
  --name NAME                Controller connection name
  --controller-url URL       AppDynamics controller URL
  --client-name NAME         AppDynamics API client name
  --client-secret-file FILE  Read client secret from FILE

Optional:
  --create-inputs TYPE       Immediately create inputs: recommended, all,
                             status, database, hardware, snapshots, security,
                             events, audit, licenses, custom
  --index INDEX              Target index for created inputs (default: appdynamics)

Splunk credentials are read from the project-root credentials file
(falls back to ~/.splunk/credentials) automatically.
Set SPLUNK_URI for remote Splunk (default: https://localhost:8089).
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) require_arg "$1" $# || exit 1; ACCT_NAME="$2"; shift 2 ;;
        --controller-url) require_arg "$1" $# || exit 1; CONTROLLER_URL="$2"; shift 2 ;;
        --client-name) require_arg "$1" $# || exit 1; CLIENT_NAME="$2"; shift 2 ;;
        --client-secret) require_arg "$1" $# || exit 1; reject_secret_arg "$1" "--client-secret-file" || exit 1 ;;
        --client-secret-file) require_arg "$1" $# || exit 1; CLIENT_SECRET=$(read_secret_file "$2"); shift 2 ;;
        --create-inputs) require_arg "$1" $# || exit 1; CREATE_INPUTS="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "${ACCT_NAME}" || -z "${CONTROLLER_URL}" || -z "${CLIENT_NAME}" || -z "${CLIENT_SECRET}" ]]; then
    log "ERROR: --name, --controller-url, --client-name, and --client-secret-file are required"
    exit 1
fi

load_splunk_credentials

SK=$(get_session_key "${SPLUNK_URI}")

log "Authenticated to Splunk REST API."

local_endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/Splunk_TA_AppDynamics_account"
log "Creating AppDynamics controller connection '${ACCT_NAME}'..."

create_body=$(form_urlencode_pairs \
    name "${ACCT_NAME}" \
    appd_controller_url "${CONTROLLER_URL}" \
    appd_client_name "${CLIENT_NAME}" \
    appd_client_secret "${CLIENT_SECRET}" \
    authentication "oauth") || exit 1

update_body=$(form_urlencode_pairs \
    appd_controller_url "${CONTROLLER_URL}" \
    appd_client_name "${CLIENT_NAME}" \
    appd_client_secret "${CLIENT_SECRET}" \
    authentication "oauth") || exit 1

http_code=$(rest_create_or_update_account "${SK}" "${local_endpoint}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
log "  SUCCESS: AppDynamics controller connection '${ACCT_NAME}' configured (HTTP ${http_code})"

if [[ -n "${CREATE_INPUTS}" ]]; then
    log "Creating '${CREATE_INPUTS}' inputs for controller connection '${ACCT_NAME}'..."
    bash "${SETUP_SCRIPT}" --enable-inputs --account "${ACCT_NAME}" --index "${INDEX}" --input-type "${CREATE_INPUTS}"
fi

log "Controller connection configuration complete."

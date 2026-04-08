#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_cisco_meraki"

ACCT_NAME=""
API_KEY=""
ORG_ID=""
REGION="global"
MAX_API_RATE="5"
AUTO_INPUTS="0"
AUTO_INDEX="meraki"

REGION_URL_MAP_global="https://api.meraki.com"
REGION_URL_MAP_india="https://api.meraki.in"
REGION_URL_MAP_canada="https://api.meraki.ca"
REGION_URL_MAP_china="https://api.meraki.cn"
REGION_URL_MAP_fedramp="https://api.gov-meraki.com"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Configure a Cisco Meraki organization account via Splunk REST API.

Usage: $(basename "$0") [OPTIONS]

Required:
  --name NAME            Account name (stanza identifier)
  --api-key KEY          Meraki Dashboard API key
  --api-key-file FILE    Read API key from FILE
  --org-id ID            Meraki organization ID

Optional:
  --region REGION        Region: global (default), india, canada, china, fedramp
  --max-api-rate N       Max API calls/sec, 1-10 (default: 5)
  --auto-inputs          Auto-create all inputs on account creation
  --index INDEX          Index for auto-created inputs (default: meraki)
  --help                 Show this help

Splunk credentials are read from the project-root credentials file (falls back to ~/.splunk/credentials) automatically.
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) require_arg "$1" $# || exit 1; ACCT_NAME="$2"; shift 2 ;;
        --api-key) require_arg "$1" $# || exit 1; echo "WARNING: --api-key exposes secrets in process listings. Prefer --api-key-file." >&2; API_KEY="$2"; shift 2 ;;
        --api-key-file) require_arg "$1" $# || exit 1; API_KEY=$(read_secret_file "$2"); shift 2 ;;
        --org-id) require_arg "$1" $# || exit 1; ORG_ID="$2"; shift 2 ;;
        --region) require_arg "$1" $# || exit 1; REGION="$2"; shift 2 ;;
        --max-api-rate) require_arg "$1" $# || exit 1; MAX_API_RATE="$2"; shift 2 ;;
        --auto-inputs) AUTO_INPUTS="1"; shift ;;
        --index) require_arg "$1" $# || exit 1; AUTO_INDEX="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage 1 ;;
    esac
done

if [[ -z "${ACCT_NAME}" || -z "${API_KEY}" || -z "${ORG_ID}" ]]; then
    log "ERROR: --name, --api-key (or --api-key-file), and --org-id are required"
    exit 1
fi

case "${REGION}" in
    global)  BASE_URL="${REGION_URL_MAP_global}" ;;
    india)   BASE_URL="${REGION_URL_MAP_india}" ;;
    canada)  BASE_URL="${REGION_URL_MAP_canada}" ;;
    china)   BASE_URL="${REGION_URL_MAP_china}" ;;
    fedramp) BASE_URL="${REGION_URL_MAP_fedramp}" ;;
    *) log "ERROR: Unknown region '${REGION}'. Use: global, india, canada, china, fedramp"; exit 1 ;;
esac

load_splunk_credentials

SK=$(get_session_key "${SPLUNK_URI}")

log "Authenticated to Splunk REST API."

local_endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/Splunk_TA_cisco_meraki_account"
log "Creating Meraki organization account '${ACCT_NAME}' (region=${REGION}, base_url=${BASE_URL})..."

create_body=$(form_urlencode_pairs \
    name "${ACCT_NAME}" \
    organization_api_key "${API_KEY}" \
    organization_id "${ORG_ID}" \
    region "${REGION}" \
    base_url "${BASE_URL}" \
    max_api_calls_per_second "${MAX_API_RATE}" \
    auth_type "basic" \
    automatic_input_creation "${AUTO_INPUTS}" \
    automatic_input_creation_index "${AUTO_INDEX}") || exit 1
update_body=$(form_urlencode_pairs \
    organization_api_key "${API_KEY}" \
    organization_id "${ORG_ID}" \
    region "${REGION}" \
    base_url "${BASE_URL}" \
    max_api_calls_per_second "${MAX_API_RATE}" \
    auth_type "basic" \
    automatic_input_creation "${AUTO_INPUTS}" \
    automatic_input_creation_index "${AUTO_INDEX}") || exit 1

http_code=$(rest_create_or_update_account "${SK}" "${local_endpoint}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
log "  SUCCESS: Meraki account '${ACCT_NAME}' configured (HTTP ${http_code})"

if [[ "${AUTO_INPUTS}" == "1" ]]; then
    log "  Auto-create inputs enabled — the TA will create all inputs for this organization."
    log "  Running an explicit enable pass for all Meraki inputs..."
    bash "${SCRIPT_DIR}/setup.sh" --enable-inputs \
        --account "${ACCT_NAME}" \
        --index "${AUTO_INDEX}" \
        --input-type all
fi

log "Account configuration complete."

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="ta_cisco_spaces"

STREAM_NAME=""
ACTIVATION_TOKEN=""
REGION=""
LOCATION_UPDATES="0"
AUTO_INPUTS=false
AUTO_INDEX="cisco_spaces"

usage() {
    cat <<EOF
Configure a Cisco Spaces meta stream via Splunk REST API.

Usage: $(basename "$0") [OPTIONS]

Required:
  --name NAME            Stream name (stanza identifier)
  --token-file FILE      Read activation token from FILE
  --region REGION        Region: io, eu, sg

Optional:
  --location-updates     Record device location updates (default: off)
  --auto-inputs          Auto-create firehose input on stream creation
  --index INDEX          Index for auto-created inputs (default: cisco_spaces)
  --help                 Show this help

Splunk credentials are read from the project-root credentials file (falls back to ~/.splunk/credentials) automatically.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) require_arg "$1" $# || exit 1; STREAM_NAME="$2"; shift 2 ;;
        --token) require_arg "$1" $# || exit 1; reject_secret_arg "$1" "--token-file" || exit 1 ;;
        --token-file) require_arg "$1" $# || exit 1; ACTIVATION_TOKEN=$(read_secret_file "$2"); shift 2 ;;
        --region) require_arg "$1" $# || exit 1; REGION="$2"; shift 2 ;;
        --location-updates) LOCATION_UPDATES="1"; shift ;;
        --auto-inputs) AUTO_INPUTS=true; shift ;;
        --index) require_arg "$1" $# || exit 1; AUTO_INDEX="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "${STREAM_NAME}" || -z "${ACTIVATION_TOKEN}" || -z "${REGION}" ]]; then
    log "ERROR: --name, --token-file, and --region are required"
    exit 1
fi

case "${REGION}" in
    io|eu|sg) ;;
    *) log "ERROR: Unknown region '${REGION}'. Use: io, eu, sg"; exit 1 ;;
esac

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }

SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

log "Authenticated to Splunk REST API."

local_endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/ta_cisco_spaces_stream"
log "Creating Cisco Spaces meta stream '${STREAM_NAME}' (region=${REGION})..."

create_body=$(form_urlencode_pairs \
    name "${STREAM_NAME}" \
    activation_token "${ACTIVATION_TOKEN}" \
    region "${REGION}" \
    location_updates_status "${LOCATION_UPDATES}") || exit 1
update_body=$(form_urlencode_pairs \
    activation_token "${ACTIVATION_TOKEN}" \
    region "${REGION}" \
    location_updates_status "${LOCATION_UPDATES}") || exit 1

http_code=$(rest_create_or_update_account "${SK}" "${local_endpoint}" "${STREAM_NAME}" "${create_body}" "${update_body}") || exit 1
log "  SUCCESS: Cisco Spaces stream '${STREAM_NAME}' configured (HTTP ${http_code})"

if $AUTO_INPUTS; then
    log "  Auto-creating firehose input for stream '${STREAM_NAME}'..."
    bash "${SCRIPT_DIR}/setup.sh" --enable-inputs \
        --stream "${STREAM_NAME}" \
        --index "${AUTO_INDEX}"
fi

log "Stream configuration complete."

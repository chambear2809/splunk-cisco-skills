#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_AppDynamics"
SETUP_SCRIPT="${SCRIPT_DIR}/setup.sh"

ANALYTICS_NAME=""
GLOBAL_ACCOUNT_NAME=""
ANALYTICS_SECRET=""
ANALYTICS_ENDPOINT="https://analytics.api.appdynamics.com"
ONPREM_ANALYTICS_URL=""
QUERY=""
INDEX="appdynamics"
SOURCE_NAME="appdynamics_analytics"
INPUT_NAME=""

usage() {
    cat <<EOF
Configure an AppDynamics analytics connection via Splunk REST API.

Usage: $(basename "$0") [OPTIONS]

Required:
  --name NAME                   Analytics connection name
  --global-account-name NAME    AppDynamics global analytics account name
  --analytics-secret SECRET     Analytics API secret
  --analytics-secret-file FILE  Read analytics API secret from FILE

Optional:
  --endpoint URL|none           Analytics endpoint (default: https://analytics.api.appdynamics.com)
  --onprem-url URL              On-prem analytics URL when --endpoint none
  --query QUERY                 Immediately create an Analytics Search input
  --index INDEX                 Target index for created analytics input (default: appdynamics)
  --source-name NAME            Source name for created analytics input (default: appdynamics_analytics)
  --input-name NAME             Explicit analytics input stanza name

Splunk credentials are read from the project-root credentials file
(falls back to ~/.splunk/credentials) automatically.
Set SPLUNK_URI for remote Splunk (default: https://localhost:8089).
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) require_arg "$1" $# || exit 1; ANALYTICS_NAME="$2"; shift 2 ;;
        --global-account-name) require_arg "$1" $# || exit 1; GLOBAL_ACCOUNT_NAME="$2"; shift 2 ;;
        --analytics-secret) require_arg "$1" $# || exit 1; echo "WARNING: --analytics-secret exposes secrets in process listings. Prefer --analytics-secret-file." >&2; ANALYTICS_SECRET="$2"; shift 2 ;;
        --analytics-secret-file) require_arg "$1" $# || exit 1; ANALYTICS_SECRET=$(read_secret_file "$2"); shift 2 ;;
        --endpoint) require_arg "$1" $# || exit 1; ANALYTICS_ENDPOINT="$2"; shift 2 ;;
        --onprem-url) require_arg "$1" $# || exit 1; ONPREM_ANALYTICS_URL="$2"; shift 2 ;;
        --query) require_arg "$1" $# || exit 1; QUERY="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --source-name) require_arg "$1" $# || exit 1; SOURCE_NAME="$2"; shift 2 ;;
        --input-name) require_arg "$1" $# || exit 1; INPUT_NAME="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "${ANALYTICS_NAME}" || -z "${GLOBAL_ACCOUNT_NAME}" || -z "${ANALYTICS_SECRET}" ]]; then
    log "ERROR: --name, --global-account-name, and --analytics-secret (or --analytics-secret-file) are required"
    exit 1
fi

if [[ "$(printf '%s' "${ANALYTICS_ENDPOINT}" | tr '[:upper:]' '[:lower:]')" == "none" ]]; then
    ANALYTICS_ENDPOINT="None"
    if [[ -z "${ONPREM_ANALYTICS_URL}" ]]; then
        log "ERROR: --onprem-url is required when --endpoint none"
        exit 1
    fi
fi

load_splunk_credentials

SK=$(get_session_key "${SPLUNK_URI}")

log "Authenticated to Splunk REST API."

local_endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/Splunk_TA_AppDynamics_analytics_account"
log "Creating AppDynamics analytics connection '${ANALYTICS_NAME}'..."

create_body=$(form_urlencode_pairs \
    name "${ANALYTICS_NAME}" \
    appd_analytics_account_name "${GLOBAL_ACCOUNT_NAME}" \
    appd_analytics_endpoint "${ANALYTICS_ENDPOINT}" \
    appd_analytics_secret "${ANALYTICS_SECRET}") || exit 1

update_body=$(form_urlencode_pairs \
    appd_analytics_account_name "${GLOBAL_ACCOUNT_NAME}" \
    appd_analytics_endpoint "${ANALYTICS_ENDPOINT}" \
    appd_analytics_secret "${ANALYTICS_SECRET}") || exit 1

if [[ -n "${ONPREM_ANALYTICS_URL}" ]]; then
    onprem_pair=$(form_urlencode_pairs appd_onprem_analytics_url "${ONPREM_ANALYTICS_URL}") || exit 1
    create_body="${create_body}&${onprem_pair}"
    update_body="${update_body}&${onprem_pair}"
fi

http_code=$(rest_create_or_update_account "${SK}" "${local_endpoint}" "${ANALYTICS_NAME}" "${create_body}" "${update_body}") || exit 1
log "  SUCCESS: AppDynamics analytics connection '${ANALYTICS_NAME}' configured (HTTP ${http_code})"

if [[ -n "${QUERY}" ]]; then
    log "Creating analytics search input for '${ANALYTICS_NAME}'..."
    declare -a args=(
        "${SETUP_SCRIPT}"
        --enable-inputs
        --index "${INDEX}"
        --input-type analytics
        --analytics-account "${ANALYTICS_NAME}"
        --query "${QUERY}"
        --source-name "${SOURCE_NAME}"
    )
    if [[ -n "${INPUT_NAME}" ]]; then
        args+=(--input-name "${INPUT_NAME}")
    fi
    bash "${args[@]}"
fi

log "Analytics connection configuration complete."

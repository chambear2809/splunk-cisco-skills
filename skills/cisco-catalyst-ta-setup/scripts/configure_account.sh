#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="TA_cisco_catalyst"

ACCT_TYPE=""
ACCT_NAME=""
HOST=""
USERNAME=""
PASSWORD=""
API_TOKEN=""
USE_CA_CERT="false"

usage() {
    cat <<EOF
Configure a Cisco Catalyst TA account via Splunk REST API.

Usage: $(basename "$0") [OPTIONS]

Required:
  --type TYPE        Account type: catalyst_center, ise, sdwan, cybervision
  --name NAME        Account name (stanza identifier)

Catalyst Center:
  --host URL         Catalyst Center URL (e.g., https://10.100.0.60)
  --username USER    Username
  --password PASS    Password

ISE:
  --host URL         ISE URL (e.g., https://10.100.0.10/admin/login.jsp)
  --username USER    Username
  --password PASS    Password

SD-WAN:
  --host URL         SD-WAN portal URL
  --username USER    Username
  --password PASS    Password

Cyber Vision:
  --host URL         Cyber Vision portal URL (e.g., https://192.168.1.100)
  --api-token TOKEN  API token

  --password-file FILE Read device password from FILE
  --api-token-file FILE Read API token from FILE

Splunk credentials are read from the project-root credentials file (falls back to ~/.splunk/credentials) automatically.
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --type) ACCT_TYPE="$2"; shift 2 ;;
        --name) ACCT_NAME="$2"; shift 2 ;;
        --host) HOST="$2"; shift 2 ;;
        --username) USERNAME="$2"; shift 2 ;;
        --password) PASSWORD="$2"; shift 2 ;;
        --password-file) PASSWORD=$(read_secret_file "$2"); shift 2 ;;
        --api-token) API_TOKEN="$2"; shift 2 ;;
        --api-token-file) API_TOKEN=$(read_secret_file "$2"); shift 2 ;;
        --use-ca-cert) USE_CA_CERT="true"; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if [[ -z "${ACCT_TYPE}" || -z "${ACCT_NAME}" ]]; then
    log "ERROR: --type and --name are required"
    exit 1
fi

load_splunk_credentials

SK=$(get_session_key "${SPLUNK_URI}")

log "Authenticated to Splunk REST API."

configure_catalyst_center() {
    if [[ -z "${HOST}" || -z "${USERNAME}" || -z "${PASSWORD}" ]]; then
        log "ERROR: --host, --username, --password required for catalyst_center"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/TA_cisco_catalyst_account"
    log "Creating Catalyst Center account '${ACCT_NAME}'..."

    local body http_code resp update_body
    body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        cisco_dna_center_host "${HOST}" \
        username "${USERNAME}" \
        password "${PASSWORD}" \
        copy_account_name "${ACCT_NAME}" \
        use_ca_cert "${USE_CA_CERT}" \
        custom_certificate "") || exit 1
    resp=$(splunk_curl_post "${SK}" \
        "${body}" \
        "${endpoint}" -w '\n%{http_code}')
    http_code=$(echo "${resp}" | tail -1)

    if [[ "${http_code}" == "201" || "${http_code}" == "200" ]]; then
        log "  SUCCESS: Account '${ACCT_NAME}' created (HTTP ${http_code})"
    elif [[ "${http_code}" == "409" ]]; then
        log "  Account already exists. Updating..."
        update_body=$(form_urlencode_pairs \
            cisco_dna_center_host "${HOST}" \
            username "${USERNAME}" \
            password "${PASSWORD}" \
            copy_account_name "${ACCT_NAME}" \
            use_ca_cert "${USE_CA_CERT}" \
            custom_certificate "") || exit 1
        resp=$(splunk_curl_post "${SK}" \
            "${update_body}" \
            "${endpoint}/${ACCT_NAME}" -w '\n%{http_code}')
        http_code=$(echo "${resp}" | tail -1)
        log "  UPDATE: HTTP ${http_code}"
    else
        log "  ERROR: HTTP ${http_code}"
        sanitize_response "${resp}"
        exit 1
    fi
}

configure_ise() {
    if [[ -z "${HOST}" || -z "${USERNAME}" || -z "${PASSWORD}" ]]; then
        log "ERROR: --host, --username, --password required for ise"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/TA_cisco_catalyst_ise_account"
    log "Creating ISE account '${ACCT_NAME}'..."

    local body http_code resp update_body
    body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        hostname "${HOST}" \
        username "${USERNAME}" \
        password "${PASSWORD}" \
        copy_account_name "${ACCT_NAME}" \
        use_ca_cert "${USE_CA_CERT}" \
        enable_proxy "false" \
        pxgrid_cert_auth "false") || exit 1
    resp=$(splunk_curl_post "${SK}" \
        "${body}" \
        "${endpoint}" -w '\n%{http_code}')
    http_code=$(echo "${resp}" | tail -1)

    if [[ "${http_code}" == "201" || "${http_code}" == "200" ]]; then
        log "  SUCCESS: Account '${ACCT_NAME}' created (HTTP ${http_code})"
    elif [[ "${http_code}" == "409" ]]; then
        log "  Account already exists. Updating..."
        update_body=$(form_urlencode_pairs \
            hostname "${HOST}" \
            username "${USERNAME}" \
            password "${PASSWORD}" \
            copy_account_name "${ACCT_NAME}" \
            use_ca_cert "${USE_CA_CERT}" \
            enable_proxy "false" \
            pxgrid_cert_auth "false") || exit 1
        resp=$(splunk_curl_post "${SK}" \
            "${update_body}" \
            "${endpoint}/${ACCT_NAME}" -w '\n%{http_code}')
        http_code=$(echo "${resp}" | tail -1)
        log "  UPDATE: HTTP ${http_code}"
    else
        log "  ERROR: HTTP ${http_code}"
        sanitize_response "${resp}"
        exit 1
    fi
}

configure_sdwan() {
    if [[ -z "${HOST}" || -z "${USERNAME}" || -z "${PASSWORD}" ]]; then
        log "ERROR: --host, --username, --password required for sdwan"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/TA_cisco_catalyst_sdwan_account"
    log "Creating SD-WAN account '${ACCT_NAME}'..."

    local body http_code resp update_body
    body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        hostname "${HOST}" \
        username "${USERNAME}" \
        password "${PASSWORD}" \
        copy_account_name "${ACCT_NAME}" \
        use_ca_cert "${USE_CA_CERT}" \
        enable_proxy "false") || exit 1
    resp=$(splunk_curl_post "${SK}" \
        "${body}" \
        "${endpoint}" -w '\n%{http_code}')
    http_code=$(echo "${resp}" | tail -1)

    if [[ "${http_code}" == "201" || "${http_code}" == "200" ]]; then
        log "  SUCCESS: Account '${ACCT_NAME}' created (HTTP ${http_code})"
    elif [[ "${http_code}" == "409" ]]; then
        log "  Account already exists. Updating..."
        update_body=$(form_urlencode_pairs \
            hostname "${HOST}" \
            username "${USERNAME}" \
            password "${PASSWORD}" \
            copy_account_name "${ACCT_NAME}" \
            use_ca_cert "${USE_CA_CERT}" \
            enable_proxy "false") || exit 1
        resp=$(splunk_curl_post "${SK}" \
            "${update_body}" \
            "${endpoint}/${ACCT_NAME}" -w '\n%{http_code}')
        http_code=$(echo "${resp}" | tail -1)
        log "  UPDATE: HTTP ${http_code}"
    else
        log "  ERROR: HTTP ${http_code}"
        sanitize_response "${resp}"
        exit 1
    fi
}

configure_cybervision() {
    if [[ -z "${HOST}" || -z "${API_TOKEN}" ]]; then
        log "ERROR: --host and --api-token required for cybervision"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/TA_cisco_catalyst_cyber_vision_account"
    log "Creating Cyber Vision account '${ACCT_NAME}'..."

    local body http_code resp update_body
    body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        ip_address "${HOST}" \
        api_token "${API_TOKEN}" \
        copy_account_name "${ACCT_NAME}" \
        use_ca_cert "${USE_CA_CERT}" \
        enable_proxy "false") || exit 1
    resp=$(splunk_curl_post "${SK}" \
        "${body}" \
        "${endpoint}" -w '\n%{http_code}')
    http_code=$(echo "${resp}" | tail -1)

    if [[ "${http_code}" == "201" || "${http_code}" == "200" ]]; then
        log "  SUCCESS: Account '${ACCT_NAME}' created (HTTP ${http_code})"
    elif [[ "${http_code}" == "409" ]]; then
        log "  Account already exists. Updating..."
        update_body=$(form_urlencode_pairs \
            ip_address "${HOST}" \
            api_token "${API_TOKEN}" \
            copy_account_name "${ACCT_NAME}" \
            use_ca_cert "${USE_CA_CERT}" \
            enable_proxy "false") || exit 1
        resp=$(splunk_curl_post "${SK}" \
            "${update_body}" \
            "${endpoint}/${ACCT_NAME}" -w '\n%{http_code}')
        http_code=$(echo "${resp}" | tail -1)
        log "  UPDATE: HTTP ${http_code}"
    else
        log "  ERROR: HTTP ${http_code}"
        sanitize_response "${resp}"
        exit 1
    fi
}

case "${ACCT_TYPE}" in
    catalyst_center) configure_catalyst_center ;;
    ise) configure_ise ;;
    sdwan) configure_sdwan ;;
    cybervision) configure_cybervision ;;
    *) log "ERROR: Unknown account type '${ACCT_TYPE}'. Use: catalyst_center, ise, sdwan, cybervision"; exit 1 ;;
esac

log "Account configuration complete."

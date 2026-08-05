#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="TA_cisco_catalyst"

ACCT_TYPE=""
ACCT_NAME=""
HOST=""
PORT="22"
USERNAME=""
PASSWORD=""
API_TOKEN=""
HOST_KEY_FINGERPRINT=""
USE_CA_CERT="false"
VERIFY_SSL="true"

usage() {
    cat <<EOF
Configure a Cisco Catalyst TA account via Splunk REST API.

Usage: $(basename "$0") [OPTIONS]

Required:
  --type TYPE        Account type: catalyst_center, ise, sdwan, cybervision, iosxe_cli
  --name NAME        Account name (stanza identifier)

Catalyst Center:
  --host URL         Catalyst Center URL (e.g., https://10.100.0.60)
  --username USER    Username
  --password-file FILE Read device password from FILE

ISE:
  --host URL         ISE URL (e.g., https://10.100.0.10/admin/login.jsp)
  --username USER    Username
  --password-file FILE Read device password from FILE

SD-WAN:
  --host URL         SD-WAN portal URL
  --username USER    Username
  --password-file FILE Read device password from FILE

Cyber Vision:
  --host URL         Cyber Vision portal URL (e.g., https://192.168.1.100)
  --api-token-file FILE Read API token from FILE

IOS-XE CLI (Beta):
  --host HOST        Bare IOS-XE device hostname or IP (no URL scheme/path)
  --port PORT        SSH port (default: 22)
  --username USER    Device username with sufficient non-interactive privilege
  --password-file FILE Read device password from FILE
  --host-key-fingerprint SHA256:... Verified device SSH host-key fingerprint

    --use-ca-cert      Enable custom CA certificate validation on the account
    --no-verify-ssl    Disable TLS certificate verification for this account only
    --verify-ssl       Enable TLS certificate verification for this account (default)

Splunk credentials are read from the project-root credentials file (falls back to ~/.splunk/credentials) automatically.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --type) require_arg "$1" $# || exit 1; ACCT_TYPE="$2"; shift 2 ;;
        --name) require_arg "$1" $# || exit 1; ACCT_NAME="$2"; shift 2 ;;
        --host) require_arg "$1" $# || exit 1; HOST="$2"; shift 2 ;;
        --port) require_arg "$1" $# || exit 1; PORT="$2"; shift 2 ;;
        --username) require_arg "$1" $# || exit 1; USERNAME="$2"; shift 2 ;;
        --host-key-fingerprint) require_arg "$1" $# || exit 1; HOST_KEY_FINGERPRINT="$2"; shift 2 ;;
        --password) require_arg "$1" $# || exit 1; reject_secret_arg "$1" "--password-file" || exit 1 ;;
        --password-file) require_arg "$1" $# || exit 1; PASSWORD=$(read_secret_file "$2"); shift 2 ;;
        --api-token) require_arg "$1" $# || exit 1; reject_secret_arg "$1" "--api-token-file" || exit 1 ;;
        --api-token-file) require_arg "$1" $# || exit 1; API_TOKEN=$(read_secret_file "$2"); shift 2 ;;
        --use-ca-cert) USE_CA_CERT="true"; shift ;;
        --no-verify-ssl) VERIFY_SSL="false"; shift ;;
        --verify-ssl) VERIFY_SSL="true"; shift ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "${ACCT_TYPE}" || -z "${ACCT_NAME}" ]]; then
    log "ERROR: --type and --name are required"
    exit 1
fi

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }

SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

log "Authenticated to Splunk REST API."

ta_handler_available() {
    local handler="$1" http_code
    http_code=$(splunk_curl "${SK}" --connect-timeout 5 --max-time 15 \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/${handler}?output_mode=json&count=0" \
        -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
    [[ "${http_code}" == "200" ]]
}

configure_catalyst_center() {
    if [[ -z "${HOST}" || -z "${USERNAME}" || -z "${PASSWORD}" ]]; then
        log "ERROR: --host, --username, and --password-file are required for catalyst_center"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/TA_cisco_catalyst_account"
    log "Creating Catalyst Center account '${ACCT_NAME}'..."

    local create_body update_body http_code
    create_body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        cisco_dna_center_host "${HOST}" \
        username "${USERNAME}" \
        password "${PASSWORD}" \
        copy_account_name "${ACCT_NAME}" \
        verify_ssl "${VERIFY_SSL}" \
        use_ca_cert "${USE_CA_CERT}" \
        custom_certificate "") || exit 1
    update_body=$(form_urlencode_pairs \
        cisco_dna_center_host "${HOST}" \
        username "${USERNAME}" \
        password "${PASSWORD}" \
        copy_account_name "${ACCT_NAME}" \
        verify_ssl "${VERIFY_SSL}" \
        use_ca_cert "${USE_CA_CERT}" \
        custom_certificate "") || exit 1

    http_code=$(rest_create_or_update_account "${SK}" "${endpoint}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
    log "  SUCCESS: Catalyst Center account '${ACCT_NAME}' configured (HTTP ${http_code})"
}

configure_ise() {
    if [[ -z "${HOST}" || -z "${USERNAME}" || -z "${PASSWORD}" ]]; then
        log "ERROR: --host, --username, and --password-file are required for ise"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/TA_cisco_catalyst_ise_account"
    log "Creating ISE account '${ACCT_NAME}'..."

    local create_body update_body http_code
    create_body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        hostname "${HOST}" \
        username "${USERNAME}" \
        password "${PASSWORD}" \
        copy_account_name "${ACCT_NAME}" \
        verify_ssl "${VERIFY_SSL}" \
        use_ca_cert "${USE_CA_CERT}" \
        enable_proxy "false" \
        pxgrid_cert_auth "false") || exit 1
    update_body=$(form_urlencode_pairs \
        hostname "${HOST}" \
        username "${USERNAME}" \
        password "${PASSWORD}" \
        copy_account_name "${ACCT_NAME}" \
        verify_ssl "${VERIFY_SSL}" \
        use_ca_cert "${USE_CA_CERT}" \
        enable_proxy "false" \
        pxgrid_cert_auth "false") || exit 1

    http_code=$(rest_create_or_update_account "${SK}" "${endpoint}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
    log "  SUCCESS: ISE account '${ACCT_NAME}' configured (HTTP ${http_code})"
}

configure_sdwan() {
    if [[ -z "${HOST}" || -z "${USERNAME}" || -z "${PASSWORD}" ]]; then
        log "ERROR: --host, --username, and --password-file are required for sdwan"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/TA_cisco_catalyst_sdwan_account"
    log "Creating SD-WAN account '${ACCT_NAME}'..."

    local create_body update_body http_code
    create_body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        hostname "${HOST}" \
        username "${USERNAME}" \
        password "${PASSWORD}" \
        copy_account_name "${ACCT_NAME}" \
        verify_ssl "${VERIFY_SSL}" \
        use_ca_cert "${USE_CA_CERT}" \
        enable_proxy "false") || exit 1
    update_body=$(form_urlencode_pairs \
        hostname "${HOST}" \
        username "${USERNAME}" \
        password "${PASSWORD}" \
        copy_account_name "${ACCT_NAME}" \
        verify_ssl "${VERIFY_SSL}" \
        use_ca_cert "${USE_CA_CERT}" \
        enable_proxy "false") || exit 1

    http_code=$(rest_create_or_update_account "${SK}" "${endpoint}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
    log "  SUCCESS: SD-WAN account '${ACCT_NAME}' configured (HTTP ${http_code})"
}

configure_cybervision() {
    if [[ -z "${HOST}" || -z "${API_TOKEN}" ]]; then
        log "ERROR: --host and --api-token-file are required for cybervision"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/TA_cisco_catalyst_cyber_vision_account"
    log "Creating Cyber Vision account '${ACCT_NAME}'..."

    local create_body update_body http_code
    create_body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        ip_address "${HOST}" \
        api_token "${API_TOKEN}" \
        copy_account_name "${ACCT_NAME}" \
        verify_ssl "${VERIFY_SSL}" \
        use_ca_cert "${USE_CA_CERT}" \
        enable_proxy "false") || exit 1
    update_body=$(form_urlencode_pairs \
        ip_address "${HOST}" \
        api_token "${API_TOKEN}" \
        copy_account_name "${ACCT_NAME}" \
        verify_ssl "${VERIFY_SSL}" \
        use_ca_cert "${USE_CA_CERT}" \
        enable_proxy "false") || exit 1

    http_code=$(rest_create_or_update_account "${SK}" "${endpoint}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
    log "  SUCCESS: Cyber Vision account '${ACCT_NAME}' configured (HTTP ${http_code})"
}

configure_iosxe_cli() {
    if [[ -z "${HOST}" || -z "${USERNAME}" || -z "${PASSWORD}" || -z "${HOST_KEY_FINGERPRINT}" ]]; then
        log "ERROR: --host, --username, --password-file, and --host-key-fingerprint are required for iosxe_cli"
        exit 1
    fi
    if [[ ! "${PORT}" =~ ^[0-9]+$ ]]; then
        log "ERROR: --port must be an integer from 1 through 65535"
        exit 1
    fi
    local port_number
    port_number=$((10#${PORT}))
    if (( port_number < 1 || port_number > 65535 )); then
        log "ERROR: --port must be an integer from 1 through 65535"
        exit 1
    fi
    if [[ "${HOST}" == *"://"* || "${HOST}" == *"/"* || "${HOST}" =~ [[:space:]] ]]; then
        log "ERROR: iosxe_cli --host must be a bare hostname or IP address without a scheme, path, or whitespace"
        exit 1
    fi
    if [[ ! "${HOST_KEY_FINGERPRINT}" =~ ^SHA256:[A-Za-z0-9+/]{43}=?$ ]]; then
        log "ERROR: --host-key-fingerprint must use SHA256:<base64> format"
        exit 1
    fi
    if ! ta_handler_available "TA_cisco_catalyst_cli_account"; then
        log "ERROR: The installed ${APP_NAME} does not expose the IOS-XE CLI account handler."
        log "IOS-XE CLI automation requires a package that implements the 3.2.44 source contract; the default package-verified 3.1.0 install does not."
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/TA_cisco_catalyst_cli_account"
    log "Creating IOS-XE CLI account '${ACCT_NAME}'..."

    local create_body update_body http_code
    create_body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        host "${HOST}" \
        port "${PORT}" \
        username "${USERNAME}" \
        password "${PASSWORD}" \
        host_key_fingerprint "${HOST_KEY_FINGERPRINT}" \
        copy_account_name "${ACCT_NAME}") || exit 1
    update_body=$(form_urlencode_pairs \
        host "${HOST}" \
        port "${PORT}" \
        username "${USERNAME}" \
        password "${PASSWORD}" \
        host_key_fingerprint "${HOST_KEY_FINGERPRINT}" \
        copy_account_name "${ACCT_NAME}") || exit 1

    http_code=$(rest_create_or_update_account "${SK}" "${endpoint}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
    log "  SUCCESS: IOS-XE CLI account '${ACCT_NAME}' configured (HTTP ${http_code})"
    log "  NOTE: Test Connection in the TA UI before enabling a Beta CLI command input."
}

case "${ACCT_TYPE}" in
    catalyst_center) configure_catalyst_center ;;
    ise) configure_ise ;;
    sdwan) configure_sdwan ;;
    cybervision) configure_cybervision ;;
    iosxe_cli) configure_iosxe_cli ;;
    *) log "ERROR: Unknown account type '${ACCT_TYPE}'. Use: catalyst_center, ise, sdwan, cybervision, iosxe_cli"; exit 1 ;;
esac

log "Account configuration complete."

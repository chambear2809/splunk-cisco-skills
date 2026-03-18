#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco_dc_networking_app_for_splunk"

ACCT_TYPE=""
ACCT_NAME=""
HOSTNAME=""
PORT="443"
AUTH_TYPE="password_authentication"
USERNAME=""
PASSWORD=""
DEVICE_IP=""
LOGIN_DOMAIN=""
PROXY_ENABLED="0"

usage() {
    cat <<EOF
Configure a Cisco DC Networking account in Splunk via REST API.

Usage: $(basename "$0") [OPTIONS]

Required:
  --type TYPE        Account type: aci, nd, nexus9k
  --name NAME        Account name (stanza identifier)
  --username USER    Account username
  --password PASS    Account password (or use --password-file)
  --password-file F  Read password from file (alternative to --password)

ACI / ND specific:
  --hostname HOSTS   Comma-separated APIC or ND hostnames/IPs
  --port PORT        Connection port (default: 443)
  --auth-type TYPE   Authentication type (default: password_authentication)
  --login-domain D   Login domain (optional)

Nexus 9K specific:
  --device-ip IP     Nexus 9K device IP address
  --port PORT        Connection port (default: 443)

Common:
  --proxy-enabled    Enable proxy (default: disabled)
  --help             Show this help

Note: Use --password-file to avoid passing the password on the command line.
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --type) ACCT_TYPE="$2"; shift 2 ;;
        --name) ACCT_NAME="$2"; shift 2 ;;
        --hostname) HOSTNAME="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --auth-type) AUTH_TYPE="$2"; shift 2 ;;
        --username) USERNAME="$2"; shift 2 ;;
        --password) PASSWORD="$2"; shift 2 ;;
        --password-file) PASSWORD=$(read_secret_file "$2"); shift 2 ;;
        --device-ip) DEVICE_IP="$2"; shift 2 ;;
        --login-domain) LOGIN_DOMAIN="$2"; shift 2 ;;
        --proxy-enabled) PROXY_ENABLED="1"; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if [[ -z "${ACCT_TYPE}" || -z "${ACCT_NAME}" || -z "${USERNAME}" || -z "${PASSWORD}" ]]; then
    log "ERROR: --type, --name, --username, and --password (or --password-file) are required"
    exit 1
fi

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

_urlencode() {
    python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"
}

configure_aci_account() {
    if [[ -z "${HOSTNAME}" ]]; then
        log "ERROR: --hostname is required for ACI accounts"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/cisco_dc_networking_app_for_splunk_aci_account"
    log "Configuring ACI account '${ACCT_NAME}' via REST..."

    local body enc_name update_body
    enc_name=$(_urlencode "${ACCT_NAME}")
    body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        apic_hostname "${HOSTNAME}" \
        apic_port "${PORT}" \
        apic_authentication_type "${AUTH_TYPE}" \
        apic_username "${USERNAME}" \
        apic_password "${PASSWORD}" \
        apic_proxy_enabled "${PROXY_ENABLED}") || exit 1
    if [[ -n "${LOGIN_DOMAIN}" ]]; then
        body="${body}&$(form_urlencode_pairs apic_login_domain "${LOGIN_DOMAIN}")"
    fi

    local http_code resp
    resp=$(splunk_curl_post "$SK" "${body}" "${endpoint}" -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)

    case "${http_code}" in
        201|200) log "ACI account '${ACCT_NAME}' created (HTTP ${http_code})" ;;
        409)
            log "Account already exists. Updating..."
            update_body=$(form_urlencode_pairs \
                apic_hostname "${HOSTNAME}" \
                apic_port "${PORT}" \
                apic_authentication_type "${AUTH_TYPE}" \
                apic_username "${USERNAME}" \
                apic_password "${PASSWORD}" \
                apic_proxy_enabled "${PROXY_ENABLED}") || exit 1
            if [[ -n "${LOGIN_DOMAIN}" ]]; then
                update_body="${update_body}&$(form_urlencode_pairs apic_login_domain "${LOGIN_DOMAIN}")"
            fi
            resp=$(splunk_curl_post "$SK" "${update_body}" "${endpoint}/${enc_name}" -w '\n%{http_code}' 2>/dev/null)
            http_code=$(echo "${resp}" | tail -1)
            log "ACI account '${ACCT_NAME}' updated (HTTP ${http_code})"
            ;;
        *) log "ERROR: Create ACI account failed (HTTP ${http_code})"; sanitize_response "${resp}" 5; exit 1 ;;
    esac
}

configure_nd_account() {
    if [[ -z "${HOSTNAME}" ]]; then
        log "ERROR: --hostname is required for Nexus Dashboard accounts"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/cisco_dc_networking_app_for_splunk_nd_account"
    log "Configuring Nexus Dashboard account '${ACCT_NAME}' via REST..."

    local body enc_name update_body
    enc_name=$(_urlencode "${ACCT_NAME}")
    body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        nd_hostname "${HOSTNAME}" \
        nd_port "${PORT}" \
        nd_authentication_type "${AUTH_TYPE}" \
        nd_username "${USERNAME}" \
        nd_password "${PASSWORD}" \
        nd_enable_proxy "${PROXY_ENABLED}") || exit 1
    if [[ -n "${LOGIN_DOMAIN}" ]]; then
        body="${body}&$(form_urlencode_pairs nd_login_domain "${LOGIN_DOMAIN}")"
    fi

    local http_code resp
    resp=$(splunk_curl_post "$SK" "${body}" "${endpoint}" -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)

    case "${http_code}" in
        201|200) log "Nexus Dashboard account '${ACCT_NAME}' created (HTTP ${http_code})" ;;
        409)
            log "Account already exists. Updating..."
            update_body=$(form_urlencode_pairs \
                nd_hostname "${HOSTNAME}" \
                nd_port "${PORT}" \
                nd_authentication_type "${AUTH_TYPE}" \
                nd_username "${USERNAME}" \
                nd_password "${PASSWORD}" \
                nd_enable_proxy "${PROXY_ENABLED}") || exit 1
            if [[ -n "${LOGIN_DOMAIN}" ]]; then
                update_body="${update_body}&$(form_urlencode_pairs nd_login_domain "${LOGIN_DOMAIN}")"
            fi
            resp=$(splunk_curl_post "$SK" "${update_body}" "${endpoint}/${enc_name}" -w '\n%{http_code}' 2>/dev/null)
            http_code=$(echo "${resp}" | tail -1)
            log "Nexus Dashboard account '${ACCT_NAME}' updated (HTTP ${http_code})"
            ;;
        *) log "ERROR: Create ND account failed (HTTP ${http_code})"; sanitize_response "${resp}" 5; exit 1 ;;
    esac
}

configure_nexus9k_account() {
    if [[ -z "${DEVICE_IP}" ]]; then
        log "ERROR: --device-ip is required for Nexus 9K accounts"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/cisco_dc_networking_app_for_splunk_nexus_9k_account"
    log "Configuring Nexus 9K account '${ACCT_NAME}' via REST..."

    local body enc_name update_body
    enc_name=$(_urlencode "${ACCT_NAME}")
    body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        nexus_9k_device_ip "${DEVICE_IP}" \
        nexus_9k_port "${PORT}" \
        nexus_9k_username "${USERNAME}" \
        nexus_9k_password "${PASSWORD}" \
        nexus_9k_enable_proxy "${PROXY_ENABLED}") || exit 1

    local http_code resp
    resp=$(splunk_curl_post "$SK" "${body}" "${endpoint}" -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)

    case "${http_code}" in
        201|200) log "Nexus 9K account '${ACCT_NAME}' created (HTTP ${http_code})" ;;
        409)
            log "Account already exists. Updating..."
            update_body=$(form_urlencode_pairs \
                nexus_9k_device_ip "${DEVICE_IP}" \
                nexus_9k_port "${PORT}" \
                nexus_9k_username "${USERNAME}" \
                nexus_9k_password "${PASSWORD}" \
                nexus_9k_enable_proxy "${PROXY_ENABLED}") || exit 1
            resp=$(splunk_curl_post "$SK" "${update_body}" "${endpoint}/${enc_name}" -w '\n%{http_code}' 2>/dev/null)
            http_code=$(echo "${resp}" | tail -1)
            log "Nexus 9K account '${ACCT_NAME}' updated (HTTP ${http_code})"
            ;;
        *) log "ERROR: Create Nexus 9K account failed (HTTP ${http_code})"; sanitize_response "${resp}" 5; exit 1 ;;
    esac
}

case "${ACCT_TYPE}" in
    aci) configure_aci_account ;;
    nd) configure_nd_account ;;
    nexus9k) configure_nexus9k_account ;;
    *) log "ERROR: Unknown account type '${ACCT_TYPE}'. Use: aci, nd, nexus9k"; exit 1 ;;
esac

log "Account configuration complete."
log "$(log_platform_restart_guidance "account changes")"

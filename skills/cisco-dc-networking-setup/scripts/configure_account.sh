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
SET_VERIFY_SSL=""

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
  --no-verify-ssl    Disable SSL certificate verification for TA API calls
  --verify-ssl       Re-enable SSL certificate verification for TA API calls
  --help             Show this help

Note: Use --password-file to avoid passing the password on the command line.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --type) require_arg "$1" $# || exit 1; ACCT_TYPE="$2"; shift 2 ;;
        --name) require_arg "$1" $# || exit 1; ACCT_NAME="$2"; shift 2 ;;
        --hostname) require_arg "$1" $# || exit 1; HOSTNAME="$2"; shift 2 ;;
        --port) require_arg "$1" $# || exit 1; PORT="$2"; shift 2 ;;
        --auth-type) require_arg "$1" $# || exit 1; AUTH_TYPE="$2"; shift 2 ;;
        --username) require_arg "$1" $# || exit 1; USERNAME="$2"; shift 2 ;;
        --password) require_arg "$1" $# || exit 1; echo "WARNING: --password exposes secrets in process listings. Prefer --password-file." >&2; PASSWORD="$2"; shift 2 ;;
        --password-file) require_arg "$1" $# || exit 1; PASSWORD=$(read_secret_file "$2"); shift 2 ;;
        --device-ip) require_arg "$1" $# || exit 1; DEVICE_IP="$2"; shift 2 ;;
        --login-domain) require_arg "$1" $# || exit 1; LOGIN_DOMAIN="$2"; shift 2 ;;
        --proxy-enabled) PROXY_ENABLED="1"; shift ;;
        --no-verify-ssl) SET_VERIFY_SSL="False"; shift ;;
        --verify-ssl) SET_VERIFY_SSL="True"; shift ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "${ACCT_TYPE}" || -z "${ACCT_NAME}" || -z "${USERNAME}" || -z "${PASSWORD}" ]]; then
    log "ERROR: --type, --name, --username, and --password (or --password-file) are required"
    exit 1
fi

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

if [[ -n "${SET_VERIFY_SSL}" ]]; then
    if rest_set_verify_ssl "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "cisco_dc_networking_app_for_splunk_settings" "additional_parameters" "${SET_VERIFY_SSL}" "verify_ssl"; then
        log "Set verify_ssl=${SET_VERIFY_SSL} in cisco_dc_networking_app_for_splunk_settings.conf."
    else
        log "ERROR: Failed to set verify_ssl in cisco_dc_networking_app_for_splunk_settings.conf."
        exit 1
    fi
fi

configure_aci_account() {
    if [[ -z "${HOSTNAME}" ]]; then
        log "ERROR: --hostname is required for ACI accounts"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/cisco_dc_networking_app_for_splunk_aci_account"
    log "Configuring ACI account '${ACCT_NAME}' via REST..."

    local create_body update_body http_code
    create_body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        apic_hostname "${HOSTNAME}" \
        apic_port "${PORT}" \
        apic_authentication_type "${AUTH_TYPE}" \
        apic_username "${USERNAME}" \
        apic_password "${PASSWORD}" \
        apic_proxy_enabled "${PROXY_ENABLED}") || exit 1
    update_body=$(form_urlencode_pairs \
        apic_hostname "${HOSTNAME}" \
        apic_port "${PORT}" \
        apic_authentication_type "${AUTH_TYPE}" \
        apic_username "${USERNAME}" \
        apic_password "${PASSWORD}" \
        apic_proxy_enabled "${PROXY_ENABLED}") || exit 1
    if [[ -n "${LOGIN_DOMAIN}" ]]; then
        local domain_pair
        domain_pair=$(form_urlencode_pairs apic_login_domain "${LOGIN_DOMAIN}")
        create_body="${create_body}&${domain_pair}"
        update_body="${update_body}&${domain_pair}"
    fi

    http_code=$(rest_create_or_update_account "${SK}" "${endpoint}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
    log "  SUCCESS: ACI account '${ACCT_NAME}' configured (HTTP ${http_code})"
}

configure_nd_account() {
    if [[ -z "${HOSTNAME}" ]]; then
        log "ERROR: --hostname is required for Nexus Dashboard accounts"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/cisco_dc_networking_app_for_splunk_nd_account"
    log "Configuring Nexus Dashboard account '${ACCT_NAME}' via REST..."

    local create_body update_body http_code
    create_body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        nd_hostname "${HOSTNAME}" \
        nd_port "${PORT}" \
        nd_authentication_type "${AUTH_TYPE}" \
        nd_username "${USERNAME}" \
        nd_password "${PASSWORD}" \
        nd_enable_proxy "${PROXY_ENABLED}") || exit 1
    update_body=$(form_urlencode_pairs \
        nd_hostname "${HOSTNAME}" \
        nd_port "${PORT}" \
        nd_authentication_type "${AUTH_TYPE}" \
        nd_username "${USERNAME}" \
        nd_password "${PASSWORD}" \
        nd_enable_proxy "${PROXY_ENABLED}") || exit 1
    if [[ -n "${LOGIN_DOMAIN}" ]]; then
        local domain_pair
        domain_pair=$(form_urlencode_pairs nd_login_domain "${LOGIN_DOMAIN}")
        create_body="${create_body}&${domain_pair}"
        update_body="${update_body}&${domain_pair}"
    fi

    http_code=$(rest_create_or_update_account "${SK}" "${endpoint}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
    log "  SUCCESS: Nexus Dashboard account '${ACCT_NAME}' configured (HTTP ${http_code})"
}

configure_nexus9k_account() {
    if [[ -z "${DEVICE_IP}" ]]; then
        log "ERROR: --device-ip is required for Nexus 9K accounts"
        exit 1
    fi

    local endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/cisco_dc_networking_app_for_splunk_nexus_9k_account"
    log "Configuring Nexus 9K account '${ACCT_NAME}' via REST..."

    local create_body update_body http_code
    create_body=$(form_urlencode_pairs \
        name "${ACCT_NAME}" \
        nexus_9k_device_ip "${DEVICE_IP}" \
        nexus_9k_port "${PORT}" \
        nexus_9k_username "${USERNAME}" \
        nexus_9k_password "${PASSWORD}" \
        nexus_9k_enable_proxy "${PROXY_ENABLED}") || exit 1
    update_body=$(form_urlencode_pairs \
        nexus_9k_device_ip "${DEVICE_IP}" \
        nexus_9k_port "${PORT}" \
        nexus_9k_username "${USERNAME}" \
        nexus_9k_password "${PASSWORD}" \
        nexus_9k_enable_proxy "${PROXY_ENABLED}") || exit 1

    http_code=$(rest_create_or_update_account "${SK}" "${endpoint}" "${ACCT_NAME}" "${create_body}" "${update_body}") || exit 1
    log "  SUCCESS: Nexus 9K account '${ACCT_NAME}' configured (HTTP ${http_code})"
}

case "${ACCT_TYPE}" in
    aci) configure_aci_account ;;
    nd) configure_nd_account ;;
    nexus9k) configure_nexus9k_account ;;
    *) log "ERROR: Unknown account type '${ACCT_TYPE}'. Use: aci, nd, nexus9k"; exit 1 ;;
esac

log "Account configuration complete."
log "$(log_platform_restart_guidance "account changes")"

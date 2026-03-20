#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco-cloud-security"
ORG_ID=""
BOOTSTRAP_ROLES=false
ACCEPT_TERMS=false
TERMS_VERSION="2.0.0"
TERMS_NAME=""
APPLY_DASHBOARD_DEFAULTS=false
SEARCH_INTERVAL=""
REFRESH_RATE=""
CLOUDLOCK_NAME=""
CLOUDLOCK_URL=""
CLOUDLOCK_TOKEN_FILE=""
CLOUDLOCK_START_DATE=""
CLOUDLOCK_INCIDENT_DETAILS="false"
CLOUDLOCK_UEBA="false"
CLEAR_DESTINATION_LISTS=false
DNS_INDEX=""
PROXY_INDEX=""
FIREWALL_INDEX=""
DLP_INDEX=""
RAVPN_INDEX=""
CREATE_INDEX=true
SK=""

DEST_LIST_IDS=()
DEST_LIST_NAMES=()
DEST_LIST_ROLES=()

usage() {
    cat <<EOF
Cisco Secure Access Settings Configuration

Usage: $(basename "$0") [OPTIONS]

Options:
  --org-id ID                    Organization ID for app settings updates
  --bootstrap-roles              Create the app's custom roles
  --accept-terms                 Insert the app's TOC acceptance record
  --terms-name NAME              Override the TOC acceptance user name
  --terms-version VERSION        TOC version (default: 2.0.0)
  --apply-dashboard-defaults     Set search_interval=12 and refresh_rate=0 unless explicitly overridden
  --search-interval HOURS        Dashboard search interval
  --refresh-rate VALUE           Dashboard refresh rate
  --cloudlock-name NAME          Cloudlock config name
  --cloudlock-url URL            Cloudlock URL
  --cloudlock-token-file PATH    File containing the Cloudlock token
  --cloudlock-start-date DD/MM/YYYY
                                 Cloudlock start date
  --cloudlock-incident-details true|false
                                 Whether to show incident details
  --cloudlock-ueba true|false    Whether to show UEBA
  --destination-list ID NAME ROLE
                                 Add one destination list selection (repeatable)
  --clear-destination-lists      Clear selected destination lists for the org
  --dns-index INDEX              DNS S3-backed index
  --proxy-index INDEX            Proxy S3-backed index
  --firewall-index INDEX         Firewall S3-backed index
  --dlp-index INDEX              DLP S3-backed index
  --ravpn-index INDEX            RA VPN S3-backed index
  --no-create-index              Do not auto-create supplied indexes
  --help                         Show this help
EOF
    exit 0
}

utc_now() {
    python3 - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M:%S"), end="")
PY
}

validate_cloudlock_date() {
    local value="$1"
    [[ -z "${value}" || "${value}" =~ ^[0-9]{2}/[0-9]{2}/[0-9]{4}$ ]]
}

update_settings_request() {
    local payload="$1"
    splunk_curl "${SK}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/update_settings" \
        -w '\n%{http_code}' 2>/dev/null || true
}

role_manager_request() {
    splunk_curl "${SK}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d '{}' \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/role_manager" \
        -w '\n%{http_code}' 2>/dev/null || true
}

toc_request() {
    local payload="$1"
    splunk_curl "${SK}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/toc_functionality" \
        -w '\n%{http_code}' 2>/dev/null || true
}

ensure_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

ensure_indexes() {
    local idx
    for idx in "${DNS_INDEX}" "${PROXY_INDEX}" "${FIREWALL_INDEX}" "${DLP_INDEX}" "${RAVPN_INDEX}"; do
        [[ -n "${idx}" ]] || continue
        if platform_create_index "${SK}" "${SPLUNK_URI}" "${idx}" "512000"; then
            log "Index '${idx}' created or already exists."
        else
            log "ERROR: Failed to create index '${idx}'."
            exit 1
        fi
    done
}

post_role_manager() {
    local response http_code body
    response="$(role_manager_request)"
    http_code="$(echo "${response}" | sed -n '$p')"
    body="$(echo "${response}" | sed '$d')"
    if [[ "${http_code}" != "200" ]]; then
        log "ERROR: Failed to bootstrap roles (HTTP ${http_code})."
        sanitize_response "${body}" 5 >&2 || true
        exit 1
    fi
    log "Bootstrapped Cisco Secure Access roles."
}

post_terms_acceptance() {
    local payload response http_code body actor
    actor="${TERMS_NAME:-${SPLUNK_USER}}"
    payload="$(python3 - "$actor" "${TERMS_VERSION}" <<'PY'
import json
import sys

print(json.dumps({
    "data": {
        "CustName": sys.argv[1],
        "CustVersion": sys.argv[2],
    }
}), end="")
PY
)"
    response="$(toc_request "${payload}")"
    http_code="$(echo "${response}" | sed -n '$p')"
    body="$(echo "${response}" | sed '$d')"
    if [[ "${http_code}" != "200" ]]; then
        log "ERROR: Failed to accept Secure Access terms (HTTP ${http_code})."
        sanitize_response "${body}" 5 >&2 || true
        exit 1
    fi
    log "Recorded Secure Access terms acceptance for ${actor}."
}

build_update_settings_payload() {
    local current_time cloudlock_token encoded_lists
    current_time="$(utc_now)"
    cloudlock_token=""
    if [[ -n "${CLOUDLOCK_TOKEN_FILE}" ]]; then
        cloudlock_token="$(read_secret_file "${CLOUDLOCK_TOKEN_FILE}")"
    fi

    encoded_lists=()
    for i in "${!DEST_LIST_IDS[@]}"; do
        encoded_lists+=("${DEST_LIST_IDS[$i]}" "${DEST_LIST_NAMES[$i]}" "${DEST_LIST_ROLES[$i]}")
    done

    python3 - "${ORG_ID}" "${current_time}" "${SEARCH_INTERVAL}" "${REFRESH_RATE}" \
        "${CLOUDLOCK_NAME}" "${CLOUDLOCK_URL}" "${cloudlock_token}" "${CLOUDLOCK_START_DATE}" \
        "${CLOUDLOCK_INCIDENT_DETAILS}" "${CLOUDLOCK_UEBA}" \
        "${DNS_INDEX}" "${PROXY_INDEX}" "${FIREWALL_INDEX}" "${DLP_INDEX}" "${RAVPN_INDEX}" \
        "${CLEAR_DESTINATION_LISTS}" "${SPLUNK_USER}" "${encoded_lists[@]}" <<'PY'
import json
import sys

(
    org_id,
    current_time,
    search_interval,
    refresh_rate,
    cloudlock_name,
    cloudlock_url,
    cloudlock_token,
    cloudlock_start_date,
    cloudlock_incident_details,
    cloudlock_ueba,
    dns_index,
    proxy_index,
    firewall_index,
    dlp_index,
    ravpn_index,
    clear_destination_lists,
    splunk_user,
    *dest_args,
) = sys.argv[1:]

payload = {}

if search_interval:
    payload["Dashboard"] = {"search_interval": search_interval}

if cloudlock_name or cloudlock_url or cloudlock_token or cloudlock_start_date:
    payload["cloudlock"] = {
        "userName": splunk_user,
        "createdDate": current_time,
        "configName": cloudlock_name,
        "url": cloudlock_url,
        "token": cloudlock_token,
        "showIncidentDetails": cloudlock_incident_details,
        "showUEBA": cloudlock_ueba,
        "cloudlock_start_date": cloudlock_start_date,
    }

if clear_destination_lists.lower() == "true":
    payload["selected_destination_lists"] = []
elif dest_args:
    rows = []
    for i in range(0, len(dest_args), 3):
        rows.append({
            "dest_list_id": dest_args[i],
            "dest_list_name": dest_args[i + 1],
            "role": dest_args[i + 2],
        })
    payload["selected_destination_lists"] = rows

s3_indexes = {}
if dns_index:
    s3_indexes["dns"] = dns_index
if proxy_index:
    s3_indexes["proxy"] = proxy_index
if firewall_index:
    s3_indexes["firewall"] = firewall_index
if dlp_index:
    s3_indexes["dlp"] = dlp_index
if ravpn_index:
    s3_indexes["ravpn"] = ravpn_index
if s3_indexes:
    s3_indexes["createdDate"] = current_time
    payload["s3_indexes"] = s3_indexes

if refresh_rate:
    payload["refresh_rate"] = refresh_rate

payload["orgId"] = org_id
print(json.dumps({"data": payload}), end="")
PY
}

post_update_settings() {
    local payload response http_code body
    payload="$(build_update_settings_payload)"
    response="$(update_settings_request "${payload}")"
    http_code="$(echo "${response}" | sed -n '$p')"
    body="$(echo "${response}" | sed '$d')"
    if [[ "${http_code}" != "200" ]]; then
        log "ERROR: Failed to update Secure Access app settings (HTTP ${http_code})."
        sanitize_response "${body}" 5 >&2 || true
        exit 1
    fi
    log "Updated Cisco Secure Access app settings for org '${ORG_ID}'."
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --org-id) require_arg "$1" $# || exit 1; ORG_ID="$2"; shift 2 ;;
        --bootstrap-roles) BOOTSTRAP_ROLES=true; shift ;;
        --accept-terms) ACCEPT_TERMS=true; shift ;;
        --terms-name) require_arg "$1" $# || exit 1; TERMS_NAME="$2"; shift 2 ;;
        --terms-version) require_arg "$1" $# || exit 1; TERMS_VERSION="$2"; shift 2 ;;
        --apply-dashboard-defaults) APPLY_DASHBOARD_DEFAULTS=true; shift ;;
        --search-interval) require_arg "$1" $# || exit 1; SEARCH_INTERVAL="$2"; shift 2 ;;
        --refresh-rate) require_arg "$1" $# || exit 1; REFRESH_RATE="$2"; shift 2 ;;
        --cloudlock-name) require_arg "$1" $# || exit 1; CLOUDLOCK_NAME="$2"; shift 2 ;;
        --cloudlock-url) require_arg "$1" $# || exit 1; CLOUDLOCK_URL="$2"; shift 2 ;;
        --cloudlock-token-file) require_arg "$1" $# || exit 1; CLOUDLOCK_TOKEN_FILE="$2"; shift 2 ;;
        --cloudlock-start-date) require_arg "$1" $# || exit 1; CLOUDLOCK_START_DATE="$2"; shift 2 ;;
        --cloudlock-incident-details) require_arg "$1" $# || exit 1; CLOUDLOCK_INCIDENT_DETAILS="$2"; shift 2 ;;
        --cloudlock-ueba) require_arg "$1" $# || exit 1; CLOUDLOCK_UEBA="$2"; shift 2 ;;
        --destination-list)
            if [[ $# -lt 4 ]]; then
                log "ERROR: Option '--destination-list' requires ID, NAME, and ROLE."
                exit 1
            fi
            DEST_LIST_IDS+=("$2")
            DEST_LIST_NAMES+=("$3")
            DEST_LIST_ROLES+=("$4")
            shift 4
            ;;
        --clear-destination-lists) CLEAR_DESTINATION_LISTS=true; shift ;;
        --dns-index) require_arg "$1" $# || exit 1; DNS_INDEX="$2"; shift 2 ;;
        --proxy-index) require_arg "$1" $# || exit 1; PROXY_INDEX="$2"; shift 2 ;;
        --firewall-index) require_arg "$1" $# || exit 1; FIREWALL_INDEX="$2"; shift 2 ;;
        --dlp-index) require_arg "$1" $# || exit 1; DLP_INDEX="$2"; shift 2 ;;
        --ravpn-index) require_arg "$1" $# || exit 1; RAVPN_INDEX="$2"; shift 2 ;;
        --no-create-index) CREATE_INDEX=false; shift ;;
        --help) usage ;;
        *) log "Unknown option: $1"; usage ;;
    esac
done

case "${CLOUDLOCK_INCIDENT_DETAILS}" in
    true|false) ;;
    *) log "ERROR: --cloudlock-incident-details must be true or false."; exit 1 ;;
esac
case "${CLOUDLOCK_UEBA}" in
    true|false) ;;
    *) log "ERROR: --cloudlock-ueba must be true or false."; exit 1 ;;
esac
validate_cloudlock_date "${CLOUDLOCK_START_DATE}" || {
    log "ERROR: --cloudlock-start-date must use DD/MM/YYYY."
    exit 1
}

if ${APPLY_DASHBOARD_DEFAULTS}; then
    [[ -n "${SEARCH_INTERVAL}" ]] || SEARCH_INTERVAL="12"
    [[ -n "${REFRESH_RATE}" ]] || REFRESH_RATE="0"
fi

needs_update_settings=false
if [[ -n "${SEARCH_INTERVAL}" || -n "${REFRESH_RATE}" || -n "${CLOUDLOCK_NAME}" || -n "${CLOUDLOCK_URL}" || -n "${CLOUDLOCK_TOKEN_FILE}" || -n "${CLOUDLOCK_START_DATE}" || "${CLEAR_DESTINATION_LISTS}" == "true" || ${#DEST_LIST_IDS[@]} -gt 0 || -n "${DNS_INDEX}" || -n "${PROXY_INDEX}" || -n "${FIREWALL_INDEX}" || -n "${DLP_INDEX}" || -n "${RAVPN_INDEX}" ]]; then
    needs_update_settings=true
fi

if ${needs_update_settings}; then
    [[ -n "${ORG_ID}" ]] || {
        log "ERROR: --org-id is required when applying Secure Access app settings."
        exit 1
    }
fi

if [[ -n "${CLOUDLOCK_NAME}" || -n "${CLOUDLOCK_URL}" || -n "${CLOUDLOCK_TOKEN_FILE}" || -n "${CLOUDLOCK_START_DATE}" ]]; then
    [[ -n "${CLOUDLOCK_NAME}" && -n "${CLOUDLOCK_URL}" && -n "${CLOUDLOCK_TOKEN_FILE}" && -n "${CLOUDLOCK_START_DATE}" ]] || {
        log "ERROR: Cloudlock settings require --cloudlock-name, --cloudlock-url, --cloudlock-token-file, and --cloudlock-start-date together."
        exit 1
    }
fi

ensure_session
if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null; then
    log "ERROR: ${APP_NAME} is not installed. Install Cisco Secure Access first."
    exit 1
fi

if ${CREATE_INDEX}; then
    ensure_indexes
fi
if ${BOOTSTRAP_ROLES}; then
    post_role_manager
fi
if ${ACCEPT_TERMS}; then
    post_terms_acceptance
fi
if ${needs_update_settings}; then
    post_update_settings
fi

if ! ${BOOTSTRAP_ROLES} && ! ${ACCEPT_TERMS} && ! ${needs_update_settings}; then
    log "ERROR: No action requested. Use --bootstrap-roles, --accept-terms, and/or settings flags."
    exit 1
fi

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="ta_cisco_thousandeyes"
POLL_INTERVAL=5
POLL_TIMEOUT=300
THOUSANDEYES_BASE_URL="https://api.thousandeyes.com/v7"
THOUSANDEYES_DEVICE_AUTH_URL="${THOUSANDEYES_BASE_URL}/oauth2/device/authorization"
THOUSANDEYES_TOKEN_URL="${THOUSANDEYES_BASE_URL}/oauth2/token"
THOUSANDEYES_CURRENT_USER_URL="${THOUSANDEYES_BASE_URL}/users/current"
THOUSANDEYES_CLIENT_ID="0oalgciz1dyS1Uonr697"
THOUSANDEYES_AUTH_SCOPE="organization:read offline_access tests:read endpoint-tests:read streams:manage alerts:manage tags:read integrations:manage"
THOUSANDEYES_DEVICE_GRANT_TYPE="urn:ietf:params:oauth:grant-type:device_code"

usage() {
    cat <<EOF
Authenticate a ThousandEyes account via OAuth 2.0 Device Code Flow.

Usage: $(basename "$0") [OPTIONS]

This script initiates an OAuth device code flow. You will be shown a
verification URL and a user code. Visit the URL in your browser and enter
the code to authorize. The script polls until authorization completes.

Options:
  --poll-interval SECS   Seconds between token polls (default: 5)
  --poll-timeout SECS    Max seconds to wait for authorization (default: 300)
  --help                 Show this help

No password or API key files are needed — the OAuth flow handles authentication.

Splunk credentials are read from the project-root credentials file (falls back
to ~/.splunk/credentials) automatically.
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --poll-interval) POLL_INTERVAL="$2"; shift 2 ;;
        --poll-timeout) POLL_TIMEOUT="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

post_external_form() {
    local url="$1" body="$2"
    printf '%s' "${body}" | curl -sS \
        "${url}" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        --connect-timeout 10 \
        --max-time 120 \
        -d @- \
        -w '\n%{http_code}'
}

get_external_json() {
    local url="$1" bearer_token="$2"
    curl -sS \
        "${url}" \
        -H "Authorization: Bearer ${bearer_token}" \
        --connect-timeout 10 \
        --max-time 120 \
        -w '\n%{http_code}'
}

parse_device_authorization_response() {
    printf '%s' "$1" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and ('entry' in item or 'device_code' in item):
                data = item
                break
    entries = data.get('entry', [data] if isinstance(data, dict) and 'device_code' in data else [])
    if entries:
        content = entries[0].get('content', entries[0]) if isinstance(entries[0], dict) else {}
        dc = content.get('device_code', '')
        uc = content.get('user_code', '')
        vu = content.get('verification_uri_complete') or content.get('verification_url') or content.get('verification_uri', '')
        print(f'device_code={dc!r}')
        print(f'user_code={uc!r}')
        print(f'verification_url={vu!r}')
except Exception:
    print('device_code=\"\"')
    print('user_code=\"\"')
    print('verification_url=\"\"')
" 2>/dev/null
}

parse_token_success_response() {
    printf '%s' "$1" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(f'access_token={data.get(\"access_token\", \"\")!r}')
    print(f'refresh_token={data.get(\"refresh_token\", \"\")!r}')
except Exception:
    print('access_token=\"\"')
    print('refresh_token=\"\"')
" 2>/dev/null
}

parse_token_error_response() {
    printf '%s' "$1" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(f'oauth_error={data.get(\"error\", \"\")!r}')
    print(f'oauth_error_description={data.get(\"error_description\", \"\")!r}')
except Exception:
    print('oauth_error=\"\"')
    print('oauth_error_description=\"\"')
" 2>/dev/null
}

parse_current_user_email() {
    printf '%s' "$1" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('email', ''), end='')
except Exception:
    pass
" 2>/dev/null
}

request_device_authorization_via_app() {
    local resp http_code resp_body
    resp=$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/authorize" \
        -w '\n%{http_code}' 2>/dev/null || true)
    http_code=$(echo "${resp}" | tail -1)
    resp_body=$(printf '%s\n' "${resp}" | sed '$d')

    case "${http_code}" in
        200|201) printf '%s' "${resp_body}" ;;
        *) return 1 ;;
    esac
}

request_device_authorization_direct() {
    local auth_body resp http_code resp_body
    auth_body=$(form_urlencode_pairs \
        client_id "${THOUSANDEYES_CLIENT_ID}" \
        scope "${THOUSANDEYES_AUTH_SCOPE}") || return 1
    resp=$(post_external_form "${THOUSANDEYES_DEVICE_AUTH_URL}" "${auth_body}" 2>/dev/null || true)
    http_code=$(echo "${resp}" | tail -1)
    resp_body=$(printf '%s\n' "${resp}" | sed '$d')

    case "${http_code}" in
        200|201) printf '%s' "${resp_body}" ;;
        *) return 1 ;;
    esac
}

poll_for_oauth_tokens() {
    local waited=0 auth_success=false poll_interval="${POLL_INTERVAL}"
    local token_body token_response token_http_code token_resp_body
    local oauth_error="" oauth_error_description=""
    access_token=""
    refresh_token=""

    while (( waited < POLL_TIMEOUT )); do
        sleep "${poll_interval}"
        waited=$((waited + poll_interval))

        token_body=$(form_urlencode_pairs \
            client_id "${THOUSANDEYES_CLIENT_ID}" \
            device_code "${device_code}" \
            grant_type "${THOUSANDEYES_DEVICE_GRANT_TYPE}") || continue
        token_response=$(post_external_form "${THOUSANDEYES_TOKEN_URL}" "${token_body}" 2>/dev/null || true)
        token_http_code=$(echo "${token_response}" | tail -1)
        token_resp_body=$(printf '%s\n' "${token_response}" | sed '$d')

        case "${token_http_code}" in
            200|201)
                eval "$(parse_token_success_response "${token_resp_body}")"
                if [[ -n "${access_token}" && -n "${refresh_token}" ]]; then
                    auth_success=true
                    break
                fi
                ;;
            400)
                eval "$(parse_token_error_response "${token_resp_body}")"
                case "${oauth_error}" in
                    authorization_pending|"")
                        ;;
                    slow_down)
                        poll_interval=$((poll_interval + 5))
                        ;;
                    access_denied|expired_token|invalid_grant)
                        log "ERROR: ${oauth_error_description:-${oauth_error}}"
                        exit 1
                        ;;
                    *)
                        log "ERROR: ${oauth_error_description:-OAuth token request failed.}"
                        exit 1
                        ;;
                esac
                ;;
            500|502|503|504)
                ;;
            *)
                log "ERROR: OAuth token request failed (HTTP ${token_http_code})"
                sanitize_response "${token_resp_body}" 5
                exit 1
                ;;
        esac

        if (( waited % 30 == 0 )); then
            log "  Still waiting... (${waited}s / ${POLL_TIMEOUT}s)"
        fi
    done

    ${auth_success}
}

fetch_current_user_email() {
    local user_response user_http_code user_resp_body
    user_response=$(get_external_json "${THOUSANDEYES_CURRENT_USER_URL}" "${access_token}" 2>/dev/null || true)
    user_http_code=$(echo "${user_response}" | tail -1)
    user_resp_body=$(printf '%s\n' "${user_response}" | sed '$d')

    case "${user_http_code}" in
        200|201)
            account_email="$(parse_current_user_email "${user_resp_body}")"
            [[ -n "${account_email}" ]]
            ;;
        *)
            log "ERROR: Failed to fetch ThousandEyes user details (HTTP ${user_http_code})"
            sanitize_response "${user_resp_body}" 5
            return 1
            ;;
    esac
}

store_oauth_account() {
    local endpoint create_body update_body
    endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/ta_cisco_thousandeyes_account"
    create_body=$(form_urlencode_pairs \
        name "${account_email}" \
        access_token "${access_token}" \
        refresh_token "${refresh_token}" \
        device_code "${device_code}" \
        user_code "${user_code}" \
        verification_url "${verification_url}" \
        code "0") || return 1
    update_body=$(form_urlencode_pairs \
        access_token "${access_token}" \
        refresh_token "${refresh_token}" \
        device_code "${device_code}" \
        user_code "${user_code}" \
        verification_url "${verification_url}" \
        code "0") || return 1

    rest_create_or_update_account "${SK}" "${endpoint}" "${account_email}" "${create_body}" "${update_body}" >/dev/null
}

load_splunk_credentials
prefer_current_cloud_search_api_uri

SK=$(get_session_key "${SPLUNK_URI}")

log "Authenticated to Splunk REST API."

if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
    log "ERROR: ThousandEyes app (${APP_NAME}) is not installed."
    exit 1
fi

log "Initiating ThousandEyes OAuth device code flow..."
log ""

authorize_body="$(request_device_authorization_via_app 2>/dev/null || true)"
if [[ -z "${authorize_body}" ]]; then
    authorize_body="$(request_device_authorization_direct 2>/dev/null || true)"
fi

if [[ -z "${authorize_body}" ]]; then
    log "ERROR: OAuth authorization request failed."
    exit 1
fi

device_code=""
user_code=""
verification_url=""
eval "$(parse_device_authorization_response "${authorize_body}")"

if [[ -z "${verification_url}" || -z "${user_code}" ]]; then
    log "ERROR: Could not parse OAuth authorization response."
    log "Raw response (sanitized):"
    sanitize_response "${authorize_body}" 10
    exit 1
fi

log "=============================================="
log "  ThousandEyes OAuth Authorization Required"
log "=============================================="
log ""
log "  1. Open this URL in your browser:"
log ""
log "     ${verification_url}"
log ""
log "  2. Enter this code when prompted:"
log ""
log "     ${user_code}"
log ""
log "=============================================="
log ""
log "Waiting for authorization (timeout: ${POLL_TIMEOUT}s)..."

if ! poll_for_oauth_tokens; then
    log "ERROR: OAuth authorization timed out after ${POLL_TIMEOUT}s."
    log "The user did not complete the browser authorization in time."
    exit 1
fi

log ""
log "SUCCESS: ThousandEyes OAuth authorization completed."

account_email=""
if ! fetch_current_user_email; then
    log "ERROR: OAuth succeeded but the authenticated ThousandEyes user could not be resolved."
    exit 1
fi

if ! store_oauth_account; then
    log "ERROR: Failed to store ThousandEyes account credentials in Splunk."
    exit 1
fi

if [[ -n "${account_email}" ]]; then
    log "Account registered as: ${account_email}"
else
    log "Account tokens stored. Check the app's Configuration page for the account name."
fi

log ""
log "Next steps:"
log "  1. Run setup.sh --enable-inputs to configure data collection"
log "  2. Run validate.sh to verify the deployment"

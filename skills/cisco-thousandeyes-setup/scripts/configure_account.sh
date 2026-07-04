#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_curl_helpers.sh"

APP_NAME="ta_cisco_thousandeyes"
POLL_INTERVAL=5
POLL_TIMEOUT=300
ACCOUNT_OUTPUT_FILE=""
THOUSANDEYES_BASE_URL="https://api.thousandeyes.com/v7"
THOUSANDEYES_DEVICE_AUTH_URL="${THOUSANDEYES_BASE_URL}/oauth2/device/authorization"
THOUSANDEYES_TOKEN_URL="${THOUSANDEYES_BASE_URL}/oauth2/token"
THOUSANDEYES_CURRENT_USER_URL="${THOUSANDEYES_BASE_URL}/users/current"
THOUSANDEYES_CLIENT_ID="0oalgciz1dyS1Uonr697"
THOUSANDEYES_AUTH_SCOPE="organization:read offline_access tests:read endpoint-tests:read streams:manage alerts:manage tags:read integrations:manage"
THOUSANDEYES_DEVICE_GRANT_TYPE="urn:ietf:params:oauth:grant-type:device_code"
# Parse multiple fields from untrusted JSON without using eval.
PARSE_FIELD_SEP=$'\x1f'

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
  --account-output-file FILE
                         Write the resolved account email to FILE
  --help                 Show this help

No password or API key files are needed — the OAuth flow handles authentication.

Splunk credentials are read from the project-root credentials file (falls back
to ~/.splunk/credentials) automatically.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --poll-interval) require_arg "$1" $# || exit 1; POLL_INTERVAL="$2"; shift 2 ;;
        --poll-timeout) require_arg "$1" $# || exit 1; POLL_TIMEOUT="$2"; shift 2 ;;
        --account-output-file) require_arg "$1" $# || exit 1; ACCOUNT_OUTPUT_FILE="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ ! "${POLL_INTERVAL}" =~ ^[0-9]+$ ]]; then
    log "ERROR: --poll-interval must be a decimal integer." >&2
    exit 2
fi
if [[ ! "${POLL_TIMEOUT}" =~ ^[0-9]+$ ]]; then
    log "ERROR: --poll-timeout must be a decimal integer." >&2
    exit 2
fi
POLL_INTERVAL=$((10#${POLL_INTERVAL}))
POLL_TIMEOUT=$((10#${POLL_TIMEOUT}))
if (( POLL_INTERVAL < 1 || POLL_INTERVAL > 300 )); then
    log "ERROR: --poll-interval must be between 1 and 300 seconds." >&2
    exit 2
fi
if (( POLL_TIMEOUT < POLL_INTERVAL || POLL_TIMEOUT > 3600 )); then
    log "ERROR: --poll-timeout must be at least the poll interval and no more than 3600 seconds." >&2
    exit 2
fi

write_account_output_file() {
    local destination="$1" value="$2"
    printf '%s\n' "${value}" | python3 /dev/fd/3 "${destination}" 3<<'PY'
import os
import stat
import sys
from pathlib import Path

destination = Path(os.path.abspath(sys.argv[1]))
payload = sys.stdin.buffer.read(4097)
if (
    len(payload) > 4096
    or not payload
    or b"\x00" in payload
    or b"\r" in payload
    or payload.count(b"\n") != 1
    or not payload.endswith(b"\n")
):
    raise SystemExit("ERROR: resolved account email is not a safe single-line value")
if not destination.name or destination.name in {".", ".."} or not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("ERROR: --account-output-file is invalid")

parent = destination.parent
flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
if sys.platform == "darwin" and len(parent.parts) > 1 and parent.parts[1] in {"tmp", "var"}:
    alias = Path("/") / parent.parts[1]
    try:
        alias_info = alias.lstat()
        target = alias.resolve(strict=True)
    except OSError:
        pass
    else:
        if (
            stat.S_ISLNK(alias_info.st_mode)
            and alias_info.st_uid == 0
            and target.parts[:2] == ("/", "private")
        ):
            parent = target.joinpath(*parent.parts[2:])

parent_fd = os.open("/", flags)
try:
    for component in parent.parts[1:]:
        child_fd = os.open(component, flags, dir_fd=parent_fd)
        os.close(parent_fd)
        parent_fd = child_fd
    read_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        existing_fd = os.open(destination.name, read_flags, dir_fd=parent_fd)
    except FileNotFoundError:
        existing_fd = None
    if existing_fd is not None:
        try:
            existing = os.fstat(existing_fd)
            if (
                not stat.S_ISREG(existing.st_mode)
                or existing.st_nlink != 1
                or stat.S_IMODE(existing.st_mode) != 0o600
            ):
                raise SystemExit("ERROR: --account-output-file destination is unsafe")
        finally:
            os.close(existing_fd)
    temporary = f".{destination.name}.{os.getpid()}.{os.urandom(16).hex()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=parent_fd,
    )
    created = True
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SystemExit("ERROR: short account output write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, destination.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        created = False
        os.fsync(parent_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if created:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
finally:
    os.close(parent_fd)
PY
}

post_external_form() {
    local url="$1" body="$2"
    if ! credential_curl_validate_request_args false "${url}"; then
        log "ERROR: ThousandEyes OAuth request rejected by credential transport policy."
        return 1
    fi
    printf '%s' "${body}" | curl -q -sS \
        "${url}" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        --connect-timeout 10 \
        --max-time 120 \
        -d @- \
        -w '\n%{http_code}' \
        "${CREDENTIAL_CURL_TRANSPORT_ARGS[@]}"
}

get_external_json() {
    local url="$1" bearer_token="$2"
    local auth_config response curl_rc restore_errexit=false

    if ! credential_curl_validate_request_args false "${url}"; then
        log "ERROR: ThousandEyes API request rejected by credential transport policy."
        return 1
    fi
    # shellcheck disable=SC1003  # single-quoted backslash pattern is intentional.
    if [[ -z "${bearer_token}" || "${bearer_token}" == *$'\n'* || "${bearer_token}" == *$'\r'* || "${bearer_token}" == *'"'* || "${bearer_token}" == *'\'* ]]; then
        log "ERROR: ThousandEyes bearer token was not a curl-config-safe single line."
        return 1
    fi

    auth_config="$(mktemp)"
    chmod 600 "${auth_config}"
    hbs_append_cleanup_trap "rm -f $(printf '%q' "${auth_config}") 2>/dev/null || true" EXIT INT TERM
    printf 'header = "Authorization: Bearer %s"\n' "${bearer_token}" > "${auth_config}"
    if ! credential_curl_validate_auth_config "${auth_config}"; then
        rm -f "${auth_config}"
        log "ERROR: ThousandEyes bearer auth config failed validation."
        return 1
    fi

    case $- in
        *e*)
            restore_errexit=true
            set +e
            ;;
    esac
    response=$(curl -q -sS \
        "${url}" \
        -K "${auth_config}" \
        --connect-timeout 10 \
        --max-time 120 \
        -w '\n%{http_code}' \
        "${CREDENTIAL_CURL_TRANSPORT_ARGS[@]}")
    curl_rc=$?
    if [[ "${restore_errexit}" == "true" ]]; then
        set -e
    fi

    rm -f "${auth_config}"
    printf '%s' "${response}"
    return "${curl_rc}"
}

parse_device_authorization_response() {
    printf '%s' "$1" | python3 -c "
import json, sys
sep = '\x1f'
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
        dc = str(content.get('device_code', '') or '')
        uc = str(content.get('user_code', '') or '')
        vu = str(content.get('verification_uri_complete') or content.get('verification_url') or content.get('verification_uri') or '')
        print(sep.join((dc, uc, vu)), end='')
    else:
        print(sep.join(('', '', '')), end='')
except Exception:
    print(sep.join(('', '', '')), end='')
" 2>/dev/null
}

parse_token_success_response() {
    printf '%s' "$1" | python3 -c "
import json, sys
sep = '\x1f'
try:
    data = json.load(sys.stdin)
    print(sep.join((str(data.get('access_token', '') or ''), str(data.get('refresh_token', '') or ''))), end='')
except Exception:
    print(sep.join(('', '')), end='')
" 2>/dev/null
}

parse_token_error_response() {
    printf '%s' "$1" | python3 -c "
import json, sys
sep = '\x1f'
try:
    data = json.load(sys.stdin)
    print(sep.join((str(data.get('error', '') or ''), str(data.get('error_description', '') or ''))), end='')
except Exception:
    print(sep.join(('', '')), end='')
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
                IFS="${PARSE_FIELD_SEP}" read -r access_token refresh_token <<< "$(parse_token_success_response "${token_resp_body}")"
                if [[ -n "${access_token}" && -n "${refresh_token}" ]]; then
                    auth_success=true
                    break
                fi
                ;;
            400)
                IFS="${PARSE_FIELD_SEP}" read -r oauth_error oauth_error_description <<< "$(parse_token_error_response "${token_resp_body}")"
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

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }

SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

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
IFS="${PARSE_FIELD_SEP}" read -r device_code user_code verification_url <<< "$(parse_device_authorization_response "${authorize_body}")"

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

if [[ -n "${ACCOUNT_OUTPUT_FILE}" && -n "${account_email}" ]]; then
    write_account_output_file "${ACCOUNT_OUTPUT_FILE}" "${account_email}"
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

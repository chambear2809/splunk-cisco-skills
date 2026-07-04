#!/usr/bin/env bash
# Test Splunkbase (splunk.com) connection using credentials from project credentials file.
# Run from project root: bash skills/shared/scripts/test_splunkbase_connection.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CRED_FILE="${PROJECT_ROOT}/credentials"

if [[ ! -f "${CRED_FILE}" ]]; then
    echo "ERROR: Credentials file not found: ${CRED_FILE}" >&2
    exit 1
fi

echo "Using credentials from: ${CRED_FILE}"
source "${SCRIPT_DIR}/../lib/credential_helpers.sh"

echo "Loading Splunkbase credentials..."
if ! load_splunkbase_credentials; then
    echo "FAIL: Could not load Splunkbase credentials." >&2
    exit 1
fi

echo "Authenticating to Splunkbase (splunkbase.splunk.com)..."
if ! get_splunkbase_session; then
    echo "FAIL: Splunkbase authentication failed. Check SB_USER/SB_PASS in credentials." >&2
    # Debug: show what the session API returned (redacted)
    if [[ -n "${DEBUG_SPLUNKBASE:-}" ]]; then
        _set_splunkbase_curl_tls_args || exit 1
        credential_curl_prepare_transport false
        response_file="$(mktemp)"
        chmod 600 "${response_file}"
        hbs_append_cleanup_trap "rm -f $(printf '%q' "${response_file}") 2>/dev/null || true" EXIT INT TERM
        # shellcheck disable=SC2154  # _tls_verify_args is populated by _set_splunkbase_curl_tls_args.
        http_code=$(curl -q -s --connect-timeout 30 --max-time 120 \
            ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} \
            -X POST "https://splunkbase.splunk.com/api/account:login" \
            -K <(
                printf 'form-string = "username=%s"\n' "$(_curl_config_escape "${SB_USER}")"
                printf 'form-string = "password=%s"\n' "$(_curl_config_escape "${SB_PASS}")"
            ) \
            -o "${response_file}" \
            -w '%{http_code}' \
            "${CREDENTIAL_CURL_TRANSPORT_ARGS[@]}" 2>/dev/null || echo "000")
        echo "DEBUG: Sanitized Session API response (HTTP ${http_code}, first 8192 input bytes):" >&2
        debug_response="$(head -c 8192 "${response_file}")"
        sanitize_response "${debug_response}" 5 >&2 || true
        debug_response=""
        rm -f "${response_file}"
    fi
    exit 1
fi

echo "OK: Splunkbase connection successful."
echo "  (session obtained; ready for Splunkbase downloads)"

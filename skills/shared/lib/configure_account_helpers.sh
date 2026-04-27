#!/usr/bin/env bash
# Shared helper for TA account creation/update via custom REST handlers.
# Provides rest_create_or_update_account() to eliminate the duplicated
# create/409-update pattern across configure_account.sh scripts.
#
# See credential_helpers.sh for the sourcing contract.

[[ -n "${_CONFIGURE_ACCOUNT_HELPERS_LOADED:-}" ]] && return 0
_CONFIGURE_ACCOUNT_HELPERS_LOADED=true

# Create or update a TA account stanza via a custom REST handler.
#
# Usage:
#   rest_create_or_update_account <session_key> <endpoint_url> <account_name> <create_body> <update_body>
#
# - endpoint_url: full URL to the custom REST handler (without trailing slash)
# - account_name: the stanza name (URL-encoded automatically)
# - create_body: form-urlencoded body for the initial POST (must include name=)
# - update_body: form-urlencoded body for the update POST (without name=)
#
# All POSTs include ?output_mode=json to satisfy UCC handler requirements.
#
# Returns 0 on success; prints the HTTP code to stdout for the caller to log.
# Returns 1 on failure.
rest_create_or_update_account() {
    local sk="$1"
    local endpoint="$2"
    local acct_name="$3"
    local create_body="$4"
    local update_body="$5"

    local http_code resp curl_rc enc_name
    enc_name=$(_urlencode "${acct_name}")

    # Capture both curl's exit status and the trailing HTTP code so transport
    # failures (DNS, TLS, connection refused) can be distinguished from
    # legitimate-but-error HTTP responses. A bare `tail -1` on garbage output
    # would otherwise yield a fake "HTTP code" and mislead the caller.
    resp=$(splunk_curl_post "${sk}" \
        "${create_body}" \
        "${endpoint}?output_mode=json" -w '\n%{http_code}' 2>/dev/null)
    curl_rc=$?
    http_code=$(echo "${resp}" | tail -1)

    if [[ "${curl_rc}" -ne 0 ]] || ! [[ "${http_code}" =~ ^[0-9]{3}$ ]]; then
        echo "ERROR: Create account failed (curl exit ${curl_rc}, transport or TLS failure; reported HTTP '${http_code:-empty}')." >&2
        echo "Verify the management URL, TLS settings, and Splunk reachability before retrying." >&2
        return 1
    fi

    case "${http_code}" in
        201|200)
            printf '%s' "${http_code}"
            return 0
            ;;
        409|400)
            if [[ "${http_code}" == "400" ]]; then
                local resp_body
                resp_body=$(printf '%s\n' "${resp}" | sed '$d')
                if ! echo "${resp_body}" | grep -qi 'Conflict\|already exists'; then
                    echo "ERROR: Create account failed (HTTP ${http_code})" >&2
                    sanitize_response "${resp}" 5 >&2
                    return 1
                fi
            fi
            resp=$(splunk_curl_post "${sk}" \
                "${update_body}" \
                "${endpoint}/${enc_name}?output_mode=json" -w '\n%{http_code}' 2>/dev/null)
            curl_rc=$?
            http_code=$(echo "${resp}" | tail -1)
            if [[ "${curl_rc}" -ne 0 ]] || ! [[ "${http_code}" =~ ^[0-9]{3}$ ]]; then
                echo "ERROR: Update account failed (curl exit ${curl_rc}, transport or TLS failure; reported HTTP '${http_code:-empty}')." >&2
                return 1
            fi
            case "${http_code}" in
                200|201)
                    printf '%s' "${http_code}"
                    return 0
                    ;;
                *)
                    echo "ERROR: Update account failed (HTTP ${http_code})" >&2
                    sanitize_response "${resp}" 5 >&2
                    return 1
                    ;;
            esac
            ;;
        *)
            echo "ERROR: Create account failed (HTTP ${http_code})" >&2
            sanitize_response "${resp}" 5 >&2
            return 1
            ;;
    esac
}

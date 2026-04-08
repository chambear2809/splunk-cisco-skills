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

    local http_code resp enc_name
    enc_name=$(_urlencode "${acct_name}")

    resp=$(splunk_curl_post "${sk}" \
        "${create_body}" \
        "${endpoint}?output_mode=json" -w '\n%{http_code}' 2>/dev/null)
    http_code=$(_extract_http_code "${resp}")

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
            http_code=$(_extract_http_code "${resp}")
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

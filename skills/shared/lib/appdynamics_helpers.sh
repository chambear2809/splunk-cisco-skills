#!/usr/bin/env bash
# Shared guardrails and small helpers for Splunk AppDynamics skills.
#
# These helpers intentionally prefer file-backed credentials. They should be
# sourced by AppDynamics setup scripts before argument parsing completes.

set -euo pipefail

appd_reject_direct_secret_args() {
    local arg
    for arg in "$@"; do
        case "${arg}" in
            --password|--password=*|--pass|--pass=*|--secret|--secret=*|--client-secret|--client-secret=*|--api-key|--api-key=*|--token|--token=*|--access-token|--access-token=*|--events-api-key|--events-api-key=*|--controller-password|--controller-password=*)
                cat >&2 <<'EOF'
Refusing direct-secret CLI input. Use a chmod-600 secret file instead:
  --token-file PATH
  --password-file PATH
  --client-secret-file PATH
  --events-api-key-file PATH

Create local-only secret files with:
  bash skills/shared/scripts/write_secret_file.sh PATH
EOF
                return 2
                ;;
        esac
    done
}

appd_file_mode_octal() {
    local path="$1"
    python3 - "${path}" <<'PY'
import os
import stat
import sys

print(format(stat.S_IMODE(os.stat(sys.argv[1]).st_mode), "03o"))
PY
}

appd_assert_secret_file() {
    local path="$1"
    local label="${2:-secret file}"
    if [[ -z "${path}" ]]; then
        return 0
    fi
    if [[ ! -f "${path}" ]]; then
        echo "FAIL: ${label} does not exist: ${path}" >&2
        return 2
    fi
    if [[ ! -s "${path}" ]]; then
        echo "FAIL: ${label} is empty: ${path}" >&2
        return 2
    fi
    local mode
    mode="$(appd_file_mode_octal "${path}")"
    if [[ "${mode}" != "600" ]]; then
        echo "FAIL: ${label} must be chmod 600; found ${mode}: ${path}" >&2
        return 2
    fi
}

appd_controller_api_url() {
    local controller_url="$1"
    local path="$2"
    printf "%s/%s\n" "${controller_url%/}" "${path#/}"
}

appd_json_result() {
    local status="$1"
    local message="$2"
    python3 - "${status}" "${message}" <<'PY'
import json
import sys

print(json.dumps({"status": sys.argv[1], "message": sys.argv[2]}, sort_keys=True))
PY
}

APPD_CURL_TLS_ARGS=()
_APPD_WARNED_INSECURE_TLS=0

appd_prepare_curl_tls_args() {
    APPD_CURL_TLS_ARGS=()

    if [[ -n "${APPD_CA_CERT:-}" ]]; then
        if [[ ! -f "${APPD_CA_CERT}" ]]; then
            echo "FAIL: APPD_CA_CERT does not exist: ${APPD_CA_CERT}" >&2
            return 2
        fi
        APPD_CURL_TLS_ARGS=(--cacert "${APPD_CA_CERT}")
        return 0
    fi

    case "${APPD_VERIFY_SSL:-true}" in
        false|False|FALSE|0|no|No|NO|off|Off|OFF)
            if [[ "${_APPD_WARNED_INSECURE_TLS}" != "1" ]]; then
                echo "WARN: TLS verification is disabled for AppDynamics API calls (APPD_VERIFY_SSL=false). Prefer APPD_CA_CERT=/path/to/ca.pem for self-signed lab controllers." >&2
                _APPD_WARNED_INSECURE_TLS=1
            fi
            APPD_CURL_TLS_ARGS=(-k)
            ;;
        true|True|TRUE|1|yes|Yes|YES|on|On|ON|"")
            ;;
        *)
            echo "FAIL: APPD_VERIFY_SSL must be true or false; got '${APPD_VERIFY_SSL}'" >&2
            return 2
            ;;
    esac
}

appd_curl() {
    appd_prepare_curl_tls_args || return $?
    curl "${APPD_CURL_TLS_ARGS[@]}" "$@"
}

appd_controller_oauth_token() {
    local controller_url="$1"
    local account_name="$2"
    local client_name="$3"
    local client_secret_file="$4"
    appd_assert_secret_file "${client_secret_file}" "AppDynamics OAuth client secret file"
    appd_curl -fsS \
        -X POST "$(appd_controller_api_url "${controller_url}" "/controller/api/oauth/access_token")" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        --data-urlencode "grant_type=client_credentials" \
        --data-urlencode "client_id=${client_name}@${account_name}" \
        --data-urlencode "client_secret@${client_secret_file}"
}

appd_events_api_headers_file() {
    local account_name="$1"
    local events_api_key_file="$2"
    local output_file="$3"
    appd_assert_secret_file "${events_api_key_file}" "AppDynamics Events API key file"
    umask 077
    {
        printf "X-Events-API-AccountName: %s\n" "${account_name}"
        printf "X-Events-API-Key: %s\n" "$(tr -d '\r\n' < "${events_api_key_file}")"
        printf "Content-Type: application/vnd.appd.events+json;v=2\n"
    } > "${output_file}"
}

appd_validate_json_file() {
    local path="$1"
    python3 -m json.tool "${path}" >/dev/null
}

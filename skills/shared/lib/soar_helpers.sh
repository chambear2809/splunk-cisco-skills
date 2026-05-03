#!/usr/bin/env bash
# Splunk SOAR helpers (On-prem and Cloud).
# Sourced by setup/validate scripts in splunk-soar-setup.
#
# Security contract:
#   - SOAR REST tokens (`ph-auth-token`) are read from chmod 600 files and
#     fed to curl via `-K <(printf 'header = "ph-auth-token: %s"' "$tok")`
#     so they never appear on argv (visible in `ps`, /proc/*/cmdline).
#   - The SOAR admin password is similarly read from a file and fed via
#     curl `--data-urlencode "password@${file}"` (for form bodies) or via
#     a curl --netrc-file equivalent — never via `-u user:pass`.
#   - TLS verification is enabled by default. Operators on a private CA
#     should set SOAR_API_CA_CERT=/path/to/ca.pem; SOAR_API_INSECURE=true
#     keeps the legacy "skip verification" behavior with a one-time warning.

[[ -n "${_SOAR_HELPERS_LOADED:-}" ]] && return 0
_SOAR_HELPERS_LOADED=true

if [[ -z "${_CRED_HELPERS_LOADED:-}" ]]; then
    _SOAR_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # shellcheck disable=SC1091
    source "${_SOAR_LIB_DIR}/credential_helpers.sh"
fi

_soar_curl_tls_args() {
    local insecure="${SOAR_API_INSECURE:-false}"
    local ca_cert="${SOAR_API_CA_CERT:-}"
    if [[ -n "${ca_cert}" ]]; then
        if [[ ! -s "${ca_cert}" ]]; then
            echo "ERROR: SOAR_API_CA_CERT not found or empty: ${ca_cert}" >&2
            return 1
        fi
        printf -- '--cacert\n%s\n' "${ca_cert}"
        return 0
    fi
    case "${insecure,,}" in
        1|true|yes)
            if [[ -z "${_WARNED_SOAR_API_INSECURE:-}" ]]; then
                echo "WARNING: TLS verification is disabled for SOAR API calls (SOAR_API_INSECURE=true). Use SOAR_API_CA_CERT=/path/to/ca.pem for private CAs in production." >&2
                _WARNED_SOAR_API_INSECURE=1
            fi
            printf -- '-k\n'
            ;;
        *) ;;
    esac
}

# soar_rest_call <tenant_url> <token_file> <method> <path> [extra curl args...]
# Calls the SOAR REST API using the ph-auth-token header. The token is fed
# to curl via `-K <(...)` (printf is a bash builtin, no fork) so it never
# appears in the curl process argv.
soar_rest_call() {
    local tenant_url="$1" token_file="$2" method="$3" path="$4"
    shift 4
    if [[ ! -s "${token_file}" ]]; then
        log "ERROR: SOAR API token missing or empty: ${token_file}"
        return 1
    fi
    local tls_args=() tls_status=0
    # _soar_curl_tls_args may legitimately return 1 when SOAR_API_CA_CERT
    # points at a missing/empty file. We must NOT swallow that with `|| true`
    # because doing so would silently fall back to default curl verification
    # against a broken operator config. Capture status separately and abort.
    {
        while IFS= read -r line; do
            [[ -n "${line}" ]] && tls_args+=("${line}")
        done
    } < <(_soar_curl_tls_args; printf 'STATUS=%d\n' "$?")
    if [[ "${#tls_args[@]}" -gt 0 ]] && [[ "${tls_args[-1]}" == STATUS=* ]]; then
        tls_status="${tls_args[-1]#STATUS=}"
        unset 'tls_args[-1]'
    fi
    if (( tls_status != 0 )); then
        log "ERROR: SOAR TLS configuration invalid (SOAR_API_CA_CERT/SOAR_API_INSECURE)."
        return 1
    fi
    local token
    token="$(cat "${token_file}")"
    curl -sS \
        ${tls_args[@]+"${tls_args[@]}"} \
        -X "${method}" \
        -K <(printf 'header = "Content-Type: application/json"\nheader = "ph-auth-token: %s"\n' "${token}") \
        "$@" \
        "${tenant_url}${path}"
}

# soar_validate_health <tenant_url> <token_file>
# Returns 0 if /rest/version returns a version string; non-zero otherwise.
soar_validate_health() {
    local tenant_url="$1" token_file="$2"
    local body
    body="$(soar_rest_call "${tenant_url}" "${token_file}" GET /rest/version 2>/dev/null || echo '{}')"
    python3 - "${body}" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1]) if sys.argv[1].strip() else {}
except Exception:
    data = {}
ver = data.get("version", "")
if not ver:
    sys.exit(1)
print(ver)
sys.exit(0)
PY
}

# soar_install_splunk_side_apps <app_install_setup_sh> <splunkbase_id...>
# Wrapper around splunk-app-install for the Splunk-side SOAR apps.
soar_install_splunk_side_apps() {
    local app_install="$1"
    shift
    if [[ ! -x "${app_install}" ]]; then
        log "ERROR: splunk-app-install setup script missing or not executable: ${app_install}"
        return 1
    fi
    local id
    for id in "$@"; do
        bash "${app_install}" --action install --source splunkbase --splunkbase-id "${id}" || return 1
    done
}

# _soar_admin_basic_auth_call <tenant_url> <admin_pw_file> <method> <path> [extra curl args...]
# Internal helper that POSTs/GETs against SOAR using HTTP Basic auth as the
# `soar_local_admin` user, with the password read from a file by curl
# (--netrc-file form) so it never lands on argv. We synthesize a netrc on
# the fly via process substitution; printf is a bash builtin so the
# password does not appear in any external process argv either.
_soar_admin_basic_auth_call() {
    local tenant_url="$1" admin_pw_file="$2" method="$3" path="$4"
    shift 4
    local pw_value
    pw_value="$(cat "${admin_pw_file}")"
    local host
    host="$(python3 -c 'from urllib.parse import urlparse; import sys; print(urlparse(sys.argv[1]).hostname or "")' "${tenant_url}")"
    if [[ -z "${host}" ]]; then
        log "ERROR: could not parse host from SOAR tenant URL: ${tenant_url}"
        return 1
    fi
    local tls_args=() tls_status=0
    # See soar_rest_call: do not swallow _soar_curl_tls_args failures.
    {
        while IFS= read -r line; do
            [[ -n "${line}" ]] && tls_args+=("${line}")
        done
    } < <(_soar_curl_tls_args; printf 'STATUS=%d\n' "$?")
    if [[ "${#tls_args[@]}" -gt 0 ]] && [[ "${tls_args[-1]}" == STATUS=* ]]; then
        tls_status="${tls_args[-1]#STATUS=}"
        unset 'tls_args[-1]'
    fi
    if (( tls_status != 0 )); then
        log "ERROR: SOAR TLS configuration invalid (SOAR_API_CA_CERT/SOAR_API_INSECURE)."
        return 1
    fi
    curl -sS \
        ${tls_args[@]+"${tls_args[@]}"} \
        -X "${method}" \
        --netrc-file <(printf 'machine %s\nlogin soar_local_admin\npassword %s\n' "${host}" "${pw_value}") \
        "$@" \
        "${tenant_url}${path}"
}

# soar_create_automation_user <tenant_url> <admin_pw_file> <username> <new_token_file>
# Creates an `automation` user (idempotent) and mints a long-lived REST token.
# The admin password and the new token are both kept off argv: the
# password is read by curl via --netrc-file (process substitution), and the
# minted token is written to a chmod 600 file under umask 077.
soar_create_automation_user() {
    local tenant_url="$1" admin_pw_file="$2" username="$3" new_token_file="$4"
    if [[ ! -s "${admin_pw_file}" ]]; then
        log "ERROR: SOAR admin password file missing or empty: ${admin_pw_file}"
        return 1
    fi

    # 1. Create the user (ignore 409 if already exists). Use mktemp for the
    #    response body so 4xx error bodies don't linger in /tmp/<predictable>.
    #    The username is built into JSON via python's json.dumps so any quote,
    #    backslash, or control character in the value cannot break out of the
    #    JSON string and modify the request structure.
    local create_body create_json
    create_body="$(mktemp)"
    chmod 600 "${create_body}"
    create_json="$(python3 -c '
import json, sys
print(json.dumps({"username": sys.argv[1], "type": "automation"}))
' "${username}")"
    _soar_admin_basic_auth_call "${tenant_url}" "${admin_pw_file}" POST /rest/ph_user \
        -H 'Content-Type: application/json' \
        --data "${create_json}" \
        > "${create_body}" || true
    rm -f "${create_body}"

    # 2. Look up the user id. The username is URL-encoded so that filter
    #    metacharacters (`"`, `&`, `=`, spaces, etc.) cannot alter the OData
    #    filter the SOAR `_filter_username` endpoint will parse.
    local lookup_body user_id encoded_username
    encoded_username="$(python3 -c '
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=""))
' "${username}")"
    lookup_body="$(mktemp)"
    chmod 600 "${lookup_body}"
    _soar_admin_basic_auth_call "${tenant_url}" "${admin_pw_file}" GET \
        "/rest/ph_user?_filter_username=%22${encoded_username}%22&include_automation=1" \
        > "${lookup_body}"
    user_id=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['data'][0]['id'])" "${lookup_body}")
    rm -f "${lookup_body}"

    # 3. Mint a long-lived token.
    local token_body token
    token_body="$(mktemp)"
    chmod 600 "${token_body}"
    _soar_admin_basic_auth_call "${tenant_url}" "${admin_pw_file}" POST \
        "/rest/ph_user/${user_id}/token" \
        > "${token_body}"
    token=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['key'])" "${token_body}")
    rm -f "${token_body}"

    umask 077
    mkdir -p "$(dirname "${new_token_file}")"
    printf '%s' "${token}" > "${new_token_file}"
    chmod 600 "${new_token_file}"
    log "OK: Automation user ${username} (id=${user_id}) ready. Token at ${new_token_file}."
}

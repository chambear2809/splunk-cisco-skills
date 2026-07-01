#!/usr/bin/env bash
# Splunk SOAR helpers (On-prem and Cloud).
# Sourced by setup/validate scripts in splunk-soar-setup.
#
# Security contract:
#   - SOAR REST tokens (`ph-auth-token`) are read from chmod 600 files and
#     fed to curl via `-K <(printf 'header = "ph-auth-token: %s"' "$tok")`
#     so they never appear on argv (visible in `ps`, /proc/*/cmdline).
#   - The SOAR admin password is similarly read from a file and fed via
#     a process-substituted curl config — never via `-u user:pass`.
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

soar_validate_tenant_url() {
    local tenant_url="${1:-}" allow_http="${SOAR_API_ALLOW_HTTP:-false}"
    python3 - "${tenant_url}" "${allow_http}" <<'PY'
import sys
from urllib.parse import urlsplit

value = sys.argv[1].strip()
allow_http = sys.argv[2].strip().lower() in {"1", "true", "yes"}
if not value or any(ch.isspace() for ch in value):
    raise SystemExit(1)
try:
    parsed = urlsplit(value)
    port = parsed.port
except ValueError:
    raise SystemExit(1)
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    raise SystemExit(1)
host = parsed.hostname.lower()
if "<" in host or ">" in host or host == "example.com" or host.endswith(".example.com"):
    raise SystemExit(1)
if parsed.scheme == "http" and not allow_http:
    raise SystemExit(1)
if parsed.username or parsed.password or parsed.query or parsed.fragment:
    raise SystemExit(1)
if port is not None and not 1 <= port <= 65535:
    raise SystemExit(1)
PY
}

soar_require_secret_file() {
    local path="${1:-}" label="${2:-SOAR secret file}" mode
    if [[ ! -f "${path}" || ! -r "${path}" || ! -s "${path}" ]]; then
        log "ERROR: ${label} must be a readable, non-empty regular file: ${path}"
        return 1
    fi
    mode="$(stat -c '%a' "${path}" 2>/dev/null || stat -f '%Lp' "${path}" 2>/dev/null || true)"
    if [[ "${mode}" != "600" ]]; then
        log "ERROR: ${label} must be chmod 600 (found ${mode:-unknown}): ${path}"
        return 1
    fi
}

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
    case "${insecure}" in
        1|true|TRUE|True|yes|YES|Yes|on|ON|On)
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
    if ! soar_validate_tenant_url "${tenant_url}"; then
        log "ERROR: SOAR tenant URL must be a real credential-free HTTPS URL without whitespace, query, or fragment."
        log "       Set SOAR_API_ALLOW_HTTP=true only for an explicitly approved non-TLS lab endpoint."
        return 1
    fi
    soar_require_secret_file "${token_file}" "SOAR API token file" || return 1
    local tls_args=() tls_status=0 last_index=0
    # _soar_curl_tls_args may legitimately return 1 when SOAR_API_CA_CERT
    # points at a missing/empty file. We must NOT swallow that with `|| true`
    # because doing so would silently fall back to default curl verification
    # against a broken operator config. Capture status separately and abort.
    {
        while IFS= read -r line; do
            [[ -n "${line}" ]] && tls_args+=("${line}")
        done
    } < <(_soar_curl_tls_args; printf 'STATUS=%d\n' "$?")
    if [[ "${#tls_args[@]}" -gt 0 ]]; then
        last_index=$(( ${#tls_args[@]} - 1 ))
    fi
    if [[ "${#tls_args[@]}" -gt 0 && "${tls_args[${last_index}]}" == STATUS=* ]]; then
        tls_status="${tls_args[${last_index}]#STATUS=}"
        unset "tls_args[${last_index}]"
    fi
    if (( tls_status != 0 )); then
        log "ERROR: SOAR TLS configuration invalid (SOAR_API_CA_CERT/SOAR_API_INSECURE)."
        return 1
    fi
    local token
    token="$(cat "${token_file}")"
    if [[ -z "${token}" || "${token}" == *$'\n'* || "${token}" == *$'\r'* || "${token}" == *'"'* || "${token}" == *'\'* ]]; then
        log "ERROR: SOAR API token file must contain one curl-config-safe line (no quote or backslash)."
        return 1
    fi
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
        bash "${app_install}" --source splunkbase --app-id "${id}" --no-update || return 1
    done
}

# _soar_admin_basic_auth_call <tenant_url> <admin_pw_file> <method> <path> [extra curl args...]
# Internal helper that POSTs/GETs against SOAR using HTTP Basic auth as the
# `soar_local_admin` user, with the password read from a file by curl
# (curl config form) so it never lands on argv. We synthesize the config on
# the fly via process substitution; printf is a bash builtin so the
# password does not appear in any external process argv either.
_soar_admin_basic_auth_call() {
    local tenant_url="$1" admin_pw_file="$2" method="$3" path="$4"
    shift 4
    if ! soar_validate_tenant_url "${tenant_url}"; then
        log "ERROR: SOAR tenant URL must be a real credential-free HTTPS URL without whitespace, query, or fragment."
        log "       Set SOAR_API_ALLOW_HTTP=true only for an explicitly approved non-TLS lab endpoint."
        return 1
    fi
    soar_require_secret_file "${admin_pw_file}" "SOAR admin password file" || return 1
    local pw_value pw_escaped
    pw_value="$(cat "${admin_pw_file}")"
    if [[ -z "${pw_value}" || "${pw_value}" == *$'\n'* || "${pw_value}" == *$'\r'* ]]; then
        log "ERROR: SOAR admin password file must contain one non-empty line."
        return 1
    fi
    pw_escaped="${pw_value//\\/\\\\}"
    pw_escaped="${pw_escaped//\"/\\\"}"
    local tls_args=() tls_status=0 last_index=0
    # See soar_rest_call: do not swallow _soar_curl_tls_args failures.
    {
        while IFS= read -r line; do
            [[ -n "${line}" ]] && tls_args+=("${line}")
        done
    } < <(_soar_curl_tls_args; printf 'STATUS=%d\n' "$?")
    if [[ "${#tls_args[@]}" -gt 0 ]]; then
        last_index=$(( ${#tls_args[@]} - 1 ))
    fi
    if [[ "${#tls_args[@]}" -gt 0 && "${tls_args[${last_index}]}" == STATUS=* ]]; then
        tls_status="${tls_args[${last_index}]#STATUS=}"
        unset "tls_args[${last_index}]"
    fi
    if (( tls_status != 0 )); then
        log "ERROR: SOAR TLS configuration invalid (SOAR_API_CA_CERT/SOAR_API_INSECURE)."
        return 1
    fi
    curl -sS \
        ${tls_args[@]+"${tls_args[@]}"} \
        -X "${method}" \
        -K <(printf 'user = "soar_local_admin:%s"\n' "${pw_escaped}") \
        "$@" \
        "${tenant_url}${path}"
}

# soar_create_automation_user <tenant_url> <admin_pw_file> <username> <new_token_file>
# Creates an `automation` user (idempotent) and mints a long-lived REST token.
# The admin password and the new token are both kept off argv: the
# password is read by curl via a config process substitution, and the
# minted token is written to a chmod 600 file under umask 077.
soar_create_automation_user() {
    local tenant_url="$1" admin_pw_file="$2" username="$3" new_token_file="$4"
    if ! soar_validate_tenant_url "${tenant_url}"; then
        log "ERROR: SOAR tenant URL must be a real credential-free HTTPS URL without whitespace, query, or fragment."
        log "       Set SOAR_API_ALLOW_HTTP=true only for an explicitly approved non-TLS lab endpoint."
        return 1
    fi
    soar_require_secret_file "${admin_pw_file}" "SOAR admin password file" || return 1

    # 1. Create the user (ignore 409 if already exists). Use mktemp for the
    #    response body so 4xx error bodies don't linger in /tmp/<predictable>.
    #    The username is built into JSON via python's json.dumps so any quote,
    #    backslash, or control character in the value cannot break out of the
    #    JSON string and modify the request structure.
    local create_body create_json create_code
    create_body="$(mktemp)"
    chmod 600 "${create_body}"
    create_json="$(python3 -c '
import json, sys
print(json.dumps({"username": sys.argv[1], "type": "automation"}))
' "${username}")"
    create_code="$(_soar_admin_basic_auth_call "${tenant_url}" "${admin_pw_file}" POST /rest/ph_user \
        -H 'Content-Type: application/json' \
        --data "${create_json}" \
        -o "${create_body}" -w '%{http_code}' 2>/dev/null || echo 000)"
    case "${create_code}" in
        200|201|409) ;;
        *)
            rm -f "${create_body}"
            log "ERROR: SOAR automation-user create returned HTTP ${create_code}."
            return 1
            ;;
    esac
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
    if ! _soar_admin_basic_auth_call "${tenant_url}" "${admin_pw_file}" GET \
        "/rest/ph_user?_filter_username=%22${encoded_username}%22&include_automation=1" \
        > "${lookup_body}"; then
        rm -f "${lookup_body}"
        log "ERROR: SOAR automation-user lookup failed."
        return 1
    fi
    if ! user_id=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['data'][0]['id'])" "${lookup_body}"); then
        rm -f "${lookup_body}"
        log "ERROR: SOAR automation-user lookup response was invalid or empty."
        return 1
    fi
    rm -f "${lookup_body}"
    if [[ ! "${user_id}" =~ ^[0-9]+$ ]]; then
        log "ERROR: SOAR automation-user lookup returned an invalid user id."
        return 1
    fi

    # 3. Mint a long-lived token.
    local token_body token
    token_body="$(mktemp)"
    chmod 600 "${token_body}"
    if ! _soar_admin_basic_auth_call "${tenant_url}" "${admin_pw_file}" POST \
        "/rest/ph_user/${user_id}/token" \
        > "${token_body}"; then
        rm -f "${token_body}"
        log "ERROR: SOAR automation-token mint request failed."
        return 1
    fi
    if ! token=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['key'])" "${token_body}"); then
        rm -f "${token_body}"
        log "ERROR: SOAR automation-token response did not contain a key."
        return 1
    fi
    rm -f "${token_body}"
    if [[ -z "${token}" || "${token}" == *$'\n'* || "${token}" == *$'\r'* ]]; then
        log "ERROR: SOAR automation-token response contained an invalid token value."
        return 1
    fi

    local token_dir token_tmp previous_umask
    token_dir="$(dirname "${new_token_file}")"
    mkdir -p "${token_dir}"
    if [[ -d "${new_token_file}" ]]; then
        log "ERROR: SOAR token destination is a directory: ${new_token_file}"
        return 1
    fi
    previous_umask="$(umask)"
    umask 077
    token_tmp="$(mktemp "${token_dir}/.soar-token.XXXXXX")"
    printf '%s' "${token}" > "${token_tmp}"
    chmod 600 "${token_tmp}"
    mv -f -- "${token_tmp}" "${new_token_file}"
    umask "${previous_umask}"
    unset token pw_value
    log "OK: Automation user ${username} (id=${user_id}) ready. Token at ${new_token_file}."
}

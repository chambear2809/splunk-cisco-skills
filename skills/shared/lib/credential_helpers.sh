#!/usr/bin/env bash
# Shared credential helper library for Splunk skill scripts.
# Source this file to get secure credential loading, session key management,
# curl wrappers that keep secrets off process argument lists, and REST API
# helpers for remote Splunk management.

_CRED_HELPERS_LOADED=true
_SB_CRED_LOADED=false

# Resolve SCRIPT_DIR for the sourcing script if not already set.
if [[ -z "${SCRIPT_DIR:-}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")" && pwd)"
fi

# Locate the credentials file. Priority:
#   1. Project-root ./credentials  (next to README.md)
#   2. ~/.splunk/credentials       (user-level fallback)
_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_PROJECT_ROOT="$(cd "${_LIB_DIR}/../../.." 2>/dev/null && pwd)"
if [[ -f "${_PROJECT_ROOT}/credentials" ]]; then
    _CRED_FILE="${_PROJECT_ROOT}/credentials"
else
    _CRED_FILE="${HOME}/.splunk/credentials"
fi

load_splunk_connection_settings() {
    if [[ -f "${_CRED_FILE}" ]]; then
        local line
        while IFS= read -r line || [[ -n "${line}" ]]; do
            line="${line%%#*}"
            [[ -z "${line}" ]] && continue
            case "${line}" in
                SPLUNK_HOST=*)      [[ -z "${SPLUNK_HOST:-}" ]]      && eval "${line}" ;;
                SPLUNK_MGMT_PORT=*) [[ -z "${SPLUNK_MGMT_PORT:-}" ]] && eval "${line}" ;;
                SPLUNK_URI=*)       [[ -z "${SPLUNK_URI:-}" ]]       && eval "${line}" ;;
                SPLUNK_SSH_HOST=*)  [[ -z "${SPLUNK_SSH_HOST:-}" ]]  && eval "${line}" ;;
                SPLUNK_SSH_PORT=*)  [[ -z "${SPLUNK_SSH_PORT:-}" ]]  && eval "${line}" ;;
                SPLUNK_SSH_USER=*)  [[ -z "${SPLUNK_SSH_USER:-}" ]]  && eval "${line}" ;;
            esac
        done < "${_CRED_FILE}"
    fi

    SPLUNK_MGMT_PORT="${SPLUNK_MGMT_PORT:-8089}"
    if [[ -z "${SPLUNK_URI:-}" && -n "${SPLUNK_HOST:-}" ]]; then
        SPLUNK_URI="https://${SPLUNK_HOST}:${SPLUNK_MGMT_PORT}"
    fi
    SPLUNK_URI="${SPLUNK_URI:-https://localhost:8089}"
}

splunk_host_from_uri() {
    local uri="${1:-${SPLUNK_URI:-}}"
    uri="${uri#http://}"
    uri="${uri#https://}"
    uri="${uri%%/*}"
    printf '%s' "${uri%%:*}"
}

load_splunk_connection_settings

load_splunk_credentials() {
    if [[ -f "${_CRED_FILE}" ]]; then
        local line
        while IFS= read -r line || [[ -n "${line}" ]]; do
            line="${line%%#*}"
            [[ -z "${line}" ]] && continue
            case "${line}" in
                SPLUNK_USER=*)
                    [[ -z "${SPLUNK_USER:-}" ]] && eval "${line}"
                    ;;
                SPLUNK_PASS=*)
                    [[ -z "${SPLUNK_PASS:-}" ]] && eval "${line}"
                    ;;
            esac
        done < "${_CRED_FILE}"
    fi

    if [[ -z "${SPLUNK_USER:-}" ]]; then
        read -rp "Splunk username: " SPLUNK_USER
    fi
    if [[ -z "${SPLUNK_PASS:-}" ]]; then
        read -rsp "Splunk password: " SPLUNK_PASS
        echo ""
    fi

    if [[ -z "${SPLUNK_USER:-}" || -z "${SPLUNK_PASS:-}" ]]; then
        echo "ERROR: Splunk credentials are required." >&2
        return 1
    fi
}

load_splunkbase_credentials() {
    if [[ -f "${_CRED_FILE}" ]]; then
        local line
        while IFS= read -r line || [[ -n "${line}" ]]; do
            line="${line%%#*}"
            [[ -z "${line}" ]] && continue
            case "${line}" in
                SB_USER=*) [[ -z "${SB_USER:-}" ]] && eval "${line}" ;;
                SB_PASS=*) [[ -z "${SB_PASS:-}" ]] && eval "${line}" ;;
            esac
        done < "${_CRED_FILE}"
    fi

    if [[ -z "${SB_USER:-}" ]]; then
        read -rp "Splunkbase (splunk.com) username: " SB_USER
    fi
    if [[ -z "${SB_PASS:-}" ]]; then
        read -rsp "Splunkbase (splunk.com) password: " SB_PASS
        echo ""
    fi

    if [[ -z "${SB_USER:-}" || -z "${SB_PASS:-}" ]]; then
        echo "ERROR: Splunkbase credentials are required." >&2
        return 1
    fi
}

load_splunk_ssh_credentials() {
    if [[ -f "${_CRED_FILE}" ]]; then
        local line
        while IFS= read -r line || [[ -n "${line}" ]]; do
            line="${line%%#*}"
            [[ -z "${line}" ]] && continue
            case "${line}" in
                SPLUNK_SSH_HOST=*) [[ -z "${SPLUNK_SSH_HOST:-}" ]] && eval "${line}" ;;
                SPLUNK_SSH_PORT=*) [[ -z "${SPLUNK_SSH_PORT:-}" ]] && eval "${line}" ;;
                SPLUNK_SSH_USER=*) [[ -z "${SPLUNK_SSH_USER:-}" ]] && eval "${line}" ;;
                SPLUNK_SSH_PASS=*) [[ -z "${SPLUNK_SSH_PASS:-}" ]] && eval "${line}" ;;
            esac
        done < "${_CRED_FILE}"
    fi

    SPLUNK_SSH_HOST="${SPLUNK_SSH_HOST:-${SPLUNK_HOST:-$(splunk_host_from_uri "${SPLUNK_URI}")}}"
    SPLUNK_SSH_PORT="${SPLUNK_SSH_PORT:-22}"
    SPLUNK_SSH_USER="${SPLUNK_SSH_USER:-splunk}"

    if [[ -z "${SPLUNK_SSH_PASS:-}" ]]; then
        if [[ ! -t 0 ]]; then
            echo "ERROR: Splunk SSH password is required for SSH staging." >&2
            return 1
        fi
        read -rsp "Splunk SSH password: " SPLUNK_SSH_PASS
        echo ""
    fi

    if [[ -z "${SPLUNK_SSH_HOST:-}" || -z "${SPLUNK_SSH_USER:-}" || -z "${SPLUNK_SSH_PASS:-}" ]]; then
        echo "ERROR: Splunk SSH host, user, and password are required." >&2
        return 1
    fi
}

# Authenticate to Splunk and return a session key.
# Password is sent via stdin to curl, not via argv.
get_session_key() {
    local uri="${1:-https://localhost:8089}"
    local sk
    sk=$(printf 'username=%s&password=%s' "${SPLUNK_USER}" "${SPLUNK_PASS}" \
        | curl -sk "${uri}/services/auth/login" -d @- 2>/dev/null \
        | sed -n 's/.*<sessionKey>\([^<]*\)<.*/\1/p' || true)

    if [[ -z "${sk}" ]]; then
        echo "ERROR: Could not authenticate to Splunk. Check credentials." >&2
        return 1
    fi
    printf '%s' "${sk}"
}

# curl wrapper that passes the Authorization header via a process-substitution
# file descriptor instead of argv, hiding the session key from ps/proc.
# Usage: splunk_curl <session_key> [curl_args...]
splunk_curl() {
    local sk="$1"; shift
    curl -sk -K <(printf 'header = "Authorization: Splunk %s"\n' "${sk}") "$@"
}

# POST wrapper that also pipes the request body via stdin.
# Usage: splunk_curl_post <session_key> <post_data> [curl_args...]
splunk_curl_post() {
    local sk="$1"; shift
    local post_data="$1"; shift
    printf '%s' "${post_data}" \
        | curl -sk -K <(printf 'header = "Authorization: Splunk %s"\n' "${sk}") -d @- "$@"
}

# Read a secret from a file, stripping leading/trailing whitespace.
# Usage: read_secret_file <filepath>
read_secret_file() {
    local fpath="$1"
    if [[ ! -f "${fpath}" ]]; then
        echo "ERROR: Secret file not found: ${fpath}" >&2
        return 1
    fi
    local val
    val=$(<"${fpath}")
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    printf '%s' "${val}"
}

# Resolve a credential that may come from a --*-file flag, a direct value,
# or an interactive prompt.
# Usage: resolve_secret <value> <prompt_text>
#   If value is empty, prompts interactively.
#   If value is a readable file path, reads from the file.
#   Otherwise returns the value as-is (backward compat).
resolve_secret() {
    local val="$1"
    local prompt="$2"

    if [[ -z "${val}" ]]; then
        read -rsp "${prompt}: " val
        echo "" >&2
    elif [[ -f "${val}" ]]; then
        val=$(read_secret_file "${val}")
    fi
    printf '%s' "${val}"
}

# Escape a value for use inside a curl config file.
_curl_config_escape() {
    python3 - "$1" <<'PY'
import sys
print(sys.argv[1].replace('\\', '\\\\').replace('"', '\\"'))
PY
}

# Check whether a downloaded file looks like a Splunk app package.
_is_splunk_package() {
    python3 - "$1" <<'PY'
import sys
import tarfile

sys.exit(0 if tarfile.is_tarfile(sys.argv[1]) else 1)
PY
}

# Authenticate to Splunkbase via the public session-login API.
# Sets SB_SESSION_ID and SB_COOKIE_JAR globals.
get_splunkbase_session() {
    local response_file cookie_file http_code response session

    response_file="$(mktemp)"
    cookie_file="$(mktemp)"
    chmod 600 "${cookie_file}"

    if [[ -n "${SB_COOKIE_JAR:-}" && -f "${SB_COOKIE_JAR}" ]]; then
        rm -f "${SB_COOKIE_JAR}"
    fi

    http_code=$(curl -sk \
        -X POST "https://splunkbase.splunk.com/api/account:login" \
        -K <(
            printf 'form-string = "username=%s"\n' "$(_curl_config_escape "${SB_USER}")"
            printf 'form-string = "password=%s"\n' "$(_curl_config_escape "${SB_PASS}")"
        ) \
        -c "${cookie_file}" \
        -o "${response_file}" \
        -w '%{http_code}' 2>/dev/null || echo "000")

    response=$(<"${response_file}")
    rm -f "${response_file}"

    session=$(printf '%s' "${response}" | sed -n 's:.*<id>\([^<]*\)</id>.*:\1:p')

    if [[ "${http_code}" != "200" || -z "${session}" ]]; then
        rm -f "${cookie_file}"
        echo "ERROR: Failed to authenticate to Splunkbase session API." >&2
        if [[ -n "${response}" ]]; then
            echo "Response: $(printf '%s' "${response}" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')" >&2
        fi
        return 1
    fi

    SB_SESSION_ID="${session}"
    SB_COOKIE_JAR="${cookie_file}"
}

# Resolve Splunkbase release metadata for an app/version.
# Usage: get_splunkbase_release_metadata <app_id> <app_version_or_empty>
# Sets SB_DOWNLOAD_SOURCE_URL, SB_DOWNLOAD_VERSION, and SB_DOWNLOAD_FILENAME globals.
get_splunkbase_release_metadata() {
    local app_id="$1"
    local app_version="$2"
    local metadata

    metadata=$(curl -sk "https://splunkbase.splunk.com/api/v1/app/${app_id}/release/" 2>/dev/null \
        | python3 -c "
import json
import sys

requested_version = sys.argv[1]
app_id = sys.argv[2]

try:
    releases = json.load(sys.stdin)
except Exception:
    sys.exit(1)

if isinstance(releases, dict):
    releases = releases.get('releases', [])

if not isinstance(releases, list) or not releases:
    sys.exit(1)

release = None
if requested_version:
    for candidate in releases:
        version = candidate.get('name') or candidate.get('title') or candidate.get('version') or ''
        if version == requested_version:
            release = candidate
            break
else:
    release = releases[0]

if release is None:
    sys.exit(1)

version = release.get('name') or release.get('title') or release.get('version') or ''
filename = release.get('filename') or ''
if not version or not filename:
    sys.exit(1)

print(f'{version}\\t{filename}\\thttps://splunkbase.splunk.com/app/{app_id}/release/{version}/download/')
" "${app_version}" "${app_id}" 2>/dev/null) || {
        echo "ERROR: Failed to resolve Splunkbase release metadata for app ${app_id}${app_version:+ version ${app_version}}." >&2
        return 1
    }

    IFS=$'\t' read -r SB_DOWNLOAD_VERSION SB_DOWNLOAD_FILENAME SB_DOWNLOAD_SOURCE_URL <<< "${metadata}"

    if [[ -z "${SB_DOWNLOAD_VERSION:-}" || -z "${SB_DOWNLOAD_FILENAME:-}" || -z "${SB_DOWNLOAD_SOURCE_URL:-}" ]]; then
        echo "ERROR: Splunkbase release metadata was incomplete for app ${app_id}${app_version:+ version ${app_version}}." >&2
        return 1
    fi
}

# Download a Splunkbase package using the current Splunkbase auth flow.
# Usage: download_splunkbase_release <app_id> <app_version_or_empty> <output_path>
# Sets SB_DOWNLOAD_SOURCE_URL, SB_DOWNLOAD_EFFECTIVE_URL, SB_DOWNLOAD_VERSION,
# and SB_DOWNLOAD_FILENAME globals.
download_splunkbase_release() {
    local app_id="$1"
    local app_version="$2"
    local output_path="$3"
    local tmp_file meta http_code effective_url

    if [[ -z "${SB_SESSION_ID:-}" || -z "${SB_COOKIE_JAR:-}" || ! -f "${SB_COOKIE_JAR:-}" ]]; then
        get_splunkbase_session || return 1
    fi

    get_splunkbase_release_metadata "${app_id}" "${app_version}" || return 1

    tmp_file="$(mktemp)"
    SB_DOWNLOAD_EFFECTIVE_URL=""

    mkdir -p "$(dirname "${output_path}")"

    meta=$(curl -skL \
        -b "${SB_COOKIE_JAR}" \
        -K <(printf 'header = "X-Auth-Token: %s"\n' "$(_curl_config_escape "${SB_SESSION_ID}")") \
        -o "${tmp_file}" \
        -w $'%{http_code}\t%{url_effective}' \
        "${SB_DOWNLOAD_SOURCE_URL}" 2>/dev/null || printf '000\t')

    http_code="${meta%%$'\t'*}"
    effective_url=""
    if [[ "${meta}" == *$'\t'* ]]; then
        effective_url="${meta#*$'\t'}"
    fi

    if [[ "${http_code}" == "200" ]] && [[ -s "${tmp_file}" ]] && _is_splunk_package "${tmp_file}"; then
        SB_DOWNLOAD_EFFECTIVE_URL="${effective_url}"
        mv -f "${tmp_file}" "${output_path}"
        return 0
    fi

    rm -f "${tmp_file}"
    echo "ERROR: Failed to download Splunkbase app ${app_id}${app_version:+ version ${app_version}}." >&2
    return 1
}

# Legacy Splunkbase helper kept for backward compatibility with older scripts.
# Authenticates via Okta, returning sid and SSOID cookies.
# Sets SB_SID and SB_SSOID globals. Credentials piped via stdin to avoid argv exposure.
get_splunkbase_cookies() {
    local json_payload
    json_payload=$(printf '%s\n%s\n' "${SB_USER}" "${SB_PASS}" | python3 -c "
import json, sys
u = sys.stdin.readline().rstrip('\n')
p = sys.stdin.readline().rstrip('\n')
print(json.dumps({'username': u, 'password': p}))
" 2>/dev/null)

    local auth_response
    auth_response=$(printf '%s' "${json_payload}" | curl -sk -D - \
        -X POST \
        -H 'Accept: application/json' \
        -H 'Content-Type: application/json' \
        -d @- \
        "https://account.splunk.com/api/v1/okta/auth" 2>/dev/null || true)

    SB_SID=$(printf '%s' "${auth_response}" | sed -n 's/^[Ss]et-[Cc]ookie: sid=\([^;]*\);.*/\1/p' | head -1)
    # Parse JSON body (after headers) for ssoid_cookie; body is everything after first blank line
    local body
    body=$(printf '%s' "${auth_response}" | sed -n '/^$/,$ p' | tail -n +2)
    SB_SSOID=$(printf '%s' "${body}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('ssoid_cookie', data.get('ssoid', '')))
except (json.JSONDecodeError, ValueError, KeyError):
    pass
" 2>/dev/null || true)

    if [[ -z "${SB_SID}" && -z "${SB_SSOID}" ]]; then
        echo "ERROR: Failed to authenticate to Splunkbase (no sid or ssoid). Check splunk.com credentials and network." >&2
        return 1
    fi
}

# Legacy wrapper — kept for backward compatibility.
# Calls get_splunkbase_cookies() and returns a cookie string.
get_splunkbase_token() {
    get_splunkbase_cookies
    local cookie_str=""
    [[ -n "${SB_SID:-}" ]] && cookie_str="sid=${SB_SID}"
    [[ -n "${SB_SSOID:-}" ]] && cookie_str="${cookie_str:+${cookie_str}; }SSOID=${SB_SSOID}"
    printf '%s' "${cookie_str}"
}

# Strip potentially sensitive fields from a Splunk REST API response
# before printing to stdout. Use instead of `echo "${resp}" | head -20`.
sanitize_response() {
    local resp="$1"
    local max_lines="${2:-20}"
    printf '%s' "${resp}" \
        | sed -E 's/(password|secret|token|api_key|client_secret|sessionKey)=[^ &"]*/\1=REDACTED/gi' \
        | head -"${max_lines}"
}

# ---------------------------------------------------------------------------
# REST API helpers for remote Splunk management
# ---------------------------------------------------------------------------

# URL-encode a string for use in REST API URL paths.
_urlencode() {
    python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"
}

# Check if a Splunk app is installed via REST.
# Usage: rest_check_app <session_key> <splunk_uri> <app_name>
rest_check_app() {
    local sk="$1" uri="$2" app="$3"
    local http_code
    http_code=$(splunk_curl "${sk}" \
        "${uri}/services/apps/local/${app}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null)
    [[ "${http_code}" == "200" ]]
}

# Get app version via REST.
# Usage: rest_get_app_version <session_key> <splunk_uri> <app_name>
rest_get_app_version() {
    local sk="$1" uri="$2" app="$3"
    splunk_curl "${sk}" \
        "${uri}/services/apps/local/${app}?output_mode=json" 2>/dev/null \
        | python3 -c "
import json, sys
d = json.load(sys.stdin)
entries = d.get('entry', [])
print(entries[0].get('content', {}).get('version', 'unknown') if entries else 'unknown')
" 2>/dev/null || echo "unknown"
}

# Check if a Splunk index exists via REST.
# Usage: rest_check_index <session_key> <splunk_uri> <index_name>
rest_check_index() {
    local sk="$1" uri="$2" idx="$3"
    local http_code
    http_code=$(splunk_curl "${sk}" \
        "${uri}/services/data/indexes/${idx}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null)
    [[ "${http_code}" == "200" ]]
}

# Create a Splunk index via REST. Returns 0 if created or already exists.
# Usage: rest_create_index <session_key> <splunk_uri> <index_name> [maxTotalDataSizeMB]
rest_create_index() {
    local sk="$1" uri="$2" idx="$3" max_size="${4:-512000}"
    local http_code resp
    resp=$(splunk_curl_post "${sk}" \
        "name=${idx}&maxTotalDataSizeMB=${max_size}" \
        "${uri}/services/data/indexes" -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        201|200) return 0 ;;
        409) return 0 ;;
        *) echo "ERROR: Create index '${idx}' failed (HTTP ${http_code})" >&2; return 1 ;;
    esac
}

# Create or update a conf stanza via REST.
# Usage: rest_set_conf <sk> <uri> <app> <conf_name> <stanza> <post_body>
rest_set_conf() {
    local sk="$1" uri="$2" app="$3" conf="$4" stanza="$5" body="$6"
    local encoded_stanza http_code resp
    encoded_stanza=$(_urlencode "${stanza}")
    resp=$(splunk_curl_post "${sk}" "${body}" \
        "${uri}/servicesNS/nobody/${app}/configs/conf-${conf}/${encoded_stanza}" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    [[ "${http_code}" == "200" ]] && return 0
    resp=$(splunk_curl_post "${sk}" "name=${stanza}&${body}" \
        "${uri}/servicesNS/nobody/${app}/configs/conf-${conf}" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        201|200|409) return 0 ;;
        *) echo "ERROR: Set conf-${conf}/${stanza} failed (HTTP ${http_code})" >&2; return 1 ;;
    esac
}

# Check if a conf stanza exists via REST.
# Usage: rest_check_conf <sk> <uri> <app> <conf_name> <stanza>
rest_check_conf() {
    local sk="$1" uri="$2" app="$3" conf="$4" stanza="$5"
    local encoded_stanza http_code
    encoded_stanza=$(_urlencode "${stanza}")
    http_code=$(splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/configs/conf-${conf}/${encoded_stanza}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null)
    [[ "${http_code}" == "200" ]]
}

# Get a value from a conf stanza via REST.
# Usage: rest_get_conf_value <sk> <uri> <app> <conf_name> <stanza> <key>
rest_get_conf_value() {
    local sk="$1" uri="$2" app="$3" conf="$4" stanza="$5" key="$6"
    local encoded_stanza
    encoded_stanza=$(_urlencode "${stanza}")
    splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/configs/conf-${conf}/${encoded_stanza}?output_mode=json" \
        2>/dev/null \
        | python3 -c "
import json, sys
d = json.load(sys.stdin)
entries = d.get('entry', [])
print(entries[0].get('content', {}).get('${key}', '') if entries else '')
" 2>/dev/null || echo ""
}

# Count stanzas in a conf file matching an optional prefix via REST.
# Usage: rest_count_conf_stanzas <sk> <uri> <app> <conf_name> [prefix_filter]
rest_count_conf_stanzas() {
    local sk="$1" uri="$2" app="$3" conf="$4" prefix="${5:-}"
    splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/configs/conf-${conf}?output_mode=json&count=0" \
        2>/dev/null \
        | python3 -c "
import json, sys
prefix = '${prefix}'
d = json.load(sys.stdin)
entries = d.get('entry', [])
if prefix:
    entries = [e for e in entries if e.get('name', '').startswith(prefix)]
print(len(entries))
" 2>/dev/null || echo "0"
}

# Count live modular inputs registered under an app, optionally filtered by
# enabled/disabled state.
# Usage: rest_count_live_inputs <sk> <uri> <app> [disabled_filter]
#   disabled_filter: "0" for enabled, "1" for disabled, empty for all
rest_count_live_inputs() {
    local sk="$1" uri="$2" app="$3" disabled_filter="${4:-}"
    splunk_curl "${sk}" \
        "${uri}/services/data/inputs/all?output_mode=json&count=0" \
        2>/dev/null \
        | python3 -c "
import json, sys
target_app = '${app}'
disabled_filter = '${disabled_filter}'

def normalize_disabled(value):
    if isinstance(value, bool):
        return '1' if value else '0'
    text = str(value).strip().lower()
    if text in ('1', 'true'):
        return '1'
    if text in ('0', 'false'):
        return '0'
    return text

try:
    data = json.load(sys.stdin)
    count = 0
    for entry in data.get('entry', []):
        acl = entry.get('acl', {}) or {}
        content = entry.get('content', {}) or {}
        entry_app = acl.get('app', '')
        if entry_app != target_app:
            continue
        disabled = normalize_disabled(content.get('disabled'))
        if disabled_filter and disabled != disabled_filter:
            continue
        count += 1
    print(count)
except Exception:
    print(0)
" 2>/dev/null || echo "0"
}

# Return live input counts for an app as: "<total> <enabled> <disabled>"
# Usage: rest_get_live_input_counts <sk> <uri> <app>
rest_get_live_input_counts() {
    local sk="$1" uri="$2" app="$3"
    splunk_curl "${sk}" \
        "${uri}/services/data/inputs/all?output_mode=json&count=0" \
        2>/dev/null \
        | python3 -c "
import json, sys
target_app = '${app}'
total = enabled = disabled = 0

def normalize_disabled(value):
    if isinstance(value, bool):
        return '1' if value else '0'
    text = str(value).strip().lower()
    if text in ('1', 'true'):
        return '1'
    if text in ('0', 'false'):
        return '0'
    return text

try:
    data = json.load(sys.stdin)
    for entry in data.get('entry', []):
        acl = entry.get('acl', {}) or {}
        content = entry.get('content', {}) or {}
        if acl.get('app', '') != target_app:
            continue
        total += 1
        normalized = normalize_disabled(content.get('disabled'))
        if normalized == '0':
            enabled += 1
        elif normalized == '1':
            disabled += 1
    print(f'{total} {enabled} {disabled}')
except Exception:
    print('0 0 0')
" 2>/dev/null || echo "0 0 0"
}

# List stanza names from a TA-specific REST handler.
# Usage: rest_list_ta_stanzas <sk> <uri> <app> <handler_path>
rest_list_ta_stanzas() {
    local sk="$1" uri="$2" app="$3" handler="$4"
    splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/${handler}?output_mode=json&count=0" \
        2>/dev/null
}

# Update a modular input's enabled/disabled state after create or update.
# Usage: rest_apply_input_enable_state <sk> <uri> <app> <input_type> <input_name> <enable_state>
rest_apply_input_enable_state() {
    local sk="$1" uri="$2" app="$3" input_type="$4" input_name="$5" enable_state="${6:-}"
    local endpoint="${uri}/servicesNS/nobody/${app}/data/inputs/${input_type}"
    local encoded_name resp http_code
    encoded_name=$(_urlencode "${input_name}")

    case "${enable_state}" in
        0|false|False)
            resp=$(splunk_curl_post "${sk}" "" \
                "${endpoint}/${encoded_name}/enable" -w '\n%{http_code}' 2>/dev/null)
            http_code=$(echo "${resp}" | tail -1)
            [[ "${http_code}" == "200" ]] || { echo "ERROR: Enable ${input_type}://${input_name} failed (HTTP ${http_code})" >&2; return 1; }
            ;;
        1|true|True)
            resp=$(splunk_curl_post "${sk}" "" \
                "${endpoint}/${encoded_name}/disable" -w '\n%{http_code}' 2>/dev/null)
            http_code=$(echo "${resp}" | tail -1)
            [[ "${http_code}" == "200" ]] || { echo "ERROR: Disable ${input_type}://${input_name} failed (HTTP ${http_code})" >&2; return 1; }
            ;;
        *)
            ;;
    esac
}

# Create a modular input via the TA's data/inputs REST handler.
# Usage: rest_create_input <sk> <uri> <app> <input_type> <input_name> <body>
rest_create_input() {
    local sk="$1" uri="$2" app="$3" input_type="$4" input_name="$5" body="$6"
    local endpoint="${uri}/servicesNS/nobody/${app}/data/inputs/${input_type}"
    local encoded_name http_code resp enable_state body_without_disabled
    encoded_name=$(_urlencode "${input_name}")

    if [[ "${body}" =~ (^|&)disabled=([^&]+) ]]; then
        enable_state="${BASH_REMATCH[2]}"
    else
        enable_state=""
    fi

    http_code=$(splunk_curl "${sk}" \
        "${endpoint}/${encoded_name}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null)
    if [[ "${http_code}" == "200" ]]; then
        body_without_disabled=$(printf '%s' "${body}" \
            | sed -E 's/(^|&)disabled=[^&]*//g; s/^&//; s/&+$//; s/&&+/\&/g')

        if [[ -n "${body_without_disabled}" ]]; then
            resp=$(splunk_curl_post "${sk}" "${body_without_disabled}" \
                "${endpoint}/${encoded_name}" -w '\n%{http_code}' 2>/dev/null)
            http_code=$(echo "${resp}" | tail -1)
            case "${http_code}" in
                200) ;;
                *)
                    if ! rest_set_conf "${sk}" "${uri}" "${app}" "inputs" "${input_type}://${input_name}" "${body_without_disabled}"; then
                        echo "ERROR: Update ${input_type}://${input_name} failed (HTTP ${http_code})" >&2
                        return 1
                    fi
                    ;;
            esac
        fi

        rest_apply_input_enable_state "${sk}" "${uri}" "${app}" "${input_type}" "${input_name}" "${enable_state}"
        return 0
    fi

    resp=$(splunk_curl_post "${sk}" "name=${input_name}&${body}" \
        "${endpoint}" -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        201|200|409)
            rest_apply_input_enable_state "${sk}" "${uri}" "${app}" "${input_type}" "${input_name}" "${enable_state}"
            return 0
            ;;
        *)
            echo "ERROR: Create ${input_type}://${input_name} failed (HTTP ${http_code})" >&2
            return 1
            ;;
    esac
}

# Run a oneshot search and return a single result field value.
# Usage: rest_oneshot_search <sk> <uri> <search_string> <result_field>
rest_oneshot_search() {
    local sk="$1" uri="$2" search="$3" field="$4"
    splunk_curl_post "${sk}" \
        "search=${search}&exec_mode=oneshot&output_mode=json" \
        "${uri}/services/search/jobs" 2>/dev/null \
        | python3 -c "
import json, sys
d = json.load(sys.stdin)
r = d.get('results', [])
print(r[0].get('${field}', '0') if r else '0')
" 2>/dev/null || echo "0"
}

# Restart Splunk via REST.
# Usage: rest_restart_splunk <session_key> <splunk_uri>
rest_restart_splunk() {
    local sk="$1" uri="$2"
    splunk_curl_post "${sk}" "" "${uri}/services/server/control/restart" >/dev/null 2>&1
}

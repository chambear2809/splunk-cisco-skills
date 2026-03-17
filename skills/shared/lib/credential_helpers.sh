#!/usr/bin/env bash
# Shared credential helper library for Splunk skill scripts.
# Source this file to get secure credential loading, session key management,
# curl wrappers that keep secrets off process argument lists, and REST API
# helpers for remote Splunk management.

_CRED_HELPERS_LOADED=true

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

_read_credential_file_entries() {
    local file_path="$1"
    python3 - "$file_path" <<'PY'
import ast
import os
import re
import sys

path = sys.argv[1]
allowed_keys = [
    "SPLUNK_HOST",
    "SPLUNK_MGMT_PORT",
    "SPLUNK_URI",
    "SPLUNK_SSH_HOST",
    "SPLUNK_SSH_PORT",
    "SPLUNK_SSH_USER",
    "SPLUNK_SSH_PASS",
    "SPLUNK_USER",
    "SPLUNK_PASS",
    "SB_USER",
    "SB_PASS",
]
allowed = set(allowed_keys)
raw_values = {}

with open(path, encoding="utf-8") as handle:
    for raw_line in handle:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in raw_line:
            continue

        key, value = raw_line.split("=", 1)
        key = key.strip()
        if key not in allowed:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            try:
                value = ast.literal_eval(value)
            except Exception:
                value = value[1:-1]

        raw_values[key] = value

pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

def resolve_value(value, stack):
    def repl(match):
        name = match.group(1)
        if name in stack:
            return match.group(0)
        if name in raw_values:
            return resolve_value(raw_values[name], stack | {name})
        return os.environ.get(name, match.group(0))
    return pattern.sub(repl, value)

for key in allowed_keys:
    if key not in raw_values:
        continue
    resolved = resolve_value(raw_values[key], {key})
    sys.stdout.buffer.write(key.encode("utf-8"))
    sys.stdout.buffer.write(b"\0")
    sys.stdout.buffer.write(resolved.encode("utf-8"))
    sys.stdout.buffer.write(b"\0")
PY
}

_load_credential_values_from_file() {
    local file_path="${1:-${_CRED_FILE}}"
    local key value current_value

    [[ -f "${file_path}" ]] || return 0

    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
        current_value="${!key-}"
        if [[ -z "${current_value}" ]]; then
            printf -v "${key}" '%s' "${value}"
        fi
    done < <(_read_credential_file_entries "${file_path}")
}

load_splunk_connection_settings() {
    _load_credential_values_from_file "${_CRED_FILE}"

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
    _load_credential_values_from_file "${_CRED_FILE}"

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
    _load_credential_values_from_file "${_CRED_FILE}"

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
    _load_credential_values_from_file "${_CRED_FILE}"

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
    local body sk
    body=$(form_urlencode_pairs username "${SPLUNK_USER}" password "${SPLUNK_PASS}") || return 1
    sk=$(printf '%s' "${body}" \
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

# Read a cookie value from a Netscape-format curl cookie jar.
# Usage: _read_cookie_jar_value <cookie_jar_path> <cookie_name>
_read_cookie_jar_value() {
    python3 - "$1" "$2" <<'PY'
import sys

cookie_file = sys.argv[1]
target_name = sys.argv[2]

try:
    with open(cookie_file, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = raw_line.rstrip("\n").split("\t")
            if len(parts) < 7:
                continue
            name = parts[5]
            value = parts[6]
            if name == target_name:
                print(value, end="")
                break
except FileNotFoundError:
    pass
PY
}

# Legacy Splunkbase helper kept for backward compatibility with older scripts.
# It now maps legacy globals onto the current Splunkbase session flow:
#   - SB_SID   -> current sessionid cookie
#   - SB_SSOID -> current csrf_splunkbase_token cookie
get_splunkbase_cookies() {
    if [[ -z "${SB_SESSION_ID:-}" || -z "${SB_COOKIE_JAR:-}" || ! -f "${SB_COOKIE_JAR:-}" ]]; then
        get_splunkbase_session || return 1
    fi

    SB_SID=$(_read_cookie_jar_value "${SB_COOKIE_JAR}" "sessionid")
    SB_SSOID=$(_read_cookie_jar_value "${SB_COOKIE_JAR}" "csrf_splunkbase_token")

    if [[ -z "${SB_SID}" ]]; then
        echo "ERROR: Failed to read sessionid cookie from Splunkbase cookie jar." >&2
        return 1
    fi
}

# Legacy wrapper — kept for backward compatibility.
# Calls get_splunkbase_cookies() and returns a cookie string.
get_splunkbase_token() {
    get_splunkbase_cookies || return 1
    local cookie_str=""
    [[ -n "${SB_SID:-}" ]] && cookie_str="sessionid=${SB_SID}"
    [[ -n "${SB_SSOID:-}" ]] && cookie_str="${cookie_str:+${cookie_str}; }csrf_splunkbase_token=${SB_SSOID}"
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

form_urlencode_pairs() {
    if (( $# % 2 != 0 )); then
        echo "ERROR: form_urlencode_pairs requires key/value pairs." >&2
        return 1
    fi

    python3 - "$@" <<'PY'
import sys
from urllib.parse import quote_plus

args = sys.argv[1:]
parts = []
for i in range(0, len(args), 2):
    key = args[i]
    value = args[i + 1]
    parts.append(f"{quote_plus(key)}={quote_plus(value)}")

print("&".join(parts), end="")
PY
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

# Check if a saved search exists via REST.
# Usage: rest_check_saved_search <session_key> <splunk_uri> <app_name> <saved_search_name>
rest_check_saved_search() {
    local sk="$1" uri="$2" app="$3" search_name="$4"
    local encoded_name http_code
    encoded_name=$(_urlencode "${search_name}")
    http_code=$(splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/saved/searches/${encoded_name}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null)
    [[ "${http_code}" == "200" ]]
}

# Get a saved search content field via REST.
# Usage: rest_get_saved_search_value <session_key> <splunk_uri> <app_name> <saved_search_name> <key>
rest_get_saved_search_value() {
    local sk="$1" uri="$2" app="$3" search_name="$4" key="$5"
    local encoded_name
    encoded_name=$(_urlencode "${search_name}")
    splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/saved/searches/${encoded_name}?output_mode=json" \
        2>/dev/null \
        | python3 -c "
import json, sys
d = json.load(sys.stdin)
entries = d.get('entry', [])
print(entries[0].get('content', {}).get('${key}', '') if entries else '')
" 2>/dev/null || echo ""
}

# Enable a saved search via REST.
# Usage: rest_enable_saved_search <session_key> <splunk_uri> <app_name> <saved_search_name>
rest_enable_saved_search() {
    local sk="$1" uri="$2" app="$3" search_name="$4"
    local encoded_name http_code resp
    encoded_name=$(_urlencode "${search_name}")
    resp=$(splunk_curl_post "${sk}" "" \
        "${uri}/servicesNS/nobody/${app}/saved/searches/${encoded_name}/enable" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        200|201|409) return 0 ;;
        *) echo "ERROR: Enable saved search '${search_name}' failed (HTTP ${http_code})" >&2; return 1 ;;
    esac
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
    local body http_code resp
    body=$(form_urlencode_pairs name "${idx}" maxTotalDataSizeMB "${max_size}") || return 1
    resp=$(splunk_curl_post "${sk}" \
        "${body}" \
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
    local create_body encoded_stanza http_code resp
    encoded_stanza=$(_urlencode "${stanza}")
    resp=$(splunk_curl_post "${sk}" "${body}" \
        "${uri}/servicesNS/nobody/${app}/configs/conf-${conf}/${encoded_stanza}" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    [[ "${http_code}" == "200" ]] && return 0
    create_body=$(form_urlencode_pairs name "${stanza}") || return 1
    if [[ -n "${body}" ]]; then
        create_body="${create_body}&${body}"
    fi
    resp=$(splunk_curl_post "${sk}" "${create_body}" \
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
    local create_body encoded_name http_code resp enable_state body_without_disabled
    encoded_name=$(_urlencode "${input_name}")

    if [[ "${body}" =~ (^|&)disabled=([^&]+) ]]; then
        enable_state="${BASH_REMATCH[2]}"
    else
        enable_state=""
    fi

    body_without_disabled=$(printf '%s' "${body}" \
        | sed -E 's/(^|&)disabled=[^&]*//g; s/^&//; s/&+$//; s/&&+/\&/g')

    http_code=$(splunk_curl "${sk}" \
        "${endpoint}/${encoded_name}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null)
    if [[ "${http_code}" == "200" ]]; then
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

    create_body=$(form_urlencode_pairs name "${input_name}") || return 1
    if [[ -n "${body_without_disabled}" ]]; then
        create_body="${create_body}&${body_without_disabled}"
    fi
    resp=$(splunk_curl_post "${sk}" "${create_body}" \
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
    local body
    body=$(form_urlencode_pairs search "${search}" exec_mode "oneshot" output_mode "json") || return 1
    splunk_curl_post "${sk}" \
        "${body}" \
        "${uri}/services/search/jobs" 2>/dev/null \
        | python3 -c "
import json, sys
d = json.load(sys.stdin)
r = d.get('results', [])
print(r[0].get('${field}', '0') if r else '0')
" 2>/dev/null || echo "0"
}

# Restart Splunk via REST and print the HTTP status code. A code of 000 can
# occur if the connection closes as splunkd begins shutting down.
# Usage: rest_restart_splunk <session_key> <splunk_uri>
rest_restart_splunk() {
    local sk="$1" uri="$2"
    splunk_curl_post "${sk}" "" "${uri}/services/server/control/restart" \
        -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000"
}

# Wait until Splunk stops accepting login requests.
# Usage: wait_for_splunk_unavailable <splunk_uri> [timeout_secs] [interval_secs]
wait_for_splunk_unavailable() {
    local uri="$1" timeout_secs="${2:-90}" interval_secs="${3:-2}"
    local waited=0
    while (( waited < timeout_secs )); do
        if ! get_session_key "${uri}" >/dev/null 2>&1; then
            return 0
        fi
        sleep "${interval_secs}"
        waited=$((waited + interval_secs))
    done
    return 1
}

# Wait until Splunk accepts login requests again after a restart.
# Usage: wait_for_splunk_ready <splunk_uri> [timeout_secs] [interval_secs]
wait_for_splunk_ready() {
    local uri="$1" timeout_secs="${2:-300}" interval_secs="${3:-5}"
    local waited=0
    while (( waited < timeout_secs )); do
        if get_session_key "${uri}" >/dev/null 2>&1; then
            return 0
        fi
        sleep "${interval_secs}"
        waited=$((waited + interval_secs))
    done
    return 1
}

# Request a restart and wait for the management API to go down and come back.
# Sets SPLUNK_RESTART_HTTP_CODE for callers that want to log the initial result.
# Usage: restart_splunk_and_wait <session_key> <splunk_uri> [shutdown_timeout] [startup_timeout]
restart_splunk_and_wait() {
    local sk="$1" uri="$2" shutdown_timeout="${3:-90}" startup_timeout="${4:-300}"

    SPLUNK_RESTART_HTTP_CODE=$(rest_restart_splunk "${sk}" "${uri}")
    case "${SPLUNK_RESTART_HTTP_CODE}" in
        000|200|201|204) ;;
        *) return 1 ;;
    esac

    sleep 2
    wait_for_splunk_unavailable "${uri}" "${shutdown_timeout}" 2 || return 2
    wait_for_splunk_ready "${uri}" "${startup_timeout}" 5 || return 3
}

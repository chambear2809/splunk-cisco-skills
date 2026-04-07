#!/usr/bin/env bash
# Splunk REST API helpers: auth, curl wrappers, app/index/conf/input/search management.
# Sourced by credential_helpers.sh; not intended for direct use.
#
# See credential_helpers.sh for the sourcing contract.

[[ -n "${_REST_HELPERS_LOADED:-}" ]] && return 0
_REST_HELPERS_LOADED=true

# Shared Python helper for normalizing the Splunk 'disabled' field.
# Safe for interpolation inside double-quoted python3 -c strings.
_PY_NORMALIZE_DISABLED="
def _normalize_disabled(value):
    if isinstance(value, bool):
        return '1' if value else '0'
    text = str(value).strip().lower()
    if text in ('1', 'true'):
        return '1'
    if text in ('0', 'false'):
        return '0'
    return text
"

_curl_ssl_flags() {
    if [[ -n "${SPLUNK_CA_CERT:-}" || "${SPLUNK_VERIFY_SSL:-false}" == "true" ]]; then
        printf '%s' "-s"
    else
        printf '%s' "-sk"
    fi
}

_tls_verify_args=()

_bool_is_true() {
    case "${1:-}" in
        1|[Tt][Rr][Uu][Ee]|[Yy]|[Yy][Ee][Ss]|[Oo][Nn])
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

_warn_once() {
    local guard_var="$1"
    local message="$2"
    if [[ -n "${!guard_var:-}" ]]; then
        return 0
    fi
    printf '%s\n' "${message}" >&2
    printf -v "${guard_var}" '%s' "true"
}

_set_tls_verify_args() {
    local verify_value="${1:-}"
    local default_verify="${2:-true}"
    local ca_cert="${3:-}"
    local warning_guard="$4"
    local warning_message="$5"

    _tls_verify_args=()

    if [[ -n "${ca_cert}" ]]; then
        if [[ ! -f "${ca_cert}" ]]; then
            echo "ERROR: CA certificate file not found: ${ca_cert}" >&2
            return 1
        fi
        _tls_verify_args+=(--cacert "${ca_cert}")
        return 0
    fi

    if [[ -z "${verify_value}" ]]; then
        verify_value="${default_verify}"
    fi

    if _bool_is_true "${verify_value}"; then
        return 0
    fi

    _tls_verify_args+=(-k)
    _warn_once "${warning_guard}" "${warning_message}"
}

_set_splunk_curl_tls_args() {
    _set_tls_verify_args \
        "${SPLUNK_VERIFY_SSL:-}" \
        "false" \
        "${SPLUNK_CA_CERT:-}" \
        "_WARNED_SPLUNK_INSECURE_TLS" \
        "WARNING: TLS verification is disabled for Splunk REST connections. Set SPLUNK_VERIFY_SSL=true or SPLUNK_CA_CERT=/path/to/ca.pem to enable verification."
}

_set_splunkbase_curl_tls_args() {
    _set_tls_verify_args \
        "${SPLUNKBASE_VERIFY_SSL:-}" \
        "true" \
        "${SPLUNKBASE_CA_CERT:-}" \
        "_WARNED_SPLUNKBASE_INSECURE_TLS" \
        "WARNING: TLS verification is disabled for Splunkbase connections. Set SPLUNKBASE_VERIFY_SSL=true or SPLUNKBASE_CA_CERT=/path/to/ca.pem to enable verification."
}

_set_app_download_curl_tls_args() {
    local verify_value="${APP_DOWNLOAD_VERIFY_SSL:-${SPLUNK_VERIFY_SSL:-}}"
    local ca_cert="${APP_DOWNLOAD_CA_CERT:-${SPLUNK_CA_CERT:-}}"

    _set_tls_verify_args \
        "${verify_value}" \
        "false" \
        "${ca_cert}" \
        "_WARNED_APP_DOWNLOAD_INSECURE_TLS" \
        "WARNING: TLS verification is disabled for remote app downloads. Set APP_DOWNLOAD_VERIFY_SSL=true or APP_DOWNLOAD_CA_CERT=/path/to/ca.pem to enable verification."
}

splunk_tls_mode() {
    if [[ -n "${SPLUNK_CA_CERT:-}" ]]; then
        printf '%s' "ca-cert"
    elif _bool_is_true "${SPLUNK_VERIFY_SSL:-false}"; then
        printf '%s' "verify"
    else
        printf '%s' "insecure"
    fi
}

splunk_export_python_tls_env() {
    local tls_mode

    tls_mode="$(splunk_tls_mode)"
    if [[ "${tls_mode}" == "ca-cert" && ! -f "${SPLUNK_CA_CERT:-}" ]]; then
        echo "ERROR: CA certificate file not found: ${SPLUNK_CA_CERT}" >&2
        return 1
    fi

    if [[ "${tls_mode}" == "insecure" ]]; then
        _warn_once \
            "_WARNED_SPLUNK_INSECURE_TLS" \
            "WARNING: TLS verification is disabled for Splunk REST connections. Set SPLUNK_VERIFY_SSL=true or SPLUNK_CA_CERT=/path/to/ca.pem to enable verification."
    fi

    export __SPLUNK_TLS_MODE="${tls_mode}"
    export __SPLUNK_TLS_CA_CERT="${SPLUNK_CA_CERT:-}"
}

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Guard for flag parsers: validates that a flag's required value is present.
# Usage (inside a while/case arg loop):
#   --flag) require_arg "$1" $# || exit 1; VAR="$2"; shift 2 ;;
require_arg() {
    if [[ "$2" -lt 2 ]]; then
        log "ERROR: Option '$1' requires a value."
        return 1
    fi
}

verify_search_api_connectivity() {
    local uri="${1:-${SPLUNK_URI:-https://localhost:8089}}"
    local host port http_code

    host="$(python3 -c "from urllib.parse import urlparse; p=urlparse('${uri}'); print(p.hostname or '')" 2>/dev/null || true)"
    port="$(python3 -c "from urllib.parse import urlparse; p=urlparse('${uri}'); print(p.port or 8089)" 2>/dev/null || echo 8089)"

    if command -v nc >/dev/null 2>&1; then
        local nc_timeout_flag="-G 5"  # macOS
        # GNU nc uses -w for connect timeout; detect by checking if -G is supported
        if ! nc -z -G 1 127.0.0.1 1 >/dev/null 2>&1 && nc -h 2>&1 | grep -q '\-w'; then
            nc_timeout_flag="-w 5"
        fi
        # shellcheck disable=SC2086  # nc_timeout_flag is intentionally unquoted
        if ! nc -z ${nc_timeout_flag} "${host}" "${port}" >/dev/null 2>&1; then
            echo "ERROR: Cannot reach ${host}:${port} (connection refused or timed out)." >&2
            if type is_splunk_cloud &>/dev/null && is_splunk_cloud 2>/dev/null; then
                echo "  HINT: Your IP may not be on the search-api allowlist. Run:" >&2
                echo "    acs ip-allowlist create search-api --subnets \$(curl -s https://checkip.amazonaws.com)/32" >&2
            fi
            return 1
        fi
    fi

    _set_splunk_curl_tls_args || return 1
    http_code=$(curl -s ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} --connect-timeout 8 --max-time 15 \
        -o /dev/null -w '%{http_code}' "${uri}/services/auth/login" 2>/dev/null || echo "000")
    case "${http_code}" in
        000)
            echo "ERROR: No HTTP response from ${uri} (TLS handshake or network failure)." >&2
            return 1
            ;;
        401|400|200|303)
            return 0
            ;;
        403)
            echo "ERROR: HTTP 403 from ${uri}. The endpoint is reachable but rejecting requests." >&2
            if type is_splunk_cloud &>/dev/null && is_splunk_cloud 2>/dev/null; then
                echo "  HINT: Your IP may not be on the search-api allowlist." >&2
            fi
            return 1
            ;;
        *)
            echo "ERROR: Unexpected HTTP ${http_code} from ${uri}/services/auth/login." >&2
            return 1
            ;;
    esac
}

get_session_key() {
    local uri="${1:-https://localhost:8089}"
    local body sk
    _set_splunk_curl_tls_args || return 1
    body=$(form_urlencode_pairs username "${SPLUNK_USER}" password "${SPLUNK_PASS}") || return 1
    sk=$(printf '%s' "${body}" \
        | curl -s ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} --connect-timeout 10 --max-time 30 "${uri}/services/auth/login" -d @- 2>/dev/null \
        | sed -n 's/.*<sessionKey>\([^<]*\)<.*/\1/p' || true)

    if [[ -z "${sk}" ]]; then
        verify_search_api_connectivity "${uri}" 2>&1 | while IFS= read -r line; do echo "${line}" >&2; done
        return 1
    fi
    printf '%s' "${sk}"
}

splunk_curl() {
    local sk="$1"; shift
    _set_splunk_curl_tls_args || return 1
    curl -s ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} -K <(printf 'header = "Authorization: Splunk %s"\n' "${sk}") "$@"
}

splunk_curl_post() {
    local sk="$1"; shift
    local post_data="$1"; shift
    _set_splunk_curl_tls_args || return 1
    printf '%s' "${post_data}" \
        | curl -s ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} -K <(printf 'header = "Authorization: Splunk %s"\n' "${sk}") -d @- "$@"
}

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

_curl_config_escape() {
    python3 - "$1" <<'PY'
import sys
print(sys.argv[1].replace('\\', '\\\\').replace('"', '\\"'))
PY
}

_is_splunk_package() {
    python3 - "$1" <<'PY'
import sys
import tarfile

sys.exit(0 if tarfile.is_tarfile(sys.argv[1]) else 1)
PY
}

sanitize_response() {
    local resp="$1"
    local max_lines="${2:-20}"
    python3 - "${max_lines}" 3<<<"${resp}" <<'PY'
import json
import os
import re
import sys

max_lines = int(sys.argv[1])
with os.fdopen(3, encoding="utf-8", errors="replace") as handle:
    text = handle.read()

def is_sensitive_key(key):
    normalized = re.sub(r"[^a-z0-9]+", "", str(key).lower())
    return any(token in normalized for token in (
        "password",
        "secret",
        "token",
        "apikey",
        "clientsecret",
        "sessionkey",
        "certificate",
        "privatekey",
        "jsontext",
        "accesssecret",
        "externalid",
        "passphrase",
    ))

def redact_json(value):
    if isinstance(value, dict):
        return {
            key: ("REDACTED" if is_sensitive_key(key) else redact_json(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    return value

def redact_text(raw):
    key_pattern = r"[A-Za-z0-9_.-]*?(?:password|secret|token|api[_-]?key|client[_-]?secret|sessionkey|certificate|private[_-]?key|json[_-]?text|access[_-]?secret|external[_-]?id|passphrase)[A-Za-z0-9_.-]*"

    def replace_equals(match):
        return f"{match.group(1)}{match.group(2)}REDACTED"

    def replace_colon(match):
        value = match.group(3)
        if value.startswith('"') and value.endswith('"'):
            replacement = '"REDACTED"'
        elif value.startswith("'") and value.endswith("'"):
            replacement = "'REDACTED'"
        else:
            replacement = "REDACTED"
        return f"{match.group(1)}{match.group(2)}{replacement}"

    raw = re.sub(
        rf"(?i)\b({key_pattern})\b(\s*=\s*)([^&\s]+)",
        replace_equals,
        raw,
    )
    raw = re.sub(
        rf"""(?ix)
        (["']?\b{key_pattern}\b["']?)
        (\s*:\s*)
        ("[^"]*"|'[^']*'|[^,\}}\]\s]+)
        """,
        replace_colon,
        raw,
    )
    return raw

try:
    sanitized = json.dumps(redact_json(json.loads(text)))
except Exception:
    sanitized = redact_text(text)

lines = sanitized.splitlines() or [sanitized]
for line in lines[:max_lines]:
    print(line)
PY
}

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

rest_check_app() {
    local sk="$1" uri="$2" app="$3"
    local http_code
    http_code=$(splunk_curl "${sk}" --connect-timeout 5 --max-time 15 \
        "${uri}/services/apps/local/${app}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null)
    [[ "${http_code}" == "200" ]]
}

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

_py_json_field() {
    python3 -c "
import json, sys
key = sys.argv[1]
d = json.load(sys.stdin)
entries = d.get('entry', [])
print(entries[0].get('content', {}).get(key, '') if entries else '')
" "$@" 2>/dev/null || echo ""
}

rest_check_saved_search() {
    local sk="$1" uri="$2" app="$3" search_name="$4"
    local encoded_name http_code
    encoded_name=$(_urlencode "${search_name}")
    http_code=$(splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/saved/searches/${encoded_name}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null)
    [[ "${http_code}" == "200" ]]
}

rest_get_saved_search_value() {
    local sk="$1" uri="$2" app="$3" search_name="$4" key="$5"
    local encoded_name
    encoded_name=$(_urlencode "${search_name}")
    splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/saved/searches/${encoded_name}?output_mode=json" \
        2>/dev/null \
        | _py_json_field "${key}"
}

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

rest_check_index() {
    local sk="$1" uri="$2" idx="$3"
    local http_code
    http_code=$(splunk_curl "${sk}" \
        "${uri}/services/data/indexes/${idx}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null)
    [[ "${http_code}" == "200" ]]
}

rest_get_index_datatype() {
    local sk="$1" uri="$2" idx="$3"
    splunk_curl "${sk}" \
        "${uri}/services/data/indexes/${idx}?output_mode=json" 2>/dev/null \
        | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    entries = d.get('entry', [])
    datatype = ''
    if entries:
        datatype = str(entries[0].get('content', {}).get('datatype', '')).strip()
    if datatype:
        print(datatype, end='')
    else:
        print('event', end='')
except Exception:
    print('', end='')
" 2>/dev/null || echo ""
}

rest_create_index() {
    local sk="$1" uri="$2" idx="$3" max_size="${4:-512000}" index_type="${5:-event}"
    local body http_code resp
    case "${index_type}" in
        metric)
            body=$(form_urlencode_pairs name "${idx}" maxTotalDataSizeMB "${max_size}" datatype "metric") || return 1
            ;;
        ""|event)
            body=$(form_urlencode_pairs name "${idx}" maxTotalDataSizeMB "${max_size}") || return 1
            ;;
        *)
            echo "ERROR: Unsupported index type '${index_type}' for index '${idx}'." >&2
            return 1
            ;;
    esac
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

rest_set_conf() {
    local sk="$1" uri="$2" app="$3" conf="$4" stanza="$5" body="$6"
    local create_body encoded_stanza http_code resp

    if type deployment_should_manage_search_config_via_bundle >/dev/null 2>&1 \
        && deployment_should_manage_search_config_via_bundle; then
        deployment_bundle_set_conf_for_current_target "${app}" "${conf}" "${stanza}" "${body}"
        return $?
    fi

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

rest_set_verify_ssl() {
    local sk="$1" uri="$2" app="$3" conf="$4" stanza="$5" field="${6:-verify_ssl}" value="$7"
    local body
    body=$(form_urlencode_pairs "${field}" "${value}") || return 1
    rest_set_conf "${sk}" "${uri}" "${app}" "${conf}" "${stanza}" "${body}"
}

rest_check_conf() {
    local sk="$1" uri="$2" app="$3" conf="$4" stanza="$5"
    local encoded_stanza http_code
    encoded_stanza=$(_urlencode "${stanza}")
    http_code=$(splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/configs/conf-${conf}/${encoded_stanza}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null)
    [[ "${http_code}" == "200" ]]
}

rest_get_conf_value() {
    local sk="$1" uri="$2" app="$3" conf="$4" stanza="$5" key="$6"
    local encoded_stanza
    encoded_stanza=$(_urlencode "${stanza}")
    splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/configs/conf-${conf}/${encoded_stanza}?output_mode=json" \
        2>/dev/null \
        | _py_json_field "${key}"
}

rest_count_conf_stanzas() {
    local sk="$1" uri="$2" app="$3" conf="$4" prefix="${5:-}"
    splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/configs/conf-${conf}?output_mode=json&count=0" \
        2>/dev/null \
        | python3 -c "
import json, sys
prefix = sys.argv[1] if len(sys.argv) > 1 else ''
d = json.load(sys.stdin)
entries = d.get('entry', [])
if prefix:
    entries = [e for e in entries if e.get('name', '').startswith(prefix)]
print(len(entries))
" "${prefix}" 2>/dev/null || echo "0"
}

rest_count_live_inputs() {
    local sk="$1" uri="$2" app="$3" disabled_filter="${4:-}"
    splunk_curl "${sk}" \
        "${uri}/services/data/inputs/all?output_mode=json&count=0" \
        2>/dev/null \
        | python3 -c "${_PY_NORMALIZE_DISABLED}
import json, sys
target_app = sys.argv[1]
disabled_filter = sys.argv[2] if len(sys.argv) > 2 else ''

try:
    data = json.load(sys.stdin)
    count = 0
    for entry in data.get('entry', []):
        acl = entry.get('acl', {}) or {}
        content = entry.get('content', {}) or {}
        entry_app = acl.get('app', '')
        if entry_app != target_app:
            continue
        disabled = _normalize_disabled(content.get('disabled'))
        if disabled_filter and disabled != disabled_filter:
            continue
        count += 1
    print(count)
except Exception:
    print(0)
" "${app}" "${disabled_filter}" 2>/dev/null || echo "0"
}

rest_get_live_input_counts() {
    local sk="$1" uri="$2" app="$3"
    splunk_curl "${sk}" \
        "${uri}/services/data/inputs/all?output_mode=json&count=0" \
        2>/dev/null \
        | python3 -c "${_PY_NORMALIZE_DISABLED}
import json, sys
target_app = sys.argv[1]
total = enabled = disabled = 0

try:
    data = json.load(sys.stdin)
    for entry in data.get('entry', []):
        acl = entry.get('acl', {}) or {}
        content = entry.get('content', {}) or {}
        if acl.get('app', '') != target_app:
            continue
        total += 1
        normalized = _normalize_disabled(content.get('disabled'))
        if normalized == '0':
            enabled += 1
        elif normalized == '1':
            disabled += 1
    print(f'{total} {enabled} {disabled}')
except Exception:
    print('0 0 0')
" "${app}" 2>/dev/null || echo "0 0 0"
}

rest_get_hec_token_state() {
    local sk="$1" uri="$2" token_name="$3"
    splunk_curl "${sk}" \
        "${uri}/services/data/inputs/http?output_mode=json&count=0" \
        2>/dev/null \
        | python3 -c "
import json, sys
target = sys.argv[1]
aliases = {target, f'http://{target}'}
try:
    data = json.load(sys.stdin)
    for entry in data.get('entry', []):
        name = entry.get('name', '')
        if name not in aliases:
            continue
        disabled = str(entry.get('content', {}).get('disabled', False)).strip().lower()
        if disabled in ('1', 'true'):
            print('disabled', end='')
        else:
            print('enabled', end='')
        raise SystemExit(0)
    print('missing', end='')
except Exception:
    print('unknown', end='')
" "${token_name}" 2>/dev/null || echo "unknown"
}

rest_get_hec_token_record() {
    local sk="$1" uri="$2" token_name="$3"
    splunk_curl "${sk}" \
        "${uri}/services/data/inputs/http?output_mode=json&count=0" \
        2>/dev/null \
        | python3 -c "
import json
import sys

target = sys.argv[1]
aliases = {target, f'http://{target}'}
try:
    data = json.load(sys.stdin)
    for entry in data.get('entry', []):
        name = entry.get('name', '')
        if name not in aliases:
            continue
        content = entry.get('content', {}) or {}
        indexes = content.get('indexes', '')
        if isinstance(indexes, list):
            indexes = ','.join(str(item) for item in indexes)
        record = {
            'name': name,
            'disabled': str(content.get('disabled', '')),
            'useACK': str(content.get('useACK', content.get('useAck', ''))),
            'indexes': str(indexes),
            'default_index': str(content.get('index', '')),
            'token': str(content.get('token', '')),
        }
        print(json.dumps(record), end='')
        raise SystemExit(0)
except Exception:
    pass

print('{}', end='')
" "${token_name}" 2>/dev/null
}

rest_json_field() {
    local json_text="$1" field="$2"
    printf '%s' "${json_text}" | python3 -c "
import json
import sys

field = sys.argv[1]
try:
    data = json.load(sys.stdin)
    value = data.get(field, '')
    if value is None:
        print('', end='')
    elif isinstance(value, bool):
        print('true' if value else 'false', end='')
    else:
        print(str(value), end='')
except Exception:
    print('', end='')
" "${field}" 2>/dev/null
}

rest_list_ta_stanzas() {
    local sk="$1" uri="$2" app="$3" handler="$4"
    splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app}/${handler}?output_mode=json&count=0" \
        2>/dev/null
}

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

rest_oneshot_search() {
    local sk="$1" uri="$2" search="$3" field="$4"
    local body
    body=$(form_urlencode_pairs search "${search}" exec_mode "oneshot" output_mode "json") || return 1
    splunk_curl_post "${sk}" \
        "${body}" \
        "${uri}/services/search/jobs" 2>/dev/null \
        | python3 -c "
import json, sys
field = sys.argv[1]
d = json.load(sys.stdin)
r = d.get('results', [])
print(r[0].get(field, '0') if r else '0')
" "${field}" 2>/dev/null || echo "0"
}

rest_restart_splunk() {
    local sk="$1" uri="$2"
    splunk_curl_post "${sk}" "" "${uri}/services/server/control/restart" \
        -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000"
}

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

restart_splunk_and_wait() {
    local sk="$1" uri="$2" shutdown_timeout="${3:-90}" startup_timeout="${4:-300}"

    # shellcheck disable=SC2034  # read by callers after restart_splunk_and_wait returns
    SPLUNK_RESTART_HTTP_CODE=$(rest_restart_splunk "${sk}" "${uri}")
    case "${SPLUNK_RESTART_HTTP_CODE}" in
        000|200|201|204) ;;
        *) return 1 ;;
    esac

    sleep 2
    wait_for_splunk_unavailable "${uri}" "${shutdown_timeout}" 2 || return 2
    wait_for_splunk_ready "${uri}" "${startup_timeout}" 5 || return 3
}

# Restart Splunk via REST and wait, with user-facing log messages.
# Expects RESTART_SPLUNK (bool) as a script-level global.
#
# Usage: app_restart_splunk_or_exit <sk> <uri> <operation> [skip_message]
app_restart_splunk_or_exit() {
    local sk="$1" uri="$2" operation="$3"
    local skip_msg="${4:-Restart manually before relying on the updated state.}"
    local rc

    if [[ "${RESTART_SPLUNK:-true}" != "true" ]]; then
        log "Skipping Splunk restart (--no-restart). ${skip_msg}"
        return 0
    fi

    log ""
    log "Restarting Splunk to complete ${operation}..."
    log "Waiting for the management API to cycle..."

    restart_splunk_and_wait "${sk}" "${uri}"
    rc=$?

    case "${SPLUNK_RESTART_HTTP_CODE:-}" in
        000)
            log "Restart request closed before an HTTP response was returned, which can happen during shutdown."
            ;;
        200|201|204)
            log "Restart request accepted (HTTP ${SPLUNK_RESTART_HTTP_CODE})."
            ;;
    esac

    case "${rc}" in
        0)
            log "SUCCESS: Splunk restart completed and the management API is responding again."
            ;;
        1)
            log "ERROR: Failed to request a Splunk restart (HTTP ${SPLUNK_RESTART_HTTP_CODE:-unknown})."
            return 1
            ;;
        2)
            log "ERROR: Splunk did not stop responding after the restart request."
            return 1
            ;;
        3)
            log "ERROR: Splunk did not come back online before the restart timeout expired."
            return 1
            ;;
        *)
            log "ERROR: Unexpected restart failure."
            return 1
            ;;
    esac
}

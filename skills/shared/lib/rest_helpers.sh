#!/usr/bin/env bash
# Splunk REST API helpers: auth, curl wrappers, app/index/conf/input/search management.
# Sourced by credential_helpers.sh; not intended for direct use.

[[ -n "${_REST_HELPERS_LOADED:-}" ]] && return 0
_REST_HELPERS_LOADED=true

_curl_ssl_flags() {
    if [[ "${SPLUNK_VERIFY_SSL:-false}" == "true" ]]; then
        printf '%s' "-s"
    else
        printf '%s' "-sk"
    fi
}

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

verify_search_api_connectivity() {
    local uri="${1:-${SPLUNK_URI:-https://localhost:8089}}"
    local host port ssl_flags http_code

    host="$(python3 -c "from urllib.parse import urlparse; p=urlparse('${uri}'); print(p.hostname or '')" 2>/dev/null || true)"
    port="$(python3 -c "from urllib.parse import urlparse; p=urlparse('${uri}'); print(p.port or 8089)" 2>/dev/null || echo 8089)"

    if command -v nc >/dev/null 2>&1; then
        if ! nc -z -G 5 "${host}" "${port}" >/dev/null 2>&1; then
            echo "ERROR: Cannot reach ${host}:${port} (connection refused or timed out)." >&2
            if type is_splunk_cloud &>/dev/null && is_splunk_cloud 2>/dev/null; then
                echo "  HINT: Your IP may not be on the search-api allowlist. Run:" >&2
                echo "    acs ip-allowlist create search-api --subnets \$(curl -s https://checkip.amazonaws.com)/32" >&2
            fi
            return 1
        fi
    fi

    ssl_flags="$(_curl_ssl_flags)"
    http_code=$(curl ${ssl_flags} --connect-timeout 8 --max-time 15 \
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
    local body sk ssl_flags
    ssl_flags="$(_curl_ssl_flags)"
    body=$(form_urlencode_pairs username "${SPLUNK_USER}" password "${SPLUNK_PASS}") || return 1
    sk=$(printf '%s' "${body}" \
        | curl ${ssl_flags} --connect-timeout 10 --max-time 30 "${uri}/services/auth/login" -d @- 2>/dev/null \
        | sed -n 's/.*<sessionKey>\([^<]*\)<.*/\1/p' || true)

    if [[ -z "${sk}" ]]; then
        verify_search_api_connectivity "${uri}" 2>&1 | while IFS= read -r line; do echo "${line}" >&2; done
        return 1
    fi
    printf '%s' "${sk}"
}

splunk_curl() {
    local sk="$1"; shift
    local ssl_flags
    ssl_flags="$(_curl_ssl_flags)"
    curl ${ssl_flags} -K <(printf 'header = "Authorization: Splunk %s"\n' "${sk}") "$@"
}

splunk_curl_post() {
    local sk="$1"; shift
    local post_data="$1"; shift
    local ssl_flags
    ssl_flags="$(_curl_ssl_flags)"
    printf '%s' "${post_data}" \
        | curl ${ssl_flags} -K <(printf 'header = "Authorization: Splunk %s"\n' "${sk}") -d @- "$@"
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
    printf '%s' "${resp}" \
        | sed -E 's/(password|secret|token|api_key|client_secret|sessionKey)=[^ &"]*/\1=REDACTED/gi' \
        | head -"${max_lines}"
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
    http_code=$(splunk_curl "${sk}" \
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
        | python3 -c "
import json, sys
target_app = sys.argv[1]
disabled_filter = sys.argv[2] if len(sys.argv) > 2 else ''

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
" "${app}" "${disabled_filter}" 2>/dev/null || echo "0"
}

rest_get_live_input_counts() {
    local sk="$1" uri="$2" app="$3"
    splunk_curl "${sk}" \
        "${uri}/services/data/inputs/all?output_mode=json&count=0" \
        2>/dev/null \
        | python3 -c "
import json, sys
target_app = sys.argv[1]
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

    SPLUNK_RESTART_HTTP_CODE=$(rest_restart_splunk "${sk}" "${uri}")
    case "${SPLUNK_RESTART_HTTP_CODE}" in
        000|200|201|204) ;;
        *) return 1 ;;
    esac

    sleep 2
    wait_for_splunk_unavailable "${uri}" "${shutdown_timeout}" 2 || return 2
    wait_for_splunk_ready "${uri}" "${startup_timeout}" 5 || return 3
}

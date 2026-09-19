#!/usr/bin/env bash
# ACS CLI context management, output parsing, status checks, and restart helpers.
# Sourced by credential_helpers.sh; not intended for direct use.
#
# See credential_helpers.sh for the sourcing contract.

[[ -n "${_ACS_HELPERS_LOADED:-}" ]] && return 0
_ACS_HELPERS_LOADED=true

_ACS_CONTEXT_PREPARED=false
_ACS_CONTEXT_TARGET=""
_ACS_CONTEXT_IDENTITY=""

_acs_invalidate_context() {
    _ACS_CONTEXT_PREPARED=false
    _ACS_CONTEXT_TARGET=""
    _ACS_CONTEXT_IDENTITY=""
}

_acs_apply_bound_target_context() {
    local bound_stack="${ACS_BOUND_SPLUNK_CLOUD_STACK:-}"
    local bound_search_head="${ACS_BOUND_SPLUNK_CLOUD_SEARCH_HEAD:-}"
    local bound_server="${ACS_BOUND_SERVER:-}"
    local configured_stack="${SPLUNK_CLOUD_STACK:-}"
    local configured_search_head="${SPLUNK_CLOUD_SEARCH_HEAD:-}"
    local configured_server="${ACS_SERVER:-https://admin.splunk.com}"

    [[ "${ACS_BOUND_TARGET_CONTEXT:-false}" == "true" ]] || return 0
    if [[ ! "${bound_stack}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
        echo "ERROR: The rendered ACS target stack identity is missing or invalid." >&2
        return 1
    fi
    if [[ -n "${bound_search_head}" \
        && ! "${bound_search_head}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
        echo "ERROR: The rendered ACS target search-head identity is invalid." >&2
        return 1
    fi
    if ! _acs_validate_server "${bound_server}"; then
        echo "ERROR: The rendered ACS control-plane origin is missing or invalid." >&2
        return 1
    fi
    if [[ "${ACS_BOUND_REQUIRE_CONFIG_MATCH:-false}" == "true" ]]; then
        if [[ "${configured_server}" != "${bound_server}" ]]; then
            echo "ERROR: The configured ACS control-plane origin changed after the rendered target was reviewed." >&2
            return 1
        fi
        if [[ -n "${configured_stack}" && "${configured_stack}" != "${bound_stack}" ]]; then
            echo "ERROR: The configured ACS stack changed after the rendered target was reviewed." >&2
            return 1
        fi
        if [[ -n "${configured_search_head}" \
            && "${configured_search_head}" != "${bound_search_head}" ]]; then
            echo "ERROR: The configured ACS search-head target changed after the rendered target was reviewed." >&2
            return 1
        fi
    fi
    SPLUNK_CLOUD_STACK="${bound_stack}"
    SPLUNK_CLOUD_SEARCH_HEAD="${bound_search_head}"
    ACS_SERVER="${bound_server}"
    export SPLUNK_CLOUD_STACK SPLUNK_CLOUD_SEARCH_HEAD ACS_SERVER
}

acs_cli_available() {
    command -v acs >/dev/null 2>&1
}
_acs_cli_command() {
    local server="${ACS_SERVER:-https://admin.splunk.com}"
    _acs_validate_server "${server}" || return 1
    command acs --format structured --server "${server}" "$@"
}

_acs_cli_current_stack_command() {
    local server="${ACS_SERVER:-https://admin.splunk.com}"
    _acs_validate_server "${server}" || return 1
    # Keep the stable local config identity surface in its documented form.
    command acs --server "${server}" config current-stack
}

acs_command() {
    if ! load_splunk_platform_settings; then
        return 1
    fi
    if ! _acs_apply_bound_target_context; then
        return 1
    fi
    local server="${ACS_SERVER:-https://admin.splunk.com}"
    local current_target=""
    local -a cmd=(acs --format structured)
    if ! _acs_validate_server "${server}"; then
        echo "ERROR: ACS_SERVER must be exactly https://admin.splunk.com or https://staging.admin.splunk.com." >&2
        return 1
    fi
    if [[ "${_ACS_CONTEXT_PREPARED}" != "true" ]]; then
        if ! acs_prepare_context; then
            return 1
        fi
    fi
    if [[ "${_ACS_CONTEXT_PREPARED}" == "true" ]]; then
        current_target="$(_acs_context_target_key)"
        if [[ -z "${_ACS_CONTEXT_TARGET}" || "${current_target}" != "${_ACS_CONTEXT_TARGET}" ]]; then
            _acs_invalidate_context
            echo "ERROR: ACS target changed after context preparation; refusing the command." >&2
            return 1
        fi
        if ! _acs_verify_current_context; then
            _acs_invalidate_context
            echo "ERROR: ACS CLI current context changed after preparation; refusing the command." >&2
            return 1
        fi
    fi
    cmd+=(--server "${server}")
    cmd+=("$@")
    "${cmd[@]}"
}

_acs_validate_server() {
    case "${1:-}" in
        https://admin.splunk.com|https://staging.admin.splunk.com) return 0 ;;
        *) return 1 ;;
    esac
}

_acs_validate_rest_url() {
    local url="${1:-}" server="${2:-}"

    python3 - "${url}" "${server}" <<'PY'
import sys
from urllib.parse import urlsplit

raw, server_raw = sys.argv[1:]
try:
    parsed = urlsplit(raw)
    server = urlsplit(server_raw)
    parsed.port
    server.port
except ValueError:
    raise SystemExit(1)

valid = (
    parsed.scheme.lower() == "https"
    and bool(parsed.hostname)
    and (parsed.scheme.lower(), parsed.hostname.lower(), parsed.port)
    == (server.scheme.lower(), server.hostname.lower(), server.port)
    and parsed.username is None
    and parsed.password is None
    and parsed.path.startswith("/")
    and not parsed.fragment
    and not any(character.isspace() for character in raw)
)
raise SystemExit(0 if valid else 1)
PY
}

_acs_validate_rest_curl_args() {
    local argument="" expect_value=false option=""

    for argument in "$@"; do
        if [[ "${expect_value}" == "true" ]]; then
            if [[ "${option}" == "-H" || "${option}" == "--header" ]]; then
                if [[ "${argument}" == *$'\n'* || "${argument}" == *$'\r'* || "${argument}" == @* ]]; then
                    echo "ERROR: ACS REST helper rejected an unsafe header value." >&2
                    return 1
                fi
                case "${argument%%:*}" in
                    [Cc]ontent-[Tt]ype|[Aa]ccept) ;;
                    *)
                        echo "ERROR: ACS REST helper permits only Content-Type or Accept caller headers; authentication is helper-owned." >&2
                        return 1
                        ;;
                    esac
            fi
            if [[ "${option}" == "-d" || "${option}" == "--data" || "${option}" == "--data-binary" ]]; then
                if [[ "${argument}" == @* && "${argument}" != "@-" ]]; then
                    echo "ERROR: ACS REST helper rejects file-backed request bodies; stream a descriptor-validated file on stdin with @-." >&2
                    return 1
                fi
            fi
            expect_value=false
            option=""
            continue
        fi
        case "${argument}" in
            -X|--request|-H|--header|-d|--data|--data-binary|-o|--output|-w|--write-out|--connect-timeout|--max-time)
                expect_value=true
                option="${argument}"
                ;;
            --header=*)
                echo "ERROR: ACS REST helper requires caller headers as a separate, validated argument." >&2
                return 1
                ;;
            --data=@*|--data-binary=@*)
                if [[ "${argument#*=}" != "@-" ]]; then
                    echo "ERROR: ACS REST helper rejects file-backed request bodies; stream a descriptor-validated file on stdin with @-." >&2
                    return 1
                fi
                ;;
            --request=*|--data=*|--data-binary=*|--output=*|--write-out=*|--connect-timeout=*|--max-time=*)
                ;;
            -f|--fail|--fail-with-body|-s|--silent|-S|--show-error)
                ;;
            --|--next|--config|--config=*|-K*|-[^-]*K*|-:*|-[^-]*:*|\
            -L*|-[^-]*L*|--location|--location-trusted|--max-redirs|--max-redirs=*|\
            --proto|--proto=*|--proto-redir|--proto-redir=*|--proto-default|--proto-default=*|\
            --globoff|--no-globoff|-g|--url|--url=*|--variable|--variable=*|--expand-*|\
            -k*|-[^-]*k*|--insecure|--no-insecure|--cacert|--cacert=*|--capath|--capath=*)
                echo "ERROR: ACS REST helper rejected caller-owned curl transport/configuration option: ${argument}" >&2
                return 1
                ;;
            -*|*)
                echo "ERROR: ACS REST helper rejected unsupported curl argument." >&2
                return 1
                ;;
        esac
    done
    if [[ "${expect_value}" == "true" ]]; then
        echo "ERROR: ACS REST helper received ${option} without a value." >&2
        return 1
    fi
}

# acs_rest_curl <absolute-https-url> [supported curl args]
#
# API-only ACS endpoints are not all exposed by the ACS CLI. Keep their bearer
# token off argv while enforcing the same transport boundary as Splunk REST:
# HTTPS only, no redirects, no URL globbing, no user/system curl config, and
# exactly the URL supplied as the first argument.
acs_rest_curl() {
    local url="${1:-}" token_escaped="" server=""
    shift || true

    if ! load_splunk_platform_settings; then
        return 1
    fi
    if ! _acs_apply_bound_target_context; then
        return 1
    fi
    server="${ACS_SERVER:-https://admin.splunk.com}"
    if ! _acs_validate_server "${server}"; then
        echo "ERROR: ACS_SERVER must be exactly https://admin.splunk.com or https://staging.admin.splunk.com." >&2
        return 1
    fi
    if ! _acs_validate_rest_url "${url}" "${server}"; then
        echo "ERROR: ACS REST URL must be a credential-free HTTPS URL on the configured, allowlisted ACS_SERVER origin." >&2
        return 1
    fi
    _acs_validate_rest_curl_args "$@" || return 1
    if [[ -z "${STACK_TOKEN:-}" || "${STACK_TOKEN}" == *$'\n'* || "${STACK_TOKEN}" == *$'\r'* ]]; then
        echo "ERROR: STACK_TOKEN must contain one non-empty line for ACS REST calls." >&2
        return 1
    fi

    if declare -F _curl_config_escape >/dev/null 2>&1; then
        token_escaped="$(_curl_config_escape "${STACK_TOKEN}")"
    else
        token_escaped="${STACK_TOKEN//\\/\\\\}"
        token_escaped="${token_escaped//\"/\\\"}"
    fi

    command curl -q -fsS "$@" \
        -K <(printf 'header = "Authorization: Bearer %s"\n' "${token_escaped}") \
        "${url}" \
        --proto '=https' --proto-redir '=https' --max-redirs 0 --globoff
}

acs_extract_http_response_json() {
    python3 -c '
import json
import sys

text = sys.stdin.read().strip()
if not text:
    print("{}", end="")
    raise SystemExit(0)

try:
    data = json.loads(text)
except Exception:
    print("{}", end="")
    raise SystemExit(0)

payload = None
if isinstance(data, list):
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "http":
            continue
        response = item.get("response")
        if isinstance(response, str) and response.strip():
            try:
                payload = json.loads(response)
                break
            except Exception:
                pass
        payload = item
        break
elif isinstance(data, dict):
    payload = data

json.dump(payload or {}, sys.stdout)
'
}

acs_apps_list_all_json() {
    local offset=0 count=100 page page_raw app_count tmp_file rc
    local -a extra_args=() cmd

    if (( $# > 0 )); then
        extra_args=("$@")
    fi

    tmp_file="$(mktemp)"
    printf '[]' > "${tmp_file}"

    while true; do
        cmd=(apps list)
        if (( ${#extra_args[@]} > 0 )); then
            cmd+=("${extra_args[@]}")
        fi
        cmd+=(--count "${count}" --offset "${offset}")

        if ! page_raw="$(acs_command "${cmd[@]}" 2>/dev/null)"; then
            rm -f "${tmp_file}"
            return 1
        fi
        if ! page="$(printf '%s' "${page_raw}" | acs_extract_http_response_json)"; then
            rm -f "${tmp_file}"
            return 1
        fi

        app_count="$(ACS_APPS_PAGE="${page}" ACS_APPS_STATE_FILE="${tmp_file}" python3 - <<'PY'
import json
import os
import sys

state_path = os.environ["ACS_APPS_STATE_FILE"]
page_text = os.environ.get("ACS_APPS_PAGE", "{}")

try:
    with open(state_path, encoding="utf-8") as handle:
        apps = json.load(handle)
except Exception:
    raise SystemExit(1)

if not isinstance(apps, list):
    raise SystemExit(1)

try:
    page = json.loads(page_text)
except Exception:
    raise SystemExit(1)

if not isinstance(page, dict) or "apps" not in page or not isinstance(page["apps"], list):
    raise SystemExit(1)
page_apps = page["apps"]
if any(not isinstance(app, dict) for app in page_apps):
    raise SystemExit(1)

apps.extend(page_apps)

with open(state_path, "w", encoding="utf-8") as handle:
    json.dump(apps, handle)

print(len(page_apps), end="")
PY
)" || {
            rm -f "${tmp_file}"
            return 1
        }

        [[ "${app_count}" =~ ^[0-9]+$ ]] || {
            rm -f "${tmp_file}"
            return 1
        }

        if (( app_count < count )); then
            break
        fi

        offset=$((offset + count))
    done

    if ACS_APPS_STATE_FILE="${tmp_file}" python3 - <<'PY'
import json
import os
import sys

state_path = os.environ["ACS_APPS_STATE_FILE"]

try:
    with open(state_path, encoding="utf-8") as handle:
        apps = json.load(handle)
except Exception:
    raise SystemExit(1)

if not isinstance(apps, list) or any(not isinstance(app, dict) for app in apps):
    raise SystemExit(1)

json.dump({"apps": apps}, sys.stdout)
PY
    then
        rc=0
    else
        rc=$?
    fi
    rm -f "${tmp_file}"
    return "${rc}"
}

_acs_context_target_key() {
    printf '%s\t%s\t%s\t%s\t%s' \
        "${ACS_SERVER:-}" \
        "${SPLUNK_CLOUD_STACK:-}" \
        "${SPLUNK_CLOUD_SEARCH_HEAD:-}" \
        "${SPLUNK_PROFILE:-}" \
        "${SPLUNK_SEARCH_PROFILE:-}"
}

_acs_current_stack_readback() {
    local raw="" identity=""
    if ! raw="$(_acs_cli_current_stack_command 2>/dev/null)"; then
        return 1
    fi
    if ! identity="$(printf '%s' "${raw}" | python3 -c '
import json
import re
import sys

text = sys.stdin.read()
if len(text.encode("utf-8")) > 16384:
    raise SystemExit(1)
stack = ""
search_head = ""

try:
    parsed = json.loads(text)
except Exception:
    parsed = None

if isinstance(parsed, dict):
    for key in ("stack", "current-stack", "current_stack", "currentStack"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            stack = value.strip()
            break
    for key in (
        "current-search-head",
        "current_search_head",
        "currentSearchHead",
        "searchHead",
    ):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            search_head = value.strip()
            break
else:
    for line in text.splitlines():
        match = re.match(r"^\s*(?:Current\s+)?Stack:\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*$", line)
        if match:
            stack = match.group(1)
            continue
        match = re.match(r"^\s*Current Search Head:\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*$", line)
        if match:
            search_head = match.group(1)
            continue

identity_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
if not identity_pattern.fullmatch(stack):
    raise SystemExit(1)
if search_head and not identity_pattern.fullmatch(search_head):
    raise SystemExit(1)
print(f"{stack}\t{search_head}", end="")
')"; then
        return 1
    fi
    printf '%s' "${identity}"
}

_acs_verify_current_context() {
    local readback=""

    if ! readback="$(_acs_current_stack_readback)"; then
        return 1
    fi
    [[ -n "${_ACS_CONTEXT_IDENTITY}" && "${readback}" == "${_ACS_CONTEXT_IDENTITY}" ]]
}

_acs_readback_matches_requested_target() {
    local readback="" observed_stack="" observed_search_head=""
    if ! readback="$(_acs_current_stack_readback)"; then
        return 1
    fi
    IFS=$'\t' read -r observed_stack observed_search_head <<<"${readback}"
    [[ -n "${observed_stack}" && "${observed_stack}" == "${SPLUNK_CLOUD_STACK:-}" ]] || return 1
    if [[ -n "${SPLUNK_CLOUD_SEARCH_HEAD:-}" ]]; then
        [[ -n "${observed_search_head}" && "${observed_search_head}" == "${SPLUNK_CLOUD_SEARCH_HEAD}" ]] || return 1
    fi
    return 0
}

acs_stack_status_snapshot() {
    local raw="" payload="" snapshot=""
    if ! acs_prepare_context; then
        return 1
    fi
    if ! raw="$(acs_command status current-stack 2>/dev/null)"; then
        return 1
    fi
    if ! payload="$(printf '%s' "${raw}" | acs_extract_http_response_json)"; then
        return 1
    fi
    if ! snapshot="$(printf '%s' "${payload}" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)

if not isinstance(data, dict):
    raise SystemExit(1)

infra_record = (
    data.get("infrastructure")
    or ((data.get("status") or {}).get("infrastructure") or {})
)
messages = data.get("messages")
if not isinstance(infra_record, dict) or not isinstance(messages, dict):
    raise SystemExit(1)
infra = infra_record.get("status")
restart_value = messages.get("restartRequired")
if not isinstance(infra, str) or not infra.strip() or not isinstance(restart_value, bool):
    raise SystemExit(1)
restart_required = str(restart_value).lower()
print(f"{infra}\t{restart_required}", end="")
')"; then
        return 1
    fi
    printf '%s' "${snapshot}"
}

acs_prepare_context() {
    local target_key="" readback="" observed_stack="" observed_search_head="" already_selected=false

    if ! load_splunk_platform_settings; then
        _ACS_CONTEXT_PREPARED=false
        _ACS_CONTEXT_TARGET=""
        _ACS_CONTEXT_IDENTITY=""
        return 1
    fi
    if ! _load_credential_values_from_file "${_CRED_FILE}"; then
        _ACS_CONTEXT_PREPARED=false
        _ACS_CONTEXT_TARGET=""
        _ACS_CONTEXT_IDENTITY=""
        return 1
    fi
    if ! _acs_apply_bound_target_context; then
        _acs_invalidate_context
        return 1
    fi
    target_key="$(_acs_context_target_key)"
    if [[ "${_ACS_CONTEXT_PREPARED}" == "true" && "${_ACS_CONTEXT_TARGET}" == "${target_key}" ]]; then
        if _acs_verify_current_context; then
            return 0
        fi
        _ACS_CONTEXT_PREPARED=false
        _ACS_CONTEXT_TARGET=""
        _ACS_CONTEXT_IDENTITY=""
    fi
    _ACS_CONTEXT_PREPARED=false
    _ACS_CONTEXT_TARGET=""
    _ACS_CONTEXT_IDENTITY=""

    if [[ -z "${SPLUNK_CLOUD_STACK:-}" ]]; then
        echo "ERROR: SPLUNK_CLOUD_STACK is required to prepare a mutation-safe ACS context." >&2
        return 1
    fi

    if ! acs_cli_available; then
        echo "ERROR: ACS CLI is required for Splunk Cloud operations. Install it with Homebrew: brew install acs" >&2
        _ACS_CONTEXT_PREPARED=false
        _ACS_CONTEXT_TARGET=""
        _ACS_CONTEXT_IDENTITY=""
        return 1
    fi

    export ACS_SERVER
    if [[ -z "${SPLUNK_USERNAME:-}" && -n "${SB_USER:-}" ]]; then
        export SPLUNK_USERNAME="${SB_USER}"
    fi
    if [[ -z "${SPLUNK_PASSWORD:-}" && -n "${SB_PASS:-}" ]]; then
        export SPLUNK_PASSWORD="${SB_PASS}"
    fi
    [[ -n "${SPLUNK_USERNAME:-}" ]] && export SPLUNK_USERNAME
    [[ -n "${SPLUNK_PASSWORD:-}" ]] && export SPLUNK_PASSWORD
    [[ -n "${STACK_USERNAME:-}" ]] && export STACK_USERNAME
    [[ -n "${STACK_PASSWORD:-}" ]] && export STACK_PASSWORD
    [[ -n "${STACK_TOKEN:-}" ]] && export STACK_TOKEN
    [[ -n "${STACK_TOKEN_USER:-}" ]] && export STACK_TOKEN_USER

    # Rendered assets bind a reviewed stack/search-head identity.  If the
    # existing ACS current-stack surface already proves that exact identity,
    # retain it and avoid an unnecessary local re-selection command.  A stale
    # or unreadable context still takes the explicit add/use path below and is
    # rejected unless the final readback matches.
    if [[ "${ACS_BOUND_TARGET_CONTEXT:-false}" == "true" ]] \
        && _acs_readback_matches_requested_target; then
        already_selected=true
    fi
    if [[ -n "${SPLUNK_CLOUD_STACK:-}" && "${already_selected}" != "true" ]]; then
        if [[ -n "${SPLUNK_CLOUD_SEARCH_HEAD:-}" ]]; then
            if ! _acs_cli_command config add-stack "${SPLUNK_CLOUD_STACK}" --target-sh "${SPLUNK_CLOUD_SEARCH_HEAD}" >/dev/null 2>&1; then
                # Existing-stack registration may fail; use-stack plus readback
                # below must still succeed before the context is trusted.
                :
            fi
            if ! _acs_cli_command config use-stack "${SPLUNK_CLOUD_STACK}" --target-sh "${SPLUNK_CLOUD_SEARCH_HEAD}" >/dev/null; then
                echo "ERROR: Could not select the requested ACS stack and search head; refusing the operation." >&2
                _ACS_CONTEXT_PREPARED=false
                _ACS_CONTEXT_TARGET=""
                _ACS_CONTEXT_IDENTITY=""
                return 1
            fi
        else
            if ! _acs_cli_command config add-stack "${SPLUNK_CLOUD_STACK}" >/dev/null 2>&1; then
                # Existing-stack registration may fail; use-stack plus readback
                # below must still succeed before the context is trusted.
                :
            fi
            if ! _acs_cli_command config use-stack "${SPLUNK_CLOUD_STACK}" >/dev/null; then
                echo "ERROR: Could not select the requested ACS stack; refusing the operation." >&2
                _ACS_CONTEXT_PREPARED=false
                _ACS_CONTEXT_TARGET=""
                _ACS_CONTEXT_IDENTITY=""
                return 1
            fi
        fi
    fi

    if [[ -n "${STACK_TOKEN:-}" ]]; then
        if ! _acs_cli_command login >/dev/null; then
            echo "ERROR: ACS authentication failed; refusing the operation." >&2
            _ACS_CONTEXT_PREPARED=false
            _ACS_CONTEXT_TARGET=""
            _ACS_CONTEXT_IDENTITY=""
            return 1
        fi
    elif [[ -n "${STACK_USERNAME:-}" || -n "${STACK_PASSWORD:-}" || -n "${STACK_TOKEN_USER:-}" ]]; then
        if [[ -z "${STACK_USERNAME:-}" || -z "${STACK_PASSWORD:-}" || -z "${STACK_TOKEN_USER:-}" ]]; then
            echo "ERROR: STACK_USERNAME, STACK_PASSWORD, and STACK_TOKEN_USER are all required for ACS login without STACK_TOKEN." >&2
            _ACS_CONTEXT_PREPARED=false
            _ACS_CONTEXT_TARGET=""
            _ACS_CONTEXT_IDENTITY=""
            return 1
        fi
        if ! _acs_cli_command login --token-user "${STACK_TOKEN_USER}" >/dev/null; then
            echo "ERROR: ACS authentication failed; refusing the operation." >&2
            _ACS_CONTEXT_PREPARED=false
            _ACS_CONTEXT_TARGET=""
            _ACS_CONTEXT_IDENTITY=""
            return 1
        fi
    fi

    if ! readback="$(_acs_current_stack_readback)"; then
        echo "ERROR: Could not read back the selected ACS stack; refusing the operation." >&2
        _ACS_CONTEXT_PREPARED=false
        _ACS_CONTEXT_TARGET=""
        _ACS_CONTEXT_IDENTITY=""
        return 1
    fi
    IFS=$'\t' read -r observed_stack observed_search_head <<<"${readback}"
    if [[ -z "${observed_stack}" || "${observed_stack}" != "${SPLUNK_CLOUD_STACK}" ]]; then
        echo "ERROR: ACS stack readback did not match the requested stack; refusing the operation." >&2
        _ACS_CONTEXT_PREPARED=false
        _ACS_CONTEXT_TARGET=""
        _ACS_CONTEXT_IDENTITY=""
        return 1
    fi
    if [[ -n "${SPLUNK_CLOUD_SEARCH_HEAD:-}" \
        && ( -z "${observed_search_head}" || "${observed_search_head}" != "${SPLUNK_CLOUD_SEARCH_HEAD}" ) ]]; then
        echo "ERROR: ACS search-head readback did not match the requested search head; refusing the operation." >&2
        _ACS_CONTEXT_PREPARED=false
        _ACS_CONTEXT_TARGET=""
        _ACS_CONTEXT_IDENTITY=""
        return 1
    fi
    _ACS_CONTEXT_IDENTITY="${readback}"
    _ACS_CONTEXT_TARGET="$(_acs_context_target_key)"
    _ACS_CONTEXT_PREPARED=true
}

cloud_requires_local_scope() {
    [[ -n "${SPLUNK_CLOUD_SEARCH_HEAD:-}" ]]
}

_acs_validate_splunk_index_name() {
    local idx="${1:-}"

    if declare -F validate_splunk_index_name >/dev/null 2>&1; then
        validate_splunk_index_name "${idx}"
        return $?
    fi

    if [[ ! "${idx}" =~ ^[A-Za-z0-9_-]{1,80}$ ]]; then
        echo "ERROR: Invalid Splunk index name '${idx}'; use 1-80 letters, numbers, underscores, or hyphens." >&2
        return 1
    fi
    return 0
}

_acs_extract_index_describe_payload() {
    python3 -c '
import json
import sys

status_keys = (
    "code", "status", "statusCode", "status_code", "httpStatus", "http_status"
)
try:
    raw = sys.stdin.read()
    if not raw.strip() or len(raw.encode("utf-8")) > 1024 * 1024:
        raise ValueError("empty or oversized describe output")
    structured = json.loads(raw)
    if isinstance(structured, dict):
        explicit_http_statuses = [
            structured[key]
            for key in ("statusCode", "status_code", "httpStatus", "http_status")
            if key in structured
        ]
        if explicit_http_statuses:
            if any(not str(value).strip().isdigit() for value in explicit_http_statuses):
                raise ValueError("describe HTTP status is invalid")
            normalized = {int(str(value).strip()) for value in explicit_http_statuses}
            if len(normalized) != 1 or not 200 <= next(iter(normalized)) <= 299:
                raise ValueError("describe HTTP status is not successful")
        payload = structured
    elif isinstance(structured, list):
        http_items = [
            item
            for item in structured
            if isinstance(item, dict) and item.get("type") == "http"
        ]
        if len(http_items) != 1:
            raise ValueError("describe output does not contain one HTTP record")
        http_item = http_items[0]
        statuses = [http_item[key] for key in status_keys if key in http_item]
        if statuses:
            if any(not str(value).strip().isdigit() for value in statuses):
                raise ValueError("describe HTTP status is invalid")
            normalized = {int(str(value).strip()) for value in statuses}
            if len(normalized) != 1 or not 200 <= next(iter(normalized)) <= 299:
                raise ValueError("describe HTTP status is not successful")
        response = http_item.get("response")
        if isinstance(response, str):
            payload = json.loads(response)
        elif isinstance(response, dict):
            payload = response
        else:
            raise ValueError("describe HTTP response is missing")
    else:
        raise ValueError("describe output has the wrong JSON type")
    if not isinstance(payload, dict):
        raise ValueError("describe payload is not an object")
    json.dump(payload, sys.stdout, separators=(",", ":"), sort_keys=True)
except Exception:
    raise SystemExit(1)
'
}

_acs_index_describe_datatype_from_raw() {
    local idx="$1" raw="$2" payload=""

    if ! payload="$(printf '%s' "${raw}" | _acs_extract_index_describe_payload)"; then
        return 1
    fi
    printf '%s' "${payload}" | python3 -c "
import json
import sys

requested = sys.argv[1]

def identity(data):
    return [
        value.strip()
        for key in ('name', 'title', 'indexName')
        if isinstance((value := data.get(key)), str) and value.strip()
    ]

def pick_datatype(data):
    candidates = [
        data.get('datatype'),
        data.get('dataType'),
    ]
    spec = data.get('spec')
    if isinstance(spec, dict):
        candidates.extend((spec.get('datatype'), spec.get('dataType')))
    for value in candidates:
        if value is None:
            continue
        value = str(value).strip()
        if value:
            return value
    return ''

try:
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        raise ValueError('describe payload is not an object')
    candidates = [data]
    for key in ('index', 'item', 'data'):
        child = data.get(key)
        if isinstance(child, dict):
            candidates.append(child)
    identified = [(item, identity(item)) for item in candidates if identity(item)]
    if any(any(value != requested for value in values) for _item, values in identified):
        raise ValueError('describe payload contains a nonmatching index identity')
    exact = [item for item, values in identified if values and all(value == requested for value in values)]
    if len(exact) != 1:
        raise ValueError('describe payload does not identify the requested index')
    record = exact[0]
    print(pick_datatype(record) or 'event', end='')
except Exception:
    raise SystemExit(1)
" "${idx}" 2>/dev/null
}

cloud_observe_index() {
    local idx="$1" describe_output="" describe_status=0 observed_type=""

    _acs_validate_splunk_index_name "${idx}" || return 2
    if ! acs_prepare_context; then
        return 2
    fi
    if describe_output="$(acs_command indexes describe "${idx}" 2>&1)"; then
        if ! observed_type="$(_acs_index_describe_datatype_from_raw "${idx}" "${describe_output}")"; then
            echo "ERROR: ACS index describe returned success without one exact index observation." >&2
            return 2
        fi
        printf '%s' "${observed_type}"
        return 0
    else
        describe_status=$?
    fi
    if _acs_index_describe_proves_absent "${idx}" "${describe_output}"; then
        return 1
    fi
    echo "ERROR: ACS index observation failed (exit ${describe_status}); absence was not verified." >&2
    return 2
}

cloud_check_index() {
    local idx="$1" observed_type="" observation_status=0
    if observed_type="$(cloud_observe_index "${idx}")"; then
        return 0
    else
        observation_status=$?
    fi
    return "${observation_status}"
}

cloud_get_index_datatype() {
    cloud_observe_index "$1"
}

_acs_index_describe_proves_absent() {
    local idx="${1:-}" raw="${2:-}"
    if (( ${#raw} == 0 || ${#raw} > 1048576 )); then
        return 1
    fi
    ACS_INDEX_DESCRIBE_OUTPUT="${raw}" python3 - "${idx}" <<'PY'
import json
import os
import re
import sys

requested = sys.argv[1]
raw = os.environ.get("ACS_INDEX_DESCRIBE_OUTPUT", "").strip()


def status_is_404(value):
    if not isinstance(value, dict):
        return False
    values = [
        str(value[key]).strip()
        for key in (
        "code",
        "status",
        "statusCode",
        "status_code",
        "httpStatus",
        "http_status",
        )
        if key in value
    ]
    return bool(values) and all(item == "404" for item in values)


def envelope_is_404(value):
    if isinstance(value, dict):
        return status_is_404(value)
    if not isinstance(value, list):
        return False
    http_items = [
        item
        for item in value
        if isinstance(item, dict) and item.get("type") == "http"
    ]
    if len(http_items) != 1:
        return False
    item = http_items[0]
    if status_is_404(item):
        return True
    response = item.get("response")
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except Exception:
            return False
    return status_is_404(response)


try:
    parsed = json.loads(raw)
except Exception:
    parsed = None
if parsed is not None and envelope_is_404(parsed):
    raise SystemExit(0)

plain = " ".join(raw.split())
plain = re.sub(r"^error:\s*", "", plain, flags=re.IGNORECASE).rstrip(".")
escaped = re.escape(requested)
patterns = (
    rf"^(?:index|resource)\s+['\"\[]?{escaped}['\"\]]?\s+(?:is\s+|was\s+)?not[ -]?found$",
    rf"^no such index[: ]+['\"\[]?{escaped}['\"\]]?$",
    rf"^(?:index|resource)\s+['\"\[]?{escaped}['\"\]]?\s+does not exist$",
    r"^(?:index|resource) not[ -]?found$",
    r"^not[ -]?found$",
)
raise SystemExit(
    0 if any(re.fullmatch(pattern, plain, flags=re.IGNORECASE) for pattern in patterns) else 1
)
PY
}

_acs_index_describe_matches_retention_from_raw() {
    local idx="$1" index_type="$2" searchable_days="$3" archival_days="$4" raw="$5" payload=""

    if ! payload="$(printf '%s' "${raw}" | _acs_extract_index_describe_payload)"; then
        return 1
    fi
    printf '%s' "${payload}" | python3 -c '
import json
import sys

requested, expected_type, expected_searchable, expected_archival = sys.argv[1:]

def identities(data):
    return [
        value.strip()
        for key in ("name", "title", "indexName")
        if isinstance((value := data.get(key)), str) and value.strip()
    ]

def field(record, key):
    if key in record:
        return record.get(key)
    spec = record.get("spec")
    return spec.get(key) if isinstance(spec, dict) else None

def integer_matches(actual, expected):
    try:
        return int(actual) == int(expected)
    except (TypeError, ValueError):
        return False

try:
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        raise ValueError("describe payload is not an object")
    candidates = [data]
    for key in ("index", "item", "data"):
        child = data.get(key)
        if isinstance(child, dict):
            candidates.append(child)
    identified = [(item, identities(item)) for item in candidates if identities(item)]
    if any(any(value != requested for value in values) for _item, values in identified):
        raise ValueError("describe payload contains a nonmatching index identity")
    exact = [item for item, values in identified if all(value == requested for value in values)]
    if len(exact) != 1:
        raise ValueError("describe payload does not contain one exact index record")
    record = exact[0]
    observed_type = field(record, "datatype")
    if observed_type is None:
        observed_type = field(record, "dataType")
    observed_type = str(observed_type or "event").strip()
    if observed_type != expected_type:
        raise ValueError("datatype mismatch")
    if not integer_matches(field(record, "searchableDays"), expected_searchable):
        raise ValueError("searchable retention mismatch")
    if not integer_matches(field(record, "splunkArchivalRetentionDays"), expected_archival):
        raise ValueError("archival retention mismatch")
except Exception:
    raise SystemExit(1)
' "${idx}" "${index_type}" "${searchable_days}" "${archival_days}" 2>/dev/null
}

cloud_verify_index_retention() {
    local idx="$1" index_type="$2" searchable_days="$3" archival_days="$4" raw=""

    _acs_validate_splunk_index_name "${idx}" || return 1
    if ! acs_prepare_context; then
        return 1
    fi
    if ! raw="$(acs_command indexes describe "${idx}" 2>/dev/null)"; then
        echo "ERROR: ACS retention readback failed for the requested index." >&2
        return 1
    fi
    if ! _acs_index_describe_matches_retention_from_raw \
        "${idx}" "${index_type}" "${searchable_days}" "${archival_days}" "${raw}"; then
        echo "ERROR: ACS retention readback did not match the requested index settings." >&2
        return 1
    fi
}

cloud_create_index() {
    local idx="$1"
    local searchable_days="${2:-${SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS:-90}}"
    local index_type="${3:-event}"
    local describe_output="" describe_status=0 observed_type=""

    _acs_validate_splunk_index_name "${idx}" || return 1
    case "${index_type}" in
        event|metric) ;;
        *)
            echo "ERROR: Unsupported index type for ACS index creation." >&2
            return 1
            ;;
    esac
    acs_prepare_context || return 1
    if describe_output="$(acs_command indexes describe "${idx}" 2>&1)"; then
        if ! observed_type="$(_acs_index_describe_datatype_from_raw "${idx}" "${describe_output}")"; then
            echo "ERROR: ACS index describe returned success without an exact index observation; refusing create." >&2
            return 1
        fi
        if [[ "${observed_type}" != "${index_type}" ]]; then
            echo "ERROR: Existing ACS index datatype does not match the requested datatype." >&2
            return 1
        fi
        return 0
    else
        describe_status=$?
    fi
    if ! _acs_index_describe_proves_absent "${idx}" "${describe_output}"; then
        echo "ERROR: ACS index observation failed (exit ${describe_status}); refusing create because absence was not verified." >&2
        return 1
    fi

    if ! acs_command indexes create --name "${idx}" --searchable-days "${searchable_days}" --data-type "${index_type}" >/dev/null; then
        return 1
    fi
    if ! describe_output="$(acs_command indexes describe "${idx}" 2>/dev/null)"; then
        echo "ERROR: ACS index create returned success, but post-create readback failed." >&2
        return 1
    fi
    if ! observed_type="$(_acs_index_describe_datatype_from_raw "${idx}" "${describe_output}")"; then
        echo "ERROR: ACS index create returned success, but post-create readback did not identify the requested index." >&2
        return 1
    fi
    if [[ "${observed_type}" != "${index_type}" ]]; then
        echo "ERROR: ACS index create returned success, but post-create datatype did not match the request." >&2
        return 1
    fi
}

acs_restart_required() {
    local infra restart_required snapshot=""
    if ! snapshot="$(acs_stack_status_snapshot)"; then
        return 1
    fi
    read -r infra restart_required <<< "${snapshot}"
    if [[ "${infra}" != "Ready" ]]; then
        echo "ERROR: ACS stack infrastructure is not Ready; restart state is not a completion observation." >&2
        return 1
    fi
    printf '%s\n' "${restart_required:-false}"
}

acs_wait_for_ready() {
    local timeout_secs="${1:-900}" interval_secs="${2:-10}"
    local waited=0 infra restart_required snapshot=""

    while (( waited < timeout_secs )); do
        if ! snapshot="$(acs_stack_status_snapshot)"; then
            return 1
        fi
        read -r infra restart_required <<< "${snapshot}"
        if [[ "${infra}" == "Ready" && "${restart_required}" != "true" ]]; then
            return 0
        fi
        sleep "${interval_secs}"
        waited=$((waited + interval_secs))
    done

    return 1
}

cloud_restart_if_required() {
    local timeout_secs="${1:-900}"
    local restart_output rc snapshot="" infra="" restart_required=""

    acs_prepare_context || return 1
    if ! snapshot="$(acs_stack_status_snapshot)"; then
        return 1
    fi
    read -r infra restart_required <<< "${snapshot}"
    if [[ "${restart_required}" != "true" ]]; then
        if [[ "${infra}" == "Ready" ]]; then
            return 0
        fi
        echo "ERROR: ACS reports no restart requirement, but stack infrastructure is not Ready; refusing to report lifecycle completion." >&2
        return 1
    fi
    if [[ "${infra}" != "Ready" ]]; then
        echo "ERROR: ACS stack infrastructure is not Ready; refusing to start a new restart." >&2
        return 1
    fi

    if restart_output=$(acs_command restart current-stack 2>&1); then
        rc=0
    else
        rc=$?
    fi

    if (( rc != 0 )) && [[ "${restart_output}" != *"another restart is already in progress"* ]]; then
        printf '%s\n' "${restart_output}" >&2
        return 1
    fi

    acs_wait_for_ready "${timeout_secs}" 10
}

acs_current_search_head_prefix() {
    local readback="" observed_stack="" observed_search_head=""

    if ! load_splunk_platform_settings; then
        return 1
    fi
    if ! acs_prepare_context; then
        return 1
    fi
    if ! readback="$(_acs_current_stack_readback)"; then
        return 1
    fi
    IFS=$'\t' read -r observed_stack observed_search_head <<<"${readback}"
    [[ -n "${observed_stack}" && -n "${observed_search_head}" ]] || return 1
    printf '%s' "${observed_search_head}"
}

cloud_current_search_api_uri() {
    local prefix suffix

    if ! load_splunk_platform_settings; then
        return 1
    fi
    [[ -n "${SPLUNK_CLOUD_STACK:-}" ]] || return 1

    if ! prefix="$(acs_current_search_head_prefix)"; then
        return 1
    fi
    [[ -n "${prefix}" ]] || return 1

    if [[ "${ACS_SERVER:-}" == "https://staging.admin.splunk.com" ]]; then
        suffix=".stg.splunkcloud.com"
    else
        suffix=".splunkcloud.com"
    fi

    printf 'https://%s.%s%s:8089' "${prefix}" "${SPLUNK_CLOUD_STACK}" "${suffix}"
}

_SEARCH_API_ALLOWLIST_CHECKED=false

_detect_public_ip() {
    local ip
    ip=$(curl -q -sS --connect-timeout 5 --max-time 10 \
        "https://checkip.amazonaws.com" \
        --proto '=https' --proto-redir '=https' --max-redirs 0 --globoff \
        2>/dev/null || true)
    ip="${ip%%[[:space:]]*}"
    if [[ "${ip}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        printf '%s' "${ip}"
        return 0
    fi
    ip=$(curl -q -sS --connect-timeout 5 --max-time 10 \
        "https://api.ipify.org" \
        --proto '=https' --proto-redir '=https' --max-redirs 0 --globoff \
        2>/dev/null || true)
    ip="${ip%%[[:space:]]*}"
    if [[ "${ip}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        printf '%s' "${ip}"
        return 0
    fi
    return 1
}

acs_ensure_search_api_access() {
    if [[ "${_SEARCH_API_ALLOWLIST_CHECKED}" == "true" ]]; then
        return 0
    fi
    if [[ "${SPLUNK_SKIP_ALLOWLIST:-false}" == "true" ]]; then
        _SEARCH_API_ALLOWLIST_CHECKED=true
        return 0
    fi

    acs_prepare_context || return 1

    local public_ip
    public_ip="$(_detect_public_ip 2>/dev/null || true)"
    if [[ -z "${public_ip}" ]]; then
        _SEARCH_API_ALLOWLIST_CHECKED=true
        return 0
    fi

    local subnet="${public_ip}/32"
    local allowlist_json="" allowlist_raw="" already_listed
    if ! allowlist_raw="$(acs_command ip-allowlist list search-api 2>/dev/null)"; then
        return 1
    fi
    if ! allowlist_json="$(printf '%s' "${allowlist_raw}" | acs_extract_http_response_json)"; then
        return 1
    fi
    if ! already_listed="$(printf '%s' "${allowlist_json}" | python3 -c "
import json, sys
target = sys.argv[1]
try:
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or 'subnets' not in data or not isinstance(data['subnets'], list):
        raise ValueError('missing subnet observation')
    subnets = data['subnets']
    for s in subnets:
        if isinstance(s, str):
            value = s
        elif isinstance(s, dict) and isinstance(s.get('subnet'), str):
            value = s['subnet']
        else:
            raise ValueError('invalid subnet observation')
        if value == target:
            print('yes', end='')
            raise SystemExit(0)
    print('no', end='')
except Exception:
    raise SystemExit(1)
" "${subnet}" 2>/dev/null)"; then
        return 1
    fi

    case "${already_listed}" in
        yes)
            ;;
        no)
            log "Adding ${subnet} to search-api IP allowlist via ACS..."
            if acs_command ip-allowlist create search-api --subnets "${subnet}" >/dev/null 2>&1; then
                log "  ${subnet} added to search-api allowlist."
            else
                log "  ERROR: Could not add ${subnet} to search-api allowlist. Add it manually before continuing."
                return 1
            fi
            ;;
        *)
            return 1
            ;;
    esac

    _SEARCH_API_ALLOWLIST_CHECKED=true
}

prefer_current_cloud_search_api_uri() {
    local current_host candidate primary_user primary_pass search_user search_pass
    local current_user current_pass primary_uri restore_primary_creds=false
    local cloud_uri_active=false platform=""

    if ! platform="$(resolve_splunk_platform)"; then
        return 1
    fi
    [[ "${platform}" == "cloud" ]] || return 0
    current_host="$(splunk_host_from_uri "${SPLUNK_URI:-}")"
    if ! primary_uri="$(_primary_cloud_search_api_uri)"; then
        return 1
    fi

    candidate="${SPLUNK_URI:-}"
    if [[ "${current_host}" != sh-* ]] \
        || ! _is_splunk_cloud_host "${candidate}"; then
        candidate=""
        if ! candidate="$(cloud_current_search_api_uri)"; then
            if [[ -n "${SPLUNK_CLOUD_SEARCH_HEAD:-}" ]]; then
                echo "ERROR: Could not verify the explicitly requested Splunk Cloud search head; refusing URI fallback." >&2
                return 1
            fi
            candidate="${primary_uri}"
        fi
        [[ -z "${candidate}" ]] && candidate="${primary_uri}"
    fi

    if ! primary_user="$(_selected_profile_credential_value "SPLUNK_USER")" \
        || ! primary_pass="$(_selected_profile_credential_value "SPLUNK_PASS")" \
        || ! search_user="$(_search_profile_credential_value "SPLUNK_USER")" \
        || ! search_pass="$(_search_profile_credential_value "SPLUNK_PASS")"; then
        return 1
    fi
    current_user="${SPLUNK_USER:-}"
    current_pass="${SPLUNK_PASS:-}"
    if _is_splunk_cloud_host "${candidate}"; then
        cloud_uri_active=true
    fi

    if [[ -z "${current_user}" && -z "${current_pass}" ]]; then
        restore_primary_creds=true
    elif [[ -n "${search_user}" && -n "${search_pass}" \
        && "${current_user}" == "${search_user}" && "${current_pass}" == "${search_pass}" ]]; then
        restore_primary_creds=true
    fi

    if [[ "${cloud_uri_active}" == true ]]; then
        # ACS preparation reloads the configured profile context. Complete that
        # verification before publishing the observed Cloud search-head route,
        # then restore the bound endpoint and credentials as one unit.
        acs_ensure_search_api_access || return 1
        _credential_transition_runtime_route "${candidate}" preserve || return 1
        if [[ "${restore_primary_creds}" == true \
            && -n "${STACK_USERNAME:-}" && -n "${STACK_PASSWORD:-}" ]]; then
            SPLUNK_USER="${STACK_USERNAME}"
            SPLUNK_PASS="${STACK_PASSWORD}"
            export SPLUNK_USER SPLUNK_PASS
        elif [[ "${restore_primary_creds}" == true \
            && -n "${primary_user}" && -n "${primary_pass}" ]]; then
            SPLUNK_USER="${primary_user}"
            SPLUNK_PASS="${primary_pass}"
            export SPLUNK_USER SPLUNK_PASS
        fi
        export SPLUNK_URI SPLUNK_SEARCH_API_URI SPLUNK_HOST SPLUNK_MGMT_PORT
    fi
}

# Wait for the Splunk Cloud stack to become Ready or require a restart.
# Unlike acs_wait_for_ready (which waits for Ready AND no restart needed),
# this returns as soon as the stack is actionable (Ready, or restart pending).
cloud_wait_for_settled() {
    local timeout_secs="${1:-300}" interval_secs="${2:-5}"
    local waited=0 infra restart_required snapshot=""

    while (( waited < timeout_secs )); do
        if ! snapshot="$(acs_stack_status_snapshot)"; then
            return 1
        fi
        read -r infra restart_required <<< "${snapshot}"
        if [[ "${infra}" == "Ready" || "${restart_required}" == "true" ]]; then
            return 0
        fi
        sleep "${interval_secs}"
        waited=$((waited + interval_secs))
    done

    return 1
}

# Cloud-side restart with user-facing log messages.
# Expects RESTART_SPLUNK (bool) as a script-level global.
#
# Usage: cloud_app_restart_or_exit <operation> [skip_message]
cloud_app_restart_or_exit() {
    local operation="$1"
    local skip_msg="${2:-Run 'acs status current-stack' and restart if required.}"

    if [[ "${RESTART_SPLUNK:-true}" != "true" ]]; then
        log "Skipping Splunk Cloud restart check (--no-restart). ${skip_msg}"
        return 0
    fi

    if ! cloud_wait_for_settled 300 5; then
        log "ERROR: Timed out or failed while observing the Splunk Cloud stack after ${operation}; completion is not verified."
        return 1
    fi

    local restart_required=""
    if ! restart_required="$(acs_restart_required)"; then
        log "ERROR: Could not determine whether the Splunk Cloud stack requires a restart."
        return 1
    fi
    if [[ "${restart_required}" != "true" ]]; then
        log "No Splunk Cloud restart required after ${operation}."
        return 0
    fi

    log "Restarting Splunk Cloud search tier via ACS to complete ${operation}..."
    if ! cloud_restart_if_required 900; then
        log "ERROR: ACS restart failed or the stack did not return to Ready status."
        return 1
    fi
    log "SUCCESS: Splunk Cloud restart completed and the stack returned to Ready."
}

log_platform_restart_guidance() {
    local prefix="${1:-changes}"
    local platform=""
    if type platform_reload_or_restart_guidance >/dev/null 2>&1; then
        platform_reload_or_restart_guidance "${prefix}"
        return $?
    fi
    if ! platform="$(resolve_splunk_platform)"; then
        return 1
    fi
    if [[ "${platform}" == "cloud" ]]; then
        echo "Splunk Cloud: check 'acs status current-stack' after ${prefix} and run 'acs restart current-stack' only if restartRequired=true."
    else
        echo "Restart Splunk to apply ${prefix}."
    fi
}

platform_check_index() {
    local sk="$1" uri="$2" idx="$3" platform=""
    _acs_validate_splunk_index_name "${idx}" || return 1
    if ! platform="$(resolve_splunk_platform)"; then
        return 1
    fi
    if [[ "${platform}" == "cloud" ]]; then
        cloud_check_index "${idx}"
    else
        if type deployment_prepare_index_rest_context >/dev/null 2>&1; then
            if ! deployment_prepare_index_rest_context "${sk}" "${uri}"; then
                return 1
            fi
            rest_check_index "${DEPLOYMENT_REST_SK}" "${DEPLOYMENT_REST_URI}" "${idx}"
            return $?
        fi
        rest_check_index "${sk}" "${uri}" "${idx}"
    fi
}

platform_get_index_datatype() {
    local sk="$1" uri="$2" idx="$3" platform=""
    _acs_validate_splunk_index_name "${idx}" || return 1
    if ! platform="$(resolve_splunk_platform)"; then
        return 1
    fi
    if [[ "${platform}" == "cloud" ]]; then
        cloud_get_index_datatype "${idx}"
    else
        if type deployment_prepare_index_rest_context >/dev/null 2>&1; then
            deployment_prepare_index_rest_context "${sk}" "${uri}" || return 1
            rest_get_index_datatype "${DEPLOYMENT_REST_SK}" "${DEPLOYMENT_REST_URI}" "${idx}"
            return $?
        fi
        rest_get_index_datatype "${sk}" "${uri}" "${idx}"
    fi
}

platform_create_index() {
    local sk="$1" uri="$2" idx="$3" max_size="${4:-512000}" index_type="${5:-event}"
    local bundle_status=0 platform=""
    _acs_validate_splunk_index_name "${idx}" || return 1
    if ! platform="$(resolve_splunk_platform)"; then
        return 1
    fi
    if [[ "${platform}" == "cloud" ]]; then
        cloud_create_index "${idx}" "${SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS:-90}" "${index_type}"
    else
        if type deployment_index_bundle_profile >/dev/null 2>&1; then
            if deployment_index_bundle_profile >/dev/null; then
                deployment_create_cluster_bundle_index "${idx}" "${max_size}" "${index_type}"
                return $?
            else
                bundle_status=$?
                if (( bundle_status == 2 )); then
                    echo "ERROR: Could not resolve the configured index-tier deployment target; refusing REST fallback." >&2
                    return 1
                fi
            fi
            deployment_prepare_index_rest_context "${sk}" "${uri}" || return 1
            rest_create_index "${DEPLOYMENT_REST_SK}" "${DEPLOYMENT_REST_URI}" "${idx}" "${max_size}" "${index_type}"
            return $?
        fi
        rest_create_index "${sk}" "${uri}" "${idx}" "${max_size}" "${index_type}"
    fi
}

# IP allowlist describe / diff helpers used by splunk-cloud-acs-allowlist-setup.
#
# Per Splunk ACS CLI docs (acs ip-allowlist --help / acs ip-allowlist-v6 --help):
# IPv4 lives under `acs ip-allowlist {describe,create,delete}`.
# IPv6 lives under the SEPARATE top-level group `acs ip-allowlist-v6 {describe,create,delete}`.
# The read-only subcommand is `describe` (not `list`).

acs_ipallowlist_describe() {
    local feature="$1"
    local raw="" payload=""
    if ! raw="$(acs_command ip-allowlist describe "${feature}" 2>/dev/null)"; then
        return 1
    fi
    if ! payload="$(printf '%s' "${raw}" | acs_extract_http_response_json)"; then
        return 1
    fi
    printf '%s' "${payload}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or 'subnets' not in data or not isinstance(data['subnets'], list):
        raise ValueError('missing subnet observation')
    values = []
    for item in data['subnets']:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict) and isinstance(item.get('subnet'), str):
            values.append(item['subnet'])
        else:
            raise ValueError('invalid subnet observation')
    print(','.join(sorted(values)))
except Exception:
    raise SystemExit(1)
" 2>/dev/null
}

acs_ipallowlist_describe_v6() {
    local feature="$1"
    local raw="" payload=""
    if ! raw="$(acs_command ip-allowlist-v6 describe "${feature}" 2>/dev/null)"; then
        return 1
    fi
    if ! payload="$(printf '%s' "${raw}" | acs_extract_http_response_json)"; then
        return 1
    fi
    printf '%s' "${payload}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or 'subnets' not in data or not isinstance(data['subnets'], list):
        raise ValueError('missing subnet observation')
    values = []
    for item in data['subnets']:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict) and isinstance(item.get('subnet'), str):
            values.append(item['subnet'])
        else:
            raise ValueError('invalid subnet observation')
    print(','.join(sorted(values)))
except Exception:
    raise SystemExit(1)
" 2>/dev/null
}

# acs_ipallowlist_apply_plan <feature> <family> <planned_csv>
# Diffs the planned IPv4 (family=ipv4) or IPv6 (family=ipv6) allowlist against
# live state and create/deletes to converge. Idempotent.
acs_ipallowlist_apply_plan() {
    local feature="$1" family="$2" planned="$3"
    local live to_add to_remove cli_group
    case "${family}" in
        ipv4)
            cli_group="ip-allowlist"
            if ! live="$(acs_ipallowlist_describe "${feature}")"; then
                return 1
            fi
            ;;
        ipv6)
            cli_group="ip-allowlist-v6"
            if ! live="$(acs_ipallowlist_describe_v6 "${feature}")"; then
                return 1
            fi
            ;;
        *)
            log "ERROR: acs_ipallowlist_apply_plan family must be ipv4|ipv6"
            return 1
            ;;
    esac

    to_add=$(python3 - "${planned}" "${live}" <<'PY'
import sys
planned = set(filter(None, sys.argv[1].split(',')))
live = set(filter(None, sys.argv[2].split(',')))
print(','.join(sorted(planned - live)))
PY
)
    to_remove=$(python3 - "${planned}" "${live}" <<'PY'
import sys
planned = set(filter(None, sys.argv[1].split(',')))
live = set(filter(None, sys.argv[2].split(',')))
print(','.join(sorted(live - planned)))
PY
)

    if [[ -n "${to_add}" ]]; then
        acs_command "${cli_group}" create "${feature}" --subnets "${to_add}" >/dev/null
    fi
    if [[ -n "${to_remove}" ]]; then
        acs_command "${cli_group}" delete "${feature}" --subnets "${to_remove}" >/dev/null
    fi
    log "OK: ${family} apply complete for feature ${feature} (added=${to_add:-0}, removed=${to_remove:-0})"
}

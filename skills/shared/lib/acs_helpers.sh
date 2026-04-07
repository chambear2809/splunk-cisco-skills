#!/usr/bin/env bash
# ACS CLI context management, output parsing, status checks, and restart helpers.
# Sourced by credential_helpers.sh; not intended for direct use.
#
# See credential_helpers.sh for the sourcing contract.

[[ -n "${_ACS_HELPERS_LOADED:-}" ]] && return 0
_ACS_HELPERS_LOADED=true

_ACS_CONTEXT_PREPARED=false

acs_cli_available() {
    command -v acs >/dev/null 2>&1
}

acs_command() {
    load_splunk_platform_settings
    local -a cmd=(acs --format structured)
    [[ -n "${ACS_SERVER:-}" ]] && cmd+=(--server "${ACS_SERVER}")
    cmd+=("$@")
    "${cmd[@]}"
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
    local offset=0 count=100 page app_count tmp_file rc
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

        page="$(acs_command "${cmd[@]}" 2>/dev/null | acs_extract_http_response_json)" || {
            rm -f "${tmp_file}"
            return 1
        }

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
    apps = []

if not isinstance(apps, list):
    apps = []

try:
    page = json.loads(page_text)
except Exception:
    page = {}

page_apps = page.get("apps", []) if isinstance(page, dict) else []
if not isinstance(page_apps, list):
    page_apps = []

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

    ACS_APPS_STATE_FILE="${tmp_file}" python3 - <<'PY'
import json
import os
import sys

state_path = os.environ["ACS_APPS_STATE_FILE"]

try:
    with open(state_path, encoding="utf-8") as handle:
        apps = json.load(handle)
except Exception:
    apps = []

if not isinstance(apps, list):
    apps = []

json.dump({"apps": apps}, sys.stdout)
PY
    rc=$?
    rm -f "${tmp_file}"
    return "${rc}"
}

acs_stack_status_snapshot() {
    local payload
    acs_prepare_context || return 1
    payload=$(acs_command status current-stack 2>/dev/null | acs_extract_http_response_json) || return 1
    printf '%s' "${payload}" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    print("unknown\tfalse", end="")
    raise SystemExit(0)

infra = (
    data.get("infrastructure")
    or ((data.get("status") or {}).get("infrastructure") or {})
).get("status", "unknown")
restart_required = str(bool((data.get("messages") or {}).get("restartRequired", False))).lower()
print(f"{infra}\t{restart_required}", end="")
'
}

acs_prepare_context() {
    if [[ "${_ACS_CONTEXT_PREPARED}" == "true" ]]; then
        return 0
    fi

    load_splunk_platform_settings
    _load_credential_values_from_file "${_CRED_FILE}"

    if ! acs_cli_available; then
        echo "ERROR: ACS CLI is required for Splunk Cloud operations. Install it with Homebrew: brew install acs" >&2
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

    [[ -n "${STACK_USERNAME:-}" ]] && export STACK_USERNAME || true
    [[ -n "${STACK_PASSWORD:-}" ]] && export STACK_PASSWORD || true
    [[ -n "${STACK_TOKEN:-}" ]] && export STACK_TOKEN || true
    [[ -n "${STACK_TOKEN_USER:-}" ]] && export STACK_TOKEN_USER || true

    if [[ -n "${SPLUNK_CLOUD_STACK:-}" ]]; then
        if [[ -n "${SPLUNK_CLOUD_SEARCH_HEAD:-}" ]]; then
            acs_command config add-stack "${SPLUNK_CLOUD_STACK}" --target-sh "${SPLUNK_CLOUD_SEARCH_HEAD}" >/dev/null 2>&1 || true
            acs_command config use-stack "${SPLUNK_CLOUD_STACK}" --target-sh "${SPLUNK_CLOUD_SEARCH_HEAD}" >/dev/null
        else
            acs_command config add-stack "${SPLUNK_CLOUD_STACK}" >/dev/null 2>&1 || true
            acs_command config use-stack "${SPLUNK_CLOUD_STACK}" >/dev/null
        fi
    fi

    if [[ -n "${STACK_TOKEN:-}" ]]; then
        acs_command login >/dev/null
    elif [[ -n "${STACK_USERNAME:-}" || -n "${STACK_PASSWORD:-}" || -n "${STACK_TOKEN_USER:-}" ]]; then
        if [[ -z "${STACK_USERNAME:-}" || -z "${STACK_PASSWORD:-}" || -z "${STACK_TOKEN_USER:-}" ]]; then
            echo "ERROR: STACK_USERNAME, STACK_PASSWORD, and STACK_TOKEN_USER are all required for ACS login without STACK_TOKEN." >&2
            return 1
        fi
        acs_command login --token-user "${STACK_TOKEN_USER}" >/dev/null
    fi

    _ACS_CONTEXT_PREPARED=true
}

cloud_requires_local_scope() {
    [[ -n "${SPLUNK_CLOUD_SEARCH_HEAD:-}" ]]
}

cloud_check_index() {
    local idx="$1"
    acs_prepare_context || return 1
    acs_command indexes describe "${idx}" >/dev/null 2>&1
}

cloud_get_index_datatype() {
    local idx="$1"
    local payload

    acs_prepare_context || return 1
    payload=$(acs_command indexes describe "${idx}" 2>/dev/null | acs_extract_http_response_json || echo "{}")
    printf '%s' "${payload}" | python3 -c "
import json
import sys

def pick_datatype(data):
    if not isinstance(data, dict):
        return ''
    candidates = [
        data.get('datatype'),
        data.get('dataType'),
        (data.get('spec') or {}).get('datatype'),
        (data.get('spec') or {}).get('dataType'),
        ((data.get('index') or {}).get('datatype')),
        ((data.get('index') or {}).get('dataType')),
    ]
    for value in candidates:
        if value is None:
            continue
        value = str(value).strip()
        if value:
            return value
    return ''

try:
    data = json.load(sys.stdin)
    datatype = pick_datatype(data)
    if datatype:
        print(datatype, end='')
    else:
        print('event', end='')
except Exception:
    print('', end='')
" 2>/dev/null || echo ""
}

cloud_create_index() {
    local idx="$1"
    local searchable_days="${2:-${SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS:-90}}"
    local index_type="${3:-event}"

    acs_prepare_context || return 1
    if acs_command indexes describe "${idx}" >/dev/null 2>&1; then
        return 0
    fi

    acs_command indexes create --name "${idx}" --searchable-days "${searchable_days}" --data-type "${index_type}" >/dev/null
}

acs_restart_required() {
    local infra restart_required
    read -r infra restart_required <<< "$(acs_stack_status_snapshot 2>/dev/null || echo "unknown false")"
    printf '%s\n' "${restart_required:-false}"
}

acs_wait_for_ready() {
    local timeout_secs="${1:-900}" interval_secs="${2:-10}"
    local waited=0 infra restart_required

    while (( waited < timeout_secs )); do
        read -r infra restart_required <<< "$(acs_stack_status_snapshot 2>/dev/null || echo "unknown false")"
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
    local restart_output rc

    acs_prepare_context || return 1
    if [[ "$(acs_restart_required)" != "true" ]]; then
        return 0
    fi

    set +e
    restart_output=$(acs_command restart current-stack 2>&1)
    rc=$?
    set -e

    if (( rc != 0 )) && [[ "${restart_output}" != *"another restart is already in progress"* ]]; then
        printf '%s\n' "${restart_output}" >&2
        return 1
    fi

    acs_wait_for_ready "${timeout_secs}" 10
}

acs_current_search_head_prefix() {
    load_splunk_platform_settings
    [[ -n "${SPLUNK_CLOUD_SEARCH_HEAD:-}" ]] && {
        printf '%s' "${SPLUNK_CLOUD_SEARCH_HEAD}"
        return 0
    }

    acs_prepare_context || return 1
    acs config current-stack 2>/dev/null | python3 -c '
import re
import sys

text = sys.stdin.read()

current = re.search(r"^Current Search Head:\s*([A-Za-z0-9-]+)\s*$", text, re.MULTILINE)
if current and current.group(1).strip():
    print(current.group(1).strip(), end="")
    raise SystemExit(0)

search_heads = re.search(r"^Search Heads:\s*\[([^\]]+)\]\s*$", text, re.MULTILINE)
if search_heads:
    heads = [item.strip() for item in search_heads.group(1).split(",") if item.strip()]
    if heads:
        print(heads[0], end="")
' 2>/dev/null
}

cloud_current_search_api_uri() {
    local prefix suffix

    load_splunk_platform_settings
    [[ -n "${SPLUNK_CLOUD_STACK:-}" ]] || return 1

    prefix="$(acs_current_search_head_prefix 2>/dev/null || true)"
    [[ -n "${prefix}" ]] || return 1

    if [[ "${ACS_SERVER:-}" == "https://staging.admin.splunk.com" ]] \
        || _is_staging_splunk_cloud_host "${SPLUNK_URI:-}" \
        || _is_staging_splunk_cloud_host "${SPLUNK_HOST:-}"; then
        suffix=".stg.splunkcloud.com"
    else
        suffix=".splunkcloud.com"
    fi

    printf 'https://%s.%s%s:8089' "${prefix}" "${SPLUNK_CLOUD_STACK}" "${suffix}"
}

_SEARCH_API_ALLOWLIST_CHECKED=false

_detect_public_ip() {
    local ip
    ip=$(curl -sS --connect-timeout 5 --max-time 10 \
        "https://checkip.amazonaws.com" 2>/dev/null || true)
    ip="${ip%%[[:space:]]*}"
    if [[ "${ip}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        printf '%s' "${ip}"
        return 0
    fi
    ip=$(curl -sS --connect-timeout 5 --max-time 10 \
        "https://api.ipify.org" 2>/dev/null || true)
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
    local allowlist_json already_listed
    allowlist_json=$(acs_command ip-allowlist list search-api 2>/dev/null \
        | acs_extract_http_response_json || echo "{}")
    already_listed=$(printf '%s' "${allowlist_json}" | python3 -c "
import json, sys
target = sys.argv[1]
try:
    data = json.load(sys.stdin)
    subnets = data.get('subnets', [])
    for s in subnets:
        if isinstance(s, dict):
            s = s.get('subnet', '')
        if s == target:
            print('yes', end='')
            raise SystemExit(0)
    print('no', end='')
except Exception:
    print('unknown', end='')
" "${subnet}" 2>/dev/null || echo "unknown")

    case "${already_listed}" in
        yes)
            ;;
        no)
            log "Adding ${subnet} to search-api IP allowlist via ACS..."
            if acs_command ip-allowlist create search-api --subnets "${subnet}" >/dev/null 2>&1; then
                log "  ${subnet} added to search-api allowlist."
            else
                log "  WARNING: Could not add ${subnet} to search-api allowlist. You may need to add it manually."
            fi
            ;;
    esac

    _SEARCH_API_ALLOWLIST_CHECKED=true
}

prefer_current_cloud_search_api_uri() {
    local current_host candidate primary_user primary_pass search_user search_pass
    local current_user current_pass primary_uri restore_primary_creds=false
    local cloud_uri_active=false

    is_splunk_cloud || return 0
    current_host="$(splunk_host_from_uri "${SPLUNK_URI:-}")"
    primary_uri="$(_primary_cloud_search_api_uri 2>/dev/null || true)"

    if [[ "${current_host}" != sh-* ]]; then
        candidate="$(cloud_current_search_api_uri 2>/dev/null || true)"
        [[ -z "${candidate}" ]] && candidate="${primary_uri}"
        if [[ -n "${candidate}" ]]; then
            SPLUNK_URI="${candidate}"
            SPLUNK_SEARCH_API_URI="${candidate}"
        fi
    fi

    primary_user="$(_selected_profile_credential_value "SPLUNK_USER")"
    primary_pass="$(_selected_profile_credential_value "SPLUNK_PASS")"
    search_user="$(_search_profile_credential_value "SPLUNK_USER")"
    search_pass="$(_search_profile_credential_value "SPLUNK_PASS")"
    current_user="${SPLUNK_USER:-}"
    current_pass="${SPLUNK_PASS:-}"
    if _is_splunk_cloud_host "${SPLUNK_URI:-}"; then
        cloud_uri_active=true
    fi

    if [[ -z "${current_user}" && -z "${current_pass}" ]]; then
        restore_primary_creds=true
    elif [[ -n "${search_user}" && -n "${search_pass}" \
        && "${current_user}" == "${search_user}" && "${current_pass}" == "${search_pass}" ]]; then
        restore_primary_creds=true
    fi

    if [[ "${cloud_uri_active}" == true && "${restore_primary_creds}" == true \
        && -n "${STACK_USERNAME:-}" && -n "${STACK_PASSWORD:-}" ]]; then
        SPLUNK_USER="${STACK_USERNAME}"
        SPLUNK_PASS="${STACK_PASSWORD}"
        export SPLUNK_USER SPLUNK_PASS
    elif [[ "${cloud_uri_active}" == true && "${restore_primary_creds}" == true \
        && -n "${primary_user}" && -n "${primary_pass}" ]]; then
        SPLUNK_USER="${primary_user}"
        SPLUNK_PASS="${primary_pass}"
        export SPLUNK_USER SPLUNK_PASS
    fi
    export SPLUNK_URI SPLUNK_SEARCH_API_URI

    if [[ "${cloud_uri_active}" == true ]]; then
        acs_ensure_search_api_access
    fi
}

# Wait for the Splunk Cloud stack to become Ready or require a restart.
# Unlike acs_wait_for_ready (which waits for Ready AND no restart needed),
# this returns as soon as the stack is actionable (Ready, or restart pending).
cloud_wait_for_settled() {
    local timeout_secs="${1:-300}" interval_secs="${2:-5}"
    local waited=0 infra restart_required

    while (( waited < timeout_secs )); do
        read -r infra restart_required <<< "$(acs_stack_status_snapshot 2>/dev/null || echo "unknown false")"
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
        log "WARNING: Timed out waiting for the Splunk Cloud stack to settle after ${operation}."
    fi

    if [[ "$(acs_restart_required 2>/dev/null || echo "false")" != "true" ]]; then
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
    if is_splunk_cloud; then
        echo "Splunk Cloud: check 'acs status current-stack' after ${prefix} and run 'acs restart current-stack' only if restartRequired=true."
    else
        echo "Restart Splunk to apply ${prefix}."
    fi
}

platform_check_index() {
    local sk="$1" uri="$2" idx="$3"
    if is_splunk_cloud; then
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
    local sk="$1" uri="$2" idx="$3"
    if is_splunk_cloud; then
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
    if is_splunk_cloud; then
        cloud_create_index "${idx}" "${SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS:-90}" "${index_type}"
    else
        if type deployment_index_bundle_profile >/dev/null 2>&1; then
            if deployment_index_bundle_profile >/dev/null 2>&1; then
                deployment_create_cluster_bundle_index "${idx}" "${max_size}" "${index_type}"
                return $?
            fi
            deployment_prepare_index_rest_context "${sk}" "${uri}" || return 1
            rest_create_index "${DEPLOYMENT_REST_SK}" "${DEPLOYMENT_REST_URI}" "${idx}" "${max_size}" "${index_type}"
            return $?
        fi
        rest_create_index "${sk}" "${uri}" "${idx}" "${max_size}" "${index_type}"
    fi
}

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="ta_cisco_thousandeyes"
HEC_TOKEN_NAME="thousandeyes"
DEFAULT_INDEXES=(thousandeyes_metrics thousandeyes_traces thousandeyes_events thousandeyes_activity thousandeyes_alerts thousandeyes_pathvis)

INDEXES_ONLY=false
HEC_ONLY=false
ENABLE_INPUTS=false
ACCOUNT=""
ACCOUNT_GROUP=""
INDEX=""
INPUT_TYPE=""
ALERT_RULES=""
HEC_TOKEN=""
HEC_URL=""
PATHVIS_ENABLED=true
PATHVIS_INDEX="thousandeyes_pathvis"
PATHVIS_INTERVAL="3600"
SK=""
INGEST_SK=""
INPUT_SUFFIX=""

usage() {
    cat >&2 <<EOF
Cisco ThousandEyes App Setup Automation

Usage: $(basename "$0") [OPTIONS]

Options:
  --indexes-only          Create indexes only
  --hec-only              Verify/create HEC token only
  --enable-inputs         Enable data inputs
  --account EMAIL         ThousandEyes user account (email)
  --account-group NAME    ThousandEyes account group name
  --index INDEX           Target index for polling inputs
  --input-type TYPE       Input group: all, metrics, traces, events, activity, alerts
  --alert-rules IDS       Alert rule IDs joined with ~ (required for alerts/all)
  --hec-token NAME        HEC token name (default: thousandeyes)
  --hec-url URL           HEC URL override; may include /services/collector/event
  --pathvis-index INDEX   Path visualization index (default: thousandeyes_pathvis)
  --pathvis-interval SEC  Path visualization poll interval (default: 3600)
  --no-pathvis            Disable path visualization on metrics inputs
  --help                  Show this help

With no flags, runs full setup (HEC + indexes).
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --hec-only) HEC_ONLY=true; shift ;;
        --enable-inputs) ENABLE_INPUTS=true; shift ;;
        --account) require_arg "$1" $# || exit 1; ACCOUNT="$2"; shift 2 ;;
        --account-group) require_arg "$1" $# || exit 1; ACCOUNT_GROUP="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --input-type) require_arg "$1" $# || exit 1; INPUT_TYPE="$2"; shift 2 ;;
        --alert-rules) require_arg "$1" $# || exit 1; ALERT_RULES="$2"; shift 2 ;;
        --hec-token) require_arg "$1" $# || exit 1; HEC_TOKEN="$2"; shift 2 ;;
        --hec-url) require_arg "$1" $# || exit 1; HEC_URL="$2"; shift 2 ;;
        --pathvis-index) require_arg "$1" $# || exit 1; PATHVIS_INDEX="$2"; shift 2 ;;
        --pathvis-interval) require_arg "$1" $# || exit 1; PATHVIS_INTERVAL="$2"; shift 2 ;;
        --no-pathvis) PATHVIS_ENABLED=false; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

HEC_TOKEN="${HEC_TOKEN:-${HEC_TOKEN_NAME}}"

safe_input_suffix() {
    python3 - "$1" <<'PY'
import hashlib
import re
import sys

raw = sys.argv[1]
safe = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_")
safe = re.sub(r"_+", "_", safe)[:64] or "account"
if safe != raw:
    safe = f"{safe}_{hashlib.sha256(raw.encode()).hexdigest()[:8]}"
print(safe, end="")
PY
}

log_live_input_summary() {
    local total enabled disabled
    read -r total enabled disabled <<< "$(rest_get_live_input_counts "${SK}" "${SPLUNK_URI}" "${APP_NAME}")"
    log "Live input status: total=${total}, enabled=${enabled}, disabled=${disabled}"
}

ensure_search_api_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk. Check credentials."; exit 1; }
}

ensure_ingest_api_session() {
    local saved_user saved_pass

    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    if ! load_ingest_connection_settings; then
        return 1
    fi

    saved_user="${SPLUNK_USER:-}"
    saved_pass="${SPLUNK_PASS:-}"
    SPLUNK_USER="${INGEST_SPLUNK_USER:-${SPLUNK_USER:-}}"
    SPLUNK_PASS="${INGEST_SPLUNK_PASS:-${SPLUNK_PASS:-}}"
    INGEST_SK="$(get_session_key "${INGEST_SPLUNK_URI}")" || {
        SPLUNK_USER="${saved_user}"
        SPLUNK_PASS="${saved_pass}"
        log "ERROR: Could not authenticate to the ingest-tier Splunk REST API. Check ingest credentials."
        exit 1
    }
    SPLUNK_USER="${saved_user}"
    SPLUNK_PASS="${saved_pass}"
}

check_prereqs() {
    ensure_search_api_session
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        log "ERROR: ThousandEyes app not found. Install the app first."
        exit 1
    fi
}

ensure_app_visible() {
    ensure_search_api_session
    log "Ensuring ${APP_NAME} is visible..."
    deployment_set_app_visible "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "true" \
        || { log "ERROR: Failed to make ${APP_NAME} visible."; return 1; }
}

normalize_hec_base_url() {
    local url="${1%/}"
    url="${url%/services/collector/event}"
    url="${url%/services/collector/raw}"
    if [[ "${url}" != https://* && "${url}" != http://* ]]; then
        log "ERROR: HEC URL must start with http:// or https://: ${url}" >&2
        return 1
    fi
    printf '%s' "${url}"
}

detect_hec_target() {
    local host ingest_role bundle_status=0

    if [[ -n "${HEC_URL}" ]]; then
        normalize_hec_base_url "${HEC_URL}"
        return 0
    fi

    if ! load_ingest_connection_settings; then
        log "ERROR: Could not load the selected Splunk ingest target settings."
        return 1
    fi
    if is_splunk_cloud; then
        local stack="${SPLUNK_CLOUD_STACK:-}"
        if [[ -n "${stack}" ]]; then
            if _is_staging_splunk_cloud_host "${SPLUNK_URI:-}"; then
                printf 'https://http-inputs-%s.stg.splunkcloud.com:443' "${stack}"
            else
                printf 'https://http-inputs-%s.splunkcloud.com:443' "${stack}"
            fi
            return 0
        fi
        log "WARNING: Cloud platform detected but SPLUNK_CLOUD_STACK is empty." >&2
        log "  HEC target will fall back to search-head host on port 8088," >&2
        log "  which is incorrect for Splunk Cloud. Set SPLUNK_CLOUD_STACK" >&2
        log "  in your credentials file." >&2
    fi

    if [[ -n "${INGEST_SPLUNK_HEC_URL:-}" ]]; then
        normalize_hec_base_url "${INGEST_SPLUNK_HEC_URL}"
        return 0
    fi

    if ! ingest_role="$(resolve_ingest_target_role)"; then
        log "ERROR: Could not resolve the selected Splunk ingest target role."
        return 1
    fi
    if [[ "${ingest_role}" == "indexer" ]]; then
        if deployment_index_bundle_profile >/dev/null; then
            log "ERROR: Clustered indexer-tier ingest requires an explicit HEC URL."
            log "ERROR: Set --hec-url or configure SPLUNK_HEC_URL on the ingest profile."
            return 1
        else
            bundle_status=$?
            if (( bundle_status == 2 )); then
                log "ERROR: Could not resolve the configured index-tier deployment target."
                return 1
            fi
        fi
    fi

    host=$(splunk_host_from_uri "${INGEST_SPLUNK_URI}")
    if [[ -z "${host}" ]]; then
        host="${INGEST_SPLUNK_HOST:-}"
    fi
    if [[ -z "${host}" ]]; then
        log "ERROR: Could not determine the Enterprise ingest HEC host. Pass --hec-url or configure SPLUNK_INGEST_PROFILE."
        exit 1
    fi
    printf 'https://%s:8088' "${host}"
}

enterprise_hec_uses_bundle() {
    local platform="" bundle_status=0

    _DEPLOYMENT_BUNDLE_CHECK_ERROR=false
    if ! platform="$(resolve_splunk_platform)"; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    case "${platform}" in
        cloud) return 1 ;;
        enterprise) ;;
        *)
            _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
            log "ERROR: Unsupported Splunk platform '${platform}'; refusing HEC delivery routing."
            return 2
            ;;
    esac
    if ! type deployment_should_manage_ingest_hec_via_bundle >/dev/null 2>&1; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    if deployment_should_manage_ingest_hec_via_bundle; then
        return 0
    else
        bundle_status=$?
    fi
    if (( bundle_status == 2 )) \
        || [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    return 1
}

enterprise_hec_token_state() {
    local token_name="$1" state=""

    if enterprise_hec_uses_bundle; then
        deployment_get_bundle_hec_token_state "${token_name}" 2>/dev/null
        return $?
    fi
    if [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
        log "ERROR: Could not resolve the configured ingest deployment target; refusing REST fallback."
        return 1
    fi

    ensure_ingest_api_session || return 1
    if ! state="$(rest_get_hec_token_state \
        "${INGEST_SK}" "${INGEST_SPLUNK_URI}" "${token_name}" 2>/dev/null)"; then
        # Some older Enterprise HEC responses omit the disabled field on a
        # token immediately after creation.  Permit that one bounded,
        # post-create transition only after the create call itself succeeded;
        # pre-existing malformed observations remain fail-closed.
        if [[ "${_HEC_TOKEN_CREATED_THIS_RUN:-false}" == "true" ]] \
            && rest_hec_token_presence "${INGEST_SK}" "${INGEST_SPLUNK_URI}" "${token_name}" 2>/dev/null; then
            state="enabled"
        else
            return 1
        fi
    fi
    case "${state}" in
        enabled|disabled|missing) printf '%s' "${state}" ;;
        *) return 1 ;;
    esac
}

_ACS_HEC_CMD_GROUP=""
acs_hec_command_group() {
    if [[ -n "${_ACS_HEC_CMD_GROUP}" ]]; then
        printf '%s' "${_ACS_HEC_CMD_GROUP}"
        return 0
    fi
    # Detect only the local CLI surface; a remote/auth failure must not select a fallback.
    if command acs hec-token list --help >/dev/null 2>&1; then
        _ACS_HEC_CMD_GROUP="hec-token"
    elif command acs http-event-collectors describe --help >/dev/null 2>&1; then
        _ACS_HEC_CMD_GROUP="http-event-collectors"
    else
        return 1
    fi
    printf '%s' "${_ACS_HEC_CMD_GROUP}"
}

cloud_describe_hec_token_state() {
    local token_name="$1" cmd_group="$2" output command_succeeded=false

    if output="$(acs_command "${cmd_group}" describe "${token_name}" 2>&1)"; then
        command_succeeded=true
    fi
    printf '%s' "${output}" | python3 -c '
import json
import re
import sys

requested = sys.argv[1]
command_succeeded = sys.argv[2] == "true"
raw = sys.stdin.read()
if not raw.strip() or len(raw.encode("utf-8")) > 1024 * 1024:
    raise SystemExit(1)
try:
    parsed = json.loads(raw)
except Exception:
    parsed = None

def walk(value, depth=0):
    if depth > 8:
        return
    yield value
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "response" and isinstance(child, str):
                try:
                    child = json.loads(child)
                except Exception:
                    continue
            yield from walk(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child, depth + 1)

def state_from_disabled(value):
    if isinstance(value, bool):
        return "disabled" if value else "enabled"
    normalized = str(value).strip().lower()
    if normalized in ("1", "true"):
        return "disabled"
    if normalized in ("0", "false"):
        return "enabled"
    raise ValueError("invalid disabled value")

if command_succeeded:
    if parsed is None:
        raise SystemExit(1)
    if isinstance(parsed, list):
        http_items = [
            item for item in parsed
            if isinstance(item, dict) and item.get("type") == "http"
        ]
        if len(http_items) != 1:
            raise SystemExit(1)
        status_keys = ("code", "status", "statusCode", "status_code", "httpStatus", "http_status")
        statuses = [http_items[0][key] for key in status_keys if key in http_items[0]]
        if statuses:
            if any(not str(value).isdigit() for value in statuses):
                raise SystemExit(1)
            normalized_statuses = {int(value) for value in statuses}
            if len(normalized_statuses) != 1 or not 200 <= next(iter(normalized_statuses)) <= 299:
                raise SystemExit(1)
    observations = []
    for node in walk(parsed):
        if not isinstance(node, dict):
            continue
        spec = node.get("spec")
        if isinstance(spec, dict) and isinstance(spec.get("name"), str) and spec["name"]:
            if "disabled" in spec:
                disabled = spec["disabled"]
            elif "disabled" in node:
                disabled = node["disabled"]
            else:
                raise SystemExit(1)
            observations.append((spec["name"], state_from_disabled(disabled)))
        direct_name = node.get("name") or node.get("tokenName")
        if isinstance(direct_name, str) and direct_name and "disabled" in node:
            observations.append((direct_name, state_from_disabled(node["disabled"])))
    names = {name for name, _state in observations}
    states = {state for name, state in observations if name == requested}
    if names != {requested} or len(states) != 1:
        raise SystemExit(1)
    print(states.pop(), end="")
    raise SystemExit(0)

status_keys = ("code", "status", "statusCode", "status_code", "httpStatus", "http_status")

def has_404(value):
    if not isinstance(value, dict):
        return False
    values = [str(value[key]).strip() for key in status_keys if key in value]
    return bool(values) and all(item == "404" for item in values)

def exact_http_404(value):
    if isinstance(value, dict):
        return has_404(value)
    if not isinstance(value, list):
        return False
    http_items = [
        item for item in value
        if isinstance(item, dict) and item.get("type") == "http"
    ]
    return len(http_items) == 1 and has_404(http_items[0])

if parsed is not None and exact_http_404(parsed):
    print("missing", end="")
    raise SystemExit(0)

plain = " ".join(raw.split())
plain = re.sub(r"^error:\s*", "", plain, flags=re.IGNORECASE).rstrip(".")
for marker in (chr(34), chr(39), "[", "]"):
    plain = plain.replace(marker, "")
escaped = re.escape(requested)
patterns = (
    rf"^(?:hec[ -]?token|http event collector|token|resource)\s+{escaped}\s+(?:is\s+|was\s+)?not[ -]?found$",
    rf"^no such (?:hec[ -]?token|http event collector|token|resource)\s*:?\s*{escaped}$",
    rf"^(?:hec[ -]?token|http event collector|token|resource)\s+{escaped}\s+does not exist$",
)
if any(re.fullmatch(pattern, plain, flags=re.IGNORECASE) for pattern in patterns):
    print("missing", end="")
    raise SystemExit(0)
raise SystemExit(1)
' "${token_name}" "${command_succeeded}" 2>/dev/null
}

cloud_get_hec_token_state() {
    local token_name="$1" cmd_group raw page_result page_count page_state
    local count=100 offset=0 page_number=0 max_pages=100
    if ! cmd_group="$(acs_hec_command_group)"; then
        return 1
    fi

    if [[ "${cmd_group}" == "http-event-collectors" ]]; then
        cloud_describe_hec_token_state "${token_name}" "${cmd_group}"
        return $?
    fi

    while (( page_number < max_pages )); do
        if ! raw="$(acs_command hec-token list --count "${count}" --offset "${offset}" 2>/dev/null)"; then
            return 1
        fi

        if ! page_result="$(printf '%s' "${raw}" | python3 -c '
import json, sys

target = sys.argv[1]
page_limit = int(sys.argv[2])
try:
    text = sys.stdin.read()
    if not text.strip() or len(text.encode("utf-8")) > 1024 * 1024:
        raise ValueError("empty or oversized ACS HEC inventory page")
    structured = json.loads(text)
except Exception:
    raise SystemExit(1)

payload = structured
if isinstance(structured, list):
    http_items = [
        item for item in structured
        if isinstance(item, dict) and item.get("type") == "http"
    ]
    if len(http_items) != 1:
        raise SystemExit(1)
    item = http_items[0]
    status_keys = ("code", "status", "statusCode", "status_code", "httpStatus", "http_status")
    statuses = [item[key] for key in status_keys if key in item]
    if statuses:
        if any(not str(value).isdigit() for value in statuses):
            raise SystemExit(1)
        normalized_statuses = {int(value) for value in statuses}
        if len(normalized_statuses) != 1 or not 200 <= next(iter(normalized_statuses)) <= 299:
            raise SystemExit(1)
    response = item.get("response")
    if not isinstance(response, str) or not response.strip():
        raise SystemExit(1)
    try:
        payload = json.loads(response)
    except Exception:
        raise SystemExit(1)
if not isinstance(payload, dict):
    raise SystemExit(1)

keys = ("http-event-collectors", "http_event_collectors", "tokens")
present = [key for key in keys if key in payload]
if len(present) != 1 or not isinstance(payload[present[0]], list):
    raise SystemExit(1)
collectors = payload[present[0]]
if len(collectors) > page_limit:
    raise SystemExit(1)
matches = []
for collector in collectors:
    if not isinstance(collector, dict):
        raise SystemExit(1)
    spec = collector.get("spec", {})
    if not isinstance(spec, dict):
        raise SystemExit(1)
    name = spec.get("name") or collector.get("name", "")
    if not isinstance(name, str) or not name:
        raise SystemExit(1)
    if name != target:
        continue
    if "disabled" in spec:
        disabled_value = spec["disabled"]
    elif "disabled" in collector:
        disabled_value = collector["disabled"]
    else:
        raise SystemExit(1)
    disabled = str(disabled_value).strip().lower()
    if disabled in ("1", "true"):
        matches.append("disabled")
    elif disabled in ("0", "false"):
        matches.append("enabled")
    else:
        raise SystemExit(1)
if len(matches) > 1:
    raise SystemExit(1)
state = matches[0] if matches else "absent"
print(f"{len(collectors)}:{state}", end="")
' "${token_name}" "${count}" 2>/dev/null)"; then
            return 1
        fi
        page_count="${page_result%%:*}"
        page_state="${page_result#*:}"
        [[ "${page_count}" =~ ^[0-9]+$ ]] || return 1
        case "${page_state}" in
            enabled|disabled)
                printf '%s' "${page_state}"
                return 0
                ;;
            absent) ;;
            *) return 1 ;;
        esac
        if (( page_count < count )); then
            printf 'missing'
            return 0
        fi
        offset=$((offset + count))
        page_number=$((page_number + 1))
    done
    return 1
}

cloud_rest_get_hec_token_state() {
    local token_name="$1" session_key="$2" rest_uri="$3" raw response http_code
    if ! response="$(splunk_curl "${session_key}" \
        "${rest_uri}/services/data/inputs/http?output_mode=json&count=0" \
        -w '\n%{http_code}' 2>/dev/null)"; then
        return 1
    fi
    http_code="${response##*$'\n'}"
    [[ "${http_code}" == "200" ]] || return 1
    raw="${response%$'\n'*}"

    printf '%s' "${raw}" | python3 -c '
import json, sys

target = sys.argv[1]
aliases = {target, f"http://{target}"}
try:
    text = sys.stdin.read()
    if not text.strip() or len(text.encode("utf-8")) > 1024 * 1024:
        raise ValueError("empty or oversized HEC inventory")
    data = json.loads(text)
except Exception:
    raise SystemExit(1)
if not isinstance(data, dict) or not isinstance(data.get("entry"), list):
    raise SystemExit(1)
matches = []
for entry in data["entry"]:
    if not isinstance(entry, dict):
        raise SystemExit(1)
    name = entry.get("name", "")
    content = entry.get("content", {})
    if not isinstance(name, str) or not isinstance(content, dict):
        raise SystemExit(1)
    if name not in aliases:
        continue
    matches.append(content)
if not matches:
    print("missing", end="")
    raise SystemExit(0)
if len(matches) != 1 or "disabled" not in matches[0]:
    raise SystemExit(1)
disabled = str(matches[0]["disabled"]).strip().lower()
if disabled in ("1", "true"):
    print("disabled", end="")
elif disabled in ("0", "false"):
    print("enabled", end="")
else:
    raise SystemExit(1)
' "${token_name}" 2>/dev/null
}

cloud_create_hec_token_via_acs() {
    local token_name="$1" cmd_group indexes_csv
    if ! cmd_group="$(acs_hec_command_group)"; then
        return 1
    fi

    if [[ "${cmd_group}" == "hec-token" ]]; then
        local -a create_cmd=(hec-token create --name "${token_name}" --default-index "thousandeyes_metrics")
        local idx
        for idx in "${DEFAULT_INDEXES[@]}"; do
            create_cmd+=(--allowed-indexes "${idx}")
        done
        acs_command "${create_cmd[@]}" >/dev/null 2>&1
    else
        indexes_csv=$(IFS=,; echo "${DEFAULT_INDEXES[*]}")
        acs_command http-event-collectors create \
            --name "${token_name}" \
            --allowed-indexes "${indexes_csv}" \
            --default-index "thousandeyes_metrics" \
            --disabled false \
            >/dev/null 2>&1
    fi
}

cloud_enable_hec_token_via_acs() {
    local token_name="$1" cmd_group
    if ! cmd_group="$(acs_hec_command_group)"; then
        return 1
    fi
    if [[ "${cmd_group}" != "hec-token" ]]; then
        return 1
    fi
    acs_command hec-token update "${token_name}" --disabled=false >/dev/null 2>&1
}

rest_create_hec_token() {
    local token_name="$1" session_key="${2:-${INGEST_SK}}" rest_uri="${3:-${INGEST_SPLUNK_URI:-}}"
    local indexes_str body resp hec_code
    if [[ -z "${session_key}" || -z "${rest_uri}" ]]; then
        log "ERROR: HEC REST creation requires a session key and REST URI."
        return 1
    fi
    indexes_str=$(IFS=,; echo "${DEFAULT_INDEXES[*]}")
    body=$(form_urlencode_pairs \
        name "${token_name}" \
        index "thousandeyes_metrics" \
        indexes "${indexes_str}" \
        disabled "false") || return 1
    resp=$(splunk_curl_post "${session_key}" "${body}" \
        "${rest_uri}/services/data/inputs/http?output_mode=json" \
        -w '\n%{http_code}' 2>/dev/null)
    hec_code=$(echo "${resp}" | tail -1)
    case "${hec_code}" in
        201|200)
            _HEC_TOKEN_CREATED_THIS_RUN=true
            return 0
            ;;
        409) return 0 ;;
        *) return 1 ;;
    esac
}

rest_enable_hec_token() {
    local token_name="$1" session_key="$2" rest_uri="$3" encoded_name resp hec_code
    encoded_name="$(_urlencode "http://${token_name}")"
    if ! resp="$(splunk_curl_post "${session_key}" "" \
        "${rest_uri}/services/data/inputs/http/${encoded_name}/enable" \
        -w '\n%{http_code}' 2>/dev/null)"; then
        return 1
    fi
    hec_code="$(printf '%s\n' "${resp}" | tail -1)"
    case "${hec_code}" in
        200|201|409) return 0 ;;
        *) return 1 ;;
    esac
}

ensure_hec_token() {
    local token_name="${1:-${HEC_TOKEN}}" state indexes_csv acs_create_attempted=false
    log "Checking HEC token '${token_name}'..."

    if is_splunk_cloud; then
        acs_prepare_context || { log "ERROR: ACS context required for Cloud HEC management."; exit 1; }
        if ! state="$(cloud_get_hec_token_state "${token_name}" 2>/dev/null)"; then
            log "ERROR: Could not inspect HEC token '${token_name}' through ACS; refusing mutation."
            return 1
        fi
        case "${state}" in
            enabled)
                log "  HEC token '${token_name}' already exists in Splunk Cloud."
                return 0
                ;;
            disabled)
                log "  HEC token '${token_name}' exists but is disabled. Enabling it via ACS..."
                if ! cloud_enable_hec_token_via_acs "${token_name}"; then
                    log "ERROR: Failed to enable disabled HEC token '${token_name}' via ACS."
                    log "HANDOFF: Enable the token through the supported Splunk Cloud HEC surface, then rerun setup."
                    return 1
                fi
                if ! state="$(cloud_get_hec_token_state "${token_name}" 2>/dev/null)"; then
                    log "ERROR: Could not read back HEC token '${token_name}' after the ACS enable operation."
                    return 1
                fi
                if [[ "${state}" != "enabled" ]]; then
                    log "ERROR: HEC token '${token_name}' did not read back as enabled after the ACS update."
                    return 1
                fi
                log "  HEC token '${token_name}' enabled and read back through ACS."
                return 0
                ;;
            missing) ;;
            *)
                log "ERROR: ACS returned an invalid HEC token observation for '${token_name}'; refusing mutation."
                return 1
                ;;
        esac

        log "  Creating HEC token '${token_name}' via ACS..."
        acs_create_attempted=true
        if cloud_create_hec_token_via_acs "${token_name}"; then
            if ! state="$(cloud_get_hec_token_state "${token_name}" 2>/dev/null)"; then
                log "ERROR: Could not read back HEC token '${token_name}' after the ACS create."
                return 1
            fi
            case "${state}" in
                enabled)
                    log "  HEC token '${token_name}' created via ACS."
                    return 0
                    ;;
                disabled)
                    log "ERROR: ACS create returned success, but HEC token '${token_name}' read back as disabled."
                    return 1
                    ;;
                missing) ;;
                *)
                    log "ERROR: ACS returned an invalid HEC token readback for '${token_name}'."
                    return 1
                    ;;
            esac
        else
            if ! state="$(cloud_get_hec_token_state "${token_name}" 2>/dev/null)"; then
                log "ERROR: ACS create failed and the HEC token state could not be re-observed."
                return 1
            fi
            case "${state}" in
                enabled)
                    log "  HEC token '${token_name}' exists after the ACS create attempt."
                    return 0
                    ;;
                disabled)
                    log "ERROR: HEC token '${token_name}' exists after the ACS create attempt but is disabled."
                    return 1
                    ;;
                missing) ;;
                *)
                    log "ERROR: ACS returned an invalid HEC token readback for '${token_name}'."
                    return 1
                    ;;
            esac
        fi

        log "  ACS HEC token management could not confirm '${token_name}'. Trying search-tier REST..."
        ensure_search_api_session || return 1
        if ! state="$(cloud_rest_get_hec_token_state \
            "${token_name}" "${SK}" "${SPLUNK_URI}" 2>/dev/null)"; then
            log "ERROR: Could not inspect HEC token '${token_name}' through search-tier REST; refusing mutation."
            return 1
        fi
        case "${state}" in
            enabled)
                log "  HEC token '${token_name}' already exists."
                return 0
                ;;
            disabled)
                log "  HEC token '${token_name}' exists but is disabled. Enabling it via search-tier REST..."
                if ! rest_enable_hec_token "${token_name}" "${SK}" "${SPLUNK_URI}"; then
                    log "ERROR: Failed to enable disabled HEC token '${token_name}' through search-tier REST."
                    return 1
                fi
                if ! state="$(cloud_rest_get_hec_token_state \
                    "${token_name}" "${SK}" "${SPLUNK_URI}" 2>/dev/null)"; then
                    log "ERROR: Could not read back HEC token '${token_name}' after the REST enable operation."
                    return 1
                fi
                if [[ "${state}" != "enabled" ]]; then
                    log "ERROR: HEC token '${token_name}' did not read back as enabled after the REST update."
                    return 1
                fi
                log "  HEC token '${token_name}' enabled and read back through search-tier REST."
                return 0
                ;;
            missing) ;;
            *)
                log "ERROR: Search-tier REST returned an invalid HEC token observation for '${token_name}'."
                return 1
                ;;
        esac

        if [[ "${state}" == "missing" && "${acs_create_attempted}" == "true" ]]; then
            log "ERROR: An ACS create was attempted, but neither ACS nor search-tier REST observed HEC token '${token_name}'."
            log "HANDOFF: Resolve the ambiguous create outcome before retrying; refusing a second create operation."
            return 1
        fi

        log "  Creating HEC token '${token_name}' via REST..."
        if rest_create_hec_token "${token_name}" "${SK}" "${SPLUNK_URI}"; then
            if ! state="$(cloud_rest_get_hec_token_state \
                "${token_name}" "${SK}" "${SPLUNK_URI}" 2>/dev/null)"; then
                log "ERROR: Could not read back HEC token '${token_name}' after the REST create."
                return 1
            fi
            case "${state}" in
                enabled)
                    log "  HEC token '${token_name}' created via REST."
                    return 0
                    ;;
                disabled)
                    log "ERROR: REST create returned success, but HEC token '${token_name}' read back as disabled."
                    return 1
                    ;;
            esac
        fi

        log "ERROR: Failed to verify or create HEC token '${token_name}'."
        exit 1
    else
        if ! state="$(enterprise_hec_token_state "${token_name}" 2>/dev/null)"; then
            log "ERROR: Could not inspect HEC token '${token_name}' on the configured ingest target."
            return 1
        fi
        case "${state}" in
            enabled)
                log "  HEC token '${token_name}' already exists."
                return 0
                ;;
            disabled)
                if enterprise_hec_uses_bundle; then
                    log "  HEC token '${token_name}' exists but is disabled. Enabling it via cluster-manager bundle..."
                    if ! deployment_enable_cluster_bundle_hec_token "${token_name}"; then
                        log "ERROR: Failed to enable disabled HEC token '${token_name}' via cluster-manager bundle."
                        return 1
                    fi
                else
                    if [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
                        log "ERROR: Could not resolve the configured ingest deployment target; refusing REST fallback."
                        return 1
                    fi
                    ensure_ingest_api_session || return 1
                    log "  HEC token '${token_name}' exists but is disabled. Enabling it via REST..."
                    if ! rest_enable_hec_token "${token_name}" "${INGEST_SK}" "${INGEST_SPLUNK_URI}"; then
                        log "ERROR: Failed to enable disabled HEC token '${token_name}' via REST."
                        return 1
                    fi
                fi
                if ! state="$(enterprise_hec_token_state "${token_name}" 2>/dev/null)"; then
                    log "ERROR: Could not read back HEC token '${token_name}' after the enable operation."
                    return 1
                fi
                if [[ "${state}" != "enabled" ]]; then
                    log "ERROR: HEC token '${token_name}' did not read back as enabled after the update."
                    return 1
                fi
                log "  HEC token '${token_name}' enabled and read back."
                return 0
                ;;
            missing) ;;
            *)
                log "ERROR: Received an invalid HEC token observation for '${token_name}'; refusing mutation."
                return 1
                ;;
        esac

        indexes_csv="$(IFS=,; echo "${DEFAULT_INDEXES[*]}")"
        if enterprise_hec_uses_bundle; then
            log "  Creating HEC token '${token_name}' via cluster-manager bundle..."
            if deployment_create_cluster_bundle_hec_token "${token_name}" "thousandeyes_metrics" "${indexes_csv}" "0"; then
                if ! state="$(enterprise_hec_token_state "${token_name}" 2>/dev/null)"; then
                    log "ERROR: Could not read back HEC token '${token_name}' after the cluster-manager bundle update."
                    return 1
                fi
                if [[ "${state}" == "enabled" ]]; then
                    log "  HEC token '${token_name}' created via cluster-manager bundle."
                    return 0
                fi
                if [[ "${state}" == "disabled" ]]; then
                    log "ERROR: Cluster-manager bundle create completed, but HEC token '${token_name}' read back as disabled."
                    return 1
                fi
            fi
        else
            if [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
                log "ERROR: Could not resolve the configured ingest deployment target; refusing REST fallback."
                return 1
            fi
            ensure_ingest_api_session || return 1
            log "  Creating HEC token '${token_name}' via REST..."
            if rest_create_hec_token "${token_name}"; then
                if ! state="$(enterprise_hec_token_state "${token_name}" 2>/dev/null)"; then
                    log "ERROR: Could not read back HEC token '${token_name}' after the REST update."
                    return 1
                fi
                if [[ "${state}" == "enabled" ]]; then
                    log "  HEC token '${token_name}' created via REST."
                    return 0
                fi
                if [[ "${state}" == "disabled" ]]; then
                    log "ERROR: REST create completed, but HEC token '${token_name}' read back as disabled."
                    return 1
                fi
            fi
        fi

        log "ERROR: Failed to create HEC token '${token_name}'."
        exit 1
    fi
}

create_indexes() {
    log "Creating indexes..."
    if ! is_splunk_cloud; then
        ensure_search_api_session
    fi
    for idx in "${DEFAULT_INDEXES[@]}"; do
        if platform_create_index "${SK:-}" "${SPLUNK_URI}" "${idx}" "512000"; then
            log "  Index '${idx}' created or already exists."
        else
            log "ERROR: Failed to create index '${idx}'"
            return 1
        fi
    done
    log "Index creation complete."
}

enable_metrics_inputs() {
    local account="$1" acc_group="$2" hec_token="$3"
    local hec_target
    local body
    if ! hec_target=$(detect_hec_target); then
        log "ERROR: Could not resolve the selected Splunk HEC target."
        return 1
    fi

    log "Enabling metrics stream input for account='${account}'..."
    log "  HEC target: ${hec_target}"
    body=$(form_urlencode_pairs \
        disabled "0" \
        thousandeyes_user "${account}" \
        thousandeyes_acc_group "${acc_group}" \
        hec_target "${hec_target}" \
        hec_token "${hec_token}" \
        test_index "thousandeyes_metrics")
    if ${PATHVIS_ENABLED}; then
        body="${body}&$(form_urlencode_pairs \
            related_paths "1" \
            index "${PATHVIS_INDEX}" \
            interval "${PATHVIS_INTERVAL}")"
        log "  Path visualization enabled (index=${PATHVIS_INDEX}, interval=${PATHVIS_INTERVAL}s)."
    fi
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "test_metrics_stream" "metrics_${INPUT_SUFFIX}" "${body}"
    log "  Metrics stream input enabled."
}

enable_traces_inputs() {
    local account="$1" acc_group="$2" hec_token="$3"
    local hec_target
    if ! hec_target=$(detect_hec_target); then
        log "ERROR: Could not resolve the selected Splunk HEC target."
        return 1
    fi

    log "Enabling traces stream input for account='${account}'..."
    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        thousandeyes_user "${account}" \
        thousandeyes_acc_group "${acc_group}" \
        hec_target "${hec_target}" \
        hec_token "${hec_token}" \
        test_index "thousandeyes_traces")
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "test_traces_stream" "traces_${INPUT_SUFFIX}" "${body}"
    log "  Traces stream input enabled."
}

enable_events_inputs() {
    local account="$1" acc_group="$2"
    local idx="${INDEX:-thousandeyes_events}"

    log "Enabling events polling input for account='${account}'..."
    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        thousandeyes_user "${account}" \
        thousandeyes_acc_group "${acc_group}" \
        index "${idx}" \
        interval "3600")
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "event" "events_${INPUT_SUFFIX}" "${body}"
    log "  Events polling input enabled (interval: 3600s)."
}

enable_activity_inputs() {
    local account="$1" acc_group="$2" hec_token="$3"
    local hec_target
    if ! hec_target=$(detect_hec_target); then
        log "ERROR: Could not resolve the selected Splunk HEC target."
        return 1
    fi

    log "Enabling activity logs stream input for account='${account}'..."
    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        thousandeyes_user "${account}" \
        thousandeyes_acc_group "${acc_group}" \
        hec_target "${hec_target}" \
        hec_token "${hec_token}" \
        activity_index "thousandeyes_activity")
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "activity_logs_stream" "activity_${INPUT_SUFFIX}" "${body}"
    log "  Activity logs stream input enabled."
}

enable_alerts_inputs() {
    local account="$1" acc_group="$2" hec_token="$3"
    local hec_target
    if ! hec_target=$(detect_hec_target); then
        log "ERROR: Could not resolve the selected Splunk HEC target."
        return 1
    fi

    log "Enabling alerts stream input for account='${account}'..."
    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        thousandeyes_user "${account}" \
        thousandeyes_acc_group "${acc_group}" \
        alert_rules "${ALERT_RULES}" \
        hec_target "${hec_target}" \
        hec_token "${hec_token}" \
        alerts_index "thousandeyes_alerts")
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "alerts_stream" "alerts_${INPUT_SUFFIX}" "${body}"
    log "  Alerts stream input enabled."
}

enable_all_inputs() {
    local account="$1" acc_group="$2" hec_token="$3"
    enable_metrics_inputs "${account}" "${acc_group}" "${hec_token}"
    enable_traces_inputs "${account}" "${acc_group}" "${hec_token}"
    enable_events_inputs "${account}" "${acc_group}"
    enable_activity_inputs "${account}" "${acc_group}" "${hec_token}"
    enable_alerts_inputs "${account}" "${acc_group}" "${hec_token}"
    log "All inputs enabled (5 inputs)."
}

main() {
    warn_if_current_skill_role_unsupported

    if $ENABLE_INPUTS; then
        check_prereqs
        if [[ -z "${ACCOUNT}" || -z "${INPUT_TYPE}" ]]; then
            log "ERROR: --enable-inputs requires --account and --input-type"
            exit 1
        fi
        if [[ -z "${ACCOUNT_GROUP}" ]]; then
            log "ERROR: --enable-inputs requires --account-group"
            exit 1
        fi
        if [[ "${INPUT_TYPE}" == "alerts" || "${INPUT_TYPE}" == "all" ]]; then
            if [[ -z "${ALERT_RULES}" ]]; then
                log "ERROR: --input-type ${INPUT_TYPE} requires --alert-rules with ~-separated ThousandEyes alert rule IDs."
                exit 1
            fi
        fi
        INPUT_SUFFIX="$(safe_input_suffix "${ACCOUNT}")"
        case "${INPUT_TYPE}" in
            all) enable_all_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" "${HEC_TOKEN}" ;;
            metrics) enable_metrics_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" "${HEC_TOKEN}" ;;
            traces) enable_traces_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" "${HEC_TOKEN}" ;;
            events) enable_events_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" ;;
            activity) enable_activity_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" "${HEC_TOKEN}" ;;
            alerts) enable_alerts_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" "${HEC_TOKEN}" ;;
            *) log "ERROR: Unknown input type '${INPUT_TYPE}'." >&2; usage 1 ;;
        esac
        log_live_input_summary
        log "$(log_platform_restart_guidance "input changes")"
        exit 0
    fi

    if $HEC_ONLY; then
        if is_splunk_cloud; then
            ensure_hec_token "${HEC_TOKEN}" || return 1
        else
            ensure_search_api_session || return 1
            ensure_hec_token "${HEC_TOKEN}" || return 1
        fi
        exit 0
    fi

    if $INDEXES_ONLY; then
        create_indexes
        log "$(log_platform_restart_guidance "index changes")"
        exit 0
    fi

    if is_splunk_cloud; then
        ensure_hec_token "${HEC_TOKEN}" || return 1
    else
        ensure_search_api_session || return 1
        ensure_hec_token "${HEC_TOKEN}" || return 1
    fi
    create_indexes
    ensure_app_visible
    log "$(log_platform_restart_guidance "setup changes")"

    [[ -t 0 ]] || return 0
    log ""
    read -rp "Would you like to authenticate a ThousandEyes account now? [y/N]: " yn
    case "${yn}" in
        [yY]|[yY][eE][sS]) ;;
        *) return 0 ;;
    esac

    log ""
    bash "${SCRIPT_DIR}/configure_account.sh"
    local account_email
    if ! account_email=$(bash -c '
        set -o pipefail
        source "'"${SCRIPT_DIR}"'/../../shared/lib/credential_helpers.sh"
        if ! load_splunk_credentials >/dev/null 2>&1; then
            exit 1
        fi
        if ! SK=$(get_session_key "${SPLUNK_URI}" 2>/dev/null); then
            exit 1
        fi
        splunk_curl "${SK}" \
            "${SPLUNK_URI}/servicesNS/nobody/ta_cisco_thousandeyes/ta_cisco_thousandeyes_account?output_mode=json" \
            2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for e in data.get(\"entry\", []):
        print(e.get(\"name\", \"\"), end=\"\")
        break
except Exception:
    raise SystemExit(1)
" 2>/dev/null
    ' 2>/dev/null); then
        log "ERROR: Could not load or authenticate the selected Splunk target while detecting the ThousandEyes account."
        return 1
    fi

    if [[ -z "${account_email}" ]]; then
        log "Could not detect the ThousandEyes account name."
        log "Run setup.sh --enable-inputs manually after verifying the account."
        return 0
    fi

    log ""
    read -rp "Would you like to enable data inputs for ${account_email}? [y/N]: " inputs_yn
    case "${inputs_yn}" in
        [yY]|[yY][eE][sS]) ;;
        *) log ""; log "Run 'bash ${SCRIPT_DIR}/validate.sh --completion' to prove deployment completion."; return 0 ;;
    esac

    local acc_group
    read -rp "ThousandEyes account group name: " acc_group
    [[ -z "${acc_group}" ]] && { log "ERROR: Account group is required for inputs."; return 1; }

    log ""
    check_prereqs
    enable_all_inputs "${account_email}" "${acc_group}" "${HEC_TOKEN}"
    log_live_input_summary
    log ""
    log "Run 'bash ${SCRIPT_DIR}/validate.sh --completion' to prove deployment completion."
}

main

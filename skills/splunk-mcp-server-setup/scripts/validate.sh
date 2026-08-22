#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_MCP_Server"
MIN_APP_VERSION="1.3.1"
PACKAGE_MANIFEST="${SCRIPT_DIR}/../package-manifest.json"
PACKAGE_REVIEW_METADATA="$(python3 - "${PACKAGE_MANIFEST}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
print(
    manifest["version"],
    str(manifest.get("production_approved", False)).lower(),
    manifest.get("review_status", "unknown"),
    sep="\t",
)
PY
)" || exit 1
IFS=$'\t' read -r REVIEWED_VERSION PACKAGE_PRODUCTION_APPROVED PACKAGE_REVIEW_STATUS <<< "${PACKAGE_REVIEW_METADATA}"

EXPECT_REQUIRE_ENCRYPTED_TOKEN=""
EXPECT_MAX_ROW_LIMIT=""
EXPECT_DEFAULT_ROW_LIMIT=""
EXPECT_GLOBAL_RATE_LIMIT=""
EXPECT_TENANT_AUTHENTICATED=""
COMPLETION=false
ACCEPT_NONPRODUCTION_PACKAGE=false
MCP_BEARER_TOKEN_FILE="${SPLUNK_MCP_BEARER_TOKEN_FILE:-}"
ALLOWED_TOOLS_FILE=""

SK=""
FAILURES=0

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk MCP Server Validation

Usage: $(basename "$0") [OPTIONS]

Optional assertions:
  --completion                       Enforce the deployment role and authenticated MCP handshake/tool probes
  --accept-nonproduction-package     Continue isolated evaluation despite a blocked package review
  --mcp-bearer-token-file PATH       Encrypted MCP bearer token file (chmod 600; required for --completion)
  --allowed-tools-file PATH          JSON array defining the exact reviewed enabled-tool allowlist
  --expect-require-encrypted-token true|false
  --expect-max-row-limit N
  --expect-default-row-limit N
  --expect-global-rate-limit N
  --expect-tenant-authenticated N

Examples:
  $(basename "$0")
  $(basename "$0") --completion
  $(basename "$0") --expect-require-encrypted-token true --expect-max-row-limit 2000

EOF
    exit "${exit_code}"
}

normalize_boolean() {
    case "${1:-}" in
        true|TRUE|True|1|yes|YES|on|ON) printf '%s' "true" ;;
        false|FALSE|False|0|no|NO|off|OFF) printf '%s' "false" ;;
        *)
            log "ERROR: Expected a boolean value, got '${1:-}'. Use true or false."
            exit 1
            ;;
    esac
}

normalize_boolean_if_possible() {
    case "${1:-}" in
        true|TRUE|True|1|yes|YES|on|ON) printf '%s' "true" ;;
        false|FALSE|False|0|no|NO|off|OFF) printf '%s' "false" ;;
        *) printf '%s' "${1:-}" ;;
    esac
}

derive_mcp_url() {
    python3 - "${1:-}" <<'PY'
from urllib.parse import urlsplit
import sys

uri = (sys.argv[1] or "").strip()
if not uri:
    raise SystemExit(1)
if "://" not in uri:
    uri = "https://" + uri

parts = urlsplit(uri)
scheme = parts.scheme.lower()
netloc = parts.netloc
if scheme not in {"http", "https"} or not netloc or parts.username or parts.password:
    raise SystemExit(1)
print(f"{scheme}://{netloc}/services/mcp", end="")
PY
}

derive_protected_resource_url() {
    python3 - "${1:-}" <<'PY'
from urllib.parse import urlsplit
import sys

uri = (sys.argv[1] or "").strip()
if "://" not in uri:
    uri = "https://" + uri
parts = urlsplit(uri)
scheme = parts.scheme.lower()
netloc = parts.netloc
if scheme not in {"http", "https"} or not netloc or parts.username or parts.password:
    raise SystemExit(1)
print(f"{scheme}://{netloc}/.well-known/oauth-protected-resource", end="")
PY
}

validate_endpoint_url() {
    python3 - "$1" <<'PY'
import ipaddress
import sys
from urllib.parse import urlsplit

parts = urlsplit(sys.argv[1])
if not parts.hostname or parts.username or parts.password:
    raise SystemExit("ERROR: MCP endpoint must include a host and no userinfo")
host = parts.hostname.lower()
loopback = host == "localhost"
try:
    loopback = loopback or ipaddress.ip_address(host).is_loopback
except ValueError:
    pass
if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
    raise SystemExit("ERROR: MCP endpoint must use HTTPS; HTTP is allowed only for loopback")
PY
}

ensure_session() {
    load_splunk_credentials || {
        log "ERROR: Splunk credentials are required."
        exit 1
    }
    SK="$(get_session_key "${SPLUNK_URI}")" || {
        log "ERROR: Could not authenticate to Splunk."
        exit 1
    }
}

http_code_for() {
    local url="$1"
    splunk_curl "${SK}" "${url}" -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000"
}

assert_mcp_bearer_token_file() {
    local path="$1" mode owner size
    [[ ! -L "${path}" && -f "${path}" && -r "${path}" && -s "${path}" ]] || {
        log "ERROR: MCP bearer token must be a readable, non-empty, non-symlink regular file: ${path}"
        exit 1
    }
    mode="$(stat -c '%a' "${path}" 2>/dev/null || stat -f '%Lp' "${path}" 2>/dev/null)"
    [[ "${mode}" == "600" ]] || {
        log "ERROR: MCP bearer token file must be chmod 600 (found ${mode:-unknown}): ${path}"
        exit 1
    }
    owner="$(stat -c '%u' "${path}" 2>/dev/null || stat -f '%u' "${path}" 2>/dev/null)"
    [[ "${owner}" == "$(id -u)" ]] || {
        log "ERROR: MCP bearer token file must be owned by the current user: ${path}"
        exit 1
    }
    size="$(stat -c '%s' "${path}" 2>/dev/null || stat -f '%z' "${path}" 2>/dev/null)"
    if [[ ! "${size}" =~ ^[0-9]+$ ]] || (( 10#${size} > 65536 )); then
        log "ERROR: MCP bearer token file size is unknown or exceeds 65536 bytes: ${path}"
        exit 1
    fi
}

assert_allowed_tools_file() {
    local path="$1" size
    [[ ! -L "${path}" && -f "${path}" && -r "${path}" ]] || {
        log "ERROR: Allowed-tools policy must be a readable, non-symlink regular file: ${path}"
        exit 1
    }
    size="$(stat -c '%s' "${path}" 2>/dev/null || stat -f '%z' "${path}" 2>/dev/null)"
    if [[ ! "${size}" =~ ^[0-9]+$ ]] || (( 10#${size} > 65536 )); then
        log "ERROR: Allowed-tools policy size is unknown or exceeds 65536 bytes: ${path}"
        exit 1
    fi
    python3 - "${path}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    value = json.load(handle)
if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
    raise SystemExit("ERROR: allowed-tools policy must be a non-empty JSON array of tool-name strings")
if len(value) != len(set(value)):
    raise SystemExit("ERROR: allowed-tools policy contains duplicate tool names")
PY
}

mcp_post_json_with_code() {
    local url="$1" payload="$2"
    local token escaped_token transport_protocol="=https"
    local -a extra_headers=()
    shift 2
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -H|--header)
                require_arg "$1" $# || return 1
                if [[ "$2" == *$'\n'* || "$2" == *$'\r'* ]]; then
                    log "ERROR: MCP probe header contains a newline."
                    return 1
                fi
                extra_headers+=(--header "$2")
                shift 2
                ;;
            *)
                log "ERROR: Unsupported MCP probe curl option: $1"
                return 1
                ;;
        esac
    done
    if [[ -n "${MCP_BEARER_TOKEN_FILE}" ]]; then
        token="$(read_secret_file "${MCP_BEARER_TOKEN_FILE}")" || return 1
        if [[ -z "${token}" || "${token}" == *$'\n'* || "${token}" == *$'\r'* || ${#token} -gt 65536 ]]; then
            log "ERROR: MCP bearer token file contains an empty or invalid header value."
            return 1
        fi
        escaped_token="$(_curl_config_escape "${token}")"
        _set_splunk_curl_tls_args || return 1
        case "${url}" in
            [Hh][Tt][Tt][Pp]://*) transport_protocol="=http,https" ;;
        esac
        # shellcheck disable=SC2154  # populated by _set_splunk_curl_tls_args
        curl -q -s ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} \
            --connect-timeout "${SPLUNK_REST_CONNECT_TIMEOUT:-10}" \
            --max-time "${SPLUNK_REST_MAX_TIME:-120}" \
            -K <(printf 'header = "Authorization: Bearer %s"\n' "${escaped_token}") \
            -X POST "${url}" \
            -H 'Accept: application/json, text/event-stream' \
            -H 'MCP-Protocol-Version: 2025-06-18' \
            -H 'Content-Type: application/json' \
            -d "${payload}" \
            -w '\n%{http_code}' "${extra_headers[@]}" \
            --proto "${transport_protocol}" \
            --proto-redir "${transport_protocol}" \
            --max-redirs 0 \
            --globoff \
            2>/dev/null || echo "000"
        return
    fi
    splunk_curl "${SK}" -X POST "${url}" \
        -H 'Accept: application/json, text/event-stream' \
        -H 'MCP-Protocol-Version: 2025-06-18' \
        -H 'Content-Type: application/json' \
        -d "${payload}" \
        -w '\n%{http_code}' "${extra_headers[@]}" 2>/dev/null || echo "000"
}

app_visible() {
    splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/apps/local/${APP_NAME}?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    value = json.load(sys.stdin)["entry"][0]["content"].get("visible", True)
    print(str(value), end="")
except Exception:
    print("unknown", end="")
' 2>/dev/null || echo "unknown"
}

assert_equal() {
    local label="$1" expected="$2" actual="$3"
    if [[ "${expected}" != "${actual}" ]]; then
        log "ERROR: ${label}: expected '${expected}', got '${actual}'."
        FAILURES=$((FAILURES + 1))
    fi
}

assert_integer_range() {
    local label="$1" actual="$2" minimum="$3" maximum="$4"
    if [[ ! "${actual}" =~ ^[0-9]+$ ]] || (( 10#${actual} < minimum || 10#${actual} > maximum )); then
        log "ERROR: ${label} must be an integer between ${minimum} and ${maximum}; got '${actual:-unset}'."
        FAILURES=$((FAILURES + 1))
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --expect-require-encrypted-token) require_arg "$1" $# || exit 1; EXPECT_REQUIRE_ENCRYPTED_TOKEN="$(normalize_boolean "$2")"; shift 2 ;;
        --expect-max-row-limit) require_arg "$1" $# || exit 1; EXPECT_MAX_ROW_LIMIT="$2"; shift 2 ;;
        --expect-default-row-limit) require_arg "$1" $# || exit 1; EXPECT_DEFAULT_ROW_LIMIT="$2"; shift 2 ;;
        --expect-global-rate-limit) require_arg "$1" $# || exit 1; EXPECT_GLOBAL_RATE_LIMIT="$2"; shift 2 ;;
        --expect-tenant-authenticated) require_arg "$1" $# || exit 1; EXPECT_TENANT_AUTHENTICATED="$2"; shift 2 ;;
        --mcp-bearer-token-file) require_arg "$1" $# || exit 1; MCP_BEARER_TOKEN_FILE="$2"; shift 2 ;;
        --allowed-tools-file) require_arg "$1" $# || exit 1; ALLOWED_TOOLS_FILE="$2"; shift 2 ;;
        --completion|--strict) COMPLETION=true; shift ;;
        --accept-nonproduction-package) ACCEPT_NONPRODUCTION_PACKAGE=true; shift ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ "${COMPLETION}" == "true" && -z "${MCP_BEARER_TOKEN_FILE}" ]]; then
    log "ERROR: --completion requires --mcp-bearer-token-file (or SPLUNK_MCP_BEARER_TOKEN_FILE)."
    exit 1
fi
if [[ -n "${MCP_BEARER_TOKEN_FILE}" ]]; then
    assert_mcp_bearer_token_file "${MCP_BEARER_TOKEN_FILE}"
fi
if [[ -n "${ALLOWED_TOOLS_FILE}" ]]; then
    assert_allowed_tools_file "${ALLOWED_TOOLS_FILE}"
fi

if [[ "${COMPLETION}" == "true" ]]; then
    require_current_skill_role_supported
else
    warn_if_role_unsupported_for_skill "splunk-mcp-server-setup"
fi
ensure_session

if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
    log "ERROR: ${APP_NAME} is not installed."
    exit 1
fi

APP_VERSION="$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}")"
APP_VISIBLE="$(app_visible)"
SSL_VERIFY_ENFORCEMENT="unverified"
if [[ "${APP_VERSION}" == "1.3.1" ]]; then
    SSL_VERIFY_ENFORCEMENT="not_implemented_by_vendor"
fi
MCP_URL="$(derive_mcp_url "${SPLUNK_URI}" || echo "unknown")"
PROTECTED_RESOURCE_URL="$(derive_protected_resource_url "${SPLUNK_URI}" || echo "unknown")"
validate_endpoint_url "${MCP_URL}" || exit 1

SERVER_BASE_URL="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "server" "base_url")"
SERVER_TIMEOUT="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "server" "timeout")"
SERVER_MAX_ROW_LIMIT="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "server" "max_row_limit")"
SERVER_DEFAULT_ROW_LIMIT="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "server" "default_row_limit")"
SERVER_SSL_VERIFY="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "server" "ssl_verify")"
SERVER_REQUIRE_ENCRYPTED_TOKEN="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "server" "require_encrypted_token")"
SERVER_REQUIRE_ENCRYPTED_TOKEN_NORMALIZED="$(normalize_boolean_if_possible "${SERVER_REQUIRE_ENCRYPTED_TOKEN}")"
SERVER_LEGACY_TOKEN_GRACE_DAYS="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "server" "legacy_token_grace_days")"
SERVER_TOKEN_DEFAULT_LIFETIME="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "server" "mcp_token_default_lifetime_seconds")"
SERVER_TOKEN_MAX_LIFETIME="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "server" "mcp_token_max_lifetime_seconds")"
SERVER_TOKEN_KEY_RELOAD_INTERVAL="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "server" "token_key_reload_interval_seconds")"
RATE_GLOBAL="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "rate_limits" "global")"
RATE_ADMISSION_GLOBAL="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "rate_limits" "admission_global")"
RATE_TENANT_AUTHENTICATED="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "rate_limits" "tenant_authenticated")"
RATE_TENANT_UNAUTHENTICATED="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "rate_limits" "tenant_unauthenticated")"
RATE_CIRCUIT_BREAKER_FAILURE_THRESHOLD="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "rate_limits" "circuit_breaker_failure_threshold")"
RATE_CIRCUIT_BREAKER_COOLDOWN_SECONDS="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "mcp" "rate_limits" "circuit_breaker_cooldown_seconds")"

MCP_PING_RESP="$(mcp_post_json_with_code "${MCP_URL}" '{"jsonrpc":"2.0","id":"validate-ping","method":"ping"}')"
MCP_PING_CODE="$(printf '%s\n' "${MCP_PING_RESP}" | tail -1)"
MCP_PING_BODY="$(printf '%s\n' "${MCP_PING_RESP}" | sed '$d')"
MCP_PING_RESULT="$(
    printf '%s' "${MCP_PING_BODY}" | python3 -c '
import json, sys
try:
    payload = json.load(sys.stdin)
    print(payload.get("result", {}).get("message", ""), end="")
except Exception:
    print("", end="")
' 2>/dev/null || true
)"

MCP_INITIALIZE_CODE="not-run"
MCP_INITIALIZE_PROTOCOL="not-run"
MCP_INITIALIZED_CODE="not-run"
MCP_INITIALIZED_EMPTY_BODY="not-run"
MCP_TOOLS_LIST_CODE="not-run"
MCP_TOOLS_LIST_HAS_GET_INFO="not-run"
MCP_TOOLS_LIST_NAMES="not-run"
MCP_TOOLS_POLICY_OK="not-run"
MCP_TOOLS_LIST_HAS_NEXT_CURSOR="not-run"
MCP_GET_INFO_CODE="not-run"
MCP_GET_INFO_OK="not-run"
MCP_UNTRUSTED_ORIGIN_CODE="not-run"
if [[ "${COMPLETION}" == "true" ]]; then
    MCP_INITIALIZE_RESP="$(mcp_post_json_with_code "${MCP_URL}" '{"jsonrpc":"2.0","id":"validate-init","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"splunk-cisco-skills-validator","version":"1.0.0"}}}')"
    MCP_INITIALIZE_CODE="$(printf '%s\n' "${MCP_INITIALIZE_RESP}" | tail -1)"
    MCP_INITIALIZE_BODY="$(printf '%s\n' "${MCP_INITIALIZE_RESP}" | sed '$d')"
    MCP_INITIALIZE_PROTOCOL="$(printf '%s' "${MCP_INITIALIZE_BODY}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result",{}).get("protocolVersion",""),end="")' 2>/dev/null || true)"

    MCP_INITIALIZED_RESP="$(mcp_post_json_with_code "${MCP_URL}" '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}')"
    MCP_INITIALIZED_CODE="$(printf '%s\n' "${MCP_INITIALIZED_RESP}" | tail -1)"
    MCP_INITIALIZED_BODY="$(printf '%s\n' "${MCP_INITIALIZED_RESP}" | sed '$d')"
    if [[ -z "${MCP_INITIALIZED_BODY}" ]]; then
        MCP_INITIALIZED_EMPTY_BODY="true"
    else
        MCP_INITIALIZED_EMPTY_BODY="false"
    fi

    MCP_TOOLS_LIST_RESP="$(mcp_post_json_with_code "${MCP_URL}" '{"jsonrpc":"2.0","id":"validate-tools","method":"tools/list","params":{}}')"
    MCP_TOOLS_LIST_CODE="$(printf '%s\n' "${MCP_TOOLS_LIST_RESP}" | tail -1)"
    MCP_TOOLS_LIST_BODY="$(printf '%s\n' "${MCP_TOOLS_LIST_RESP}" | sed '$d')"
    MCP_TOOLS_LIST_HAS_GET_INFO="$(printf '%s' "${MCP_TOOLS_LIST_BODY}" | python3 -c 'import json,sys; names={x.get("name") for x in json.load(sys.stdin).get("result",{}).get("tools",[])}; print("true" if "splunk_get_info" in names else "false",end="")' 2>/dev/null || printf 'false')"
    TOOL_POLICY_METADATA="$(
        printf '%s' "${MCP_TOOLS_LIST_BODY}" | python3 -c '
import json, sys

payload = json.load(sys.stdin)
result = payload.get("result", {})
tools = result.get("tools", [])
valid_entries = isinstance(tools, list) and all(
    isinstance(item, dict) and isinstance(item.get("name"), str) and item.get("name")
    for item in tools
)
raw_names = [item["name"] for item in tools] if valid_entries else []
names = sorted(set(raw_names))
if sys.argv[1]:
    with open(sys.argv[1], encoding="utf-8") as handle:
        expected = sorted(json.load(handle))
else:
    expected = ["splunk_get_info"]
has_next = bool(result.get("nextCursor"))
policy_ok = valid_entries and len(raw_names) == len(names) and names == expected and not has_next
print(json.dumps(names, separators=(",", ":")), str(policy_ok).lower(), str(has_next).lower(), sep="\t", end="")
' "${ALLOWED_TOOLS_FILE}" 2>/dev/null || printf '%s\t%s\t%s' '[]' 'false' 'false'
    )"
    IFS=$'\t' read -r MCP_TOOLS_LIST_NAMES MCP_TOOLS_POLICY_OK MCP_TOOLS_LIST_HAS_NEXT_CURSOR <<< "${TOOL_POLICY_METADATA}"

    MCP_GET_INFO_RESP="$(mcp_post_json_with_code "${MCP_URL}" '{"jsonrpc":"2.0","id":"validate-get-info","method":"tools/call","params":{"name":"splunk_get_info","arguments":{}}}')"
    MCP_GET_INFO_CODE="$(printf '%s\n' "${MCP_GET_INFO_RESP}" | tail -1)"
    MCP_GET_INFO_BODY="$(printf '%s\n' "${MCP_GET_INFO_RESP}" | sed '$d')"
    MCP_GET_INFO_OK="$(printf '%s' "${MCP_GET_INFO_BODY}" | python3 -c 'import json,sys; p=json.load(sys.stdin); print("true" if "result" in p and not p.get("result",{}).get("isError",False) else "false",end="")' 2>/dev/null || printf 'false')"

    MCP_UNTRUSTED_ORIGIN_RESP="$(mcp_post_json_with_code "${MCP_URL}" '{"jsonrpc":"2.0","id":"validate-origin","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"security-probe","version":"1.0.0"}}}' -H 'Origin: https://untrusted.invalid')"
    MCP_UNTRUSTED_ORIGIN_CODE="$(printf '%s\n' "${MCP_UNTRUSTED_ORIGIN_RESP}" | tail -1)"
fi

MCP_TOOLS_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_tools?output_mode=json")"
MCP_RATE_LIMITS_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_rate_limits?output_mode=json")"
MCP_TOKEN_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_token?output_mode=json")"
MCP_TOOL_ROLES_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_tool_roles?output_mode=json")"
MCP_GUARDRAILS_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_guardrails?output_mode=json")"
ALLOWED_SPL_COMMANDS_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/allowed_spl_cmds?output_mode=json")"
MCP_TOOLS_COLLECTION_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/storage/collections/config/mcp_tools?output_mode=json")"
MCP_TOOLS_ENABLED_COLLECTION_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/storage/collections/config/mcp_tools_enabled?output_mode=json")"
MCP_TOOL_ROLES_COLLECTION_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/storage/collections/config/mcp_tool_roles?output_mode=json")"
PROTECTED_RESOURCE_CODE="$(http_code_for "${PROTECTED_RESOURCE_URL}")"
VIEW_DASHBOARD_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/ui/views/dashboard?output_mode=json")"
VIEW_MONITORING_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/ui/views/monitoring?output_mode=json")"
VIEW_TOOLS_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/ui/views/tools?output_mode=json")"
VIEW_TOOL_SETTINGS_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/ui/views/tool_settings?output_mode=json")"

log "Splunk MCP Server validation summary:"
printf '%s\n' "  app=${APP_NAME}" \
               "  version=${APP_VERSION}" \
               "  visible=${APP_VISIBLE}" \
               "  derived_mcp_url=${MCP_URL}" \
               "  derived_protected_resource_url=${PROTECTED_RESOURCE_URL}" \
               "  base_url=${SERVER_BASE_URL:-unset}" \
               "  timeout=${SERVER_TIMEOUT:-unset}" \
               "  max_row_limit=${SERVER_MAX_ROW_LIMIT:-unset}" \
               "  default_row_limit=${SERVER_DEFAULT_ROW_LIMIT:-unset}" \
               "  ssl_verify_configured=${SERVER_SSL_VERIFY:-unset}" \
               "  ssl_verify_enforcement=${SSL_VERIFY_ENFORCEMENT}" \
               "  require_encrypted_token=${SERVER_REQUIRE_ENCRYPTED_TOKEN_NORMALIZED:-unset}" \
               "  legacy_token_grace_days=${SERVER_LEGACY_TOKEN_GRACE_DAYS:-unset}" \
               "  token_default_lifetime_seconds=${SERVER_TOKEN_DEFAULT_LIFETIME:-unset}" \
               "  token_max_lifetime_seconds=${SERVER_TOKEN_MAX_LIFETIME:-unset}" \
               "  token_key_reload_interval_seconds=${SERVER_TOKEN_KEY_RELOAD_INTERVAL:-unset}" \
               "  rate_limit_global=${RATE_GLOBAL:-unset}" \
               "  rate_limit_admission_global=${RATE_ADMISSION_GLOBAL:-unset}" \
               "  rate_limit_tenant_authenticated=${RATE_TENANT_AUTHENTICATED:-unset}" \
               "  rate_limit_tenant_unauthenticated=${RATE_TENANT_UNAUTHENTICATED:-unset}" \
               "  rate_limit_circuit_breaker_failure_threshold=${RATE_CIRCUIT_BREAKER_FAILURE_THRESHOLD:-unset}" \
               "  rate_limit_circuit_breaker_cooldown_seconds=${RATE_CIRCUIT_BREAKER_COOLDOWN_SECONDS:-unset}" \
               "  endpoint_services_mcp_ping_http=${MCP_PING_CODE}" \
               "  endpoint_services_mcp_ping_result=${MCP_PING_RESULT:-unset}" \
               "  endpoint_services_mcp_initialize_http=${MCP_INITIALIZE_CODE}" \
               "  endpoint_services_mcp_protocol=${MCP_INITIALIZE_PROTOCOL}" \
               "  endpoint_services_mcp_initialized_notification_http=${MCP_INITIALIZED_CODE}" \
               "  endpoint_services_mcp_initialized_notification_empty_body=${MCP_INITIALIZED_EMPTY_BODY}" \
               "  endpoint_services_mcp_tools_list_http=${MCP_TOOLS_LIST_CODE}" \
               "  endpoint_services_mcp_tools_list_has_get_info=${MCP_TOOLS_LIST_HAS_GET_INFO}" \
               "  endpoint_services_mcp_tools_list_names=${MCP_TOOLS_LIST_NAMES}" \
               "  endpoint_services_mcp_tools_policy_ok=${MCP_TOOLS_POLICY_OK}" \
               "  endpoint_services_mcp_tools_list_has_next_cursor=${MCP_TOOLS_LIST_HAS_NEXT_CURSOR}" \
               "  endpoint_services_mcp_get_info_http=${MCP_GET_INFO_CODE}" \
               "  endpoint_services_mcp_get_info_ok=${MCP_GET_INFO_OK}" \
               "  endpoint_services_mcp_untrusted_origin_http=${MCP_UNTRUSTED_ORIGIN_CODE}" \
               "  endpoint_mcp_tools_http=${MCP_TOOLS_CODE}" \
               "  endpoint_mcp_rate_limits_http=${MCP_RATE_LIMITS_CODE}" \
               "  endpoint_mcp_token_http=${MCP_TOKEN_CODE}" \
               "  endpoint_mcp_tool_roles_http=${MCP_TOOL_ROLES_CODE}" \
               "  endpoint_mcp_guardrails_http=${MCP_GUARDRAILS_CODE}" \
               "  endpoint_allowed_spl_cmds_http=${ALLOWED_SPL_COMMANDS_CODE}" \
               "  endpoint_protected_resource_http=${PROTECTED_RESOURCE_CODE}" \
               "  kv_mcp_tools_http=${MCP_TOOLS_COLLECTION_CODE}" \
               "  kv_mcp_tools_enabled_http=${MCP_TOOLS_ENABLED_COLLECTION_CODE}" \
               "  kv_mcp_tool_roles_http=${MCP_TOOL_ROLES_COLLECTION_CODE}" \
               "  view_dashboard_http=${VIEW_DASHBOARD_CODE}" \
               "  view_monitoring_http=${VIEW_MONITORING_CODE}" \
               "  view_tools_http=${VIEW_TOOLS_CODE}" \
               "  view_tool_settings_http=${VIEW_TOOL_SETTINGS_CODE}"

python3 - "${APP_VERSION}" "${MIN_APP_VERSION}" <<'PY' || FAILURES=$((FAILURES + 1))
import sys

def version(value):
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return ()

actual, minimum = sys.argv[1:]
if not version(actual) or version(actual) < version(minimum):
    print(f"ERROR: Splunk MCP Server {minimum} or newer is required; found {actual or 'unknown'}", file=sys.stderr)
    raise SystemExit(1)
PY

if [[ "${APP_VERSION}" != "${REVIEWED_VERSION}" || "${PACKAGE_PRODUCTION_APPROVED}" != "true" ]]; then
    if [[ "${ACCEPT_NONPRODUCTION_PACKAGE}" == "true" ]]; then
        log "WARNING: Continuing isolated validation of a non-production-approved package."
    elif [[ "${COMPLETION}" == "true" ]]; then
        log "ERROR: Installed ${APP_NAME} ${APP_VERSION} is not production-approved by this repository review."
        log "       reviewed_version=${REVIEWED_VERSION} review_status=${PACKAGE_REVIEW_STATUS}"
        FAILURES=$((FAILURES + 1))
    else
        log "WARNING: Installed ${APP_NAME} ${APP_VERSION} is not production-approved (review_status=${PACKAGE_REVIEW_STATUS})."
    fi
fi

[[ "${APP_VISIBLE}" == "True" || "${APP_VISIBLE}" == "true" ]] || {
    log "ERROR: ${APP_NAME} is installed but not visible in Splunk Web."
    FAILURES=$((FAILURES + 1))
}

[[ "${MCP_PING_CODE}" == "200" && "${MCP_PING_RESULT}" == "pong" ]] || {
    log "ERROR: /services/mcp ping probe failed."
    FAILURES=$((FAILURES + 1))
}
if [[ "${COMPLETION}" == "true" ]]; then
    [[ "${MCP_INITIALIZE_CODE}" == "200" && "${MCP_INITIALIZE_PROTOCOL}" == "2025-06-18" ]] || {
        log "ERROR: Authenticated MCP initialize failed or did not negotiate protocol 2025-06-18."
        FAILURES=$((FAILURES + 1))
    }
    [[ "${MCP_INITIALIZED_CODE}" == "202" && "${MCP_INITIALIZED_EMPTY_BODY}" == "true" ]] || {
        log "ERROR: MCP notifications/initialized must return HTTP 202 with an empty body."
        FAILURES=$((FAILURES + 1))
    }
    [[ "${MCP_TOOLS_LIST_CODE}" == "200" && "${MCP_TOOLS_LIST_HAS_GET_INFO}" == "true" ]] || {
        log "ERROR: Authenticated tools/list did not expose splunk_get_info."
        FAILURES=$((FAILURES + 1))
    }
    [[ "${MCP_TOOLS_POLICY_OK}" == "true" ]] || {
        log "ERROR: Enabled MCP tools do not exactly match the reviewed allowlist, or tools/list was paginated."
        FAILURES=$((FAILURES + 1))
    }
    [[ "${MCP_GET_INFO_CODE}" == "200" && "${MCP_GET_INFO_OK}" == "true" ]] || {
        log "ERROR: Safe splunk_get_info tools/call failed."
        FAILURES=$((FAILURES + 1))
    }
    [[ "${MCP_UNTRUSTED_ORIGIN_CODE}" == "403" ]] || {
        log "ERROR: /services/mcp did not reject an untrusted Origin with HTTP 403."
        FAILURES=$((FAILURES + 1))
    }
    [[ "${SERVER_REQUIRE_ENCRYPTED_TOKEN_NORMALIZED}" == "true" ]] || {
        log "ERROR: Production completion requires require_encrypted_token=true."
        FAILURES=$((FAILURES + 1))
    }
    if [[ "${APP_VERSION}" == "1.3.1" ]]; then
        log "ERROR: Splunk MCP Server 1.3.1 records ssl_verify but does not enforce it for internal HTTP calls."
        FAILURES=$((FAILURES + 1))
    fi
    assert_integer_range "legacy_token_grace_days" "${SERVER_LEGACY_TOKEN_GRACE_DAYS}" 0 0
    assert_integer_range "mcp_token_default_lifetime_seconds" "${SERVER_TOKEN_DEFAULT_LIFETIME}" 1 86400
    assert_integer_range "mcp_token_max_lifetime_seconds" "${SERVER_TOKEN_MAX_LIFETIME}" 1 86400
    if [[ "${SERVER_TOKEN_DEFAULT_LIFETIME}" =~ ^[0-9]+$ && "${SERVER_TOKEN_MAX_LIFETIME}" =~ ^[0-9]+$ ]] \
       && (( 10#${SERVER_TOKEN_DEFAULT_LIFETIME} > 10#${SERVER_TOKEN_MAX_LIFETIME} )); then
        log "ERROR: Default token lifetime cannot exceed the maximum token lifetime."
        FAILURES=$((FAILURES + 1))
    fi
    assert_integer_range "rate_limits.global" "${RATE_GLOBAL}" 1 10000
    assert_integer_range "rate_limits.admission_global" "${RATE_ADMISSION_GLOBAL}" 1 10000
    assert_integer_range "rate_limits.tenant_authenticated" "${RATE_TENANT_AUTHENTICATED}" 1 10000
    assert_integer_range "rate_limits.tenant_unauthenticated" "${RATE_TENANT_UNAUTHENTICATED}" 1 10000
fi

[[ "${MCP_TOOLS_CODE}" == "200" ]] || {
    log "ERROR: /mcp_tools did not return HTTP 200."
    FAILURES=$((FAILURES + 1))
}
[[ "${MCP_RATE_LIMITS_CODE}" == "200" ]] || {
    log "ERROR: /mcp_rate_limits did not return HTTP 200."
    FAILURES=$((FAILURES + 1))
}
[[ "${MCP_TOOL_ROLES_CODE}" == "200" ]] || {
    log "ERROR: /mcp_tool_roles did not return HTTP 200."
    FAILURES=$((FAILURES + 1))
}
[[ "${MCP_GUARDRAILS_CODE}" == "200" ]] || {
    log "ERROR: /mcp_guardrails did not return HTTP 200."
    FAILURES=$((FAILURES + 1))
}
[[ "${ALLOWED_SPL_COMMANDS_CODE}" == "200" ]] || {
    log "ERROR: /allowed_spl_cmds did not return HTTP 200."
    FAILURES=$((FAILURES + 1))
}
case "${SERVER_REQUIRE_ENCRYPTED_TOKEN_NORMALIZED}" in
    true)
        [[ "${MCP_TOKEN_CODE}" == "200" || "${MCP_TOKEN_CODE}" == "400" ]] || {
            log "ERROR: /mcp_token returned unexpected HTTP ${MCP_TOKEN_CODE}."
            FAILURES=$((FAILURES + 1))
        }
        ;;
    false)
        [[ "${MCP_TOKEN_CODE}" == "412" ]] || {
            log "ERROR: /mcp_token should fail closed with HTTP 412 when require_encrypted_token=false."
            FAILURES=$((FAILURES + 1))
        }
        ;;
    *)
        log "ERROR: Could not determine require_encrypted_token state from mcp.conf."
        FAILURES=$((FAILURES + 1))
        ;;
esac
[[ "${PROTECTED_RESOURCE_CODE}" == "200" || "${PROTECTED_RESOURCE_CODE}" == "404" ]] || {
    log "ERROR: OAuth protected-resource metadata returned unexpected HTTP ${PROTECTED_RESOURCE_CODE}."
    FAILURES=$((FAILURES + 1))
}
[[ "${MCP_TOOLS_COLLECTION_CODE}" == "200" ]] || {
    log "ERROR: KV Store collection config for mcp_tools is missing."
    FAILURES=$((FAILURES + 1))
}
[[ "${MCP_TOOLS_ENABLED_COLLECTION_CODE}" == "200" ]] || {
    log "ERROR: KV Store collection config for mcp_tools_enabled is missing."
    FAILURES=$((FAILURES + 1))
}
[[ "${MCP_TOOL_ROLES_COLLECTION_CODE}" == "200" ]] || {
    log "ERROR: KV Store collection config for mcp_tool_roles is missing."
    FAILURES=$((FAILURES + 1))
}
for view_check in \
    "dashboard:${VIEW_DASHBOARD_CODE}" \
    "monitoring:${VIEW_MONITORING_CODE}" \
    "tools:${VIEW_TOOLS_CODE}" \
    "tool_settings:${VIEW_TOOL_SETTINGS_CODE}"; do
    view_name="${view_check%%:*}"
    view_code="${view_check#*:}"
    [[ "${view_code}" == "200" ]] || {
        log "ERROR: Shipped view ${view_name} is not visible (HTTP ${view_code})."
        FAILURES=$((FAILURES + 1))
    }
done

if [[ -n "${EXPECT_REQUIRE_ENCRYPTED_TOKEN}" ]]; then
    assert_equal "require_encrypted_token" "${EXPECT_REQUIRE_ENCRYPTED_TOKEN}" "${SERVER_REQUIRE_ENCRYPTED_TOKEN_NORMALIZED}"
fi
if [[ -n "${EXPECT_MAX_ROW_LIMIT}" ]]; then
    assert_equal "max_row_limit" "${EXPECT_MAX_ROW_LIMIT}" "${SERVER_MAX_ROW_LIMIT}"
fi
if [[ -n "${EXPECT_DEFAULT_ROW_LIMIT}" ]]; then
    assert_equal "default_row_limit" "${EXPECT_DEFAULT_ROW_LIMIT}" "${SERVER_DEFAULT_ROW_LIMIT}"
fi
if [[ -n "${EXPECT_GLOBAL_RATE_LIMIT}" ]]; then
    assert_equal "rate_limits.global" "${EXPECT_GLOBAL_RATE_LIMIT}" "${RATE_GLOBAL}"
fi
if [[ -n "${EXPECT_TENANT_AUTHENTICATED}" ]]; then
    assert_equal "rate_limits.tenant_authenticated" "${EXPECT_TENANT_AUTHENTICATED}" "${RATE_TENANT_AUTHENTICATED}"
fi

if (( FAILURES > 0 )); then
    exit 1
fi

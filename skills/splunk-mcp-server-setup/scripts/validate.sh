#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_MCP_Server"

EXPECT_REQUIRE_ENCRYPTED_TOKEN=""
EXPECT_MAX_ROW_LIMIT=""
EXPECT_DEFAULT_ROW_LIMIT=""
EXPECT_GLOBAL_RATE_LIMIT=""
EXPECT_TENANT_AUTHENTICATED=""

SK=""
FAILURES=0

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk MCP Server Validation

Usage: $(basename "$0") [OPTIONS]

Optional assertions:
  --expect-require-encrypted-token true|false
  --expect-max-row-limit N
  --expect-default-row-limit N
  --expect-global-rate-limit N
  --expect-tenant-authenticated N

Examples:
  $(basename "$0")
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
parts = urlsplit(uri)
scheme = parts.scheme or "https"
netloc = parts.netloc or parts.path
if not netloc:
    raise SystemExit(1)
print(f"{scheme}://{netloc}/services/mcp", end="")
PY
}

derive_protected_resource_url() {
    python3 - "${1:-}" <<'PY'
from urllib.parse import urlsplit
import sys

uri = (sys.argv[1] or "").strip()
parts = urlsplit(uri)
scheme = parts.scheme or "https"
netloc = parts.netloc or parts.path
if not netloc:
    raise SystemExit(1)
print(f"{scheme}://{netloc}/.well-known/oauth-protected-resource", end="")
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

post_json_with_code() {
    local url="$1" payload="$2"
    splunk_curl "${SK}" -X POST "${url}" \
        -H 'Content-Type: application/json' \
        -d "${payload}" \
        -w '\n%{http_code}' 2>/dev/null || echo "000"
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

while [[ $# -gt 0 ]]; do
    case "$1" in
        --expect-require-encrypted-token) require_arg "$1" $# || exit 1; EXPECT_REQUIRE_ENCRYPTED_TOKEN="$(normalize_boolean "$2")"; shift 2 ;;
        --expect-max-row-limit) require_arg "$1" $# || exit 1; EXPECT_MAX_ROW_LIMIT="$2"; shift 2 ;;
        --expect-default-row-limit) require_arg "$1" $# || exit 1; EXPECT_DEFAULT_ROW_LIMIT="$2"; shift 2 ;;
        --expect-global-rate-limit) require_arg "$1" $# || exit 1; EXPECT_GLOBAL_RATE_LIMIT="$2"; shift 2 ;;
        --expect-tenant-authenticated) require_arg "$1" $# || exit 1; EXPECT_TENANT_AUTHENTICATED="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

warn_if_role_unsupported_for_skill "splunk-mcp-server-setup"
ensure_session

if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
    log "ERROR: ${APP_NAME} is not installed."
    exit 1
fi

APP_VERSION="$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}")"
APP_VISIBLE="$(app_visible)"
MCP_URL="$(derive_mcp_url "${SPLUNK_URI}" || echo "unknown")"
PROTECTED_RESOURCE_URL="$(derive_protected_resource_url "${SPLUNK_URI}" || echo "unknown")"

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

MCP_PING_RESP="$(post_json_with_code "${MCP_URL}" '{"jsonrpc":"2.0","id":"validate-ping","method":"ping"}')"
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

MCP_TOOLS_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_tools?output_mode=json")"
MCP_RATE_LIMITS_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_rate_limits?output_mode=json")"
MCP_TOKEN_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_token?output_mode=json")"
MCP_TOOLS_COLLECTION_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/storage/collections/config/mcp_tools?output_mode=json")"
MCP_TOOLS_ENABLED_COLLECTION_CODE="$(http_code_for "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/storage/collections/config/mcp_tools_enabled?output_mode=json")"
PROTECTED_RESOURCE_CODE="$(http_code_for "${PROTECTED_RESOURCE_URL}")"

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
               "  ssl_verify=${SERVER_SSL_VERIFY:-unset}" \
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
               "  endpoint_mcp_tools_http=${MCP_TOOLS_CODE}" \
               "  endpoint_mcp_rate_limits_http=${MCP_RATE_LIMITS_CODE}" \
               "  endpoint_mcp_token_http=${MCP_TOKEN_CODE}" \
               "  endpoint_protected_resource_http=${PROTECTED_RESOURCE_CODE}" \
               "  kv_mcp_tools_http=${MCP_TOOLS_COLLECTION_CODE}" \
               "  kv_mcp_tools_enabled_http=${MCP_TOOLS_ENABLED_COLLECTION_CODE}"

[[ "${APP_VISIBLE}" == "True" || "${APP_VISIBLE}" == "true" ]] || {
    log "ERROR: ${APP_NAME} is installed but not visible in Splunk Web."
    FAILURES=$((FAILURES + 1))
}

[[ "${MCP_PING_CODE}" == "200" && "${MCP_PING_RESULT}" == "pong" ]] || {
    log "ERROR: /services/mcp ping probe failed."
    FAILURES=$((FAILURES + 1))
}

[[ "${MCP_TOOLS_CODE}" == "200" ]] || {
    log "ERROR: /mcp_tools did not return HTTP 200."
    FAILURES=$((FAILURES + 1))
}
[[ "${MCP_RATE_LIMITS_CODE}" == "200" ]] || {
    log "ERROR: /mcp_rate_limits did not return HTTP 200."
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

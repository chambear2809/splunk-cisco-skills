#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_AI_Assistant_Cloud"
MIN_ENTERPRISE_VERSION="9.2.0"

PASS=0
WARN=0
FAIL=0
SK=""

EXPECT_CONFIGURED=""
EXPECT_ONBOARDED=""
EXPECT_PROXY_ENABLED=""

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
info() { log "  INFO: $*"; }

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk AI Assistant for SPL Validation

Usage: $(basename "$0") [OPTIONS]

Runs read-only validation for ${APP_NAME}.

Checks:
  - Splunk API authentication
  - ${APP_NAME} installation, visibility, and configured state
  - KV Store readiness
  - app-owned REST health (/version)
  - Enterprise onboarding and proxy state

Optional assertions:
  --expect-configured true|false
  --expect-onboarded true|false
  --expect-proxy-enabled true|false

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

version_at_least() {
    python3 - "$1" "$2" <<'PY'
import re
import sys

def parse(value: str) -> list[int]:
    numbers = re.findall(r"\d+", value or "")
    if not numbers:
        return [0]
    return [int(item) for item in numbers]

left = parse(sys.argv[1])
right = parse(sys.argv[2])
size = max(len(left), len(right))
left += [0] * (size - len(left))
right += [0] * (size - len(right))
raise SystemExit(0 if left >= right else 1)
PY
}

ensure_session() {
    load_splunk_credentials || {
        return 1
    }
    SK="$(get_session_key "${SPLUNK_URI}")" || {
        return 1
    }
}

app_metadata_json() {
    splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/apps/local/${APP_NAME}?output_mode=json" 2>/dev/null || true
}

app_metadata_field() {
    local payload="$1"
    local field="$2"

    APP_METADATA_PAYLOAD="${payload}" APP_METADATA_FIELD="${field}" python3 <<'PY'
import json
import os

payload = os.environ.get("APP_METADATA_PAYLOAD", "")
field = os.environ.get("APP_METADATA_FIELD", "")

try:
    data = json.loads(payload)
    entry = data.get("entry", [{}])[0]
    value = entry.get("content", {}).get(field, "")
except Exception:
    value = ""

if isinstance(value, bool):
    print("true" if value else "false", end="")
else:
    print(str(value), end="")
PY
}

server_version() {
    splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/server/info?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    payload = json.load(sys.stdin)
    entries = payload.get("entry", [])
    if entries:
        print(entries[0].get("content", {}).get("version", "unknown"), end="")
    else:
        print("unknown", end="")
except Exception:
    print("unknown", end="")
' 2>/dev/null || echo "unknown"
}

kvstore_status() {
    splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/kvstore/status?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    payload = json.load(sys.stdin)
    entries = payload.get("entry", [])
    if entries:
        print(entries[0].get("content", {}).get("current", {}).get("status", "unknown"), end="")
    else:
        print("unknown", end="")
except Exception:
    print("unknown", end="")
' 2>/dev/null || echo "unknown"
}

saia_handler_url() {
    local handler="$1"
    printf '%s/servicesNS/nobody/%s/%s?output_mode=json' "${SPLUNK_URI}" "${APP_NAME}" "${handler}"
}

saia_request_with_code() {
    local method="$1"
    local handler="$2"
    local url

    url="$(saia_handler_url "${handler}")"
    splunk_curl "${SK}" \
        -X "${method}" \
        "${url}" \
        -H "Source-App-ID: ${APP_NAME}" \
        -w '\n%{http_code}' 2>/dev/null || echo "000"
}

http_code_from_response() {
    printf '%s\n' "${1}" | tail -1
}

body_from_response() {
    printf '%s\n' "${1}" | sed '$d'
}

collection_doc_json() {
    local collection="$1"

    splunk_curl "${SK}" \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/storage/collections/data/${collection}?output_mode=json&count=1" 2>/dev/null \
        | python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
    if isinstance(payload, list) and payload:
        print(json.dumps(payload[0]), end="")
    elif isinstance(payload, dict):
        print(json.dumps(payload), end="")
    else:
        print("{}", end="")
except Exception:
    print("{}", end="")
' 2>/dev/null || echo "{}"
}

json_field() {
    local payload="$1"
    local field="$2"

    JSON_FIELD_PAYLOAD="${payload}" JSON_FIELD_NAME="${field}" python3 <<'PY'
import json
import os

payload = os.environ.get("JSON_FIELD_PAYLOAD", "{}")
field = os.environ.get("JSON_FIELD_NAME", "")

try:
    value = json.loads(payload).get(field, "")
except Exception:
    value = ""

if value is None:
    value = ""
if isinstance(value, bool):
    print("true" if value else "false", end="")
elif isinstance(value, (dict, list)):
    print(json.dumps(value), end="")
else:
    print(str(value), end="")
PY
}

decode_onboarding_field() {
    local encoded_value="$1"
    local field="$2"

    python3 - "${encoded_value}" "${field}" <<'PY'
import base64
import json
import sys

encoded_value = sys.argv[1]
field = sys.argv[2]

if not encoded_value:
    print("", end="")
    raise SystemExit(0)

padding = "=" * (-len(encoded_value) % 4)
try:
    decoded = base64.urlsafe_b64decode(encoded_value + padding).decode("utf-8")
    payload = json.loads(decoded)
except Exception:
    print("", end="")
    raise SystemExit(0)

print(str(payload.get(field, "")), end="")
PY
}

assert_expected_state() {
    local label="$1"
    local expected="$2"
    local actual="$3"

    [[ -n "${expected}" ]] || return 0

    if [[ "${actual}" == "${expected}" ]]; then
        pass "${label} matches expected state (${expected})"
    else
        fail "${label} expected ${expected}, got ${actual}"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --expect-configured) require_arg "$1" $# || exit 1; EXPECT_CONFIGURED="$(normalize_boolean "$2")"; shift 2 ;;
        --expect-onboarded) require_arg "$1" $# || exit 1; EXPECT_ONBOARDED="$(normalize_boolean "$2")"; shift 2 ;;
        --expect-proxy-enabled) require_arg "$1" $# || exit 1; EXPECT_PROXY_ENABLED="$(normalize_boolean "$2")"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

log "=== Splunk AI Assistant for SPL Validation ==="
log ""

warn_if_current_skill_role_unsupported

log "--- Splunk Authentication ---"
if ! ensure_session; then
    fail "Could not authenticate to Splunk REST API — check credentials"
    log ""
    log "=== Validation Summary ==="
    log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
    exit 1
fi

platform_version="$(server_version)"
if [[ "${platform_version}" == "unknown" ]]; then
    warn "Could not determine the target Splunk version"
else
    pass "Connected to Splunk ${platform_version}"
fi

log ""
log "--- App Presence ---"
if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null; then
    app_metadata="$(app_metadata_json)"
    app_version="$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || echo "unknown")"
    pass "${APP_NAME} installed (version: ${app_version})"
else
    fail "${APP_NAME} is not installed"
fi

if [[ ${FAIL} -gt 0 ]]; then
    log ""
    log "=== Validation Summary ==="
    log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
    exit 1
fi

visible="$(app_metadata_field "${app_metadata}" "visible")"
configured="$(app_metadata_field "${app_metadata}" "configured")"
case "${visible}" in
    True|true|1) pass "${APP_NAME} is visible in Splunk Web" ;;
    False|false|0) warn "${APP_NAME} is installed but hidden in Splunk Web" ;;
    *) warn "Could not determine whether ${APP_NAME} is visible in Splunk Web" ;;
esac

log ""
log "--- Local Prerequisites ---"
case "$(kvstore_status)" in
    ready) pass "KV Store status is ready" ;;
    *)
        warn "KV Store is not reporting ready; the assistant stores chat state in KV Store"
        ;;
esac

log ""
log "--- App REST Health ---"
version_probe_response="$(saia_request_with_code "GET" "version")"
version_probe_code="$(http_code_from_response "${version_probe_response}")"
version_probe_body="$(body_from_response "${version_probe_response}")"
handler_version="$(json_field "${version_probe_body}" "version")"
if [[ "${version_probe_code}" == "200" ]]; then
    pass "Custom REST handler /version is reachable${handler_version:+ (handler version: ${handler_version})}"
else
    warn "Could not verify the app-owned /version REST handler (HTTP ${version_probe_code})"
fi

log ""
log "--- App Setup State ---"
case "${configured}" in
    True|true|1)
        configured_state="true"
        pass "${APP_NAME} is marked configured in app metadata"
        ;;
    False|false|0|"")
        configured_state="false"
        if is_splunk_cloud; then
            info "${APP_NAME} is not marked configured yet"
        else
            warn "${APP_NAME} is installed but not marked configured yet"
        fi
        ;;
    *)
        configured_state="unknown"
        warn "Could not determine whether ${APP_NAME} is marked configured"
        ;;
esac

onboarded_state="false"
proxy_enabled_state="false"

log ""
log "--- Platform-Specific Checks ---"
if is_splunk_cloud; then
    pass "Target is Splunk Cloud"
    info "This app must stay on the public Splunkbase install path for Cloud."
    info "Enterprise cloud-connected onboarding and proxy settings do not apply on Splunk Cloud."
else
    cc_config_json="$(collection_doc_json "cloud_connected_configurations")"
    encoded_onboarding_data="$(json_field "${cc_config_json}" "encoded_onboarding_data")"
    scs_region="$(json_field "${cc_config_json}" "scs_region")"
    tenant_name="$(json_field "${cc_config_json}" "tenant_name")"
    tenant_hostname="$(json_field "${cc_config_json}" "tenant_hostname")"
    service_principal="$(json_field "${cc_config_json}" "service_principal")"
    scs_token="$(json_field "${cc_config_json}" "scs_token")"
    scs_token_expiry="$(json_field "${cc_config_json}" "scs_token_expiry")"
    last_setup_timestamp="$(json_field "${cc_config_json}" "last_setup_timestamp")"

    proxy_response="$(saia_request_with_code "GET" "cloudconnectedproxysettings")"
    proxy_code="$(http_code_from_response "${proxy_response}")"
    proxy_body="$(body_from_response "${proxy_response}")"
    proxy_settings="$(json_field "${proxy_body}" "proxy_settings")"
    if [[ -z "${proxy_settings}" ]]; then
        proxy_settings="{}"
    fi
    proxy_type="$(json_field "${proxy_settings}" "type")"
    proxy_host="$(json_field "${proxy_settings}" "hostname")"
    proxy_port="$(json_field "${proxy_settings}" "port")"
    proxy_username="$(json_field "${proxy_settings}" "username")"

    onboarding_started="false"
    if [[ -n "${encoded_onboarding_data}" || -n "${scs_region}" ]]; then
        onboarding_started="true"
    fi
    if [[ -n "${tenant_hostname}" && -n "${service_principal}" && -n "${scs_token}" ]]; then
        onboarded_state="true"
    fi
    if [[ -n "${proxy_type}" && -n "${proxy_host}" && -n "${proxy_port}" ]]; then
        proxy_enabled_state="true"
    fi

    pass "Target is Splunk Enterprise"
    if [[ "${platform_version}" != "unknown" ]] && version_at_least "${platform_version}" "${MIN_ENTERPRISE_VERSION}"; then
        pass "Enterprise version ${platform_version} meets the documented 9.2+ baseline"
    elif [[ "${platform_version}" != "unknown" ]]; then
        warn "Enterprise version ${platform_version} is older than the documented 9.2+ baseline"
    fi

    if [[ "${onboarded_state}" == "true" ]]; then
        pass "Cloud-connected activation completed for tenant '${tenant_name:-unknown}' (${tenant_hostname:-unknown})"
        if [[ -n "${scs_token_expiry}" ]]; then
            pass "Cloud-connected access token expiry is recorded"
        fi
        if [[ -n "${last_setup_timestamp}" ]]; then
            pass "Last setup timestamp is recorded (${last_setup_timestamp})"
        fi
    elif [[ "${onboarding_started}" == "true" ]]; then
        onboarding_tenant_hint="$(decode_onboarding_field "${encoded_onboarding_data}" "tenant_name")"
        onboarding_region_hint="$(decode_onboarding_field "${encoded_onboarding_data}" "region")"
        onboarding_email_hint="$(decode_onboarding_field "${encoded_onboarding_data}" "email")"
        warn "Onboarding form has been submitted but activation is still pending"
        info "Remaining blocker: apply the Splunk-issued activation code/token with setup.sh --complete-onboarding"
        if [[ -n "${onboarding_tenant_hint}" ]]; then
            info "Pending onboarding tenant: ${onboarding_tenant_hint}"
        fi
        if [[ -n "${onboarding_region_hint}" ]]; then
            info "Pending onboarding region: ${onboarding_region_hint}"
        elif [[ -n "${scs_region}" ]]; then
            info "Pending onboarding region: ${scs_region}"
        fi
        if [[ -n "${onboarding_email_hint}" ]]; then
            info "Pending onboarding email: ${onboarding_email_hint}"
        fi
    else
        warn "Cloud-connected onboarding has not started yet"
    fi

    if [[ "${proxy_code}" == "200" ]]; then
        if [[ "${proxy_enabled_state}" == "true" ]]; then
            proxy_summary="${proxy_type}://${proxy_host}:${proxy_port}"
            if [[ -n "${proxy_username}" ]]; then
                proxy_summary="${proxy_summary} (auth user: ${proxy_username})"
            fi
            pass "Outbound proxy is configured: ${proxy_summary}"
        else
            info "Outbound proxy is not configured"
        fi
    else
        warn "Could not determine proxy settings from the app-owned REST handler (HTTP ${proxy_code})"
    fi

    if [[ "${onboarded_state}" != "true" ]]; then
        warn "Ensure outbound HTTPS access to *.scs.splunk.com:443 from the search head"
    fi
fi

log ""
log "--- Assertions ---"
assert_expected_state "configured state" "${EXPECT_CONFIGURED}" "${configured_state}"
assert_expected_state "onboarded state" "${EXPECT_ONBOARDED}" "${onboarded_state}"
assert_expected_state "proxy-enabled state" "${EXPECT_PROXY_ENABLED}" "${proxy_enabled_state}"

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"

if [[ ${FAIL} -gt 0 ]]; then
    log "  Status: ISSUES FOUND — review failures above"
    exit 1
elif [[ ${WARN} -gt 0 ]]; then
    log "  Status: OK with warnings"
    exit 0
else
    log "  Status: ALL CHECKS PASSED"
    exit 0
fi

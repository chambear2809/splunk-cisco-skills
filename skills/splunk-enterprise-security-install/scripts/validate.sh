#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="SplunkEnterpriseSecuritySuite"

PASS=0
WARN=0
FAIL=0
SK=""

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Enterprise Security Install Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --help          Show this help text

Checks are read-only and use Splunk REST credentials from the credentials file.

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage 0 ;;
        *)
            log "ERROR: Unknown option '$1'"
            usage 1
            ;;
    esac
done

ensure_session() {
    load_splunk_credentials || {
        fail "Could not load Splunk credentials."
        return 1
    }
    warn_if_current_skill_role_unsupported
    SK="$(get_session_key "${SPLUNK_URI}")" || {
        fail "Could not authenticate to Splunk REST API."
        return 1
    }
}

app_field() {
    local app="$1" field="$2"
    splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/apps/local/${app}?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
field = sys.argv[1]
try:
    data = json.load(sys.stdin)
    entries = data.get("entry", [])
    value = entries[0].get("content", {}).get(field, "") if entries else ""
    if isinstance(value, bool):
        print("true" if value else "false", end="")
    else:
        print(str(value), end="")
except Exception:
    print("", end="")
' "${field}" 2>/dev/null || true
}

kvstore_status() {
    splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/kvstore/status?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get("entry", [])
    print(entries[0].get("content", {}).get("current", {}).get("status", "unknown") if entries else "unknown", end="")
except Exception:
    print("unknown", end="")
' 2>/dev/null || echo "unknown"
}

conf_value_global() {
    local conf="$1" stanza="$2" key="$3"
    local encoded
    encoded="$(_urlencode "${stanza}")"
    splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/configs/conf-${conf}/${encoded}?output_mode=json" 2>/dev/null \
        | python3 -c '
import json, sys
field = sys.argv[1]
try:
    data = json.load(sys.stdin)
    entries = data.get("entry", [])
    print(entries[0].get("content", {}).get(field, "") if entries else "", end="")
except Exception:
    print("", end="")
' "${key}" 2>/dev/null || true
}

check_app_installed() {
    local app="$1" severity="${2:-fail}" version disabled visible configured configured_version

    if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null; then
        version="$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null || echo "unknown")"
        disabled="$(app_field "${app}" disabled)"
        visible="$(app_field "${app}" visible)"
        configured="$(app_field "${app}" configured)"
        pass "${app} installed (version: ${version}, disabled: ${disabled:-unknown}, visible: ${visible:-unknown}, configured: ${configured:-unknown})"
        if [[ "${app}" == "${APP_NAME}" ]]; then
            configured_version="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "ess_setup" "install" "configured_version" 2>/dev/null || true)"
            if [[ -n "${configured_version}" ]]; then
                pass "ess_setup configured_version is ${configured_version}"
            else
                warn "ess_setup configured_version is empty; run post-install setup if ES was just installed"
            fi
        fi
    else
        if [[ "${severity}" == "fail" ]]; then
            fail "${app} not found"
        else
            warn "${app} not found"
        fi
    fi
}

log "=== Splunk Enterprise Security Install Validation ==="
log ""

log "--- Splunk Authentication ---"
if ! ensure_session; then
    log ""
    log "=== Validation Summary ==="
    log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
    exit 1
fi
pass "Authenticated to ${SPLUNK_URI}"

log ""
log "--- Core ES Apps ---"
REQUIRED_APPS=(
    "SplunkEnterpriseSecuritySuite"
    "DA-ESS-AccessProtection"
    "DA-ESS-EndpointProtection"
    "DA-ESS-IdentityManagement"
    "DA-ESS-NetworkProtection"
    "DA-ESS-ThreatIntelligence"
    "SA-AccessProtection"
    "SA-AuditAndDataProtection"
    "SA-EndpointProtection"
    "SA-IdentityManagement"
    "SA-NetworkProtection"
    "SA-ThreatIntelligence"
    "Splunk_SA_CIM"
    "Splunk_ML_Toolkit"
)

for app in "${REQUIRED_APPS[@]}"; do
    check_app_installed "${app}" "fail"
done

log ""
log "--- ES 8.x Supporting Apps ---"
SUPPORTING_APPS=(
    "missioncontrol"
    "SA-ContentVersioning"
    "SA-Detections"
    "SA-EntitlementManagement"
    "SA-TestModeControl"
    "SA-UEBA"
    "SA-Utils"
    "DA-ESS-UEBA"
    "dlx-app"
    "exposure-analytics"
    "ocsf_cim_addon_for_splunk"
    "Splunk_TA_ueba"
    "splunk_cloud_connect"
    "Splunk_SA_Scientific_Python_linux_x86_64"
    "Splunk_SA_Scientific_Python_windows_x86_64"
)

for app in "${SUPPORTING_APPS[@]}"; do
    check_app_installed "${app}" "warn"
done

log ""
log "--- KV Store ---"
kv_status="$(kvstore_status)"
case "${kv_status}" in
    ready) pass "KV Store status: ready" ;;
    *) warn "KV Store status: ${kv_status}; ES depends on healthy KV Store" ;;
esac

log ""
log "--- Data Model Acceleration Enforcement ---"
DM_STANZAS=(
    "dm_accel_settings://Authentication"
    "dm_accel_settings://Endpoint"
    "dm_accel_settings://Network_Traffic"
    "dm_accel_settings://Risk"
    "dm_accel_settings://Web"
)
for stanza in "${DM_STANZAS[@]}"; do
    if rest_check_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "${stanza}" 2>/dev/null; then
        disabled="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "${stanza}" "disabled" 2>/dev/null || true)"
        accel="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "${stanza}" "acceleration" 2>/dev/null || true)"
        pass "${stanza} present (disabled: ${disabled:-unknown}, acceleration: ${accel:-unknown})"
    else
        warn "${stanza} not found"
    fi
done

log ""
log "--- Platform Guardrails ---"
lookup_order="$(conf_value_global "limits" "lookup" "enforce_auto_lookup_order")"
case "${lookup_order}" in
    true|True|1) pass "limits.conf [lookup] enforce_auto_lookup_order is enabled" ;;
    "") warn "Could not read limits.conf [lookup] enforce_auto_lookup_order" ;;
    *) warn "limits.conf [lookup] enforce_auto_lookup_order is '${lookup_order}', expected true for ES" ;;
esac

check_numeric_limit() {
    local conf="$1" stanza="$2" key="$3" minimum="$4" label="$5"
    local value
    value="$(conf_value_global "${conf}" "${stanza}" "${key}")"
    if [[ -z "${value}" ]]; then
        warn "${label}: could not read ${conf}.conf [${stanza}] ${key}"
        return
    fi
    if ! [[ "${value}" =~ ^[0-9]+$ ]]; then
        warn "${label}: ${conf}.conf [${stanza}] ${key} is '${value}' (expected integer >= ${minimum})"
        return
    fi
    if (( value >= minimum )); then
        pass "${label}: ${conf}.conf [${stanza}] ${key} is ${value} (>= ${minimum})"
    else
        warn "${label}: ${conf}.conf [${stanza}] ${key} is ${value}; ES SHC recommends >= ${minimum}"
    fi
}

check_numeric_limit "web" "settings" "max_upload_size" 2048 "Search head/SHC max_upload_size"
check_numeric_limit "server" "httpServer" "max_content_length" 5000000000 "SHC max_content_length"
check_numeric_limit "server" "settings" "splunkdConnectionTimeout" 300 "SHC splunkdConnectionTimeout"

ta_for_indexers_version="$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "Splunk_TA_ForIndexers" 2>/dev/null || echo "")"
if [[ -n "${ta_for_indexers_version}" ]]; then
    pass "Splunk_TA_ForIndexers is installed on this tier (version: ${ta_for_indexers_version})"
else
    warn "Splunk_TA_ForIndexers is not installed on this tier; on-prem indexer clusters must deploy it through the cluster manager"
fi

log ""
log "--- Key ES Indexes ---"
INDEXES=(
    "notable"
    "notable_summary"
    "risk"
    "threat_activity"
    "cim_modactions"
    "ba_test"
    "sequenced_events"
)
for idx in "${INDEXES[@]}"; do
    if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
        pass "Index '${idx}' exists"
    else
        warn "Index '${idx}' not found via the configured index management context"
    fi
done

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"

if [[ ${FAIL} -gt 0 ]]; then
    log "  Status: ISSUES FOUND"
    exit 1
elif [[ ${WARN} -gt 0 ]]; then
    log "  Status: OK with warnings"
    exit 0
else
    log "  Status: ALL CHECKS PASSED"
    exit 0
fi

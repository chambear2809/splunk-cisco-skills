#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco_dc_networking_app_for_splunk"

PASS=0
FAIL=0
WARN=0

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

log "=== Cisco DC Networking TA Validation ==="
log ""

log "--- App Installation ---"
if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials — check credentials file"
elif ! SK=$(get_session_key "${SPLUNK_URI}"); then
    fail "Could not authenticate to Splunk REST API — check credentials"
else
    if rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null; then
        version=$(rest_get_app_version "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || echo "unknown")
        pass "App installed (version: ${version})"
    else
        fail "App not found — install Cisco DC Networking app first"
    fi
fi

if [[ -n "${SK}" ]]; then
log ""
log "--- Indexes ---"
REQUIRED_INDEXES=("cisco_aci" "cisco_nd" "cisco_nexus_9k")
for idx in "${REQUIRED_INDEXES[@]}"; do
    if rest_check_index "$SK" "$SPLUNK_URI" "$idx" 2>/dev/null; then
        pass "Index '${idx}' exists"
    else
        warn "Index '${idx}' not found (may exist at system level)"
    fi
done

log ""
log "--- Search Macros ---"
for macro in "cisco_dc_aci_index" "cisco_dc_nd_index" "cisco_dc_nexus_9k_index"; do
    def=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "$macro" "definition" 2>/dev/null || true)
    if [[ -n "${def}" ]]; then
        pass "Macro '${macro}' defined"
    else
        warn "Macro '${macro}' not found"
    fi
done

log ""
log "--- Account Configuration ---"
for label_handler in "ACI:cisco_dc_networking_app_for_splunk_aci_account" "ND:cisco_dc_networking_app_for_splunk_nd_account" "Nexus9K:cisco_dc_networking_app_for_splunk_nexus_9k_account"; do
    label="${label_handler%%:*}"
    handler="${label_handler#*:}"
    json=$(rest_list_ta_stanzas "$SK" "$SPLUNK_URI" "$APP_NAME" "$handler" 2>/dev/null || true)
    if [[ -n "${json}" ]]; then
        count=$(echo "${json}" | python3 -c "import json,sys; d=json.load(sys.stdin); e=d.get('entry',[]); print(len(e))" 2>/dev/null || echo "0")
        if [[ "${count}" -gt 0 ]]; then
            pass "${label} account conf exists with ${count} account(s)"
        else
            warn "${label} account conf exists but has no stanzas"
        fi
    else
        warn "No ${label} account conf found"
    fi
done

log ""
log "--- Data Inputs ---"
input_count=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || echo "0")
enabled_inputs=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME" "0" 2>/dev/null || echo "0")
disabled_inputs=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME" "1" 2>/dev/null || echo "0")
if [[ "${input_count}" -gt 0 ]]; then
    if [[ "${enabled_inputs}" -eq "${input_count}" ]]; then
        pass "${enabled_inputs} input(s) enabled"
    elif [[ "${enabled_inputs}" -gt 0 ]]; then
        warn "${enabled_inputs} input(s) enabled, ${disabled_inputs} disabled"
    else
        warn "${input_count} input stanza(s) exist but all are disabled"
    fi
else
    warn "No inputs configured"
fi

log ""
log "--- Data Flow Check ---"
    for idx in "cisco_aci" "cisco_nd" "cisco_nexus_9k"; do
        event_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" "| tstats count where index=${idx}" "count" 2>/dev/null || echo "0")
        if [[ "${event_count}" -gt 0 ]]; then
            pass "Index '${idx}' has ${event_count} events in the last hour"
        else
            warn "Index '${idx}' has no events in the last hour (may be normal if just configured)"
        fi
    done

log ""
log "--- Settings ---"
ssl_verify=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "cisco_dc_networking_app_for_splunk_settings" "default" "verify_ssl" 2>/dev/null || true)
if [[ "${ssl_verify}" == "True" ]]; then
    pass "SSL verification is enabled"
else
    warn "SSL verification is disabled (verify_ssl = ${ssl_verify})"
fi
fi

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

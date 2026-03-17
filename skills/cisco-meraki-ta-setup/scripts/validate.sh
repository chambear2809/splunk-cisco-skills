#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_cisco_meraki"

PASS=0
FAIL=0
WARN=0

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

log "=== Cisco Meraki TA Validation ==="
log ""

log "--- App Installation ---"
if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials — check credentials file"
elif ! SK=$(get_session_key "${SPLUNK_URI}"); then
    fail "Could not authenticate to Splunk REST API — check credentials"
fi

if [[ ${FAIL} -gt 0 ]]; then
    log ""
    log "=== Validation Summary ==="
    log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
    exit 1
fi

if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
    version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}")
    pass "TA installed, version: ${version}"
else
    fail "Cisco Meraki TA not found"
fi

log ""
log "--- Index ---"
if rest_check_index "${SK}" "${SPLUNK_URI}" "meraki"; then
    pass "Index 'meraki' exists"
else
    warn "Index 'meraki' not found (may need to run setup.sh)"
fi

log ""
log "--- Account Configuration ---"
account_json=$(rest_list_ta_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "Splunk_TA_cisco_meraki_account" 2>/dev/null || true)
if [[ -n "${account_json}" ]]; then
    count=$(echo "${account_json}" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    entries = d.get('entry', [])
    print(len(entries))
    for e in entries:
        print(e.get('name', ''))
except Exception:
    print(0)
" 2>/dev/null | head -1)
    if [[ "${count}" -gt 0 ]]; then
        pass "Organization account conf exists with ${count} account(s)"
        echo "${account_json}" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    for e in d.get('entry', []):
        print('    Account:', e.get('name', ''))
except Exception:
    pass
" 2>/dev/null || true
    else
        warn "Organization account conf exists but has no stanzas"
    fi
else
    warn "No organization account conf found"
fi

log ""
log "--- Data Inputs ---"
input_count=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || echo "0")
enabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "0" 2>/dev/null || echo "0")
disabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "1" 2>/dev/null || echo "0")
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
event_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where index=meraki" "count" 2>/dev/null || echo "0")
if [[ "${event_count}" -gt 0 ]]; then
    pass "Index 'meraki' has ${event_count} events"
else
    warn "Index 'meraki' has no events (may be normal if just configured)"
fi

sourcetype_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats dc(sourcetype) as stcount where index=meraki | eval stcount=stcount-0" "stcount" 2>/dev/null || echo "0")
if [[ "${sourcetype_count}" -gt 0 ]]; then
    pass "${sourcetype_count} distinct sourcetype(s) in meraki index"
else
    warn "No sourcetypes found in meraki index yet"
fi

log ""
log "--- Settings ---"
proxy_enabled=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "splunk_ta_cisco_meraki_settings" "default" "proxy_enabled" 2>/dev/null || true)
loglevel=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "splunk_ta_cisco_meraki_settings" "default" "loglevel" 2>/dev/null || true)
if rest_check_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "splunk_ta_cisco_meraki_settings" "default" 2>/dev/null; then
    log "  Local settings stanza exists"
    [[ -n "${proxy_enabled}" ]] && log "  Proxy enabled: ${proxy_enabled}"
    [[ -n "${loglevel}" ]] && log "  Log level: ${loglevel}"
    pass "Settings present"
else
    warn "No local settings.conf — using defaults"
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

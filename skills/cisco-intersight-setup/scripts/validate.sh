#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_Cisco_Intersight"

PASS=0
FAIL=0
WARN=0

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

log "=== Cisco Intersight TA Validation ==="
log ""

load_splunk_credentials
SK=$(get_session_key "${SPLUNK_URI}") || true
if [[ -z "${SK}" ]]; then
    fail "Could not authenticate to Splunk REST API — check credentials"
    log ""
    log "=== Validation Summary ==="
    log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
    exit 1
fi

log "--- App Installation ---"
if rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME"; then
    version=$(rest_get_app_version "$SK" "$SPLUNK_URI" "$APP_NAME")
    pass "TA installed: ${APP_NAME} (version ${version})"
else
    fail "TA not found: ${APP_NAME}"
fi

log ""
log "--- Index ---"
if rest_check_index "$SK" "$SPLUNK_URI" "intersight"; then
    pass "Index 'intersight' exists"
else
    warn "Index 'intersight' not found (may need setup)"
fi

log ""
log "--- Macro ---"
macro_def=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_intersight_index" "definition")
if [[ -n "${macro_def}" ]]; then
    if echo "${macro_def}" | grep -q 'intersight'; then
        pass "Macro 'cisco_intersight_index' points to intersight index"
    else
        warn "Macro 'cisco_intersight_index' does not reference intersight: ${macro_def}"
    fi
else
    warn "Macro 'cisco_intersight_index' not found"
fi

log ""
log "--- Account Configuration ---"
acct_json=$(rest_list_ta_stanzas "$SK" "$SPLUNK_URI" "$APP_NAME" "Splunk_TA_Cisco_Intersight_account")
acct_count=$(echo "${acct_json}" 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    entries = d.get('entry', [])
    print(len(entries))
    for e in entries:
        print(e.get('name', '?'))
except: print(0)
" 2>/dev/null || echo "0")
if [[ "${acct_count}" -gt 0 ]]; then
    pass "Intersight account(s) configured: ${acct_count}"
    echo "${acct_json}" 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    for e in d.get('entry', []):
        name = e.get('name', '?')
        c = e.get('content', {})
        hostname = c.get('intersight_hostname', '?')
        acct_name = c.get('intersight_account_name', '?')
        print(f'    Account: {name} (hostname={hostname}, intersight_account={acct_name})')
except: pass
" 2>/dev/null || true
else
    warn "No Intersight accounts configured"
fi

log ""
log "--- Data Inputs ---"
total_inputs=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME")
enabled_inputs=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME" "0")
disabled_inputs=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME" "1")
audit_inputs=$(rest_count_conf_stanzas "$SK" "$SPLUNK_URI" "$APP_NAME" "inputs" "audit_alarms://")
inv_inputs=$(rest_count_conf_stanzas "$SK" "$SPLUNK_URI" "$APP_NAME" "inputs" "inventory://")
metrics_inputs=$(rest_count_conf_stanzas "$SK" "$SPLUNK_URI" "$APP_NAME" "inputs" "metrics://")
custom_inputs=$(rest_count_conf_stanzas "$SK" "$SPLUNK_URI" "$APP_NAME" "inputs" "custom_input://")

log "  Live inputs: total=${total_inputs}, enabled=${enabled_inputs}, disabled=${disabled_inputs}"
log "  Audit/Alarms: ${audit_inputs} | Inventory: ${inv_inputs} | Metrics: ${metrics_inputs} | Custom: ${custom_inputs}"

if [[ "${total_inputs}" -gt 0 ]]; then
    if [[ "${enabled_inputs}" -eq "${total_inputs}" ]]; then
        pass "${enabled_inputs} input(s) enabled"
    elif [[ "${enabled_inputs}" -gt 0 ]]; then
        warn "${enabled_inputs} input(s) enabled, ${disabled_inputs} disabled"
    else
        warn "${total_inputs} input stanza(s) exist but all are disabled"
    fi
else
    warn "No inputs configured"
fi

log ""
log "--- Data Flow Check ---"
event_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" "| tstats count where index=intersight" "count")
if [[ "${event_count}" -gt 0 ]]; then
    pass "Index 'intersight' has ${event_count} events"
else
    warn "Index 'intersight' has no events (may be normal if just configured)"
fi

sourcetype_breakdown=$(splunk_curl_post "${SK}" \
    "search=| tstats count where index=intersight by sourcetype | sort -count&exec_mode=oneshot&output_mode=json" \
    "${SPLUNK_URI}/services/search/jobs" 2>/dev/null \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
for r in d.get('results', []):
    print(f\"    {r.get('sourcetype','?')}: {r.get('count','0')} events\")
" 2>/dev/null || true)

if [[ -n "${sourcetype_breakdown}" ]]; then
    log "  Sourcetype breakdown:"
    echo "${sourcetype_breakdown}"
fi

acct_check=$(splunk_curl "${SK}" \
    "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/Splunk_TA_Cisco_Intersight_account?output_mode=json" \
    2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
entries = d.get('entry', [])
for e in entries:
    name = e.get('name', '?')
    content = e.get('content', {})
    hostname = content.get('intersight_hostname', '?')
    acct_name = content.get('intersight_account_name', '?')
    print(f'    {name}: hostname={hostname}, intersight_account={acct_name}')
print(f'  Total: {len(entries)} account(s) via REST API')
" 2>/dev/null || true)

if [[ -n "${acct_check}" ]]; then
    log "  Accounts via REST API:"
    echo "${acct_check}"
fi

log ""
log "--- Settings ---"
ssl_val=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "splunk_ta_cisco_intersight_settings" "additional_parameters" "ssl_validation")
if [[ -n "${ssl_val}" ]]; then
    if [[ "${ssl_val}" == "true" || "${ssl_val}" == "True" ]]; then
        pass "SSL validation is enabled"
    else
        warn "SSL validation is disabled (ssl_validation = ${ssl_val})"
    fi
else
    pass "SSL validation uses default (true) or not overridden"
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

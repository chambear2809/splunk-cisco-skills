#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="ta_cisco_thousandeyes"

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

log "=== Cisco ThousandEyes App Validation ==="
log ""

log "--- App Installation ---"
if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials — check credentials file"
fi

if [[ ${FAIL} -eq 0 ]] && ! SK=$(get_session_key "${SPLUNK_URI}"); then
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
    pass "App installed, version: ${version}"
else
    fail "ThousandEyes app (${APP_NAME}) not found"
fi

log ""
log "--- HEC Token ---"
hec_state=$(rest_get_hec_token_state "${SK}" "${SPLUNK_URI}" "thousandeyes" 2>/dev/null || echo "unknown")
case "${hec_state}" in
    enabled) pass "HEC token 'thousandeyes' exists" ;;
    disabled) warn "HEC token 'thousandeyes' exists but is disabled" ;;
    missing) warn "HEC token 'thousandeyes' not found (run setup.sh --hec-only)" ;;
    *) warn "Could not determine HEC token 'thousandeyes' status" ;;
esac

log ""
log "--- Indexes ---"
EXPECTED_INDEXES=(thousandeyes_metrics thousandeyes_traces thousandeyes_events thousandeyes_activity thousandeyes_alerts thousandeyes_pathvis)
for idx in "${EXPECTED_INDEXES[@]}"; do
    if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
        pass "Index '${idx}' exists"
    else
        warn "Index '${idx}' not found (run setup.sh --indexes-only)"
    fi
done

log ""
log "--- Account Configuration (OAuth) ---"
account_json=$(rest_list_ta_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "ta_cisco_thousandeyes_account" 2>/dev/null || true)
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
        pass "OAuth account configured (${count} account(s))"
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
        warn "Account endpoint exists but has no configured accounts"
    fi
else
    warn "No OAuth accounts configured (run configure_account.sh)"
fi

log ""
log "--- Token Refresh Input ---"
refresh_status=$(splunk_curl "${SK}" \
    "${SPLUNK_URI}/services/data/inputs/thousandeyes_refresh_tokens?output_mode=json&count=0" \
    2>/dev/null \
    | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    entries = d.get('entry', [])
    if entries:
        disabled = entries[0].get('content', {}).get('disabled', True)
        if str(disabled).lower() in ('0', 'false'):
            print('enabled', end='')
        else:
            print('disabled', end='')
    else:
        print('missing', end='')
except Exception:
    print('unknown', end='')
" 2>/dev/null || echo "unknown")

case "${refresh_status}" in
    enabled) pass "Token refresh input is enabled" ;;
    disabled) warn "Token refresh input exists but is disabled" ;;
    missing) warn "Token refresh input not found" ;;
    *) warn "Could not determine token refresh input status" ;;
esac

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
    warn "No data inputs configured (run setup.sh --enable-inputs)"
fi

log ""
log "--- Data Flow Check ---"
for idx_label in "thousandeyes_metrics:metrics" "thousandeyes_traces:traces" "thousandeyes_events:events" "thousandeyes_activity:activity" "thousandeyes_alerts:alerts" "thousandeyes_pathvis:pathvis"; do
    idx="${idx_label%%:*}"
    label="${idx_label#*:}"
    event_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where index=${idx}" "count" 2>/dev/null || echo "0")
    if [[ "${event_count}" -gt 0 ]]; then
        pass "Index '${idx}' has ${event_count} events (${label})"
    else
        warn "Index '${idx}' has no events yet (${label})"
    fi
done

log ""
log "--- Settings ---"
if rest_check_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "ta_cisco_thousandeyes_settings" "logging" 2>/dev/null; then
    loglevel=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "ta_cisco_thousandeyes_settings" "logging" "loglevel" 2>/dev/null || true)
    [[ -n "${loglevel}" ]] && log "  Log level: ${loglevel}"
    pass "Settings present"
else
    warn "No local settings — using defaults"
fi

log ""
log "--- ITSI Integration (Optional) ---"
if rest_check_app "${SK}" "${SPLUNK_URI}" "SA-ITOA" 2>/dev/null; then
    pass "Splunk ITSI (SA-ITOA) is installed — ThousandEyes ITSI integration available"
else
    log "  INFO: Splunk ITSI (SA-ITOA) not installed — ITSI integration inactive (this is normal)"
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

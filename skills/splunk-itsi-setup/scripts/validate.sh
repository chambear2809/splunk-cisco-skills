#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

log "=== Splunk ITSI Validation ==="
log ""

warn_if_current_skill_role_unsupported

log "--- Splunk Authentication ---"
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

log ""
log "--- Core ITSI Apps ---"
ITSI_APPS=("SA-ITOA" "itsi" "SA-UserAccess" "SA-ITSI-Licensechecker")
for app in "${ITSI_APPS[@]}"; do
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null || echo "unknown")
        pass "${app} installed (version: ${version})"
    else
        case "${app}" in
            SA-ITOA)
                fail "${app} not found — ITSI core is not installed"
                ;;
            itsi)
                fail "${app} not found — ITSI UI is not installed"
                ;;
            *)
                warn "${app} not found (supporting component)"
                ;;
        esac
    fi
done

log ""
log "--- KVStore Health ---"
kvstore_status=$(splunk_curl "${SK}" \
    "${SPLUNK_URI}/services/kvstore/status?output_mode=json" \
    2>/dev/null \
    | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    entries = d.get('entry', [])
    if entries:
        status = entries[0].get('content', {}).get('current', {}).get('status', 'unknown')
        print(status, end='')
    else:
        print('unknown', end='')
except Exception:
    print('unknown', end='')
" 2>/dev/null || echo "unknown")

case "${kvstore_status}" in
    ready) pass "KVStore status: ready" ;;
    *) warn "KVStore status: ${kvstore_status} (ITSI requires healthy KVStore)" ;;
esac

log ""
log "--- ITSI KVStore Collections ---"
itsi_collections=("itsi_services" "itsi_kpi_template" "itsi_notable_event_group")
for coll in "${itsi_collections[@]}"; do
    coll_code=$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/servicesNS/nobody/SA-ITOA/storage/collections/data/${coll}?output_mode=json&count=1" \
        -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
    case "${coll_code}" in
        200) pass "KVStore collection '${coll}' accessible" ;;
        404) warn "KVStore collection '${coll}' not found (may initialize after first use)" ;;
        *) warn "KVStore collection '${coll}' returned HTTP ${coll_code}" ;;
    esac
done

log ""
log "--- Integration Readiness ---"
if rest_check_app "${SK}" "${SPLUNK_URI}" "ta_cisco_thousandeyes" 2>/dev/null; then
    te_version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "ta_cisco_thousandeyes" 2>/dev/null || echo "unknown")
    pass "Cisco ThousandEyes app detected (version: ${te_version}) — ITSI integration available"
else
    log "  INFO: Cisco ThousandEyes app not installed — ThousandEyes-ITSI integration inactive (this is normal)"
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

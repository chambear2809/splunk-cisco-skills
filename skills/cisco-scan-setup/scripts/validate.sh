#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/cisco-scan-setup/scripts/validate.sh [--completion] [--help]

Validates the deployed Splunk Cisco App Navigator using configured Splunk credentials.
EOF
    exit 0
fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

COMPLETION=false
for arg in "$@"; do
    case "${arg}" in
        --completion) COMPLETION=true ;;
        *) echo "ERROR: Unknown validation option" >&2; exit 1 ;;
    esac
done

APP_NAME="splunk-cisco-app-navigator"
SYNC_SEARCH_NAME="SCAN - Splunkbase Catalog Sync"
MIN_PRODUCT_COUNT=90
MIN_SAVED_SEARCH_COUNT=40

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() {
    if ${COMPLETION}; then
        fail "$*"
    else
        log "  WARN: $*"; WARN=$((WARN + 1))
    fi
}

log "=== Splunk Cisco App Navigator (SCAN) Validation ==="
log ""

warn_if_current_skill_role_unsupported

log "--- Authentication ---"
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
log "--- App Installation ---"
if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
    version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}")
    pass "App installed, version: ${version}"
else
    fail "App '${APP_NAME}' not found"
fi

log ""
log "--- Product Catalog ---"
catalog_count=$(splunk_curl "${SK}" \
    "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/configs/conf-products?output_mode=json&count=0" 2>/dev/null \
    | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(len(d.get('entry', [])))
except Exception:
    print(0)
" 2>/dev/null || echo "0")

if [[ "${catalog_count}" -ge "${MIN_PRODUCT_COUNT}" ]]; then
    pass "Product catalog has ${catalog_count} stanzas"
elif [[ "${catalog_count}" -gt 0 ]]; then
    warn "Product catalog has ${catalog_count} stanzas (expected ${MIN_PRODUCT_COUNT}+)"
else
    fail "Product catalog returned 0 stanzas or is inaccessible"
fi

log ""
log "--- Splunkbase Lookup ---"
lookup_code=$(splunk_curl "${SK}" --connect-timeout 5 --max-time 15 \
    "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/transforms/lookups/scan_splunkbase_apps?output_mode=json" \
    -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")

if [[ "${lookup_code}" == "200" ]]; then
    pass "Lookup 'scan_splunkbase_apps' exists"
else
    warn "Lookup 'scan_splunkbase_apps' not accessible (HTTP ${lookup_code})"
fi

log ""
log "--- Catalog Sync Connectivity ---"
sync_result=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
    "| synccatalog dryrun=true" "status" 2>/dev/null || echo "error")

if [[ "${sync_result}" != "Dry Run" ]]; then
    sync_s3_version=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
        "| synccatalog dryrun=true" "s3_version" 2>/dev/null || echo "")
    if [[ -n "${sync_s3_version}" ]] && [[ "${sync_s3_version}" != "0" ]]; then
        pass "S3 reachable, remote catalog version: ${sync_s3_version}"
    else
        warn "Could not verify S3 connectivity (synccatalog returned: ${sync_result})"
    fi
else
    local_ver=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
        "| synccatalog dryrun=true" "local_version" 2>/dev/null || echo "unknown")
    s3_ver=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
        "| synccatalog dryrun=true" "s3_version" 2>/dev/null || echo "unknown")
    pass "S3 reachable (local: ${local_ver}, remote: ${s3_ver})"
fi

log ""
log "--- Saved Searches ---"
search_count=$(splunk_curl "${SK}" \
    "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/saved/searches?output_mode=json&count=0" 2>/dev/null \
    | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    entries = d.get('entry', [])
    scan_entries = [e for e in entries if e.get('name', '').startswith('SCAN')]
    print(len(scan_entries))
except Exception:
    print(0)
" 2>/dev/null || echo "0")

if [[ "${search_count}" -ge "${MIN_SAVED_SEARCH_COUNT}" ]]; then
    pass "${search_count} SCAN saved searches found"
elif [[ "${search_count}" -gt 0 ]]; then
    warn "${search_count} SCAN saved searches found (expected ${MIN_SAVED_SEARCH_COUNT}+)"
else
    fail "No SCAN saved searches found"
fi

log ""
log "--- Scheduled Sync Job ---"
if rest_check_saved_search "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "${SYNC_SEARCH_NAME}"; then
    is_scheduled=$(rest_get_saved_search_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "${SYNC_SEARCH_NAME}" "is_scheduled" 2>/dev/null || echo "")
    next_time=$(rest_get_saved_search_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "${SYNC_SEARCH_NAME}" "next_scheduled_time" 2>/dev/null || echo "")
    if [[ "${is_scheduled}" == "1" ]]; then
        pass "Sync job '${SYNC_SEARCH_NAME}' is scheduled"
        [[ -n "${next_time}" ]] && log "    Next run: ${next_time}"
    else
        warn "Sync job '${SYNC_SEARCH_NAME}' exists but is not scheduled (is_scheduled=${is_scheduled})"
    fi
else
    warn "Sync job '${SYNC_SEARCH_NAME}' not found"
fi

log ""
log "--- Shipped Views and Catalog Results ---"
app_visible=$(splunk_curl "${SK}" "${SPLUNK_URI}/services/apps/local/${APP_NAME}?output_mode=json" 2>/dev/null \
    | python3 -c 'import json,sys; v=json.load(sys.stdin)["entry"][0]["content"]["visible"]; print("1" if str(v).lower() in ("true", "1") else "0")' 2>/dev/null || echo "0")
if [[ "${app_visible}" == "1" ]]; then
    pass "SCAN is visible in Splunk Web"
else
    warn "SCAN is hidden or its visibility cannot be verified"
fi
views=$(splunk_curl "${SK}" \
    "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/ui/views?output_mode=json&count=0" 2>/dev/null \
    | python3 -c 'import json,sys; print(" ".join(e.get("name", "") for e in json.load(sys.stdin).get("entry", [])))' 2>/dev/null || true)
for view in ecosystem_intelligence cisco_glass_pane products user_guide; do
    if [[ " ${views} " == *" ${view} "* ]]; then
        pass "Shipped view is accessible: ${view}"
    else
        warn "Shipped view is missing or inaccessible: ${view}"
    fi
done
lookup_rows=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
    "| inputlookup scan_splunkbase_apps | stats count as catalog_rows" "catalog_rows" 2>/dev/null || echo "0")
if [[ "${lookup_rows}" =~ ^[0-9]+$ && "${lookup_rows}" -gt 0 ]]; then
    pass "Dashboard source lookup returns ${lookup_rows} rows"
else
    warn "Dashboard source lookup returns no rows; catalog dashboards are not ready"
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

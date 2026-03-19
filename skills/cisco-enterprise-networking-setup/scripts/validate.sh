#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco-catalyst-app"
readonly SAVED_SEARCHES=(
    "cisco_catalyst_location"
    "cisco_catalyst_sdwan_netflow"
    "cisco_catalyst_sdwan_policy"
    "cisco_catalyst_meraki_organization_mapping"
    "cisco_catalyst_meraki_devices_serial_mapping"
)

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

log "=== Cisco Enterprise Networking App Validation ==="
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
        fail "App not found — install Cisco Enterprise Networking app first"
    fi
fi

if [[ -n "${SK}" ]]; then
log ""
log "--- Companion TA ---"
if rest_check_app "$SK" "$SPLUNK_URI" "TA_cisco_catalyst" 2>/dev/null; then
    pass "Cisco Catalyst TA (TA_cisco_catalyst) is installed"
else
    fail "Cisco Catalyst TA not found — dashboards will have no data"
fi

log ""
log "--- Macros ---"
def=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_catalyst_app_index" "definition" 2>/dev/null || true)
if [[ -n "${def}" ]]; then
    pass "cisco_catalyst_app_index macro defined: ${def}"
    for idx in "catalyst" "ise" "sdwan" "cybervision"; do
        if echo "${def}" | grep -q "${idx}"; then
            pass "  Index '${idx}' included in macro"
        else
            warn "  Index '${idx}' NOT in macro — dashboards won't search this index"
        fi
    done
else
    warn "cisco_catalyst_app_index macro not found"
fi

log ""
log "--- Data Model ---"
accel=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "datamodels" "Cisco_Catalyst_App" "acceleration" 2>/dev/null || true)
if [[ "${accel}" == "true" ]]; then
    pass "Data model acceleration is enabled"
else
    warn "Data model acceleration is not enabled (optional for production)"
fi

log ""
log "--- Saved Searches ---"
for search_name in "${SAVED_SEARCHES[@]}"; do
    if ! rest_check_saved_search "$SK" "$SPLUNK_URI" "$APP_NAME" "${search_name}" 2>/dev/null; then
        fail "Saved search '${search_name}' not found"
        continue
    fi

    disabled=$(rest_get_saved_search_value "$SK" "$SPLUNK_URI" "$APP_NAME" "${search_name}" "disabled" 2>/dev/null || true)
    cron_schedule=$(rest_get_saved_search_value "$SK" "$SPLUNK_URI" "$APP_NAME" "${search_name}" "cron_schedule" 2>/dev/null || true)
    case "${disabled}" in
        0|false|False|"")
            pass "Saved search '${search_name}' enabled${cron_schedule:+ (schedule: ${cron_schedule})}"
            ;;
        *)
            warn "Saved search '${search_name}' is disabled${cron_schedule:+ (schedule: ${cron_schedule})}"
            ;;
    esac
done

log ""
log "--- Data Flow Check ---"
for idx in "catalyst" "ise" "sdwan" "cybervision"; do
    event_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" "| tstats count where index=${idx}" "count" 2>/dev/null || echo "0")
    if [[ "${event_count}" -gt 0 ]]; then
        pass "Index '${idx}' has ${event_count} events"
    else
        warn "Index '${idx}' has no events (configure TA first)"
    fi
done
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

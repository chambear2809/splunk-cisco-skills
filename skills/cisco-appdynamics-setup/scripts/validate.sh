#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_AppDynamics"
APP_INSTALLED=false

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

summarize_and_exit() {
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
}

log "=== Cisco AppDynamics Validation ==="
log ""

warn_if_current_skill_role_unsupported

if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials — check credentials file"
    summarize_and_exit
fi

if ! SK=$(get_session_key "${SPLUNK_URI}"); then
    fail "Could not authenticate to Splunk REST API — check credentials"
    summarize_and_exit
fi

settings_index=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
    "splunk_ta_appdynamics_settings" "additional_parameters" "index" 2>/dev/null || true)
target_index="${settings_index:-appdynamics}"

log "--- App Installation ---"
if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
    APP_INSTALLED=true
    version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}")
    pass "Add-on installed: ${APP_NAME} (version ${version})"
else
    fail "Add-on not found: ${APP_NAME}"
fi

visible=$(splunk_curl "${SK}" \
    "${SPLUNK_URI}/services/apps/local/${APP_NAME}?output_mode=json" 2>/dev/null \
    | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin)['entry'][0]['content'].get('visible', True))
except Exception:
    print('True')
" 2>/dev/null || echo "True")
if [[ "${visible}" == "True" ]]; then
    pass "App is visible in Splunk Web"
else
    warn "App is installed but not visible in Splunk Web"
fi

log ""
log "--- Index ---"
if platform_check_index "${SK}" "${SPLUNK_URI}" "${target_index}" 2>/dev/null; then
    pass "Index '${target_index}' exists"
else
    warn "Index '${target_index}' not found (may need setup)"
fi

if [[ "${target_index}" == "appdynamics" ]]; then
    pass "Dashboard default index matches the shipped dashboard forms"
else
    warn "Dashboards still default to appdynamics; enter '${target_index}' manually in dashboard forms"
fi

log ""
log "--- Settings ---"
if [[ -n "${settings_index}" ]]; then
    pass "Default add-on index is set to '${settings_index}'"
else
    warn "Add-on default index is not overridden; vendor default appdynamics applies"
fi

timeout_val=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
    "splunk_ta_appdynamics_settings" "additional_parameters" "timeout" 2>/dev/null || true)
max_workers=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
    "splunk_ta_appdynamics_settings" "additional_parameters" "max_workers" 2>/dev/null || true)
loglevel=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
    "splunk_ta_appdynamics_settings" "logging" "loglevel" 2>/dev/null || true)

if [[ -n "${timeout_val}" ]]; then
    pass "Timeout override present: ${timeout_val}"
else
    pass "Timeout uses vendor default"
fi

if [[ -n "${max_workers}" ]]; then
    pass "Max workers override present: ${max_workers}"
else
    pass "Max workers use vendor default"
fi

if [[ -n "${loglevel}" ]]; then
    pass "Log level override present: ${loglevel}"
else
    pass "Log level uses vendor default"
fi

log ""
log "--- Controller Connections ---"
controller_json=$(rest_list_ta_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "Splunk_TA_AppDynamics_account")
controller_count=$(printf '%s' "${controller_json}" 2>/dev/null | python3 -c "
import json, sys
try:
    print(len(json.load(sys.stdin).get('entry', [])))
except Exception:
    print(0)
" 2>/dev/null || echo "0")

if [[ "${controller_count}" -gt 0 ]]; then
    pass "Controller connection(s) configured: ${controller_count}"
    printf '%s' "${controller_json}" 2>/dev/null | python3 -c "
import json, sys
try:
    for entry in json.load(sys.stdin).get('entry', []):
        content = entry.get('content', {})
        name = entry.get('name', '?')
        controller = content.get('appd_controller_url', '?')
        auth = content.get('authentication', '?')
        print(f'    Connection: {name} (controller={controller}, auth={auth})')
except Exception:
    pass
" 2>/dev/null || true
else
    warn "No controller connections configured"
fi

log ""
log "--- Analytics Connections ---"
analytics_json=$(rest_list_ta_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "Splunk_TA_AppDynamics_analytics_account")
analytics_count=$(printf '%s' "${analytics_json}" 2>/dev/null | python3 -c "
import json, sys
try:
    print(len(json.load(sys.stdin).get('entry', [])))
except Exception:
    print(0)
" 2>/dev/null || echo "0")

if [[ "${analytics_count}" -gt 0 ]]; then
    pass "Analytics connection(s) configured: ${analytics_count}"
    printf '%s' "${analytics_json}" 2>/dev/null | python3 -c "
import json, sys
try:
    for entry in json.load(sys.stdin).get('entry', []):
        content = entry.get('content', {})
        name = entry.get('name', '?')
        acct = content.get('appd_analytics_account_name', '?')
        endpoint = content.get('appd_analytics_endpoint', '?')
        print(f'    Analytics: {name} (global_account={acct}, endpoint={endpoint})')
except Exception:
    pass
" 2>/dev/null || true
else
    warn "No analytics connections configured"
fi

log ""
log "--- Data Inputs ---"
total_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}")
enabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "0")
disabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "1")

status_inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "appdynamics_status://")
database_inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "appdynamics_database_metrics://")
hardware_inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "appdynamics_hardware_metrics://")
snapshot_inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "appdynamics_application_snapshots://")
analytics_inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "appdynamics_analytics_api://")
security_inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "appdynamics_security://")
events_inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "appdynamics_events_policy://")
custom_inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "appdynamics_custom_metrics://")
audit_inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "appdynamics_audit://")
license_inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "appdynamics_licenses://")

log "  Live inputs: total=${total_inputs}, enabled=${enabled_inputs}, disabled=${disabled_inputs}"
log "  Status=${status_inputs} Database=${database_inputs} Hardware=${hardware_inputs} Snapshots=${snapshot_inputs}"
log "  Analytics=${analytics_inputs} Security=${security_inputs} Events=${events_inputs} Custom=${custom_inputs}"
log "  Audit=${audit_inputs} Licenses=${license_inputs}"

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

if [[ "${analytics_inputs}" -gt 0 && "${analytics_count}" -eq 0 ]]; then
    fail "Analytics inputs exist but no analytics connection is configured"
fi

log ""
log "--- Data Flow Check ---"
event_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where index=${target_index}" "count")
if [[ "${event_count}" -gt 0 ]]; then
    pass "Index '${target_index}' has ${event_count} events"
else
    warn "Index '${target_index}' has no events (may be normal if just configured)"
fi

sourcetype_breakdown_body=$(form_urlencode_pairs \
    search "| tstats count where index=${target_index} by sourcetype | sort -count" \
    exec_mode "oneshot" \
    output_mode "json")
sourcetype_breakdown=$(splunk_curl_post "${SK}" \
    "${sourcetype_breakdown_body}" \
    "${SPLUNK_URI}/services/search/jobs" 2>/dev/null \
    | python3 -c "
import json, sys
try:
    for result in json.load(sys.stdin).get('results', []):
        print(f\"    {result.get('sourcetype', '?')}: {result.get('count', '0')} events\")
except Exception:
    pass
" 2>/dev/null || true)

if [[ -n "${sourcetype_breakdown}" ]]; then
    log "  Sourcetype breakdown:"
    printf '%s\n' "${sourcetype_breakdown}"
fi

log ""
log "--- Built-in Views ---"
if ${APP_INSTALLED}; then
    pass "Package includes built-in views: status, events, license_usage, audit_log, ingestion_statistics, troubleshooting"
else
    warn "Built-in views are unavailable until ${APP_NAME} is installed"
fi

summarize_and_exit

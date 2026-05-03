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
Splunk Enterprise Security Configuration Validation

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

collection_accessible() {
    local app="$1" collection="$2" code
    code="$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/servicesNS/nobody/${app}/storage/collections/data/${collection}?output_mode=json&count=1" \
        -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")"
    [[ "${code}" == "200" ]]
}

oneshot_count() {
    local search="$1"
    rest_oneshot_search "${SK}" "${SPLUNK_URI}" "${search}" "count" 2>/dev/null || echo "0"
}

check_index_group() {
    local label="$1"
    shift
    local idx
    log "--- ${label} ---"
    for idx in "$@"; do
        if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
            pass "Index '${idx}' exists"
        else
            warn "Index '${idx}' not found via the configured index management context"
        fi
    done
    log ""
}

CORE_INDEXES=(
    audit_summary
    ba_test
    cim_modactions
    cms_main
    endpoint_summary
    gia_summary
    ioc
    notable
    notable_summary
    risk
    sequenced_events
    threat_activity
    whois
)

UEBA_INDEXES=(ers ueba_summaries ubaroute ueba)
PCI_INDEXES=(pci pci_posture_summary pci_summary)
EXPOSURE_INDEXES=(ea_sources ea_discovery ea_analytics)
MISSION_CONTROL_INDEXES=(
    mc_aux_incidents
    mc_artifacts
    mc_investigations
    mc_events
    mc_incidents_backup
    kvcollection_retention_archive
)
DLX_INDEXES=(dlx_confidence dlx_kpi)

log "=== Splunk Enterprise Security Configuration Validation ==="
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
log "--- ES App and KV Store ---"
if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null; then
    version="$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || echo "unknown")"
    pass "${APP_NAME} installed (version: ${version})"
else
    fail "${APP_NAME} is not installed"
fi

kv_status="$(kvstore_status)"
case "${kv_status}" in
    ready) pass "KV Store status: ready" ;;
    *) warn "KV Store status: ${kv_status}; ES configuration depends on healthy KV Store" ;;
esac

log ""
check_index_group "Core ES Indexes" "${CORE_INDEXES[@]}"
check_index_group "UEBA Indexes" "${UEBA_INDEXES[@]}"
check_index_group "PCI Indexes" "${PCI_INDEXES[@]}"
check_index_group "Exposure Analytics Indexes" "${EXPOSURE_INDEXES[@]}"
check_index_group "Mission Control Indexes" "${MISSION_CONTROL_INDEXES[@]}"
check_index_group "Detection Lifecycle Indexes" "${DLX_INDEXES[@]}"

log "--- Role and Permission Configuration ---"
lookup_order="$(conf_value_global "limits" "lookup" "enforce_auto_lookup_order")"
case "${lookup_order}" in
    true|True|1) pass "limits.conf [lookup] enforce_auto_lookup_order is enabled" ;;
    "") warn "Could not read limits.conf [lookup] enforce_auto_lookup_order" ;;
    *) warn "limits.conf [lookup] enforce_auto_lookup_order is '${lookup_order}', expected true for ES" ;;
esac

managed_roles="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" \
    "app_permissions_manager://enforce_es_permissions" "managed_roles" 2>/dev/null || true)"
if [[ -n "${managed_roles}" ]]; then
    pass "App Permissions Manager managed roles: ${managed_roles}"
    for role in ess_analyst ess_user; do
        if [[ ",${managed_roles// /}," == *",${role},"* ]]; then
            pass "Managed roles include ${role}"
        else
            warn "Managed roles do not include ${role}"
        fi
    done
else
    warn "Could not read App Permissions Manager managed roles"
fi

log ""
log "--- Data Model Acceleration Enforcement ---"
DM_STANZAS=(
    Authentication
    Endpoint
    Intrusion_Detection
    Malware
    Network_Resolution
    Network_Sessions
    Network_Traffic
    Risk
    Splunk_Audit
    Web
)
for dm in "${DM_STANZAS[@]}"; do
    stanza="dm_accel_settings://${dm}"
    if rest_check_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "${stanza}" 2>/dev/null; then
        disabled="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "${stanza}" "disabled" 2>/dev/null || true)"
        accel="$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "${stanza}" "acceleration" 2>/dev/null || true)"
        pass "${stanza} present (disabled: ${disabled:-unknown}, acceleration: ${accel:-unknown})"
    else
        warn "${stanza} not found"
    fi
done

log ""
log "--- KV Store Collections ---"
COLLECTIONS=(
    "SplunkEnterpriseSecuritySuite:es_activity_queue"
    "SplunkEnterpriseSecuritySuite:es_notable_events"
    "SplunkEnterpriseSecuritySuite:asset_export_time_collection"
    "SplunkEnterpriseSecuritySuite:identity_export_time_collection"
    "SplunkEnterpriseSecuritySuite:investigative_canvas"
    "SplunkEnterpriseSecuritySuite:files"
)
for item in "${COLLECTIONS[@]}"; do
    app="${item%%:*}"
    collection="${item#*:}"
    if collection_accessible "${app}" "${collection}"; then
        pass "KV Store collection ${app}/${collection} accessible"
    else
        warn "KV Store collection ${app}/${collection} not accessible yet"
    fi
done

log ""
log "--- Data Smoke Checks ---"
for idx in notable risk threat_activity; do
    count="$(oneshot_count "| tstats count where index=${idx}")"
    case "${count}" in
        ''|0) warn "Index '${idx}' has no events in tstats smoke check" ;;
        *) pass "Index '${idx}' has ${count} event(s)" ;;
    esac
done

dm_count="$(oneshot_count '| tstats count from datamodel=Risk.All_Risk')"
case "${dm_count}" in
    ''|0) warn "Risk data model returned no events" ;;
    *) pass "Risk data model returned ${dm_count} event(s)" ;;
esac

log ""
log "--- Urgency Matrix ---"
urgency_count="$(oneshot_count '| rest splunk_server=local /servicesNS/nobody/SA-ThreatIntelligence/configs/conf-urgency | stats count')"
case "${urgency_count}" in
    ''|0) warn "No urgency.conf stanzas found; verify the ES urgency matrix is populated" ;;
    *) pass "${urgency_count} urgency.conf stanza(s) present" ;;
esac

log ""
log "--- Notable Suppressions ---"
suppression_count="$(oneshot_count '| rest splunk_server=local /servicesNS/nobody/SA-ThreatIntelligence/configs/conf-notable_suppressions | search title="notable_suppression://*" | stats count')"
case "${suppression_count}" in
    ''|0) warn "No notable suppression stanzas configured" ;;
    *) pass "${suppression_count} notable suppression stanza(s) configured" ;;
esac

log ""
log "--- Correlation Searches by Security Domain ---"
correlation_breakdown="$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
    '| rest splunk_server=local /servicesNS/-/-/admin/correlationsearches | stats count by security_domain | sort -count | head 10 | eval line=security_domain." => ".count | stats list(line) as lines | eval lines=mvjoin(lines, "; ")' \
    "lines" 2>/dev/null || true)"
if [[ -n "${correlation_breakdown}" ]]; then
    pass "Correlation searches by security_domain: ${correlation_breakdown}"
else
    warn "Could not enumerate correlation searches from correlationsearches.conf"
fi

log ""
log "--- Glass Tables ---"
view_count="$(oneshot_count '| rest splunk_server=local /servicesNS/-/-/data/ui/views | search "eai:type"="html" OR label="*Glass*" | stats count')"
case "${view_count}" in
    ''|0) warn "No Glass Table-style views found" ;;
    *) pass "${view_count} glass-table style view(s) present" ;;
esac

log ""
log "--- Content Library / ESCU ---"
for app in DA-ESS-ContentUpdate SA-ContentLibrary; do
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null; then
        version="$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null || echo "unknown")"
        pass "${app} installed (version: ${version})"
    else
        warn "${app} not installed; ESCU content subscriptions require it"
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

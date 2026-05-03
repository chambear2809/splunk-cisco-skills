#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco-cloud-security"
ADDON_NAME="TA-cisco-cloud-security-addon"
ORG_ID=""
SK=""
SKIP_DATA_FLOW=false
DATA_FLOW_EARLIEST="-1h@h"

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
info() { log "  INFO: $*"; }

usage() {
    cat >&2 <<EOF
Cisco Secure Access Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --org-id ID                Validate one specific org account
  --skip-data-flow           Skip the per-index 'tstats' event-flow probe
  --data-flow-earliest TIME  Earliest time for the event-flow probe (default: -1h@h)
  --help                     Show this help
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --org-id) require_arg "$1" $# || exit 1; ORG_ID="$2"; shift 2 ;;
        --skip-data-flow) SKIP_DATA_FLOW=true; shift ;;
        --data-flow-earliest) require_arg "$1" $# || exit 1; DATA_FLOW_EARLIEST="$2"; shift 2 ;;
        --help) usage ;;
        *) log "Unknown option: $1" >&2; usage 1 ;;
    esac
done

probe_index_event_flow() {
    local idx="$1"
    local label="$2"
    [[ -z "${idx}" ]] && return 0
    local count
    count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" \
        "| tstats count where index=${idx} earliest=${DATA_FLOW_EARLIEST} latest=now" \
        "count" 2>/dev/null || echo "0")
    if [[ "${count}" =~ ^[0-9]+$ ]] && [[ "${count}" -gt 0 ]]; then
        pass "${label} index '${idx}' has ${count} events since ${DATA_FLOW_EARLIEST}"
    else
        warn "${label} index '${idx}' has no events since ${DATA_FLOW_EARLIEST} (may be normal if just configured)"
    fi
}

org_accounts_get() {
    local query="$1"
    splunk_curl "${SK}" \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/org_accounts?${query}" \
        -w '\n%{http_code}' 2>/dev/null || true
}

collection_get() {
    local collection="$1"
    splunk_curl "${SK}" \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/storage/collections/data/$(_urlencode "${collection}")" \
        2>/dev/null || echo "[]"
}

log "=== Cisco Secure Access Validation ==="
log ""

warn_if_current_skill_role_unsupported

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
        fail "App not found — install Cisco Secure Access first"
    fi
    if rest_check_app "$SK" "$SPLUNK_URI" "$ADDON_NAME" 2>/dev/null; then
        version=$(rest_get_app_version "$SK" "$SPLUNK_URI" "$ADDON_NAME" 2>/dev/null || echo "unknown")
        pass "Add-on installed (version: ${version})"
    else
        fail "Add-on not found - install Cisco Secure Access add-on first"
    fi
fi

if [[ -n "${SK:-}" ]]; then
log ""
log "--- Org Accounts ---"
if [[ -n "${ORG_ID}" ]]; then
    query="orgId=$(_urlencode "${ORG_ID}")&fields=all"
    response="$(org_accounts_get "${query}")"
    http_code="$(echo "${response}" | sed -n '$p')"
    body="$(echo "${response}" | sed '$d')"
    if [[ "${http_code}" == "200" ]]; then
        pass "Org account '${ORG_ID}' exists"
        payload_summary="$(printf '%s' "${body}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    payload = data.get('payload', {})
    rows = payload.get('data', [])
    if rows:
        row = rows[0]
        print('|'.join([
            row.get('orgId', ''),
            row.get('investigate_index', '') or '',
            row.get('privateapp_index', '') or '',
            row.get('appdiscovery_index', '') or '',
        ]), end='')
except Exception:
    pass
")"
        IFS='|' read -r _ investigate_idx privateapp_idx appdiscovery_idx <<< "${payload_summary}"
        if [[ -n "${investigate_idx}" ]]; then pass "Investigate index configured: ${investigate_idx}"; else info "Investigate index not configured"; fi
        if [[ -n "${privateapp_idx}" ]]; then pass "Private Apps index configured: ${privateapp_idx}"; else info "Private Apps index not configured"; fi
        if [[ -n "${appdiscovery_idx}" ]]; then pass "App Discovery index configured: ${appdiscovery_idx}"; else info "App Discovery index not configured"; fi

        if ! $SKIP_DATA_FLOW; then
            log ""
            log "--- Data Flow (org-account indexes) ---"
            probe_index_event_flow "${investigate_idx}" "Investigate"
            probe_index_event_flow "${privateapp_idx}" "Private Apps"
            probe_index_event_flow "${appdiscovery_idx}" "App Discovery"
        fi
    elif [[ "${http_code}" == "404" ]]; then
        fail "Org account '${ORG_ID}' not found"
    else
        fail "Failed to query org account '${ORG_ID}' (HTTP ${http_code})"
    fi
else
    response="$(org_accounts_get "fields=all&draw=1&start=0&length=100")"
    http_code="$(echo "${response}" | sed -n '$p')"
    body="$(echo "${response}" | sed '$d')"
    if [[ "${http_code}" == "200" ]]; then
        account_count="$(printf '%s' "${body}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    payload = data.get('payload', {})
    print(int(payload.get('recordsTotal', 0)), end='')
except Exception:
    print(0, end='')
")"
        if [[ "${account_count}" -gt 0 ]]; then
            pass "Configured org accounts: ${account_count}"
        else
            warn "No Secure Access org accounts are configured yet"
        fi
    else
        fail "Failed to enumerate Secure Access org accounts (HTTP ${http_code})"
    fi
fi

log ""
log "--- App Bootstrap ---"
terms_count="$(collection_get "cloudlock-v2-tos" | python3 -c "
import json, sys
try:
    print(len(json.load(sys.stdin)), end='')
except Exception:
    print(0, end='')
")"
if [[ "${terms_count}" -gt 0 ]]; then
    pass "Terms acceptance record present"
else
    warn "Terms acceptance record not found — app UI may still prompt for acknowledgement"
fi

global_org_value="$(collection_get "global_org" | python3 -c "
import json, sys
try:
    rows = json.load(sys.stdin)
    if rows:
        print(rows[0].get('orgId', ''), end='')
except Exception:
    pass
")"
if [[ -n "${global_org_value}" ]]; then
    pass "Global org configured: ${global_org_value}"
    if [[ -n "${ORG_ID}" && "${ORG_ID}" != "${global_org_value}" ]]; then
        fail "Requested org '${ORG_ID}' does not match global org '${global_org_value}'"
    fi
else
    warn "Global org not configured"
fi

log ""
log "--- Dashboard Settings ---"
dashboard_interval="$(collection_get "dashboard_settings" | python3 -c "
import json, sys
try:
    rows = json.load(sys.stdin)
    if rows:
        print(rows[-1].get('search_interval', ''), end='')
except Exception:
    pass
")"
if [[ -n "${dashboard_interval}" ]]; then
    pass "Dashboard search interval configured: ${dashboard_interval}"
else
    warn "Dashboard search interval not stored — the UI falls back to 12 hours"
fi

refresh_rate="$(collection_get "refresh_rate" | python3 -c "
import json, sys
try:
    rows = json.load(sys.stdin)
    if rows:
        print(rows[-1].get('refresh_rate', ''), end='')
except Exception:
    pass
")"
if [[ -n "${refresh_rate}" ]]; then
    pass "Refresh rate configured: ${refresh_rate}"
else
    warn "Refresh rate not stored"
fi

cloudlock_status="$(collection_get "cloudlock_settings" | python3 -c "
import json, sys
try:
    rows = json.load(sys.stdin)
    if rows:
        row = rows[-1]
        print('|'.join([
            row.get('configName', ''),
            row.get('status', ''),
            row.get('url', '')
        ]), end='')
except Exception:
    pass
")"
IFS='|' read -r cloudlock_name cloudlock_state _ <<< "${cloudlock_status}"
if [[ -n "${cloudlock_name}" ]]; then
    pass "Cloudlock settings present: ${cloudlock_name}${cloudlock_state:+ (${cloudlock_state})}"
else
    info "Cloudlock settings not configured"
fi

org_filter="${ORG_ID:-${global_org_value:-}}"
dest_count="$(collection_get "selected_destination_lists" | python3 -c "
import json, sys
org_id = sys.argv[1]
try:
    rows = json.load(sys.stdin)
    if org_id:
        rows = [row for row in rows if row.get('orgId') == org_id]
    print(len(rows), end='')
except Exception:
    print(0, end='')
" "${org_filter}")"
if [[ "${dest_count}" -gt 0 ]]; then
    pass "Selected destination lists configured: ${dest_count}"
else
    info "No selected destination lists configured"
fi

s3_summary="$(collection_get "s3_indexes" | python3 -c "
import json, sys
org_id = sys.argv[1]
try:
    rows = json.load(sys.stdin)
    if org_id:
        rows = [row for row in rows if row.get('orgId') == org_id]
    if rows:
        row = rows[-1]
        values = [row.get(key, '') for key in ('dns_index', 'proxy_index', 'firewall_index', 'dlp_index', 'ravpn_index')]
        print('|'.join(values), end='')
except Exception:
    pass
" "${org_filter}")"
IFS='|' read -r dns_idx proxy_idx firewall_idx dlp_idx ravpn_idx <<< "${s3_summary}"
if [[ -n "${dns_idx}${proxy_idx}${firewall_idx}${dlp_idx}${ravpn_idx}" ]]; then
    pass "S3-backed indexes configured"
    [[ -n "${dns_idx}" ]] && info "DNS index: ${dns_idx}"
    [[ -n "${proxy_idx}" ]] && info "Proxy index: ${proxy_idx}"
    [[ -n "${firewall_idx}" ]] && info "Firewall index: ${firewall_idx}"
    [[ -n "${dlp_idx}" ]] && info "DLP index: ${dlp_idx}"
    [[ -n "${ravpn_idx}" ]] && info "RA VPN index: ${ravpn_idx}"
    if ! $SKIP_DATA_FLOW; then
        log ""
        log "--- Data Flow (S3-backed indexes) ---"
        probe_index_event_flow "${dns_idx}" "DNS"
        probe_index_event_flow "${proxy_idx}" "Proxy"
        probe_index_event_flow "${firewall_idx}" "Firewall"
        probe_index_event_flow "${dlp_idx}" "DLP"
        probe_index_event_flow "${ravpn_idx}" "RA VPN"
    fi
else
    info "S3-backed dashboard indexes not configured"
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

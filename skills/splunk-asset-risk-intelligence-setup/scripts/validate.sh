#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="SplunkAssetRiskIntelligence"
ARI_INDEXES=("ari_staging" "ari_asset" "ari_internal" "ari_ta")
ARI_ROLES=("ari_admin" "ari_analyst")

PASS=0
FAIL=0
WARN=0

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Asset and Risk Intelligence Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --help  Show this help
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

log "=== Splunk Asset and Risk Intelligence Validation ==="
log ""
warn_if_current_skill_role_unsupported

log "--- Splunk Authentication ---"
if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials; check credentials file"
elif ! SK=$(get_session_key "${SPLUNK_URI}"); then
    fail "Could not authenticate to Splunk REST API; check credentials"
fi

if [[ ${FAIL} -eq 0 ]]; then
    log ""
    log "--- App Presence ---"
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || echo "unknown")
        pass "${APP_NAME} installed (version: ${version})"
    else
        fail "${APP_NAME} not found"
    fi

    log ""
    log "--- Required Indexes ---"
    for idx in "${ARI_INDEXES[@]}"; do
        if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
            pass "Index '${idx}' exists"
        else
            fail "Index '${idx}' not found"
        fi
    done

    log ""
    log "--- KV Store ---"
    kvstore_status=$(splunk_curl "${SK}" "${SPLUNK_URI}/services/kvstore/status?output_mode=json" 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get('entry', [])
    print(entries[0].get('content', {}).get('current', {}).get('status', 'unknown') if entries else 'unknown')
except Exception:
    print('unknown')
" 2>/dev/null || echo "unknown")
    if [[ "${kvstore_status}" == "ready" ]]; then
        pass "KV Store status: ready"
    else
        warn "KV Store status: ${kvstore_status}; ARI requires healthy KV Store"
    fi

    log ""
    log "--- ARI Roles ---"
    for role in "${ARI_ROLES[@]}"; do
        code=$(splunk_curl "${SK}" "${SPLUNK_URI}/services/authorization/roles/${role}?output_mode=json" -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
        if [[ "${code}" == "200" ]]; then
            pass "Role '${role}' exists"
        else
            warn "Role '${role}' not found or not visible (HTTP ${code}); complete ARI role setup after install"
        fi
    done

    log ""
    log "--- ES Exposure Analytics Handoff ---"
    if rest_check_app "${SK}" "${SPLUNK_URI}" "SplunkEnterpriseSecuritySuite" 2>/dev/null; then
        pass "Enterprise Security detected; ARI exposure analytics handoff is applicable for ES 8.5+"
    else
        warn "Enterprise Security not detected; skip ES Exposure Analytics integration unless ES is installed"
    fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"

if [[ ${FAIL} -gt 0 ]]; then
    log "  Status: ISSUES FOUND"
    exit 1
elif [[ ${WARN} -gt 0 ]]; then
    log "  Status: OK with warnings"
else
    log "  Status: ALL CHECKS PASSED"
fi

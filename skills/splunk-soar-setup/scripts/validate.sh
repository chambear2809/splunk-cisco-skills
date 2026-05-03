#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

SOAR_APP_NAME="splunk_app_soar"
EXPORT_APP_NAME="phantom"
CHECK_EXPORT=false
SOAR_URL=""

usage() {
    cat <<EOF
Splunk SOAR Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --export        Also require Splunk App for SOAR Export
  --soar-url URL  Non-secret SOAR URL for reachability/handoff notes
  --help          Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --export) CHECK_EXPORT=true; shift ;;
        --soar-url) require_arg "$1" $# || exit 1; SOAR_URL="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

PASS=0
FAIL=0
WARN=0
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

check_app() {
    local app="$1" required="$2" version
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null || echo "unknown")
        pass "${app} installed (version: ${version})"
    elif [[ "${required}" == "true" ]]; then
        fail "${app} not found"
    else
        warn "${app} not found"
    fi
}

log "=== Splunk SOAR Validation ==="
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
    log "--- Apps ---"
    check_app "${SOAR_APP_NAME}" true
    if [[ "${CHECK_EXPORT}" == "true" ]]; then
        check_app "${EXPORT_APP_NAME}" true
    else
        check_app "${EXPORT_APP_NAME}" false
    fi

    log ""
    log "--- Deployment Placement ---"
    pass "Splunk App for SOAR belongs on search heads"
    warn "For distributed Enterprise environments with indexers, deploy splunk_app_soar to indexers because it contains indexes or index-time transformations"
    warn "Deployment Server placement is not supported for Splunk App for SOAR"

    log ""
    log "--- Handoffs ---"
    if [[ -n "${SOAR_URL}" ]]; then
        pass "SOAR URL captured for operator validation: ${SOAR_URL}"
    else
        warn "No SOAR URL supplied; verify SOAR connectivity in the app UI"
    fi
    warn "This validator checks Splunk-side SOAR apps only; for server-side checks, run the rendered splunk-soar-rendered/validate.sh after install"
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


#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_Security_Essentials"
PASS=0
FAIL=0
WARN=0

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Security Essentials Validation

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
info() { log "  INFO: $*"; }

log "=== Splunk Security Essentials Validation ==="
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
    log "--- Setup Checklist (manual) ---"
    # These items cannot be verified from the search-tier REST API; they are
    # product/UI gates that an operator must complete by hand. Surface them
    # as INFO so a healthy install reports "ALL CHECKS PASSED" without a
    # permanent WARN that operators learn to ignore. Posture dashboards are
    # explicitly optional, so they ride at INFO too.
    info "Manual gate: complete Data Inventory Introspection in the SSE UI"
    info "Manual gate: complete Content Mapping for the in-scope sourcetypes"
    info "Manual gate: review app configuration (settings, roles, scheduling)"
    info "Optional: enable posture dashboards in the SSE UI after the data inventory review"
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

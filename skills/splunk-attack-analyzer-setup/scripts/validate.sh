#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

INDEX_NAME="saa"

usage() {
    cat <<EOF
Splunk Attack Analyzer Validation

Usage: $(basename "$0") [--index NAME]
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --index) require_arg "$1" $# || exit 1; INDEX_NAME="$2"; shift 2 ;;
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

log "=== Splunk Attack Analyzer Validation ==="
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
    for app in Splunk_TA_SAA Splunk_App_SAA; do
        if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null; then
            version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null || echo "unknown")
            pass "${app} installed (version: ${version})"
        else
            fail "${app} not found"
        fi
    done

    log ""
    log "--- Index ---"
    if platform_check_index "${SK}" "${SPLUNK_URI}" "${INDEX_NAME}" 2>/dev/null; then
        pass "Index '${INDEX_NAME}' exists"
    else
        fail "Index '${INDEX_NAME}' not found"
    fi

    log ""
    log "--- Dashboard Macro ---"
    if rest_check_conf "${SK}" "${SPLUNK_URI}" "Splunk_App_SAA" "macros" "saa_indexes" 2>/dev/null; then
        definition=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "Splunk_App_SAA" "macros" "saa_indexes" "definition" 2>/dev/null || true)
        if [[ "${definition}" == *"${INDEX_NAME}"* ]]; then
            pass "saa_indexes macro points at '${INDEX_NAME}'"
        else
            warn "saa_indexes macro exists but definition is '${definition:-empty}'"
        fi
    else
        warn "saa_indexes macro not found in Splunk_App_SAA"
    fi

    log ""
    log "--- Input Handoff ---"
    input_count=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "Splunk_TA_SAA" "0" 2>/dev/null || echo "0")
    if [[ "${input_count}" =~ ^[0-9]+$ && "${input_count}" -gt 0 ]]; then
        pass "Detected ${input_count} enabled live input(s) owned by Splunk_TA_SAA"
    else
        warn "No enabled Splunk_TA_SAA inputs detected; create a completed-jobs input in the add-on UI"
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

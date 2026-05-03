#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

KAFKA_APP_NAME="Splunk-UBA-SA-Kafka"
CHECK_KAFKA_APP=false
UBA_HOST=""
UBA_INDEXES=("ueba" "ueba_summaries" "ubaroute" "ers")
SUPPORT_APPS=("SplunkEnterpriseSecuritySuite" "SA-UEBA" "DA-ESS-UEBA" "Splunk_TA_ueba")
EOS_DATE="2025-12-12"
END_OF_SUPPORT_DATE="2027-01-31"

usage() {
    cat <<EOF
Splunk UBA Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --kafka-app      Require Splunk UBA Kafka Ingestion App
  --uba-host HOST  Non-secret existing UBA host for handoff notes
  --help           Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kafka-app) CHECK_KAFKA_APP=true; shift ;;
        --uba-host) require_arg "$1" $# || exit 1; UBA_HOST="$2"; shift 2 ;;
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

check_optional_app() {
    local app="$1" required="$2" version
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null || echo "unknown")
        pass "${app} installed (version: ${version})"
    elif [[ "${required}" == "true" ]]; then
        fail "${app} not found"
    else
        warn "${app} not found or not visible"
    fi
}

log "=== Splunk UBA / UEBA Readiness Validation ==="
log ""
warn_if_current_skill_role_unsupported

log "--- Product Status ---"
warn "Standalone Splunk UBA end-of-sale: ${EOS_DATE}; end-of-support: ${END_OF_SUPPORT_DATE}"
warn "New UEBA work should target Splunk Enterprise Security Premier UEBA"
[[ -n "${UBA_HOST}" ]] && pass "Existing UBA host supplied for handoff: ${UBA_HOST}"

log ""
log "--- Splunk Authentication ---"
if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials; check credentials file"
elif ! SK=$(get_session_key "${SPLUNK_URI}"); then
    fail "Could not authenticate to Splunk REST API; check credentials"
fi

if [[ ${FAIL} -eq 0 ]]; then
    log ""
    log "--- ES / UEBA Support Apps ---"
    for app in "${SUPPORT_APPS[@]}"; do
        check_optional_app "${app}" false
    done
    if [[ "${CHECK_KAFKA_APP}" == "true" ]]; then
        check_optional_app "${KAFKA_APP_NAME}" true
    else
        check_optional_app "${KAFKA_APP_NAME}" false
    fi

    log ""
    log "--- UBA / UEBA Indexes ---"
    for idx in "${UBA_INDEXES[@]}"; do
        if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
            pass "Index '${idx}' exists"
        else
            warn "Index '${idx}' not found; confirm whether this deployment uses custom UBA/UEBA indexes"
        fi
    done

    log ""
    log "--- Migration Handoff ---"
    warn "Standalone UBA server install remains a manual/professional-services handoff"
    warn "Use splunk-enterprise-security-config for ES Premier UEBA readiness where applicable"
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

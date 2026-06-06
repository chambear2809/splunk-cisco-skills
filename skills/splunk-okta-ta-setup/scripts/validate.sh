#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/splunk-okta-ta-setup/scripts/validate.sh [--index IDX]

Validates Splunk_TA_okta_identity_cloud installation, index, configured inputs,
and Okta data using configured Splunk credentials.
EOF
    exit 0
fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_okta_identity_cloud"
INDEX="okta"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done

PASS=0
WARN=0
FAIL=0
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

log "=== Splunk Add-on for Okta Identity Cloud Validation ==="
warn_if_current_skill_role_unsupported

if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials"
else
    SK=$(get_session_key "${SPLUNK_URI}") || { fail "Could not authenticate to Splunk REST API"; SK=""; }
fi

if [[ -n "${SK:-}" ]]; then
    app_present=false
    index_present=false
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || echo "unknown")
        pass "Add-on installed: ${APP_NAME} (${version})"
        app_present=true
    else
        fail "Add-on missing: ${APP_NAME}"
    fi

    if platform_check_index "${SK}" "${SPLUNK_URI}" "${INDEX}"; then
        pass "Index ${INDEX} exists"
        index_present=true
    else
        warn "Index ${INDEX} not found"
    fi

    if ${app_present}; then
        inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "okta_identity_cloud://")
        if [[ "${inputs}" -gt 0 ]]; then
            pass "okta_identity_cloud input stanzas: ${inputs}"
        else
            warn "No okta_identity_cloud inputs configured yet"
        fi
    fi

    if ${index_present}; then
        log_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
            "| tstats count where index=${INDEX} sourcetype=OktaIM2:log" "count")
        if [[ "${log_count}" -gt 0 ]]; then
            pass "OktaIM2:log events in ${INDEX}: ${log_count}"
        else
            warn "No OktaIM2:log events found in ${INDEX}"
        fi
    fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
[[ "${FAIL}" -eq 0 ]]

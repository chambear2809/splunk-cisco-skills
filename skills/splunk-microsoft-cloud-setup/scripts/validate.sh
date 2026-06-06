#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/splunk-microsoft-cloud-setup/scripts/validate.sh [--o365-index IDX] [--azure-index IDX]

Validates the Office 365 and Microsoft Cloud Services add-ons, indexes,
configured inputs, and ingested data using configured Splunk credentials.
EOF
    exit 0
fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

O365_APP="splunk_ta_o365"
MSCS_APP="Splunk_TA_microsoft-cloudservices"
O365_INDEX="o365"
AZURE_INDEX="azure"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --o365-index) require_arg "$1" $# || exit 1; O365_INDEX="$2"; shift 2 ;;
        --azure-index) require_arg "$1" $# || exit 1; AZURE_INDEX="$2"; shift 2 ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done

PASS=0
WARN=0
FAIL=0
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

log "=== Microsoft Cloud Add-ons Validation ==="
warn_if_current_skill_role_unsupported

if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials"
else
    SK=$(get_session_key "${SPLUNK_URI}") || { fail "Could not authenticate to Splunk REST API"; SK=""; }
fi

if [[ -n "${SK:-}" ]]; then
    o365_present=false
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${O365_APP}"; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${O365_APP}" 2>/dev/null || echo "unknown")
        pass "Add-on installed: ${O365_APP} (${version})"
        o365_present=true
    else
        warn "Add-on not installed: ${O365_APP}"
    fi
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${MSCS_APP}"; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${MSCS_APP}" 2>/dev/null || echo "unknown")
        pass "Add-on installed: ${MSCS_APP} (${version})"
    else
        warn "Add-on not installed: ${MSCS_APP}"
    fi

    if platform_check_index "${SK}" "${SPLUNK_URI}" "${O365_INDEX}"; then
        pass "Index ${O365_INDEX} exists"
    else
        warn "Index ${O365_INDEX} not found"
    fi
    if platform_check_index "${SK}" "${SPLUNK_URI}" "${AZURE_INDEX}"; then
        pass "Index ${AZURE_INDEX} exists"
    else
        warn "Index ${AZURE_INDEX} not found"
    fi

    if ${o365_present}; then
        mgmt_inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${O365_APP}" "inputs" "splunk_ta_o365_management_activity://")
        if [[ "${mgmt_inputs}" -gt 0 ]]; then
            pass "Office 365 management activity inputs: ${mgmt_inputs}"
        else
            warn "No splunk_ta_o365_management_activity inputs configured yet"
        fi
        evt=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
            "| tstats count where index=${O365_INDEX} sourcetype=o365:management:activity" "count")
        if [[ "${evt}" -gt 0 ]]; then
            pass "o365:management:activity events in ${O365_INDEX}: ${evt}"
        else
            warn "No o365:management:activity events found in ${O365_INDEX}"
        fi
    fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
[[ "${FAIL}" -eq 0 ]]

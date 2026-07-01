#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/splunk-windows-ta-setup/scripts/validate.sh [--event-index IDX] [--perfmon-index IDX]

Validates Splunk_TA_windows installation, indexes, and WinEventLog/Perfmon data
using configured Splunk credentials.
Pass --completion to treat every readiness warning as a failure.
EOF
    exit 0
fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_windows"
EVENT_INDEX="wineventlog"
PERFMON_INDEX="perfmon"
COMPLETION=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --event-index) require_arg "$1" $# || exit 1; EVENT_INDEX="$2"; shift 2 ;;
        --perfmon-index) require_arg "$1" $# || exit 1; PERFMON_INDEX="$2"; shift 2 ;;
        --completion|--strict) COMPLETION=true; shift ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done
validate_splunk_index_name "${EVENT_INDEX}" || exit 1
validate_splunk_index_name "${PERFMON_INDEX}" || exit 1

PASS=0
WARN=0
FAIL=0
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { if [[ "${COMPLETION}" == "true" ]]; then fail "$*"; else log "  WARN: $*"; WARN=$((WARN + 1)); fi; }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

log "=== Splunk Add-on for Microsoft Windows Validation ==="
check_current_skill_role_for_validation "${COMPLETION}" || fail "Deployment role is unsupported for this skill"

if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials"
else
    SK=$(get_session_key "${SPLUNK_URI}") || { fail "Could not authenticate to Splunk REST API"; SK=""; }
fi

if [[ -n "${SK:-}" ]]; then
    index_present=false
    app_present=false
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || echo "unknown")
        pass "Add-on installed: ${APP_NAME} (${version})"
        app_present=true
    else
        fail "Add-on missing: ${APP_NAME}"
    fi

    if [[ "${COMPLETION}" == "true" && "${app_present}" == "true" ]]; then
        enabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "0" 2>/dev/null || echo 0)
        [[ "${enabled_inputs}" =~ ^[0-9]+$ && "${enabled_inputs}" -gt 0 ]] && pass "Enabled app inputs: ${enabled_inputs}" || fail "No enabled inputs owned by ${APP_NAME}"
    fi

    if platform_check_index "${SK}" "${SPLUNK_URI}" "${EVENT_INDEX}"; then
        pass "Index ${EVENT_INDEX} exists"
        index_present=true
    else
        warn "Index ${EVENT_INDEX} not found"
    fi
    if platform_check_index "${SK}" "${SPLUNK_URI}" "${PERFMON_INDEX}"; then
        pass "Index ${PERFMON_INDEX} exists"
    else
        warn "Index ${PERFMON_INDEX} not found"
    fi

    if ${index_present}; then
        event_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
            "| tstats count where index=${EVENT_INDEX} sourcetype=WinEventLog:Security" "count")
        if [[ "${event_count}" -gt 0 ]]; then
            pass "WinEventLog:Security events in ${EVENT_INDEX}: ${event_count}"
        else
            warn "No WinEventLog:Security events found in ${EVENT_INDEX}"
        fi
    fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
[[ "${FAIL}" -eq 0 ]]

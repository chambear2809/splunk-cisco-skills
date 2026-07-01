#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STRICT=false
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/cisco-webex-setup/scripts/validate.sh [--strict|--completion] [--help]

Validates Webex Add-on/App installation, dashboard macros, account stanzas,
inputs, and starter data presence using configured Splunk credentials.
Diagnostic mode reports incomplete onboarding as warnings. --strict and its
alias --completion make completion-critical findings exit nonzero.
EOF
    exit 0
fi
while [[ $# -gt 0 ]]; do
    case "$1" in
        --strict|--completion) STRICT=true; shift ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

ADDON_APP="ta_cisco_webex_add_on_for_splunk"
DASHBOARD_APP="cisco_webex_meetings_app_for_splunk"
PASS=0
WARN=0
FAIL=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
completion_issue() { if ${STRICT}; then fail "$@"; else warn "$@"; fi; }

log "=== Cisco Webex Validation ==="
warn_if_current_skill_role_unsupported

if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials"
else
    SK=$(get_session_key "${SPLUNK_URI}") || { fail "Could not authenticate to Splunk REST API"; SK=""; }
fi

if [[ -n "${SK:-}" ]]; then
    addon_present=false
    dashboard_present=false
    for app in "${ADDON_APP}" "${DASHBOARD_APP}"; do
        if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}"; then
            version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null || echo "unknown")
            pass "Installed app present: ${app} (${version})"
            [[ "${app}" == "${ADDON_APP}" ]] && addon_present=true
            [[ "${app}" == "${DASHBOARD_APP}" ]] && dashboard_present=true
        else
            fail "Required app missing: ${app}"
        fi
    done

    if ${dashboard_present}; then
        for idx in wx wxc wxcc; do
            if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
                pass "Webex index exists: ${idx}"
            else
                completion_issue "Webex index is missing: ${idx}"
            fi
        done
        for macro in webex_meeting webex_calling webex_contact_center webex_indexes; do
            def=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${DASHBOARD_APP}" "macros" "${macro}" "definition")
            if [[ -n "${def}" ]]; then
                pass "Macro ${macro} exists (${def})"
            else
                completion_issue "Macro ${macro} not found"
            fi
        done
        for macro_expected in webex_meeting:wx webex_calling:wxc webex_contact_center:wxcc; do
            macro="${macro_expected%%:*}"
            expected="${macro_expected#*:}"
            def=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${DASHBOARD_APP}" "macros" "${macro}" "definition")
            [[ "${def}" == *"${expected}"* ]] || completion_issue "Macro ${macro} is not aligned to index ${expected}"
        done
        combined_def=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${DASHBOARD_APP}" "macros" "webex_indexes" "definition")
        if [[ "${combined_def}" != *webex_meeting* || "${combined_def}" != *webex_calling* || "${combined_def}" != *webex_contact_center* ]]; then
            completion_issue "Macro webex_indexes is not aligned to all Webex dashboard macros"
        fi
    else
        warn "Skipping Webex dashboard macro checks because ${DASHBOARD_APP} is missing"
    fi

    if ${dashboard_present}; then
        view_count=$(splunk_curl "${SK}" "${SPLUNK_URI}/servicesNS/nobody/${DASHBOARD_APP}/data/ui/views?output_mode=json&count=0" 2>/dev/null \
            | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("entry", [])))' 2>/dev/null || echo "0")
        if [[ "${view_count}" -gt 0 ]]; then
            pass "Shipped Webex dashboard views are visible: ${view_count}"
        else
            completion_issue "No dashboard views are visible for ${DASHBOARD_APP}"
        fi
    fi

    if ${addon_present}; then
        acct_count=$(rest_list_ta_stanzas "${SK}" "${SPLUNK_URI}" "${ADDON_APP}" "ta_cisco_webex_add_on_for_splunk_account" \
            | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("entry", [])))' 2>/dev/null || echo "0")
        if [[ "${acct_count}" -gt 0 ]]; then
            pass "Webex account stanzas configured: ${acct_count}"
        else
            completion_issue "No Webex accounts configured"
        fi

        total_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${ADDON_APP}")
        enabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${ADDON_APP}" "0")
        if [[ "${total_inputs}" -gt 0 && "${enabled_inputs}" -gt 0 ]]; then
            pass "Webex inputs present: total=${total_inputs}, enabled=${enabled_inputs}"
        elif [[ "${total_inputs}" -gt 0 ]]; then
            completion_issue "Webex inputs exist but none are enabled"
        else
            completion_issue "No Webex inputs configured"
        fi
    else
        warn "Skipping Webex account and input checks because ${ADDON_APP} is missing"
    fi

    if ${addon_present} || ${dashboard_present}; then
        event_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" '| tstats count where index IN (wx,wxc,wxcc)' "count")
        if [[ "${event_count}" -gt 0 ]]; then
            pass "Webex default indexes contain ${event_count} event(s)"
        else
            completion_issue "No events found in wx/wxc/wxcc"
        fi
    fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
[[ "${FAIL}" -eq 0 ]]

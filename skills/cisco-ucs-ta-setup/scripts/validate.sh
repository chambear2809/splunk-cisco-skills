#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STRICT=false
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/cisco-ucs-ta-setup/scripts/validate.sh [--strict|--completion] [--help]

Validates Cisco UCS TA installation, index, templates, server records, inputs,
and starter data using configured Splunk credentials.
Diagnostic mode reports incomplete onboarding as warnings. --strict and its
alias --completion make completion-critical findings exit nonzero. This TA
ships no standalone dashboards.
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

APP_NAME="Splunk_TA_cisco-ucs"
PASS=0
WARN=0
FAIL=0
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
completion_issue() { if ${STRICT}; then fail "$@"; else warn "$@"; fi; }

log "=== Cisco UCS TA Validation ==="
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
        pass "TA installed: ${APP_NAME} (${version})"
        app_present=true
    else
        fail "TA missing: ${APP_NAME}"
    fi
    if platform_check_index "${SK}" "${SPLUNK_URI}" "cisco_ucs"; then
        pass "Index cisco_ucs exists"
        index_present=true
    else
        completion_issue "Index cisco_ucs not found"
    fi

    if ${app_present}; then
        for template in UCS_Fault UCS_Inventory UCS_Performance; do
            content=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "splunk_ta_cisco_ucs_templates" "${template}" "content")
            if [[ -n "${content}" ]]; then
                pass "Template ${template} exists"
            else
                completion_issue "Template ${template} not found"
            fi
        done

        server_count=$(rest_list_ta_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "splunk_ta_cisco_ucs_servers" \
            | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("entry", [])))' 2>/dev/null || echo "0")
        if [[ "${server_count}" -gt 0 ]]; then
            pass "UCS Manager server records: ${server_count}"
        else
            completion_issue "No UCS Manager server records configured"
        fi

        input_count=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "cisco_ucs_task://")
        enabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "0")
        if [[ "${input_count}" -gt 0 && "${enabled_inputs}" -gt 0 ]]; then
            pass "cisco_ucs_task input stanzas: ${input_count}, enabled live inputs: ${enabled_inputs}"
        elif [[ "${input_count}" -gt 0 ]]; then
            completion_issue "cisco_ucs_task input stanzas exist but none are enabled"
        else
            completion_issue "No cisco_ucs_task inputs configured"
        fi
    else
        warn "Skipping UCS template, server, and task checks because ${APP_NAME} is missing"
    fi

    if ${index_present}; then
        event_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" '| tstats count where index=cisco_ucs sourcetype=cisco:ucs' "count")
        if [[ "${event_count}" -gt 0 ]]; then
            pass "cisco_ucs has ${event_count} cisco:ucs event(s)"
        else
            completion_issue "No cisco:ucs events found in cisco_ucs"
        fi
    fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
[[ "${FAIL}" -eq 0 ]]

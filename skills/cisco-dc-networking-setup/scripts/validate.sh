#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STRICT=false
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/cisco-dc-networking-setup/scripts/validate.sh [--strict|--completion] [--help]

Validates the deployed Cisco DC Networking app using configured Splunk credentials.
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

APP_NAME="cisco_dc_networking_app_for_splunk"
SK=""

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
completion_issue() { if ${STRICT}; then fail "$@"; else warn "$@"; fi; }

log "=== Cisco DC Networking TA Validation ==="
log ""

warn_if_current_skill_role_unsupported

log "--- App Installation ---"
if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials — check credentials file"
elif ! SK=$(get_session_key "${SPLUNK_URI}"); then
    fail "Could not authenticate to Splunk REST API — check credentials"
else
    if rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null; then
        version=$(rest_get_app_version "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || echo "unknown")
        pass "App installed (version: ${version})"
    else
        fail "App not found — install Cisco DC Networking app first"
    fi
fi

if [[ -n "${SK:-}" ]]; then
log ""
log "--- Indexes ---"
REQUIRED_INDEXES=("cisco_aci" "cisco_nd" "cisco_nexus_9k")
for idx in "${REQUIRED_INDEXES[@]}"; do
    if platform_check_index "$SK" "$SPLUNK_URI" "$idx" 2>/dev/null; then
        pass "Index '${idx}' exists"
    else
        completion_issue "Index '${idx}' not found"
    fi
done

log ""
log "--- Search Macros ---"
for macro_index in "cisco_dc_aci_index:cisco_aci" "cisco_dc_nd_index:cisco_nd" "cisco_dc_n9k_index:cisco_nexus_9k"; do
    macro="${macro_index%%:*}"
    expected_index="${macro_index#*:}"
    def=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "$macro" "definition" 2>/dev/null || true)
    if [[ -n "${def}" && "${def}" == *"${expected_index}"* ]]; then
        pass "Macro '${macro}' includes ${expected_index}"
    elif [[ -n "${def}" ]]; then
        completion_issue "Macro '${macro}' does not include ${expected_index}: ${def}"
    else
        completion_issue "Macro '${macro}' not found; shipped dashboards cannot be proven aligned"
    fi
done

view_count=$(splunk_curl "$SK" "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/ui/views?output_mode=json&count=0" 2>/dev/null \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("entry", [])))' 2>/dev/null || echo "0")
if [[ "${view_count}" -gt 0 ]]; then
    pass "Shipped dashboard views are visible: ${view_count}"
else
    completion_issue "No dashboard views are visible for ${APP_NAME}"
fi

log ""
log "--- Account Configuration ---"
account_total=0
for label_handler in "ACI:cisco_dc_networking_app_for_splunk_aci_account" "ND:cisco_dc_networking_app_for_splunk_nd_account" "Nexus9K:cisco_dc_networking_app_for_splunk_nexus_9k_account"; do
    label="${label_handler%%:*}"
    handler="${label_handler#*:}"
    json=$(rest_list_ta_stanzas "$SK" "$SPLUNK_URI" "$APP_NAME" "$handler" 2>/dev/null || true)
    if [[ -n "${json}" ]]; then
        count=$(echo "${json}" | python3 -c "import json,sys; d=json.load(sys.stdin); e=d.get('entry',[]); print(len(e))" 2>/dev/null || echo "0")
        if [[ "${count}" -gt 0 ]]; then
            account_total=$((account_total + count))
            pass "${label} account conf exists with ${count} account(s)"
        else
            warn "${label} account conf exists but has no stanzas"
        fi
    else
        warn "No ${label} account conf found"
    fi
done
[[ "${account_total}" -gt 0 ]] || completion_issue "No ACI, Nexus Dashboard, or Nexus 9K account is configured"

log ""
log "--- Data Inputs ---"
input_count=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || echo "0")
enabled_inputs=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME" "0" 2>/dev/null || echo "0")
disabled_inputs=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME" "1" 2>/dev/null || echo "0")
if [[ "${input_count}" -gt 0 ]]; then
    if [[ "${enabled_inputs}" -eq "${input_count}" ]]; then
        pass "${enabled_inputs} input(s) enabled"
    elif [[ "${enabled_inputs}" -gt 0 ]]; then
        warn "${enabled_inputs} input(s) enabled, ${disabled_inputs} disabled"
    else
        completion_issue "${input_count} input stanza(s) exist but all are disabled"
    fi
else
    completion_issue "No inputs configured"
fi

log ""
log "--- Data Flow Check ---"
event_total=0
for idx in "cisco_aci" "cisco_nd" "cisco_nexus_9k"; do
    event_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" "| tstats count where index=${idx} earliest=-1h@h latest=now" "count" 2>/dev/null || echo "0")
    if [[ "${event_count}" -gt 0 ]]; then
        event_total=$((event_total + event_count))
        pass "Index '${idx}' has ${event_count} events in the last hour"
    else
        warn "Index '${idx}' has no events in the last hour (may be normal if just configured)"
    fi
done
[[ "${event_total}" -gt 0 ]] || completion_issue "No DC Networking events were found in the last hour"

log ""
log "--- Settings ---"
ssl_verify=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "cisco_dc_networking_app_for_splunk_settings" "additional_parameters" "verify_ssl" 2>/dev/null || true)
if [[ "${ssl_verify}" == "True" || "${ssl_verify}" == "1" ]]; then
    pass "SSL verification is enabled"
else
    warn "SSL verification is disabled (verify_ssl = ${ssl_verify})"
fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"

if [[ ${FAIL} -gt 0 ]]; then
    log "  Status: ISSUES FOUND — review failures above"
    exit 1
elif [[ ${WARN} -gt 0 ]]; then
    log "  Status: OK with warnings"
    exit 0
else
    log "  Status: ALL CHECKS PASSED"
    exit 0
fi

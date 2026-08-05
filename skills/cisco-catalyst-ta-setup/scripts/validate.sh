#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STRICT=false
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/cisco-catalyst-ta-setup/scripts/validate.sh [--strict|--completion] [--help]

Validates the deployed Cisco Catalyst TA using configured Splunk credentials.
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

APP_NAME="TA_cisco_catalyst"
SK=""

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
completion_issue() { if ${STRICT}; then fail "$@"; else warn "$@"; fi; }

get_verify_ssl_setting() {
    splunk_curl "$SK" \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/TA_cisco_catalyst_settings/additional_parameters?output_mode=json" \
        2>/dev/null \
        | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get('entry', [])
    value = ''
    if entries:
        value = str(entries[0].get('content', {}).get('verify_ssl', '')).strip()
    print(value, end='')
except Exception:
    print('', end='')
" 2>/dev/null || true
}

log "=== Cisco Catalyst TA Validation ==="
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
        pass "TA installed (version: ${version})"
    else
        fail "TA not found — install Cisco Catalyst TA first"
    fi
fi

if [[ -n "${SK:-}" ]]; then
log ""
log "--- Indexes ---"
REQUIRED_INDEXES=("catalyst" "ise" "sdwan" "cybervision")
for idx in "${REQUIRED_INDEXES[@]}"; do
    if platform_check_index "$SK" "$SPLUNK_URI" "$idx" 2>/dev/null; then
        pass "Index '${idx}' exists"
    else
        completion_issue "Index '${idx}' not found"
    fi
done

log ""
log "--- Account Configuration ---"
account_total=0
tls_disabled_accounts=0
for label_handler in "Catalyst Center:TA_cisco_catalyst_account" "ISE:TA_cisco_catalyst_ise_account" "SD-WAN:TA_cisco_catalyst_sdwan_account" "Cyber Vision:TA_cisco_catalyst_cyber_vision_account" "IOS-XE CLI (Beta):TA_cisco_catalyst_cli_account"; do
    label="${label_handler%%:*}"
    handler="${label_handler#*:}"
    json=$(rest_list_ta_stanzas "$SK" "$SPLUNK_URI" "$APP_NAME" "$handler" 2>/dev/null || true)
    if [[ -n "${json}" ]]; then
        count=$(echo "${json}" | python3 -c "import json,sys; d=json.load(sys.stdin); e=d.get('entry',[]); print(len(e))" 2>/dev/null || echo "0")
        insecure_count=$(echo "${json}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(sum(str(e.get('content',{}).get('verify_ssl','')).strip().lower() in ('0','false','no','off') for e in d.get('entry',[])))" 2>/dev/null || echo "0")
        tls_disabled_accounts=$((tls_disabled_accounts + insecure_count))
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
[[ "${account_total}" -gt 0 ]] || completion_issue "No Cisco Catalyst or IOS-XE CLI product account is configured"

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
product_specs=(
    "Catalyst Center|catalyst|(sourcetype=cisco:dnac:* OR sourcetype=cisco:catalyst:center:*)"
    "ISE|ise|sourcetype=cisco:ise:*"
    "SD-WAN|sdwan|sourcetype=cisco:sdwan:*"
    "Cyber Vision|cybervision|sourcetype=cisco:cybervision:*"
)
for product_spec in "${product_specs[@]}"; do
    IFS="|" read -r product idx sourcetype_filter <<< "${product_spec}"
    event_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" "| tstats count where index=${idx} earliest=-24h ${sourcetype_filter}" "count" 2>/dev/null || echo "0")
    if [[ "${event_count}" -gt 0 ]]; then
        event_total=$((event_total + event_count))
        pass "${product} index '${idx}' has ${event_count} canonical events in the last 24 hours"
    else
        warn "${product} index '${idx}' has no canonical events in the last 24 hours"
    fi
done

cli_event_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" '| tstats count where index=* earliest=-24h sourcetype=cisco:iosxe:cli:*' "count" 2>/dev/null || echo "0")
if [[ "${cli_event_count}" -gt 0 ]]; then
    event_total=$((event_total + cli_event_count))
    pass "IOS-XE CLI (Beta) has ${cli_event_count} canonical events in the last 24 hours"
else
    warn "IOS-XE CLI (Beta) has no cisco:iosxe:cli:* events in the last 24 hours"
fi
[[ "${event_total}" -gt 0 ]] || completion_issue "No recent Catalyst Center, ISE, SD-WAN, Cyber Vision, or IOS-XE CLI events were found"

log ""
log "--- SD-WAN Text-Syslog Readiness ---"
sdwan_receiver_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" '| rest /services/data/inputs/all count=0 | search sourcetype="cisco:firewall:logs" | stats count as count' "count" 2>/dev/null || echo "0")
sdwan_utd_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" '| tstats count where index=* earliest=-24h sourcetype="cisco:sdwan:utd:logs"' "count" 2>/dev/null || echo "0")
sdwan_zbfw_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" '| tstats count where index=* earliest=-24h sourcetype IN ("cisco:sdwan:session:audit:trail:start","cisco:sdwan:session:audit:trail","cisco:sdwan:pass:pkt","cisco:sdwan:drop:pkt","cisco:sdwan:log:summary","cisco:sdwan:block:host","cisco:sdwan:unblock:host","cisco:sdwan:alert:on","cisco:sdwan:alert:off","cisco:sdwan:host:tcp:alert:on","cisco:sdwan:sessions:maximum")' "count" 2>/dev/null || echo "0")
sdwan_system_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" '| tstats count where index=* earliest=-24h sourcetype IN ("cisco:sdwan:syslog","cisco:sdwan:system:logs","cisco:sdwan:acl:logs","cisco:sdwan:sgacl:logs")' "count" 2>/dev/null || echo "0")
sdwan_text_count=$((sdwan_utd_count + sdwan_zbfw_count + sdwan_system_count))

if [[ "${sdwan_receiver_count}" -gt 0 ]]; then
    pass "${sdwan_receiver_count} local input(s) use the required cisco:firewall:logs SD-WAN ingress sourcetype"
elif [[ "${sdwan_text_count}" -gt 0 ]]; then
    pass "SD-WAN text events are arriving without a local cisco:firewall:logs input (consistent with an external SC4S/HEC or upstream parsing path)"
else
    warn "No local cisco:firewall:logs receiver or recent SD-WAN text-syslog event evidence was found"
fi

if [[ "${sdwan_text_count}" -gt 0 ]]; then
    pass "SD-WAN text syslog found: UTD=${sdwan_utd_count}, ZBFW=${sdwan_zbfw_count}, system/ACL=${sdwan_system_count}"
else
    warn "No recent UTD, ZBFW, or ordinary SD-WAN text-syslog events were found; a listener alone does not enable Cisco-side producers"
fi
log "  INFO: HSL and Unified Logging are NetFlow/IPFIX paths and are intentionally outside this text-syslog check."

log ""
log "--- Settings ---"
ssl_verify="$(get_verify_ssl_setting)"
if [[ "${tls_disabled_accounts}" -gt 0 ]]; then
    warn "${tls_disabled_accounts} account(s) disable TLS certificate verification"
elif [[ "${ssl_verify}" == "1" || "${ssl_verify}" == "True" || "${ssl_verify}" == "true" ]]; then
    pass "TLS certificate verification is enabled and no account opt-outs were found"
else
    warn "Legacy global TLS verification is disabled (verify_ssl = ${ssl_verify})"
fi

log ""
log "--- Shipped Dashboard ---"
ta_view_count=$(splunk_curl "$SK" "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/ui/views/data_collection_health?output_mode=json" 2>/dev/null \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("entry", [])))' 2>/dev/null || echo "0")
if [[ "${ta_view_count}" -gt 0 ]]; then
    pass "TA Data Collection Health dashboard is visible"
else
    completion_issue "TA Data Collection Health dashboard is not visible"
fi

log ""
log "--- Optional Companion App ---"
if rest_check_app "$SK" "$SPLUNK_URI" "cisco-catalyst-app" 2>/dev/null; then
    pass "Cisco Enterprise Networking app is installed"
    view_count=$(splunk_curl "$SK" "${SPLUNK_URI}/servicesNS/nobody/cisco-catalyst-app/data/ui/views?output_mode=json&count=0" 2>/dev/null \
        | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("entry", [])))' 2>/dev/null || echo "0")
    if [[ "${view_count}" -gt 0 ]]; then
        pass "Cisco Enterprise Networking dashboard views are visible: ${view_count}"
    else
        completion_issue "No dashboard views are visible for cisco-catalyst-app"
    fi
    companion_macro=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "cisco-catalyst-app" "macros" "cisco_catalyst_app_index" "definition" 2>/dev/null || true)
    macro_aligned=true
    for idx in catalyst ise sdwan cybervision; do
        [[ "${companion_macro}" == *"${idx}"* ]] || macro_aligned=false
    done
    if ${macro_aligned}; then
        pass "Companion dashboard macro includes all Catalyst indexes"
    else
        completion_issue "Companion dashboard macro is missing or not aligned to catalyst/ise/sdwan/cybervision"
    fi
else
    warn "Cisco Enterprise Networking app (cisco-catalyst-app) is not installed; optional cross-product dashboards were not checked"
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

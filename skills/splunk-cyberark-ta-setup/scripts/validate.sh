#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
usage() { cat <<'EOF'
Usage: bash skills/splunk-cyberark-ta-setup/scripts/validate.sh [--index IDX] [--products LIST] [--completion]

Validates CyberArk EPM and legacy EPV/PTA add-on installation, index, inputs, and package-backed CyberArk source types.
EOF
}
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
INDEX="cyberark"; PRODUCTS="epm,epv_pta"; COMPLETION=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
    --products) require_arg "$1" $# || exit 1; PRODUCTS="$2"; shift 2 ;;
    --completion|--strict) COMPLETION=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done
[[ "${INDEX}" =~ ^[A-Za-z0-9_-]{1,80}$ ]] || { echo "ERROR: invalid Splunk index name: ${INDEX}" >&2; exit 1; }
IFS=',' read -r -a selected_products <<<"${PRODUCTS}"
[[ "${#selected_products[@]}" -gt 0 ]] || { echo "ERROR: --products must select epm and/or epv_pta." >&2; exit 1; }
for product in "${selected_products[@]}"; do
  case "${product}" in epm|epv_pta) ;; *) echo "ERROR: Unsupported CyberArk product: ${product}" >&2; exit 1 ;; esac
done
selected(){ [[ ",${PRODUCTS}," == *",$1,"* ]]; }
PASS=0; WARN=0; FAIL=0
pass(){ log "  PASS: $*"; PASS=$((PASS+1)); }; warn(){ if [[ "${COMPLETION}" == "true" ]]; then fail "$*"; else log "  WARN: $*"; WARN=$((WARN+1)); fi; }; fail(){ log "  FAIL: $*"; FAIL=$((FAIL+1)); }
log "=== CyberArk Add-on Validation ==="; check_current_skill_role_for_validation "${COMPLETION}" || fail "Deployment role is unsupported for this skill"
if ! load_splunk_credentials; then fail "Could not load Splunk credentials"; else SK=$(get_session_key "${SPLUNK_URI}") || { fail "Could not authenticate to Splunk REST API"; SK=""; }; fi
if [[ -n "${SK:-}" ]]; then
  installed_apps=0
  if selected epm; then
    if rest_check_app "${SK}" "${SPLUNK_URI}" Splunk_TA_cyberark_epm; then version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" Splunk_TA_cyberark_epm 2>/dev/null || echo "unknown"); pass "Add-on installed: Splunk_TA_cyberark_epm (${version})"; installed_apps=$((installed_apps+1)); else warn "Add-on not installed: Splunk_TA_cyberark_epm"; fi
  fi
  if selected epv_pta; then
    if rest_check_app "${SK}" "${SPLUNK_URI}" Splunk_TA_cyberark; then version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" Splunk_TA_cyberark 2>/dev/null || echo "unknown"); pass "Add-on installed: Splunk_TA_cyberark (${version})"; installed_apps=$((installed_apps+1)); else warn "Add-on not installed: Splunk_TA_cyberark"; fi
  fi
  [[ "${installed_apps}" -gt 0 ]] || fail "No CyberArk add-on is installed"
  if platform_check_index "${SK}" "${SPLUNK_URI}" "${INDEX}"; then pass "Index ${INDEX} exists"; else warn "Index ${INDEX} not found"; fi
  if selected epm; then
    total=0; for prefix in application_events:// inbox_events:// admin_audit_logs:// account_admin_audit_logs:// policy_audit:// policy_audit_events:// threat_detection:// policies_and_computers://; do total=$((total + $(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "Splunk_TA_cyberark_epm" "inputs" "${prefix}"))); done
    [[ "${total}" -gt 0 ]] && pass "CyberArk EPM input stanzas: ${total}" || warn "No CyberArk EPM inputs configured yet"
    if [[ "${COMPLETION}" == "true" ]]; then enabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "Splunk_TA_cyberark_epm" "0" 2>/dev/null || echo 0); [[ "${enabled_inputs}" =~ ^[0-9]+$ && "${enabled_inputs}" -gt 0 ]] && pass "Enabled CyberArk EPM inputs: ${enabled_inputs}" || fail "No enabled CyberArk EPM inputs detected"; fi
    epm_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where index=${INDEX} sourcetype IN (\"cyberark:epm:raw:events\",\"cyberark:epm:raw:policy:events\",\"cyberark:epm:admin:audit\",\"cyberark:epm:account:admin:audit\",\"cyberark:epm:application:events\",\"cyberark:epm:policy:audit\",\"cyberark:epm:threat:detection\")" "count")
    [[ "${epm_count}" -gt 0 ]] && pass "CyberArk EPM events in ${INDEX}: ${epm_count}" || warn "No CyberArk EPM events found in ${INDEX}"
  fi
  if selected epv_pta; then
    legacy_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where index=${INDEX} sourcetype IN (\"cyberark:epv:cef\",\"cyberark:pta:cef\")" "count")
    [[ "${legacy_count}" -gt 0 ]] && pass "CyberArk EPV/PTA events in ${INDEX}: ${legacy_count}" || warn "No CyberArk EPV/PTA events found in ${INDEX}"
  fi
fi
log ""; log "=== Validation Summary ==="; log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"; [[ "${FAIL}" -eq 0 ]]

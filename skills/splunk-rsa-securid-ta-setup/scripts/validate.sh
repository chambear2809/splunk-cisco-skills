#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
usage() { cat <<'EOF'
Usage: bash skills/splunk-rsa-securid-ta-setup/scripts/validate.sh [--index IDX] [--products LIST] [--completion]

Validates RSA SecurID CAS and AM add-on installation, index, inputs, and package-backed RSA source types.
EOF
}
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
INDEX="rsa"; PRODUCTS="cas,am"; COMPLETION=false
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
[[ "${#selected_products[@]}" -gt 0 ]] || { echo "ERROR: --products must select cas and/or am." >&2; exit 1; }
for product in "${selected_products[@]}"; do
  case "${product}" in cas|am) ;; *) echo "ERROR: Unsupported RSA SecurID product: ${product}" >&2; exit 1 ;; esac
done
selected(){ [[ ",${PRODUCTS}," == *",$1,"* ]]; }
PASS=0; WARN=0; FAIL=0
pass(){ log "  PASS: $*"; PASS=$((PASS+1)); }; warn(){ if [[ "${COMPLETION}" == "true" ]]; then fail "$*"; else log "  WARN: $*"; WARN=$((WARN+1)); fi; }; fail(){ log "  FAIL: $*"; FAIL=$((FAIL+1)); }
log "=== RSA SecurID Add-on Validation ==="; check_current_skill_role_for_validation "${COMPLETION}" || fail "Deployment role is unsupported for this skill"
if ! load_splunk_credentials; then fail "Could not load Splunk credentials"; else SK=$(get_session_key "${SPLUNK_URI}") || { fail "Could not authenticate to Splunk REST API"; SK=""; }; fi
if [[ -n "${SK:-}" ]]; then
  installed_apps=0
  if selected cas; then
    if rest_check_app "${SK}" "${SPLUNK_URI}" Splunk_TA_rsa_securid_cas; then version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" Splunk_TA_rsa_securid_cas 2>/dev/null || echo "unknown"); pass "Add-on installed: Splunk_TA_rsa_securid_cas (${version})"; installed_apps=$((installed_apps+1)); else warn "Add-on not installed: Splunk_TA_rsa_securid_cas"; fi
  fi
  if selected am; then
    if rest_check_app "${SK}" "${SPLUNK_URI}" Splunk_TA_rsa-securid; then version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" Splunk_TA_rsa-securid 2>/dev/null || echo "unknown"); pass "Add-on installed: Splunk_TA_rsa-securid (${version})"; installed_apps=$((installed_apps+1)); else warn "Add-on not installed: Splunk_TA_rsa-securid"; fi
  fi
  [[ "${installed_apps}" -gt 0 ]] || fail "No RSA SecurID add-on is installed"
  if platform_check_index "${SK}" "${SPLUNK_URI}" "${INDEX}"; then pass "Index ${INDEX} exists"; else warn "Index ${INDEX} not found"; fi
  if selected cas; then
    total=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "Splunk_TA_rsa_securid_cas" "inputs" "cloud_administration_api://")
    [[ "${total}" -gt 0 ]] && pass "RSA CAS input stanzas: ${total}" || warn "No RSA CAS inputs configured yet"
    if [[ "${COMPLETION}" == "true" ]]; then enabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "Splunk_TA_rsa_securid_cas" "0" 2>/dev/null || echo 0); [[ "${enabled_inputs}" =~ ^[0-9]+$ && "${enabled_inputs}" -gt 0 ]] && pass "Enabled RSA CAS inputs: ${enabled_inputs}" || fail "No enabled RSA CAS inputs detected"; fi
    cas_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where index=${INDEX} sourcetype IN (\"rsa:securid:cas:adminlog:json\",\"rsa:securid:cas:usereventlog:json\",\"rsa:securid:cas:riskuser:json\")" "count")
    [[ "${cas_count}" -gt 0 ]] && pass "RSA CAS events in ${INDEX}: ${cas_count}" || warn "No RSA CAS events found in ${INDEX}"
  fi
  if selected am; then
    am_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where index=${INDEX} sourcetype IN (\"rsa:securid:syslog\",\"rsa:securid:admin:syslog\",\"rsa:securid:runtime:syslog\",\"rsa:securid:system:syslog\")" "count")
    [[ "${am_count}" -gt 0 ]] && pass "RSA Authentication Manager events in ${INDEX}: ${am_count}" || warn "No RSA Authentication Manager events found in ${INDEX}"
  fi
fi
log ""; log "=== Validation Summary ==="; log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"; [[ "${FAIL}" -eq 0 ]]

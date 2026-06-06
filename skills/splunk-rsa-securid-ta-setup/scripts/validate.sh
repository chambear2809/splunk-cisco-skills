#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then cat <<'EOF'
Usage: bash skills/splunk-rsa-securid-ta-setup/scripts/validate.sh [--index IDX]

Validates RSA SecurID CAS and AM add-on installation, index, inputs, and package-backed RSA source types.
EOF
exit 0; fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
INDEX="rsa"
while [[ $# -gt 0 ]]; do case "$1" in --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;; *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;; esac; done
PASS=0; WARN=0; FAIL=0
pass(){ log "  PASS: $*"; PASS=$((PASS+1)); }; warn(){ log "  WARN: $*"; WARN=$((WARN+1)); }; fail(){ log "  FAIL: $*"; FAIL=$((FAIL+1)); }
log "=== RSA SecurID Add-on Validation ==="; warn_if_current_skill_role_unsupported
if ! load_splunk_credentials; then fail "Could not load Splunk credentials"; else SK=$(get_session_key "${SPLUNK_URI}") || { fail "Could not authenticate to Splunk REST API"; SK=""; }; fi
if [[ -n "${SK:-}" ]]; then
  for app in Splunk_TA_rsa_securid_cas Splunk_TA_rsa-securid; do if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}"; then version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null || echo "unknown"); pass "Add-on installed: ${app} (${version})"; else warn "Add-on not installed: ${app}"; fi; done
  if platform_check_index "${SK}" "${SPLUNK_URI}" "${INDEX}"; then pass "Index ${INDEX} exists"; else warn "Index ${INDEX} not found"; fi
  total=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "Splunk_TA_rsa_securid_cas" "inputs" "cloud_administration_api://")
  [[ "${total}" -gt 0 ]] && pass "RSA CAS input stanzas: ${total}" || warn "No RSA CAS inputs configured yet"
  count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where index=${INDEX} sourcetype IN (\"rsa:securid:cas:adminlog:json\",\"rsa:securid:syslog\")" "count")
  [[ "${count}" -gt 0 ]] && pass "RSA SecurID events in ${INDEX}: ${count}" || warn "No RSA SecurID events found in ${INDEX}"
fi
log ""; log "=== Validation Summary ==="; log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"; [[ "${FAIL}" -eq 0 ]]

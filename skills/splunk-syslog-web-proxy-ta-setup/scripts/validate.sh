#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then cat <<'EOF'
Usage: bash skills/splunk-syslog-web-proxy-ta-setup/scripts/validate.sh [--index IDX] [--syslog-index IDX] [--windows-index IDX]

Validates selected web/proxy add-on apps and package-backed source types using configured Splunk credentials.
EOF
exit 0; fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
INDEX="web"; SYSLOG_INDEX="netproxy"; WINDOWS_INDEX="iis"
while [[ $# -gt 0 ]]; do case "$1" in --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;; --syslog-index) require_arg "$1" $# || exit 1; SYSLOG_INDEX="$2"; shift 2 ;; --windows-index) require_arg "$1" $# || exit 1; WINDOWS_INDEX="$2"; shift 2 ;; *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;; esac; done
PASS=0; WARN=0; FAIL=0
pass(){ log "  PASS: $*"; PASS=$((PASS+1)); }; warn(){ log "  WARN: $*"; WARN=$((WARN+1)); }; fail(){ log "  FAIL: $*"; FAIL=$((FAIL+1)); }
log "=== Syslog/Web/Proxy Add-on Validation ==="; warn_if_current_skill_role_unsupported
if ! load_splunk_credentials; then fail "Could not load Splunk credentials"; else SK=$(get_session_key "${SPLUNK_URI}") || { fail "Could not authenticate to Splunk REST API"; SK=""; }; fi
if [[ -n "${SK:-}" ]]; then
  for app in Splunk_TA_apache Splunk_TA_nginx Splunk_TA_microsoft-iis Splunk_TA_tomcat Splunk_TA_haproxy Splunk_TA_squid Splunk_TA_bluecoat-proxysg Splunk_TA_websense-cg Splunk_TA_checkpoint_log_exporter Splunk_TA_f5-bigip Splunk_TA_citrix-netscaler Splunk_TA_infoblox; do if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}"; then pass "Add-on installed: ${app}"; fi; done
  for idx in "${INDEX}" "${SYSLOG_INDEX}" "${WINDOWS_INDEX}"; do if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}"; then pass "Index ${idx} exists"; else warn "Index ${idx} not found"; fi; done
  count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where (index=${INDEX} sourcetype IN (\"apache:access\",\"nginx:plus:access\",\"tomcat:access:log\",\"haproxy:http\")) OR (index=${WINDOWS_INDEX} sourcetype=\"ms:iis:auto\") OR (index=${SYSLOG_INDEX} sourcetype IN (\"bluecoat:proxysg:access:syslog\",\"cp_log:syslog\",\"f5:bigip:syslog\",\"infoblox:dns\"))" "count")
  [[ "${count}" -gt 0 ]] && pass "Web/proxy/appliance events found: ${count}" || warn "No selected web/proxy/appliance events found"
fi
log ""; log "=== Validation Summary ==="; log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"; [[ "${FAIL}" -eq 0 ]]

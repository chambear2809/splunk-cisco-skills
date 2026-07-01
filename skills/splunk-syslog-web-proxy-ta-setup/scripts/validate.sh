#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
usage(){ cat <<'EOF'
Usage: bash skills/splunk-syslog-web-proxy-ta-setup/scripts/validate.sh [--products LIST] [--index IDX] [--syslog-index IDX] [--windows-index IDX] [--completion]

Validates selected web/proxy add-on apps and package-backed source types using configured Splunk credentials.
EOF
}
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
INDEX="web"; SYSLOG_INDEX="netproxy"; WINDOWS_INDEX="iis"; PRODUCTS="apache,nginx,iis,tomcat,haproxy,squid,bluecoat,forcepoint,checkpoint,f5,citrix,infoblox"; COMPLETION=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --products) require_arg "$1" $# || exit 1; PRODUCTS="$2"; shift 2 ;;
    --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
    --syslog-index) require_arg "$1" $# || exit 1; SYSLOG_INDEX="$2"; shift 2 ;;
    --windows-index) require_arg "$1" $# || exit 1; WINDOWS_INDEX="$2"; shift 2 ;;
    --completion|--strict) COMPLETION=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done
for index_name in "${INDEX}" "${SYSLOG_INDEX}" "${WINDOWS_INDEX}"; do
  [[ "${index_name}" =~ ^[A-Za-z0-9_-]{1,80}$ ]] || { echo "ERROR: invalid Splunk index name: ${index_name}" >&2; exit 1; }
done
IFS=',' read -r -a selected_products <<<"${PRODUCTS}"
[[ "${#selected_products[@]}" -gt 0 ]] || { echo "ERROR: --products must select at least one product." >&2; exit 1; }
for product in "${selected_products[@]}"; do
  case "${product}" in apache|nginx|iis|tomcat|haproxy|squid|bluecoat|forcepoint|checkpoint|f5|citrix|infoblox) ;; *) echo "ERROR: unsupported product: ${product}" >&2; exit 1 ;; esac
done

product_app(){ case "$1" in apache) echo Splunk_TA_apache ;; nginx) echo Splunk_TA_nginx ;; iis) echo Splunk_TA_microsoft-iis ;; tomcat) echo Splunk_TA_tomcat ;; haproxy) echo Splunk_TA_haproxy ;; squid) echo Splunk_TA_squid ;; bluecoat) echo Splunk_TA_bluecoat-proxysg ;; forcepoint) echo Splunk_TA_websense-cg ;; checkpoint) echo Splunk_TA_checkpoint_log_exporter ;; f5) echo Splunk_TA_f5-bigip ;; citrix) echo Splunk_TA_citrix-netscaler ;; infoblox) echo Splunk_TA_infoblox ;; esac; }
product_index(){ case "$1" in apache|nginx|tomcat|haproxy) echo "${INDEX}" ;; iis) echo "${WINDOWS_INDEX}" ;; *) echo "${SYSLOG_INDEX}" ;; esac; }
product_sourcetypes(){ case "$1" in
  apache) echo '"apache:access","apache:access:combined","apache:access:json","apache:access:kv","apache:error"' ;;
  nginx) echo '"nginx:plus:access","nginx:plus:kv","nginx:plus:error","nginx:plus:api","nginx:app:protect"' ;;
  iis) echo '"ms:iis:auto","ms:iis:default","ms:iis:default:85","ms:iis:splunk","ms:iis:webglobalmodule"' ;;
  tomcat) echo '"tomcat:access:log","tomcat:access:log:splunk","tomcat:runtime:log","tomcat:jmx"' ;;
  haproxy) echo '"haproxy:default","haproxy:http","haproxy:tcp","haproxy:clf:http","haproxy:splunk:http"' ;;
  squid) echo '"squid:access","squid:access:recommended"' ;;
  bluecoat) echo '"bluecoat","bluecoat:proxysg:access:syslog","bluecoat:proxysg:access:file","bluecoat:proxysg:access:kv"' ;;
  forcepoint) echo '"websense","websense:cg:kv"' ;;
  checkpoint) echo '"cp_log","cp_log:syslog"' ;;
  f5) echo '"f5:bigip:syslog","f5:bigip:asm:syslog","f5:bigip:apm:syslog","f5:telemetry:json","f5:bigip:ltm:icontrol","f5:bigip:system:icontrol"' ;;
  citrix) echo '"citrix:netscaler","citrix:netscaler:syslog","citrix:netscaler:ipfix","citrix:netscaler:ipfix:syslog","citrix:netscaler:nitro","citrix:netscaler:appfw","citrix:netscaler:appfw:cef"' ;;
  infoblox) echo '"infoblox:dns","infoblox:dhcp","infoblox:audit","infoblox:threatprotect","infoblox:file","infoblox:port"' ;;
esac; }
PASS=0; WARN=0; FAIL=0
pass(){ log "  PASS: $*"; PASS=$((PASS+1)); }; warn(){ if [[ "${COMPLETION}" == "true" ]]; then fail "$*"; else log "  WARN: $*"; WARN=$((WARN+1)); fi; }; fail(){ log "  FAIL: $*"; FAIL=$((FAIL+1)); }
log "=== Syslog/Web/Proxy Add-on Validation ==="; check_current_skill_role_for_validation "${COMPLETION}" || fail "Deployment role is unsupported for this skill"
if ! load_splunk_credentials; then fail "Could not load Splunk credentials"; else SK=$(get_session_key "${SPLUNK_URI}") || { fail "Could not authenticate to Splunk REST API"; SK=""; }; fi
if [[ -n "${SK:-}" ]]; then
  installed_apps=0
  for product in "${selected_products[@]}"; do app="$(product_app "${product}")"; if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}"; then pass "Add-on installed: ${app}"; installed_apps=$((installed_apps+1)); else warn "Selected add-on is not installed: ${app}"; fi; done
  [[ "${installed_apps}" -gt 0 ]] || fail "None of the supported syslog/web/proxy add-ons is installed"
  checked_indexes=""
  for product in "${selected_products[@]}"; do
    idx="$(product_index "${product}")"
    if [[ ",${checked_indexes}," != *",${idx},"* ]]; then
      if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}"; then pass "Index ${idx} exists"; else warn "Index ${idx} not found"; fi
      checked_indexes="${checked_indexes:+${checked_indexes},}${idx}"
    fi
    sts="$(product_sourcetypes "${product}")"
    count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where index=\"${idx}\" sourcetype IN (${sts})" "count" 2>/dev/null || echo 0)
    [[ "${count}" =~ ^[0-9]+$ && "${count}" -gt 0 ]] && pass "${product} events found in ${idx}: ${count}" || warn "No ${product} events found in ${idx}"
  done
fi
log ""; log "=== Validation Summary ==="; log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"; [[ "${FAIL}" -eq 0 ]]

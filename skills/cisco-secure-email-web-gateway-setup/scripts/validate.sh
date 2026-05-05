#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PRODUCT="both"
ESA_INDEX="email"
WSA_INDEX="netproxy"

usage() {
    cat >&2 <<EOF
Usage: $(basename "$0") [--product esa|wsa|both] [--esa-index INDEX] [--wsa-index INDEX]
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --product) require_arg "$1" $# || exit 1; PRODUCT="$2"; shift 2 ;;
        --esa-index) require_arg "$1" $# || exit 1; ESA_INDEX="$2"; shift 2 ;;
        --wsa-index) require_arg "$1" $# || exit 1; WSA_INDEX="$2"; shift 2 ;;
        --help|-h) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

case "${PRODUCT}" in esa|wsa|both) ;; *) echo "ERROR: --product must be esa, wsa, or both." >&2; exit 1 ;; esac
want_esa() { [[ "${PRODUCT}" == "esa" || "${PRODUCT}" == "both" ]]; }
want_wsa() { [[ "${PRODUCT}" == "wsa" || "${PRODUCT}" == "both" ]]; }

PASS=0; WARN=0; FAIL=0
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

log "=== Cisco Secure Email/Web Gateway Validation ==="
warn_if_current_skill_role_unsupported
if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials"
    SK=""
else
    SK=$(get_session_key "${SPLUNK_URI}" 2>/dev/null || true)
    [[ -n "${SK}" ]] || fail "Could not authenticate to Splunk REST API"
fi

check_product() {
    local app="$1" macro="$2" index="$3" search="$4" app_present=false
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}"; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${app}" 2>/dev/null || echo "unknown")
        pass "Installed app present: ${app} (${version})"
        app_present=true
    else
        fail "App missing: ${app}"
    fi
    if platform_check_index "${SK}" "${SPLUNK_URI}" "${index}"; then
        pass "Index ${index} exists"
    else
        warn "Index ${index} not found"
    fi
    if ! ${app_present}; then
        warn "Skipping macro and data checks because ${app} is missing"
        return 0
    fi
    def=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${app}" "macros" "${macro}" "definition")
    if [[ -n "${def}" ]]; then
        pass "Macro ${macro} exists (${def})"
    else
        warn "Macro ${macro} not found"
    fi
    count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "${search}" "count")
    if [[ "${count}" -gt 0 ]]; then
        pass "${app} data present: ${count} event(s)"
    else
        warn "No recent/default-index data found for ${app}"
    fi
}

if [[ -n "${SK}" ]]; then
    want_esa && check_product "Splunk_TA_cisco-esa" "Cisco_ESA_Index" "${ESA_INDEX}" "| tstats count where index=${ESA_INDEX} sourcetype=cisco:esa:*"
    want_wsa && check_product "Splunk_TA_cisco-wsa" "Cisco_WSA_Index" "${WSA_INDEX}" "| tstats count where index=${WSA_INDEX} sourcetype=cisco:wsa:*"
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
[[ "${FAIL}" -eq 0 ]]

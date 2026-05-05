#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/cisco-talos-intelligence-setup/scripts/validate.sh [--help]

Validates Cisco Talos Intelligence app readiness without querying Talos.
EOF
    exit 0
fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_Talos_Intelligence"
ES_APP_NAME="SplunkEnterpriseSecuritySuite"
PASS=0; WARN=0; FAIL=0
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

version_at_least() {
    python3 - "$1" "$2" <<'PY'
import re
import sys

def parts(value):
    nums = [int(x) for x in re.findall(r"\d+", value)]
    return nums + [0] * (4 - len(nums))

sys.exit(0 if parts(sys.argv[1]) >= parts(sys.argv[2]) else 1)
PY
}

is_fedramp_target() {
    local value
    value="${SPLUNK_CLOUD_STACK:-} ${SPLUNK_CLOUD_SEARCH_HEAD:-} ${SPLUNK_URI:-} ${SPLUNK_HOST:-} ${ACS_SERVER:-}"
    value="${value,,}"
    [[ "${value}" == *fedramp* || "${value}" == *splunkcloudgc.com* || "${value}" == *".gov."* ]]
}

log "=== Cisco Talos Intelligence Validation ==="
warn_if_current_skill_role_unsupported

if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials"
    SK=""
else
    SK=$(get_session_key "${SPLUNK_URI}" 2>/dev/null || true)
    [[ -n "${SK}" ]] || fail "Could not authenticate to Splunk REST API"
fi

if [[ -n "${SK}" ]]; then
    supported_posture=true
    talos_app_present=false
    if is_splunk_cloud; then
        pass "Target platform appears to be Splunk Cloud"
    else
        fail "Talos is documented for Splunk Enterprise Security Cloud only"
        supported_posture=false
    fi

    if is_fedramp_target; then
        fail "FedRAMP/GovCloud targets are not supported for Talos Intelligence"
        supported_posture=false
    else
        pass "Target does not look like a FedRAMP/GovCloud stack"
    fi

    if rest_check_app "${SK}" "${SPLUNK_URI}" "${ES_APP_NAME}"; then
        es_version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${ES_APP_NAME}" 2>/dev/null || echo "unknown")
        if [[ "${es_version}" == "unknown" ]]; then
            fail "Enterprise Security is installed but its version could not be determined"
            supported_posture=false
        elif version_at_least "${es_version}" "7.3.2"; then
            pass "Enterprise Security version ${es_version} meets the 7.3.2+ baseline"
        else
            fail "Enterprise Security ${es_version} is below the 7.3.2+ Talos baseline"
            supported_posture=false
        fi
    else
        fail "Enterprise Security app missing: ${ES_APP_NAME}"
        supported_posture=false
    fi

    if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || echo "unknown")
        pass "Talos app installed: ${APP_NAME} (${version})"
        talos_app_present=true
    else
        fail "Talos app missing: ${APP_NAME}"
    fi

    if ! ${supported_posture}; then
        warn "Skipping Talos package configuration checks because this target is not a supported ES Cloud posture"
    elif ! ${talos_app_present}; then
        warn "Skipping Talos package configuration checks because ${APP_NAME} is missing"
    else
    api_url=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "app" "api" "url")
    if [[ "${api_url}" == "https://es-api.talos.cisco.com" ]]; then
        pass "Talos API URL is ${api_url}"
    else
        warn "Unexpected or missing Talos API URL: ${api_url:-missing}"
    fi

    cap_admin=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "authorize" "role_admin" "get_talos_enrichment")
    cap_analyst=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "authorize" "role_ess_analyst" "get_talos_enrichment")
    if [[ "${cap_admin}" == "enabled" || "${cap_analyst}" == "enabled" ]]; then
        pass "get_talos_enrichment capability is mapped"
    else
        warn "get_talos_enrichment capability mapping not found"
    fi

    rest_handler=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "restmap" "query_reputation" "handler")
    if [[ -n "${rest_handler}" ]]; then
        pass "query_reputation custom REST handler is registered (${rest_handler})"
    else
        fail "query_reputation custom REST handler is not registered"
    fi

    acct_json=$(rest_list_ta_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "Splunk_TA_Talos_Intelligence_account" 2>/dev/null || true)
    acct_summary=$(printf '%s' "${acct_json}" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get("entry", [])
    for e in entries:
        c = e.get("content", {})
        name = e.get("name", "?")
        fingerprint = c.get("fingerprint", "")
        print(f"{name}|{fingerprint}")
except Exception:
    pass
' 2>/dev/null || true)
    if [[ -n "${acct_summary}" ]]; then
        pass "Talos service account stanza exists"
        while IFS='|' read -r name fingerprint; do
            [[ -z "${name}" ]] && continue
            if [[ -n "${fingerprint}" ]]; then
                pass "Service account ${name} has fingerprint ${fingerprint}"
            else
                warn "Service account ${name} exists but fingerprint is missing"
            fi
        done <<< "${acct_summary}"
    else
        warn "No Talos service account stanza found. Splunk Cloud may need to finish provisioning; docs note a wait after service-account generation."
    fi

    for action in intelligence_collection_from_talos intelligence_enrichment_with_talos; do
        label=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "alert_actions" "${action}" "label")
        if [[ -n "${label}" ]]; then
            pass "Alert action ${action} present (${label})"
        else
            fail "Alert action ${action} missing"
        fi
    done

    disabled=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "threatlist://talos_intelligence_ip_blacklist" "disabled")
    if [[ "${disabled}" == "1" || "${disabled}" == "true" || "${disabled}" == "True" ]]; then
        pass "Talos IP blacklist threatlist remains disabled"
    else
        warn "Talos IP blacklist threatlist is enabled or state is unknown (${disabled:-missing})"
    fi
    fi

fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
[[ "${FAIL}" -eq 0 ]]

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="SplunkAssetRiskIntelligence"
ES_APP_NAME="SplunkEnterpriseSecuritySuite"
LATEST_RESEARCHED_VERSION="1.2.1"
ARI_INDEXES=("ari_staging" "ari_asset" "ari_internal" "ari_ta")
ARI_ROLES=("ari_admin" "ari_analyst")
ARI_CAPABILITIES=(
    "ari_manage_data_source_settings"
    "ari_manage_metric_settings"
    "ari_manage_report_exceptions"
    "ari_dashboard_add_alerts"
    "ari_edit_table_fields"
    "ari_save_filters"
    "ari_manage_filters"
    "ari_manage_homepage_settings"
)

PASS=0
FAIL=0
WARN=0

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Asset and Risk Intelligence Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --help  Show this help
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

version_lt() {
    python3 - "$1" "$2" <<'PY'
import re
import sys
from itertools import zip_longest

def parse(value):
    parts = []
    for piece in str(value).split("."):
        match = re.match(r"(\d+)", piece)
        if not match:
            break
        parts.append(int(match.group(1)))
    return parts

left = parse(sys.argv[1])
right = parse(sys.argv[2])
if not left or not right:
    sys.exit(1)
for lpart, rpart in zip_longest(left, right, fillvalue=0):
    if lpart < rpart:
        sys.exit(0)
    if lpart > rpart:
        sys.exit(1)
sys.exit(1)
PY
}

json_field_from_first_entry() {
    local field="$1"
    python3 -c '
import json
import sys

field = sys.argv[1]
try:
    data = json.load(sys.stdin)
    entries = data.get("entry", [])
    print(entries[0].get("content", {}).get(field, "") if entries else "")
except Exception:
    print("")
' "${field}"
}

count_json_entries() {
    python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
    print(len(data.get("entry", [])))
except Exception:
    print("unknown")
'
}

capability_present() {
    local capability="$1"
    python3 -c '
import json
import sys

wanted = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for entry in data.get("entry", []):
    values = {
        str(entry.get("name", "")),
        str(entry.get("title", "")),
        str(entry.get("content", {}).get("capability", "")),
    }
    if wanted in values:
        sys.exit(0)
sys.exit(1)
' "${capability}"
}

parse_related_products() {
    python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    print("unknown")
    sys.exit(0)

found = []
for entry in data.get("entry", []):
    haystack = " ".join(
        str(value)
        for value in (
            entry.get("name", ""),
            entry.get("title", ""),
            entry.get("content", {}).get("label", ""),
            entry.get("content", {}).get("description", ""),
        )
    ).lower()
    if "asset and risk intelligence" not in haystack:
        continue
    if "technical add-on" in haystack or "add-on for asset and risk intelligence" in haystack:
        if "windows" in haystack:
            found.append("Windows TA")
        elif "linux" in haystack:
            found.append("Linux TA")
        elif "mac" in haystack or "macos" in haystack or "mac os" in haystack:
            found.append("macOS TA")
        else:
            found.append("ARI TA")
    if "echo" in haystack:
        found.append("Echo")

print(", ".join(sorted(set(found))) if found else "none")
'
}

log "=== Splunk Asset and Risk Intelligence Validation ==="
log ""
warn_if_current_skill_role_unsupported

log "--- Splunk Authentication ---"
if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials; check credentials file"
elif ! SK=$(get_session_key "${SPLUNK_URI}"); then
    fail "Could not authenticate to Splunk REST API; check credentials"
fi

if [[ ${FAIL} -eq 0 ]]; then
    log ""
    log "--- Platform Compatibility ---"
    server_info_json=$(splunk_curl "${SK}" "${SPLUNK_URI}/services/server/info?output_mode=json" 2>/dev/null || true)
    platform_version=$(printf '%s' "${server_info_json}" | json_field_from_first_entry version)
    if [[ -z "${platform_version}" ]]; then
        warn "Could not read Splunk platform version; verify ARI compatibility manually"
    elif version_lt "${platform_version}" "9.1.3"; then
        warn "Splunk platform ${platform_version} is below 9.1.3; Splunkbase lists ARI 1.2.1 for 9.0-10.3, but ARI docs signal 9.1.3+"
    else
        pass "Splunk platform version ${platform_version} is compatible with ARI 1.2.x guidance"
    fi

    log ""
    log "--- App Presence ---"
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || echo "unknown")
        pass "${APP_NAME} installed (version: ${version})"
        if [[ "${version}" != "${LATEST_RESEARCHED_VERSION}" ]]; then
            warn "${APP_NAME} version ${version} differs from latest researched ${LATEST_RESEARCHED_VERSION}; review release notes before production rollout"
        fi
    else
        fail "${APP_NAME} not found"
    fi

    log ""
    log "--- Required Indexes ---"
    for idx in "${ARI_INDEXES[@]}"; do
        if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
            pass "Index '${idx}' exists"
        else
            fail "Index '${idx}' not found"
        fi
    done

    log ""
    log "--- KV Store ---"
    kvstore_status=$(splunk_curl "${SK}" "${SPLUNK_URI}/services/kvstore/status?output_mode=json" 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get('entry', [])
    print(entries[0].get('content', {}).get('current', {}).get('status', 'unknown') if entries else 'unknown')
except Exception:
    print('unknown')
" 2>/dev/null || echo "unknown")
    if [[ "${kvstore_status}" == "ready" ]]; then
        pass "KV Store status: ready"
    else
        warn "KV Store status: ${kvstore_status}; ARI requires healthy KV Store"
    fi

    log ""
    log "--- ARI Roles ---"
    for role in "${ARI_ROLES[@]}"; do
        code=$(splunk_curl "${SK}" "${SPLUNK_URI}/services/authorization/roles/${role}?output_mode=json" -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
        if [[ "${code}" == "200" ]]; then
            pass "Role '${role}' exists"
        else
            warn "Role '${role}' not found or not visible (HTTP ${code}); complete ARI role setup after install"
        fi
    done

    log ""
    log "--- ARI Capabilities ---"
    capability_json=$(splunk_curl "${SK}" "${SPLUNK_URI}/services/authorization/capabilities?output_mode=json&count=0" 2>/dev/null || true)
    if [[ -z "${capability_json}" ]]; then
        warn "Could not read Splunk capabilities; verify ARI capabilities from Permission settings"
    else
        for capability in "${ARI_CAPABILITIES[@]}"; do
            if printf '%s' "${capability_json}" | capability_present "${capability}"; then
                pass "Capability '${capability}' is visible"
            else
                warn "Capability '${capability}' not visible; complete ARI post-install role/capability setup if needed"
            fi
        done
    fi

    log ""
    log "--- ARI Saved Searches ---"
    saved_search_json=$(splunk_curl "${SK}" "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/saved/searches?output_mode=json&count=0" 2>/dev/null || true)
    saved_search_count=$(printf '%s' "${saved_search_json}" | count_json_entries)
    case "${saved_search_count}" in
        ''|unknown)
            warn "Could not enumerate app-owned saved searches; verify ARI processing searches from the app UI"
            ;;
        0)
            warn "No app-owned saved searches were visible; confirm post-install configuration completed"
            ;;
        *)
            pass "ARI app-owned saved searches visible (${saved_search_count})"
            ;;
    esac

    log ""
    log "--- ARI Technical Add-on Data ---"
    ari_ta_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where index=ari_ta earliest=-24h latest=now | eval count=count-0" "count" 2>/dev/null || echo "0")
    if [[ "${ari_ta_count}" =~ ^[0-9]+$ && "${ari_ta_count}" -gt 0 ]]; then
        pass "ari_ta data visible in the last 24 hours (${ari_ta_count} events)"
    else
        warn "No ari_ta data visible in the last 24 hours; deploy ARI Technical Add-ons and activate ARI data sources when needed"
    fi

    log ""
    log "--- Enterprise Security Hints ---"
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${ES_APP_NAME}" 2>/dev/null; then
        es_version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${ES_APP_NAME}" 2>/dev/null || echo "unknown")
        pass "Enterprise Security detected (version: ${es_version})"
        if [[ "${es_version}" == "unknown" ]]; then
            warn "Could not determine ES version; Exposure Analytics handoff applies to ES 8.5+"
        elif version_lt "${es_version}" "8.5.0"; then
            warn "ES ${es_version} is below 8.5.0; use normal ARI-to-ES integration rather than ES 8.5+ Exposure Analytics"
        else
            pass "ES ${es_version} can use the ARI Exposure Analytics handoff"
        fi
    else
        warn "Enterprise Security not detected; ARI-to-ES and Exposure Analytics handoffs are not applicable on this search tier"
    fi

    log ""
    log "--- Related Product Evidence ---"
    apps_json=$(splunk_curl "${SK}" "${SPLUNK_URI}/services/apps/local?output_mode=json&count=0" 2>/dev/null || true)
    related_products=$(printf '%s' "${apps_json}" | parse_related_products)
    case "${related_products}" in
        ''|unknown)
            warn "Could not enumerate related ARI products"
            ;;
        none)
            warn "No ARI Technical Add-on or Echo evidence observed; this can be normal before endpoint collection or secondary-search-head rollout"
            ;;
        *)
            pass "Related ARI product evidence observed: ${related_products}"
            ;;
    esac

    log ""
    log "--- Operator Handoffs ---"
    pass "Post-install configuration, data sources, metrics, responses, audit, investigations, ES integration, Add-on, Echo, upgrade, and teardown prerequisites are documented in the skill reference"
    warn "ARI app-specific UI/API configuration remains an operator handoff until stable app-specific REST contracts are proven"
    if [[ -n "${platform_version:-}" ]] && version_lt "${platform_version}" "9.1.3"; then
        warn "Compatibility review recommended before enabling production ARI processing on platform ${platform_version}"
    fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"

if [[ ${FAIL} -gt 0 ]]; then
    log "  Status: ISSUES FOUND"
    exit 1
elif [[ ${WARN} -gt 0 ]]; then
    log "  Status: OK with warnings"
else
    log "  Status: ALL CHECKS PASSED"
fi

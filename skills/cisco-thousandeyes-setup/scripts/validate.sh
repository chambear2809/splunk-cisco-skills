#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/cisco-thousandeyes-setup/scripts/validate.sh [--help]

Validates the deployed Cisco ThousandEyes app using configured Splunk credentials.
EOF
    exit 0
fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="ta_cisco_thousandeyes"

PASS=0
FAIL=0
WARN=0
INGEST_SK=""

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

log "=== Cisco ThousandEyes App Validation ==="
log ""

warn_if_current_skill_role_unsupported

log "--- App Installation ---"
if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials — check credentials file"
fi

if [[ ${FAIL} -eq 0 ]] && ! SK=$(get_session_key "${SPLUNK_URI}"); then
    fail "Could not authenticate to Splunk REST API — check credentials"
fi

ensure_ingest_session() {
    local saved_user saved_pass

    if ! load_splunk_credentials; then
        fail "Could not load Splunk credentials — check credentials file"
        return 1
    fi
    load_ingest_connection_settings

    saved_user="${SPLUNK_USER:-}"
    saved_pass="${SPLUNK_PASS:-}"
    SPLUNK_USER="${INGEST_SPLUNK_USER:-${SPLUNK_USER:-}}"
    SPLUNK_PASS="${INGEST_SPLUNK_PASS:-${SPLUNK_PASS:-}}"
    if ! INGEST_SK=$(get_session_key "${INGEST_SPLUNK_URI}"); then
        SPLUNK_USER="${saved_user}"
        SPLUNK_PASS="${saved_pass}"
        fail "Could not authenticate to the ingest-tier Splunk REST API — check ingest credentials"
        return 1
    fi
    SPLUNK_USER="${saved_user}"
    SPLUNK_PASS="${saved_pass}"
    return 0
}

inspect_hec_token_state() {
    local token_name="$1"

    if is_splunk_cloud; then
        rest_get_hec_token_state "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "unknown"
        return 0
    fi
    if type deployment_should_manage_ingest_hec_via_bundle >/dev/null 2>&1 \
        && deployment_should_manage_ingest_hec_via_bundle; then
        deployment_get_bundle_hec_token_state "${token_name}" 2>/dev/null || echo "unknown"
        return 0
    fi
    ensure_ingest_session || return 1
    rest_get_hec_token_state "${INGEST_SK}" "${INGEST_SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "unknown"
}

if [[ ${FAIL} -gt 0 ]]; then
    log ""
    log "=== Validation Summary ==="
    log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
    exit 1
fi

if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
    version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}")
    pass "App installed, version: ${version}"
else
    fail "ThousandEyes app (${APP_NAME}) not found"
fi

log ""
log "--- HEC Token ---"
hec_state=$(inspect_hec_token_state "thousandeyes" 2>/dev/null || echo "unknown")
case "${hec_state}" in
    enabled) pass "HEC token 'thousandeyes' exists" ;;
    disabled) warn "HEC token 'thousandeyes' exists but is disabled" ;;
    missing) warn "HEC token 'thousandeyes' not found (run setup.sh --hec-only)" ;;
    *) warn "Could not determine HEC token 'thousandeyes' status" ;;
esac

log ""
log "--- Indexes ---"
EXPECTED_INDEXES=(thousandeyes_metrics thousandeyes_traces thousandeyes_events thousandeyes_activity thousandeyes_alerts thousandeyes_pathvis)
for idx in "${EXPECTED_INDEXES[@]}"; do
    if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
        pass "Index '${idx}' exists"
    else
        warn "Index '${idx}' not found (run setup.sh --indexes-only)"
    fi
done

log ""
log "--- Account Configuration (OAuth) ---"
account_json=$(rest_list_ta_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "ta_cisco_thousandeyes_account" 2>/dev/null || true)
if [[ -n "${account_json}" ]]; then
    count=$(echo "${account_json}" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    entries = d.get('entry', [])
    print(len(entries))
    for e in entries:
        print(e.get('name', ''))
except Exception:
    print(0)
" 2>/dev/null | head -1)
    if [[ "${count}" -gt 0 ]]; then
        pass "OAuth account configured (${count} account(s))"
        echo "${account_json}" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    for e in d.get('entry', []):
        print('    Account:', e.get('name', ''))
except Exception:
    pass
" 2>/dev/null || true
    else
        warn "Account endpoint exists but has no configured accounts"
    fi
else
    warn "No OAuth accounts configured (run configure_account.sh)"
fi

log ""
log "--- Token Refresh Input ---"
refresh_status=$(splunk_curl "${SK}" \
    "${SPLUNK_URI}/services/data/inputs/thousandeyes_refresh_tokens?output_mode=json&count=0" \
    2>/dev/null \
    | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    entries = d.get('entry', [])
    if entries:
        disabled = entries[0].get('content', {}).get('disabled', True)
        if str(disabled).lower() in ('0', 'false'):
            print('enabled', end='')
        else:
            print('disabled', end='')
    else:
        print('missing', end='')
except Exception:
    print('unknown', end='')
" 2>/dev/null || echo "unknown")

case "${refresh_status}" in
    enabled) pass "Token refresh input is enabled" ;;
    disabled) warn "Token refresh input exists but is disabled" ;;
    missing) warn "Token refresh input not found" ;;
    *) warn "Could not determine token refresh input status" ;;
esac

log ""
log "--- HEC Target Validation ---"
_hec_platform="$(resolve_splunk_platform)"
_hec_targets_json=$(splunk_curl "${SK}" \
    "${SPLUNK_URI}/services/data/inputs/all?output_mode=json&count=0" 2>/dev/null || echo "{}")
_hec_target_issues=$(echo "${_hec_targets_json}" | python3 -c "
import json, sys

platform = sys.argv[1]
is_cloud = (platform == 'cloud')

data = json.load(sys.stdin)
issues = []
checked = 0
for entry in data.get('entry', []):
    acl = entry.get('acl', {}) or {}
    if acl.get('app', '') != 'ta_cisco_thousandeyes':
        continue
    content = entry.get('content', {}) or {}
    hec = content.get('hec_target', '')
    if not hec:
        continue
    checked += 1
    name = entry.get('name', '')
    if is_cloud:
        if ':8088' in hec or not ('http-inputs-' in hec and '.splunkcloud.com' in hec):
            issues.append(f'{name}: {hec}')
    else:
        if 'http-inputs-' in hec and '.splunkcloud.com' in hec:
            issues.append(f'{name}: {hec}')

print(f'checked={checked}')
for i in issues:
    print(i)
" "${_hec_platform}" 2>/dev/null || echo "checked=0")

_hec_checked=$(echo "${_hec_target_issues}" | head -1 | sed 's/checked=//')
_hec_bad=$(echo "${_hec_target_issues}" | tail -n +2)
if [[ "${_hec_checked}" -gt 0 ]]; then
    if [[ -z "${_hec_bad}" ]]; then
        pass "HEC targets on ${_hec_checked} streaming input(s) match platform (${_hec_platform})"
    else
        fail "HEC target mismatch — inputs point to wrong endpoint for ${_hec_platform}:"
        echo "${_hec_bad}" | while IFS= read -r line; do
            [[ -n "${line}" ]] && log "    ${line}"
        done
        if [[ "${_hec_platform}" == "cloud" ]]; then
            log "    Expected: https://http-inputs-{stack}.splunkcloud.com:443"
            log "    Fix: re-run setup.sh --enable-inputs to update HEC targets"
        else
            log "    Expected: https://{host}:8088"
        fi
    fi
else
    log "  INFO: No streaming inputs with hec_target found (nothing to check)"
fi

log ""
log "--- Path Visualization ---"
_pathvis_status=$(echo "${_hec_targets_json}" | python3 -c "
import json, sys

data = json.load(sys.stdin)
metrics_inputs = 0
enabled = 0
details = []

for entry in data.get('entry', []):
    acl = entry.get('acl', {}) or {}
    if acl.get('app', '') != 'ta_cisco_thousandeyes':
        continue
    content = entry.get('content', {}) or {}
    if content.get('test_index', '') != 'thousandeyes_metrics':
        continue
    metrics_inputs += 1
    related_paths = str(content.get('related_paths', '')).strip().lower()
    if related_paths in ('1', 'true', 'yes', 'on'):
        enabled += 1
        details.append(
            f\"{entry.get('name', '')}: index={content.get('index', '') or 'unset'}, interval={content.get('interval', '') or 'unset'}\"
        )

print(f'metrics={metrics_inputs}')
print(f'enabled={enabled}')
for detail in details:
    print(detail)
" 2>/dev/null || echo $'metrics=0\nenabled=0')
_pathvis_metrics=$(echo "${_pathvis_status}" | sed -n '1s/metrics=//p')
_pathvis_enabled=$(echo "${_pathvis_status}" | sed -n '2s/enabled=//p')
_pathvis_details=$(echo "${_pathvis_status}" | tail -n +3)
if [[ "${_pathvis_metrics:-0}" -gt 0 ]]; then
    if [[ "${_pathvis_enabled:-0}" -gt 0 ]]; then
        pass "Path visualization enabled on ${_pathvis_enabled} metrics input(s)"
        echo "${_pathvis_details}" | while IFS= read -r line; do
            [[ -n "${line}" ]] && log "    ${line}"
        done
    else
        warn "Metrics stream inputs exist but related_paths is not enabled; thousandeyes_pathvis will stay empty"
    fi
else
    log "  INFO: No metrics stream inputs found (nothing to check)"
fi

log ""
log "--- Data Inputs ---"
input_count=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || echo "0")
enabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "0" 2>/dev/null || echo "0")
disabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "1" 2>/dev/null || echo "0")
if [[ "${input_count}" -gt 0 ]]; then
    if [[ "${enabled_inputs}" -eq "${input_count}" ]]; then
        pass "${enabled_inputs} input(s) enabled"
    elif [[ "${enabled_inputs}" -gt 0 ]]; then
        warn "${enabled_inputs} input(s) enabled, ${disabled_inputs} disabled"
    else
        warn "${input_count} input stanza(s) exist but all are disabled"
    fi
else
    warn "No data inputs configured (run setup.sh --enable-inputs)"
fi

log ""
log "--- Data Flow Check ---"
for idx_label in "thousandeyes_metrics:metrics" "thousandeyes_traces:traces" "thousandeyes_events:events" "thousandeyes_activity:activity" "thousandeyes_alerts:alerts" "thousandeyes_pathvis:pathvis"; do
    idx="${idx_label%%:*}"
    label="${idx_label#*:}"
    event_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where index=${idx}" "count" 2>/dev/null || echo "0")
    if [[ "${event_count}" -gt 0 ]]; then
        pass "Index '${idx}' has ${event_count} events (${label})"
    else
        warn "Index '${idx}' has no events yet (${label})"
    fi
done

log ""
log "--- Settings ---"
if rest_check_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "ta_cisco_thousandeyes_settings" "logging" 2>/dev/null; then
    loglevel=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "ta_cisco_thousandeyes_settings" "logging" "loglevel" 2>/dev/null || true)
    [[ -n "${loglevel}" ]] && log "  Log level: ${loglevel}"
    pass "Settings present"
else
    warn "No local settings — using defaults"
fi

log ""
log "--- ITSI Integration (Optional) ---"
if rest_check_app "${SK}" "${SPLUNK_URI}" "SA-ITOA" 2>/dev/null; then
    pass "Splunk ITSI (SA-ITOA) is installed — ThousandEyes ITSI integration available"
else
    log "  INFO: Splunk ITSI (SA-ITOA) not installed — ITSI integration inactive (this is normal)"
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

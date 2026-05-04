#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/splunk-stream-setup/scripts/validate.sh [--help]

Validates the deployed Splunk Stream stack using configured Splunk credentials.
EOF
    exit 0
fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"


PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
info() { log "  INFO: $*"; }
finish_validation() {
    local force_fail="${1:-false}"
    log ""
    log "=== Validation Summary ==="
    log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"

    if [[ "${force_fail}" == "true" || ${FAIL} -gt 0 ]]; then
        log "  Status: ISSUES FOUND — review failures above"
        exit 1
    elif [[ ${WARN} -gt 0 ]]; then
        log "  Status: OK with warnings"
        exit 0
    else
        log "  Status: ALL CHECKS PASSED"
        exit 0
    fi
}

log "=== Splunk Stream Validation ==="
log ""

warn_if_current_skill_role_unsupported

if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials. Check credentials file."
    finish_validation true
fi

if ! SK=$(get_session_key "${SPLUNK_URI}"); then
    fail "Could not authenticate to Splunk. Check credentials and SPLUNK_SEARCH_API_URI/SPLUNK_URI."
    finish_validation true
fi

CLOUD_MODE=false
if is_splunk_cloud; then
    CLOUD_MODE=true
fi

STREAM_VALIDATE_ROLE="$(resolve_splunk_target_role)"
WIRE_DATA_PRESENT=false

stream_role_is_search_tier() {
    [[ "${STREAM_VALIDATE_ROLE:-}" == "search-tier" ]]
}

stream_role_is_forwarder() {
    [[ "${STREAM_VALIDATE_ROLE:-}" == "heavy-forwarder" || "${STREAM_VALIDATE_ROLE:-}" == "universal-forwarder" ]]
}

stream_role_is_indexer() {
    [[ "${STREAM_VALIDATE_ROLE:-}" == "indexer" ]]
}

# --- App Installation ---
log "--- App Installation ---"

if rest_check_app "${SK}" "${SPLUNK_URI}" "splunk_app_stream"; then
    version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "splunk_app_stream")
    pass "Splunk Stream installed (v${version})"
else
    if stream_role_is_forwarder; then
        warn "Splunk Stream search-tier app is not installed on this forwarder target. Validate the search tier separately."
    elif stream_role_is_indexer; then
        info "Splunk Stream search-tier app is not installed on this indexer target (expected on dedicated indexers)."
    else
        fail "Splunk Stream not installed"
    fi
fi

if rest_check_app "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream"; then
    version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream")
    pass "Splunk TA Stream (Forwarder) installed (v${version})"
else
    if stream_role_is_search_tier; then
        warn "Splunk TA Stream (Forwarder) is not installed on this search-tier target. Validate a heavy or universal forwarder separately."
    elif stream_role_is_indexer; then
        info "Splunk TA Stream (Forwarder) is not installed on this indexer target (expected on dedicated indexers)."
    elif ${CLOUD_MODE}; then
        warn "Splunk TA Stream (Forwarder) not installed on the Cloud search tier. This is expected when Stream forwarders run on infrastructure you control."
    else
        fail "Splunk TA Stream (Forwarder) not installed"
    fi
fi

if rest_check_app "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream_wire_data"; then
    WIRE_DATA_PRESENT=true
    version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream_wire_data")
    pass "Splunk TA Stream Wire Data installed (v${version})"
else
    if stream_role_is_indexer; then
        fail "Splunk TA Stream Wire Data not installed"
    elif stream_role_is_search_tier || stream_role_is_forwarder; then
        warn "Splunk TA Stream Wire Data not installed on this target."
    elif ${CLOUD_MODE}; then
        warn "Splunk TA Stream Wire Data not installed on the Cloud search tier."
    else
        fail "Splunk TA Stream Wire Data not installed"
    fi
fi

# --- Stream Forwarder Binary ---
log ""
log "--- Stream Forwarder Binary ---"
info "Binary check skipped in remote mode — streamfwd must run on the Splunk host"

# --- Indexes ---
log ""
log "--- Indexes ---"

if platform_check_index "${SK}" "${SPLUNK_URI}" "netflow"; then
    pass "Index 'netflow' exists"
else
    warn "Index 'netflow' not found"
fi

if platform_check_index "${SK}" "${SPLUNK_URI}" "stream"; then
    pass "Index 'stream' exists"
else
    warn "Index 'stream' not found"
fi

# --- Stream Forwarder Configuration ---
log ""
log "--- Stream Forwarder Config ---"

if stream_role_is_search_tier; then
    warn "Forwarder-side streamfwd validation is skipped on the search tier. Validate Splunk_TA_stream against the forwarder management endpoint."
elif stream_role_is_indexer; then
    info "Forwarder-side streamfwd validation is skipped on the indexer tier."
elif ${CLOUD_MODE}; then
    info "Cloud mode: forwarder-side streamfwd validation is skipped on the search tier. Run this validation against the forwarder management endpoint to validate Splunk_TA_stream."
elif rest_check_conf "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "streamfwd" "streamfwd"; then
    pass "streamfwd.conf stanza exists"

    ip_addr=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "streamfwd" "streamfwd" "ipAddr")
    port=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "streamfwd" "streamfwd" "port")

    if [[ -n "${ip_addr}" && "${ip_addr}" != "127.0.0.1" ]]; then
        pass "Forwarder IP: ${ip_addr}"
    elif [[ "${ip_addr}" == "127.0.0.1" ]]; then
        warn "Forwarder IP is localhost (127.0.0.1) — remote forwarders cannot connect"
    else
        warn "No ipAddr configured"
    fi

    if [[ -n "${port}" ]]; then
        pass "Forwarder port: ${port}"
    else
        warn "No port configured (default 8889 will be used)"
    fi

    nf_port=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "streamfwd" "streamfwd" "netflowReceiver.0.port" 2>/dev/null || true)
    if [[ -n "${nf_port}" ]]; then
        pass "NetFlow receiver configured on port ${nf_port}"
    else
        info "No NetFlow receiver configured"
    fi
else
    fail "streamfwd.conf stanza not found — stream forwarder not configured"
fi

# --- Stream Input Configuration ---
log ""
log "--- Stream Input (inputs.conf) ---"

if stream_role_is_search_tier; then
    warn "Forwarder-side streamfwd input validation is skipped on the search tier."
elif stream_role_is_indexer; then
    info "Forwarder-side streamfwd input validation is skipped on the indexer tier."
elif ${CLOUD_MODE}; then
    info "Cloud mode: streamfwd input validation is skipped on the search tier."
elif rest_check_conf "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "inputs" "streamfwd://streamfwd"; then
    pass "streamfwd://streamfwd input stanza exists"

    app_location=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "inputs" "streamfwd://streamfwd" "splunk_stream_app_location")
    if [[ -n "${app_location}" ]]; then
        pass "Stream app location: ${app_location}"
    else
        warn "splunk_stream_app_location is empty — streamfwd may not connect to Stream app"
    fi

    ssl_verify=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "inputs" "streamfwd://streamfwd" "sslVerifyServerCert")
    if [[ "${ssl_verify}" == "true" ]]; then
        pass "SSL verification: enabled"
    elif [[ "${ssl_verify}" == "false" ]]; then
        warn "SSL verification: disabled (acceptable for self-signed certs)"
    fi

    disabled=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "inputs" "streamfwd://streamfwd" "disabled")
    if [[ "${disabled}" == "0" ]]; then
        pass "Stream forwarder input: enabled"
    elif [[ "${disabled}" == "1" ]]; then
        fail "Stream forwarder input: disabled"
    fi
else
    fail "streamfwd://streamfwd input stanza not found — stream forwarder input not configured"
fi

# --- Enabled Streams ---
log ""
log "--- Enabled Protocol Streams ---"
info "Stream enable/disable status requires Stream Web UI or local access — skipped in remote mode. Use data flow check below."

# --- Wire Data Knowledge Objects ---
log ""
log "--- Wire Data Knowledge Objects ---"

if ${WIRE_DATA_PRESENT}; then
    pass "Wire Data TA installed — CIM field mappings available"
else
    info "Wire Data TA knowledge-object checks are skipped because Splunk_TA_stream_wire_data is not installed on this target."
fi

# --- Data Flow Check ---
log ""
log "--- Data Flow Check ---"

for search_target in "source=stream" "index=netflow"; do
    event_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| tstats count where ${search_target}" "count")

    if [[ "${event_count}" -gt 0 ]] 2>/dev/null; then
        pass "${search_target} has ${event_count} events"
    else
        warn "${search_target} has no events (may be normal if just configured)"
    fi
done

if stream_role_is_forwarder || stream_role_is_indexer; then
    info "KV Store check skipped on ${STREAM_VALIDATE_ROLE:-this target}; Stream UI KV Store health belongs on the search tier."
else
    kvstore_status=$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/kvstore/status?output_mode=json" 2>/dev/null \
        | python3 -c "
import json, sys
d = json.load(sys.stdin)
entries = d.get('entry', [])
if entries:
    status = entries[0].get('content', {}).get('current', {}).get('status', 'unknown')
    print(status)
else:
    print('unknown')
" 2>/dev/null || echo "unknown")

    if [[ "${kvstore_status}" == "ready" ]]; then
        pass "KV Store status: ready"
    else
        warn "KV Store status: ${kvstore_status} (Stream app requires healthy KV Store)"
    fi
fi

finish_validation false

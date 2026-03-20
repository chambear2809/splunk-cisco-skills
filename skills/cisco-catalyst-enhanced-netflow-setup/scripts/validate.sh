#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="splunk_app_stream_ipfix_cisco_hsl"
APP_LABEL="Cisco Catalyst Enhanced Netflow Add-on for Splunk"
STREAM_FWD_APP="Splunk_TA_stream"
STREAM_SEARCH_APP="splunk_app_stream"
CATALYST_TA_APP="TA_cisco_catalyst"
ENTERPRISE_APP="cisco-catalyst-app"
SK=""

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
info() { log "  INFO: $*"; }

log "=== Cisco Catalyst Enhanced Netflow Add-on Validation ==="
log ""

log "--- Target Context ---"
if is_splunk_cloud; then
    fail "This add-on targets forwarders you control — run validation against the Enterprise/forwarder management endpoint"
fi

log ""
log "--- App Installation ---"
if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials — check credentials file"
elif ! SK=$(get_session_key "${SPLUNK_URI}"); then
    fail "Could not authenticate to Splunk REST API — check credentials"
else
    if rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null; then
        version=$(rest_get_app_version "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || echo "unknown")
        pass "App installed (version: ${version})"
    else
        fail "App not found — install ${APP_LABEL} first"
    fi
fi

if [[ -n "${SK:-}" ]]; then
log ""
log "--- Stream Receiver Context ---"
if rest_check_app "$SK" "$SPLUNK_URI" "${STREAM_FWD_APP}" 2>/dev/null; then
    pass "${STREAM_FWD_APP} is installed on this target"

    if rest_check_conf "$SK" "$SPLUNK_URI" "${STREAM_FWD_APP}" "streamfwd" "streamfwd" 2>/dev/null; then
        pass "streamfwd.conf stanza exists"

        nf_ip=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "${STREAM_FWD_APP}" "streamfwd" "streamfwd" "netflowReceiver.0.ip" 2>/dev/null || true)
        nf_port=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "${STREAM_FWD_APP}" "streamfwd" "streamfwd" "netflowReceiver.0.port" 2>/dev/null || true)
        nf_decoder=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "${STREAM_FWD_APP}" "streamfwd" "streamfwd" "netflowReceiver.0.decoder" 2>/dev/null || true)

        if [[ -n "${nf_ip}" ]]; then pass "NetFlow receiver IP: ${nf_ip}"; else warn "No netflowReceiver.0.ip configured"; fi
        if [[ -n "${nf_port}" ]]; then pass "NetFlow receiver port: ${nf_port}"; else warn "No netflowReceiver.0.port configured"; fi
        if [[ -n "${nf_decoder}" ]]; then pass "NetFlow decoder: ${nf_decoder}"; else warn "No netflowReceiver.0.decoder configured"; fi
    else
        warn "${STREAM_FWD_APP} is installed but streamfwd.conf is not configured"
    fi
else
    warn "${STREAM_FWD_APP} not found — this add-on is typically installed on the host that parses NetFlow/IPFIX"
fi

if rest_check_app "$SK" "$SPLUNK_URI" "${STREAM_SEARCH_APP}" 2>/dev/null; then
    pass "${STREAM_SEARCH_APP} is installed on this target"
else
    info "${STREAM_SEARCH_APP} not present on this target (normal on dedicated forwarders)"
fi

log ""
log "--- Related Cisco Apps ---"
if rest_check_app "$SK" "$SPLUNK_URI" "${CATALYST_TA_APP}" 2>/dev/null; then
    pass "${CATALYST_TA_APP} is installed"
else
    warn "${CATALYST_TA_APP} not found — Cisco Catalyst data collection is handled elsewhere"
fi

if rest_check_app "$SK" "$SPLUNK_URI" "${ENTERPRISE_APP}" 2>/dev/null; then
    pass "${ENTERPRISE_APP} is installed on this target"
else
    info "${ENTERPRISE_APP} not present on this target (normal when this host is only the parsing tier)"
fi

log ""
log "--- App Behavior ---"
pass "No app-local accounts or inputs are expected for ${APP_NAME}"
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

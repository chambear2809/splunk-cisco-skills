#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="splunk_app_stream_ipfix_cisco_hsl"
APP_LABEL="Cisco Catalyst Enhanced Netflow Add-on for Splunk"
APP_ID="6872"
PACKAGE_PATTERN="cisco-catalyst-enhanced-netflow-add-on-for-splunk_*"
STREAM_FWD_APP="Splunk_TA_stream"
STREAM_SEARCH_APP="splunk_app_stream"
CATALYST_TA_APP="TA_cisco_catalyst"
ENTERPRISE_APP="cisco-catalyst-app"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
PROJECT_TA_DIR="${SCRIPT_DIR}/../../../splunk-ta"
TA_CACHE="${TA_CACHE:-${PROJECT_TA_DIR}}"

INSTALL_APP=false
RESTART_SPLUNK=true
RENDER_STREAM_RECEIVER_PLAN=false
STREAM_RECEIVER_JSON=false
STREAM_FORWARDER_IP="<forwarder-ip>"
STREAM_PORT="8889"
STREAM_WEB_URL="https://<search-head>:8000"
STREAM_SSL_VERIFY="false"
NETFLOW_IP="0.0.0.0"
NETFLOW_PORT="9995"
NETFLOW_DECODER="netflow"
SK=""

usage() {
    cat >&2 <<EOF
Cisco Catalyst Enhanced Netflow Add-on Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --install                 Install the add-on first
  --stream-receiver-plan    Render the Splunk Stream NetFlow/IPFIX receiver handoff plan
  --no-restart              Skip restart when --install is used
  --forwarder-ip IP         Forwarder-side streamfwd bind IP for the handoff plan
  --stream-port PORT        Stream forwarder management port for the handoff plan (default: 8889)
  --splunk-web-url URL      Splunk Web URL for streamfwd to call back to
  --ssl-verify true|false   Stream SSL verification setting for the handoff plan
  --netflow-ip IP           NetFlow receiver bind IP for the handoff plan (default: 0.0.0.0)
  --netflow-port PORT       NetFlow receiver port for the handoff plan (default: 9995)
  --netflow-decoder TYPE    NetFlow decoder for the handoff plan: netflow or sflow
  --json                    Emit JSON for --stream-receiver-plan
  --help                    Show this help

With no flags, reports installation status and the local NetFlow receiver context.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL_APP=true; shift ;;
        --stream-receiver-plan) RENDER_STREAM_RECEIVER_PLAN=true; shift ;;
        --no-restart) RESTART_SPLUNK=false; shift ;;
        --forwarder-ip) require_arg "$1" $# || exit 1; STREAM_FORWARDER_IP="$2"; shift 2 ;;
        --stream-port) require_arg "$1" $# || exit 1; STREAM_PORT="$2"; shift 2 ;;
        --splunk-web-url) require_arg "$1" $# || exit 1; STREAM_WEB_URL="$2"; shift 2 ;;
        --ssl-verify) require_arg "$1" $# || exit 1; STREAM_SSL_VERIFY="$2"; shift 2 ;;
        --netflow-ip) require_arg "$1" $# || exit 1; NETFLOW_IP="$2"; shift 2 ;;
        --netflow-port) require_arg "$1" $# || exit 1; NETFLOW_PORT="$2"; shift 2 ;;
        --netflow-decoder) require_arg "$1" $# || exit 1; NETFLOW_DECODER="$2"; shift 2 ;;
        --json) STREAM_RECEIVER_JSON=true; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

if $RENDER_STREAM_RECEIVER_PLAN; then
    plan_args=(
        "--forwarder-ip" "${STREAM_FORWARDER_IP}"
        "--stream-port" "${STREAM_PORT}"
        "--splunk-web-url" "${STREAM_WEB_URL}"
        "--ssl-verify" "${STREAM_SSL_VERIFY}"
        "--netflow-ip" "${NETFLOW_IP}"
        "--netflow-port" "${NETFLOW_PORT}"
        "--netflow-decoder" "${NETFLOW_DECODER}"
    )
    if $STREAM_RECEIVER_JSON; then
        plan_args+=("--json")
    fi
    python3 "${SCRIPT_DIR}/stream_receiver_plan.py" "${plan_args[@]}"
    exit $?
fi

ensure_forwarder_target() {
    if is_splunk_cloud; then
        log "ERROR: ${APP_LABEL} targets forwarders you control and should not be installed on the Splunk Cloud search tier."
        log "Set SPLUNK_PLATFORM=enterprise and point SPLUNK_SEARCH_API_URI at the forwarder-side management endpoint."
        exit 1
    fi
}

find_local_package() {
    python3 -c "
import fnmatch
import sys
from pathlib import Path

pattern = sys.argv[1].lower()
seen = set()
for raw_dir in sys.argv[2:]:
    directory = Path(raw_dir)
    if not directory.is_dir():
        continue
    for child in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_file():
            continue
        name = child.name.lower()
        if not (name.endswith('.tgz') or name.endswith('.spl') or name.endswith('.tar.gz')):
            continue
        resolved = str(child.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        if fnmatch.fnmatch(name, pattern):
            print(resolved, end='')
            raise SystemExit(0)
" "${PACKAGE_PATTERN}" "${PROJECT_TA_DIR}" "${TA_CACHE}" 2>/dev/null || true
}

resolve_latest_version() {
    if ! _set_splunkbase_curl_tls_args; then
        log "ERROR: Could not configure Splunkbase TLS settings for version resolution."
        log "Check SPLUNKBASE_CA_CERT (must be a readable file) or unset it to use system roots."
        return 1
    fi
    # shellcheck disable=SC2154  # _tls_verify_args is populated by _set_splunkbase_curl_tls_args.
    curl -s ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} \
        "https://splunkbase.splunk.com/api/v1/app/${APP_ID}/release/" 2>/dev/null \
        | python3 -c "
import json
import sys
try:
    releases = json.load(sys.stdin)
    if isinstance(releases, list) and releases:
        print(releases[0].get('name', ''), end='')
except Exception:
    pass
" 2>/dev/null || true
}

ensure_session() {
    ensure_forwarder_target
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

install_addon() {
    local version package_path

    ensure_session
    if rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME"; then
        log "${APP_LABEL} already installed — skipping install."
        return 0
    fi

    version="$(resolve_latest_version)"
    if [[ -n "${version}" ]]; then
        log "Trying Splunkbase install for ${APP_LABEL} (app ID ${APP_ID}, version ${version})..."
        if [[ "${RESTART_SPLUNK}" == "true" ]]; then
            if bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${APP_ID}" --app-version "${version}" --no-update; then
                return 0
            fi
        else
            if bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${APP_ID}" --app-version "${version}" --no-update --no-restart; then
                return 0
            fi
        fi
        log "Splunkbase install failed for ${APP_LABEL}; falling back to local package."
    else
        log "WARNING: Could not resolve the latest Splunkbase version for app ID ${APP_ID}; using local fallback if available."
    fi

    package_path="$(find_local_package)"
    if [[ -z "${package_path}" ]]; then
        log "ERROR: No local package matching ${PACKAGE_PATTERN} found in ${PROJECT_TA_DIR} or ${TA_CACHE}."
        exit 1
    fi

    log "Installing ${APP_LABEL} from ${package_path}..."
    if [[ "${RESTART_SPLUNK}" == "true" ]]; then
        bash "${APP_INSTALL_SCRIPT}" --source local --file "${package_path}" --no-update
    else
        bash "${APP_INSTALL_SCRIPT}" --source local --file "${package_path}" --no-update --no-restart
    fi
}

report_stream_receiver_context() {
    if rest_check_app "$SK" "$SPLUNK_URI" "${STREAM_FWD_APP}" 2>/dev/null; then
        log "Detected ${STREAM_FWD_APP} on this target."
        if rest_check_conf "$SK" "$SPLUNK_URI" "${STREAM_FWD_APP}" "streamfwd" "streamfwd" 2>/dev/null; then
            local nf_ip nf_port nf_decoder
            nf_ip=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "${STREAM_FWD_APP}" "streamfwd" "streamfwd" "netflowReceiver.0.ip" 2>/dev/null || true)
            nf_port=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "${STREAM_FWD_APP}" "streamfwd" "streamfwd" "netflowReceiver.0.port" 2>/dev/null || true)
            nf_decoder=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "${STREAM_FWD_APP}" "streamfwd" "streamfwd" "netflowReceiver.0.decoder" 2>/dev/null || true)

            if [[ -n "${nf_ip}" ]]; then log "  NetFlow receiver IP: ${nf_ip}"; else log "  WARNING: No netflowReceiver.0.ip configured"; fi
            if [[ -n "${nf_port}" ]]; then log "  NetFlow receiver port: ${nf_port}"; else log "  WARNING: No netflowReceiver.0.port configured"; fi
            if [[ -n "${nf_decoder}" ]]; then log "  NetFlow decoder: ${nf_decoder}"; else log "  WARNING: No netflowReceiver.0.decoder configured"; fi
        else
            log "  WARNING: ${STREAM_FWD_APP} is installed but streamfwd.conf is not configured."
            log "  Use the splunk-stream-setup skill if this host should receive NetFlow/IPFIX."
        fi
    else
        log "WARNING: ${STREAM_FWD_APP} is not installed on this target."
        log "Install and configure the NetFlow/IPFIX receiver path separately if this host should parse NetFlow data."
    fi
}

report_related_apps() {
    if rest_check_app "$SK" "$SPLUNK_URI" "${STREAM_SEARCH_APP}" 2>/dev/null; then
        log "Detected ${STREAM_SEARCH_APP} on this target."
    else
        log "INFO: ${STREAM_SEARCH_APP} not present on this target (normal on dedicated forwarders)."
    fi

    if rest_check_app "$SK" "$SPLUNK_URI" "${CATALYST_TA_APP}" 2>/dev/null; then
        log "Detected ${CATALYST_TA_APP} on this target."
    else
        log "INFO: ${CATALYST_TA_APP} not present on this target."
    fi

    if rest_check_app "$SK" "$SPLUNK_URI" "${ENTERPRISE_APP}" 2>/dev/null; then
        log "Detected ${ENTERPRISE_APP} on this target."
    else
        log "INFO: ${ENTERPRISE_APP} not present on this target."
    fi
}

main() {
    warn_if_current_skill_role_unsupported

    if $INSTALL_APP; then
        install_addon
    fi

    ensure_session
    if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null; then
        log "ERROR: ${APP_LABEL} is not installed. Re-run with --install or install app ID ${APP_ID} first."
        exit 1
    fi

    local version
    version=$(rest_get_app_version "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || echo "unknown")
    log "Installed app: ${APP_NAME} (version: ${version})"
    log "No app-local accounts or inputs require configuration; this add-on ships static IPFIX/HSL mappings."
    report_stream_receiver_context
    report_related_apps
}

main

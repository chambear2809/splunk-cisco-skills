#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PROJECT_TA_DIR="${SCRIPT_DIR}/../../../splunk-ta"
TA_CACHE="${TA_CACHE:-${PROJECT_TA_DIR}}"

INSTALL=false
INDEXES_ONLY=false
CONFIGURE_STREAMFWD=false
FULL_SETUP=false

IP_ADDR=""
PORT="8889"
SPLUNK_WEB_URL=""
SSL_VERIFY="false"
NETFLOW_IP=""
NETFLOW_PORT=""
NETFLOW_DECODER="netflow"

usage() {
    cat <<EOF
Splunk Stream Setup Automation

Usage: $(basename "$0") [OPTIONS]

Operations:
  --install                Install missing Stream apps from local cache
  --indexes-only           Create indexes only
  --configure-streamfwd    Configure the stream forwarder
  (no flags)               Full setup: install + indexes + configure

Stream Forwarder Options (used with --configure-streamfwd or full setup):
  --ip-addr IP             IP address for streamfwd to bind to
  --port PORT              Port for streamfwd (default: 8889)
  --splunk-web-url URL     Splunk Web URL (e.g. https://host:8000)
  --ssl-verify true|false  SSL certificate verification (default: false)

NetFlow Options (optional):
  --netflow-ip IP          NetFlow receiver bind IP (e.g. 0.0.0.0)
  --netflow-port PORT      NetFlow receiver port (e.g. 9995)
  --netflow-decoder TYPE   Flow decoder: netflow, sflow (default: netflow)

Environment:
  SPLUNK_URI               Splunk management URI (default: https://localhost:8089)
  TA_CACHE                 Local cache for app packages (default: project-root splunk-ta/)

Splunk credentials are read from the project-root credentials file automatically.
Run: bash ${SCRIPT_DIR}/../../shared/scripts/setup_credentials.sh
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL=true; shift ;;
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --configure-streamfwd) CONFIGURE_STREAMFWD=true; shift ;;
        --ip-addr) IP_ADDR="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --splunk-web-url) SPLUNK_WEB_URL="$2"; shift 2 ;;
        --ssl-verify) SSL_VERIFY="$2"; shift 2 ;;
        --netflow-ip) NETFLOW_IP="$2"; shift 2 ;;
        --netflow-port) NETFLOW_PORT="$2"; shift 2 ;;
        --netflow-decoder) NETFLOW_DECODER="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

if ! $INSTALL && ! $INDEXES_ONLY && ! $CONFIGURE_STREAMFWD; then
    FULL_SETUP=true
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

_get_session_key() {
    load_splunk_credentials || return 1
    SK=$(get_session_key "${SPLUNK_URI}") || return 1
}

check_connectivity() {
    _get_session_key || return 1
    local http_code
    http_code=$(splunk_curl "${SK}" "${SPLUNK_URI}/services/server/info?output_mode=json" -o /dev/null -w '%{http_code}' 2>/dev/null) || true
    if [[ "${http_code}" != "200" ]]; then
        log "ERROR: Cannot connect to Splunk at ${SPLUNK_URI}. Check SPLUNK_URI and credentials."
        return 1
    fi
    return 0
}

install_app_from_file() {
    local pkg_file="$1"
    local app_name="$2"

    if rest_check_app "${SK}" "${SPLUNK_URI}" "${app_name}"; then
        log "  ${app_name} already installed — skipping"
        return 0
    fi

    if [[ ! -f "${pkg_file}" ]]; then
        log "  ERROR: Package not found: ${pkg_file}"
        return 1
    fi

    log "  Installing ${app_name} from ${pkg_file}..."
    local response
    response=$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/apps/local" \
        -F "name=${pkg_file}" \
        -F "filename=true" \
        -F "update=true" 2>&1)

    if echo "${response}" | grep -q "<title>${app_name}</title>\|<id>.*${app_name}"; then
        log "  ${app_name} installed successfully"
    elif echo "${response}" | grep -q "already exists"; then
        log "  ${app_name} already exists"
    else
        log "  WARNING: Install response for ${app_name} — verify manually"
        echo "${response}" | head -5
    fi
}

install_apps() {
    log "=== Installing Splunk Stream Apps ==="
    _get_session_key || exit 1

    install_app_from_file \
        "${TA_CACHE}/splunk-app-for-stream_816.tgz" \
        "splunk_app_stream"

    install_app_from_file \
        "${TA_CACHE}/splunk-add-on-for-stream-forwarders_816.tgz" \
        "Splunk_TA_stream"

    install_app_from_file \
        "${TA_CACHE}/splunk-add-on-for-stream-wire-data_816.tgz" \
        "Splunk_TA_stream_wire_data"

    log "App installation complete."
}

create_indexes() {
    log "=== Creating Indexes ==="
    _get_session_key || exit 1

    rest_create_index "${SK}" "${SPLUNK_URI}" "netflow" "512000" || true
    rest_create_index "${SK}" "${SPLUNK_URI}" "stream" "512000" || true

    log "Index creation complete."
}

configure_streamfwd() {
    log "=== Configuring Stream Forwarder ==="
    _get_session_key || exit 1

    if [[ -z "${IP_ADDR}" ]]; then
        read -rp "Stream forwarder IP address: " IP_ADDR
    fi
    if [[ -z "${SPLUNK_WEB_URL}" ]]; then
        read -rp "Splunk Web URL (e.g. https://host:8000): " SPLUNK_WEB_URL
    fi

    local streamfwd_body="port=${PORT}&ipAddr=${IP_ADDR}"
    if [[ -n "${NETFLOW_IP}" && -n "${NETFLOW_PORT}" ]]; then
        log "  Adding NetFlow receiver (${NETFLOW_IP}:${NETFLOW_PORT}, decoder=${NETFLOW_DECODER})..."
        streamfwd_body="${streamfwd_body}&netflowReceiver.0.ip=${NETFLOW_IP}&netflowReceiver.0.port=${NETFLOW_PORT}&netflowReceiver.0.decoder=${NETFLOW_DECODER}"
    fi

    log "  Setting streamfwd.conf (ipAddr=${IP_ADDR}, port=${PORT})..."
    rest_set_conf "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "streamfwd" "streamfwd" "${streamfwd_body}" || true

    local stream_app_location="${SPLUNK_WEB_URL}/en-us/custom/splunk_app_stream/"
    local stream_app_encoded
    stream_app_encoded=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "${stream_app_location}" 2>/dev/null) || stream_app_encoded="${stream_app_location}"
    log "  Setting inputs.conf (stream_app_location=${stream_app_location})..."
    rest_set_conf "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "inputs" "streamfwd://streamfwd" \
        "splunk_stream_app_location=${stream_app_encoded}&stream_forwarder_id=&disabled=0&sslVerifyServerCert=${SSL_VERIFY}" || true

    log "Stream forwarder configuration complete."
}

main() {
    if ! check_connectivity; then
        exit 1
    fi

    if $INDEXES_ONLY; then
        create_indexes
        log "Restart Splunk to apply changes."
        exit 0
    fi

    if $INSTALL; then
        install_apps
        log "Restart Splunk to apply changes."
        exit 0
    fi

    if $CONFIGURE_STREAMFWD; then
        configure_streamfwd
        log "Restart Splunk to apply changes."
        exit 0
    fi

    if $FULL_SETUP; then
        install_apps
        create_indexes
        configure_streamfwd
        log ""
        log "=== Full setup complete ==="
        log "Restart Splunk to apply changes."
        log "Then enable protocol streams with configure_streams.sh."
    fi
}

main

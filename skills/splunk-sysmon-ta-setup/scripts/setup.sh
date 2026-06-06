#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_microsoft_sysmon"
APP_ID="5709"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"

INSTALL=false
NO_RESTART=false
CREATE_INDEX=false
RENDER=false
INDEX="sysmon"
MODE="endpoint"
OUTPUT_DIR=""
SK=""

usage() {
    cat >&2 <<EOF
Splunk Add-on for Microsoft Sysmon Setup (${APP_NAME}, Splunkbase ${APP_ID})

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                 Render deployment inputs, plan, validation SPL
  --install                Install ${APP_NAME} from Splunkbase
  --no-restart             Skip restart during package installation
  --create-index           Create the Sysmon event index
  --index INDEX            Event index (default: sysmon)
  --mode MODE              endpoint or wec (default: endpoint)
  --output-dir DIR         Render output directory
  --help                   Show this help

This script renders one collection mode at a time to avoid duplicate direct
endpoint plus WEC ingestion.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) RENDER=true; shift ;;
        --install) INSTALL=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --create-index) CREATE_INDEX=true; shift ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --mode) require_arg "$1" $# || exit 1; MODE="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --help|-h) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ "${MODE}" != "endpoint" && "${MODE}" != "wec" ]]; then
    echo "ERROR: --mode must be endpoint or wec" >&2
    exit 1
fi

if [[ "${INSTALL}" == "false" && "${CREATE_INDEX}" == "false" && "${RENDER}" == "false" ]]; then
    RENDER=true
fi

ensure_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    if ! is_splunk_cloud; then
        SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
    fi
}

run_render() {
    local cmd=(python3 "${RENDER_SCRIPT}" --phase render --index "${INDEX}" --mode "${MODE}")
    [[ -n "${OUTPUT_DIR}" ]] && cmd+=(--output-dir "${OUTPUT_DIR}")
    "${cmd[@]}"
}

install_package() {
    local cmd=(bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${APP_ID}" --no-update)
    [[ "${NO_RESTART}" == "true" ]] && cmd+=(--no-restart)
    "${cmd[@]}"
}

create_index() {
    ensure_session
    if platform_create_index "${SK:-}" "${SPLUNK_URI:-}" "${INDEX}" "512000"; then
        log "Ensured index '${INDEX}' exists."
    else
        log "ERROR: Failed to ensure index '${INDEX}'."
        exit 1
    fi
}

main() {
    warn_if_current_skill_role_unsupported
    [[ "${INSTALL}" == "true" ]] && install_package
    [[ "${CREATE_INDEX}" == "true" ]] && create_index
    [[ "${RENDER}" == "true" ]] && run_render
    log "Sysmon add-on step complete. Roll out one collection mode, then run validate.sh."
}

main

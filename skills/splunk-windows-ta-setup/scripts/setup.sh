#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_windows"
APP_ID="742"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"

INSTALL=false
NO_RESTART=false
CREATE_INDEX=false
RENDER=false
EVENT_INDEX="wineventlog"
PERFMON_INDEX="perfmon"
OUTPUT_DIR=""
SK=""

usage() {
    cat >&2 <<EOF
Splunk Add-on for Microsoft Windows Setup (Splunk_TA_windows, Splunkbase ${APP_ID})

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                 Render reviewable inputs.conf overlay, plan, and validation SPL (offline)
  --install                Install ${APP_NAME} from Splunkbase
  --no-restart             Skip restart during package installation
  --create-index           Create the event and Perfmon indexes
  --event-index INDEX      WinEventLog/WinHostMon index (default: wineventlog)
  --perfmon-index INDEX    Perfmon index (default: perfmon)
  --output-dir DIR         Render output directory
  --help                   Show this help

Windows inputs run on Windows Universal Forwarders. This skill renders the
forwarder overlay and manages the search-tier app and indexes; roll the
forwarder app out with skills/splunk-agent-management-setup.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) RENDER=true; shift ;;
        --install) INSTALL=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --create-index) CREATE_INDEX=true; shift ;;
        --event-index) require_arg "$1" $# || exit 1; EVENT_INDEX="$2"; shift 2 ;;
        --perfmon-index) require_arg "$1" $# || exit 1; PERFMON_INDEX="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --help|-h) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done
validate_splunk_index_name "${EVENT_INDEX}" || exit 1
validate_splunk_index_name "${PERFMON_INDEX}" || exit 1

# Default action: render when nothing else was requested.
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
    local cmd=(python3 "${RENDER_SCRIPT}" --phase render --event-index "${EVENT_INDEX}" --perfmon-index "${PERFMON_INDEX}")
    [[ -n "${OUTPUT_DIR}" ]] && cmd+=(--output-dir "${OUTPUT_DIR}")
    "${cmd[@]}"
}

install_package() {
    local cmd=(bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${APP_ID}" --no-update)
    [[ "${NO_RESTART}" == "true" ]] && cmd+=(--no-restart)
    "${cmd[@]}"
}

create_indexes() {
    ensure_session
    local idx
    for idx in "${EVENT_INDEX}" "${PERFMON_INDEX}"; do
        if platform_create_index "${SK:-}" "${SPLUNK_URI:-}" "${idx}" "512000"; then
            log "Ensured index '${idx}' exists."
        else
            log "ERROR: Failed to ensure index '${idx}'."
            exit 1
        fi
    done
}

main() {
    warn_if_current_skill_role_unsupported
    if [[ "${INSTALL}" == "true" || "${CREATE_INDEX}" == "true" ]]; then
        require_current_skill_role_supported
    fi
    [[ "${CREATE_INDEX}" == "true" ]] && require_index_management_target_role
    [[ "${INSTALL}" == "true" ]] && install_package
    [[ "${CREATE_INDEX}" == "true" ]] && create_indexes
    [[ "${RENDER}" == "true" ]] && run_render
    log "Windows add-on step complete. Roll the forwarder app out with splunk-agent-management-setup and validate with validate.sh."
}

main

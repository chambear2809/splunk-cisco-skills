#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_MS_Security"
APP_ID="6207"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"

INSTALL=false
NO_RESTART=false
CREATE_INDEX=false
RENDER=false
INDEX="microsoft_security"
ACCOUNT_NAME="ms_security_prod"
FEEDS="incidents,atp_alerts,machines,simulations,event_hub,threat_intel"
OUTPUT_DIR=""
SK=""

usage() {
    cat >&2 <<EOF
Splunk Add-on for Microsoft Security Setup (${APP_NAME}, Splunkbase ${APP_ID})

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                 Render inputs, macros, account runbook, plan, validation SPL
  --install                Install ${APP_NAME} from Splunkbase
  --no-restart             Skip restart during package installation
  --create-index           Create the Microsoft Security event index
  --index INDEX            Event index (default: microsoft_security)
  --account-name NAME      Account stanza name referenced by inputs (default: ms_security_prod)
  --feeds LIST             Feeds: incidents,atp_alerts,machines,simulations,event_hub,threat_intel
  --output-dir DIR         Render output directory
  --help                   Show this help

Microsoft client secrets are configured in the add-on Configuration tab, never
via this script.
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
        --account-name) require_arg "$1" $# || exit 1; ACCOUNT_NAME="$2"; shift 2 ;;
        --feeds) require_arg "$1" $# || exit 1; FEEDS="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --help|-h) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done
validate_splunk_index_name "${INDEX}" || exit 1

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
    local cmd=(python3 "${RENDER_SCRIPT}" --phase render --index "${INDEX}" --account-name "${ACCOUNT_NAME}" --feeds "${FEEDS}")
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
    if [[ "${INSTALL}" == "true" || "${CREATE_INDEX}" == "true" ]]; then
        require_current_skill_role_supported
    fi
    [[ "${CREATE_INDEX}" == "true" ]] && require_index_management_target_role
    [[ "${INSTALL}" == "true" ]] && install_package
    [[ "${CREATE_INDEX}" == "true" ]] && create_index
    [[ "${RENDER}" == "true" ]] && run_render
    log "Microsoft Security add-on step complete. Configure the account, enable inputs, then run validate.sh."
}

main

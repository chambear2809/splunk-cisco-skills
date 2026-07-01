#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_Google_Workspace"
APP_ID="5556"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"

INSTALL=false
NO_RESTART=false
CREATE_INDEX=false
RENDER=false
INDEX="google_workspace"
ACCOUNT_NAME="gws_prod"
INPUTS="activity_report,gws_gmail_logs,gws_gmail_logs_migrated,gws_user_identity,gws_alert_center,gws_usage_report"
APPLICATIONS="admin,login,token,drive,calendar,groups_enterprise"
OUTPUT_DIR=""
SK=""

usage() {
    cat >&2 <<EOF
Splunk Add-on for Google Workspace Setup (${APP_NAME}, Splunkbase ${APP_ID})

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                 Render inputs, settings, account runbook, plan, validation SPL
  --install                Install ${APP_NAME} from Splunkbase
  --no-restart             Skip restart during package installation
  --create-index           Create the Google Workspace event index
  --index INDEX            Event index (default: google_workspace)
  --account-name NAME      Account stanza name referenced by inputs (default: gws_prod)
  --inputs LIST            Input families to render
  --applications LIST      activity_report applications to render
  --output-dir DIR         Render output directory
  --help                   Show this help

Google service-account certificate material is configured in the add-on
Configuration tab, never via this script.
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
        --inputs) require_arg "$1" $# || exit 1; INPUTS="$2"; shift 2 ;;
        --applications) require_arg "$1" $# || exit 1; APPLICATIONS="$2"; shift 2 ;;
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
    local cmd=(python3 "${RENDER_SCRIPT}" --phase render --index "${INDEX}" --account-name "${ACCOUNT_NAME}" --inputs "${INPUTS}" --applications "${APPLICATIONS}")
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
    log "Google Workspace add-on step complete. Configure the account, enable inputs, then run validate.sh."
}

main

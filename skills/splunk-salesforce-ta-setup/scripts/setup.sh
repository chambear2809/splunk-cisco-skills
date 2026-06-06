#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_salesforce"
APP_ID="3549"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"

INSTALL=false
NO_RESTART=false
CREATE_INDEX=false
RENDER=false
JSON=false
DRY_RUN=false
INDEX="salesforce"
ACCOUNT_NAME="salesforce_prod"
OBJECTS="user,loginhistory,account,opportunity,dashboard,report,contentversion"
NO_EVENT_LOG=false
OUTPUT_DIR=""
SK=""

usage() {
    cat >&2 <<EOF
Splunk Add-on for Salesforce Setup (${APP_NAME}, Splunkbase ${APP_ID})

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                 Render inputs, account runbook, plan, validation SPL
  --install                Install ${APP_NAME} from Splunkbase
  --no-restart             Skip restart during package installation
  --create-index           Create the Salesforce event index
  --index INDEX            Event index (default: salesforce)
  --account-name NAME      Account stanza name referenced by inputs
  --objects LIST           Object selectors: user,loginhistory,account,opportunity,dashboard,report,contentversion
  --no-event-log           Omit the sfdc_event_log input stanza
  --output-dir DIR         Render output directory
  --json                   Emit JSON from render script
  --dry-run                Show render targets without writing files
  --help                   Show this help

Salesforce account secrets are configured through the add-on account flow, never via this script.
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
        --objects) require_arg "$1" $# || exit 1; OBJECTS="$2"; shift 2 ;;
        --no-event-log) NO_EVENT_LOG=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --json) JSON=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help|-h) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

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
    local cmd=(python3 "${RENDER_SCRIPT}" --phase render --index "${INDEX}" --account-name "${ACCOUNT_NAME}" --objects "${OBJECTS}")
    [[ "${NO_EVENT_LOG}" == "true" ]] && cmd+=(--no-event-log)
    [[ -n "${OUTPUT_DIR}" ]] && cmd+=(--output-dir "${OUTPUT_DIR}")
    [[ "${JSON}" == "true" ]] && cmd+=(--json)
    [[ "${DRY_RUN}" == "true" ]] && cmd+=(--dry-run)
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

warn_if_current_skill_role_unsupported
[[ "${INSTALL}" == "true" ]] && install_package
[[ "${CREATE_INDEX}" == "true" ]] && create_index
[[ "${RENDER}" == "true" ]] && run_render
log "Salesforce add-on step complete. Configure the account, enable inputs, then run validate.sh."

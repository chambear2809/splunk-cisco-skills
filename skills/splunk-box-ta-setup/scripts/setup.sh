#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_box"
APP_ID="2679"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"

INSTALL=false; NO_RESTART=false; CREATE_INDEX=false; RENDER=false; JSON=false; DRY_RUN=false
INDEX="box"; ACCOUNT_NAME="box_prod"; INPUTS="historical,live,file"; REST_ENDPOINT="api.box.com"; FILE_OR_FOLDER_ID="0"; OUTPUT_DIR=""; SK=""

usage() {
    cat >&2 <<EOF
Splunk Add-on for Box Setup (${APP_NAME}, Splunkbase ${APP_ID})

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                 Render inputs, account runbook, plan, validation SPL
  --install                Install ${APP_NAME} from Splunkbase
  --no-restart             Skip restart during package installation
  --create-index           Create the Box event index
  --index INDEX            Event index (default: box)
  --account-name NAME      Account stanza name referenced by inputs
  --inputs LIST            Inputs: historical,live,file
  --rest-endpoint HOST     Box REST endpoint host (default: api.box.com)
  --file-or-folder-id ID   Starter Box folder/file ID for file ingestion templates
  --output-dir DIR         Render output directory
  --json                   Emit JSON from render script
  --dry-run                Show render targets without writing files
  --help                   Show this help

Box credentials are configured through the add-on account flow, never via this script.
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
        --rest-endpoint) require_arg "$1" $# || exit 1; REST_ENDPOINT="$2"; shift 2 ;;
        --file-or-folder-id) require_arg "$1" $# || exit 1; FILE_OR_FOLDER_ID="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --json) JSON=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help|-h) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done
[[ "${INSTALL}" == "false" && "${CREATE_INDEX}" == "false" && "${RENDER}" == "false" ]] && RENDER=true

ensure_session() { load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }; if ! is_splunk_cloud; then SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }; fi; }
run_render() { local cmd=(python3 "${RENDER_SCRIPT}" --phase render --index "${INDEX}" --account-name "${ACCOUNT_NAME}" --inputs "${INPUTS}" --rest-endpoint "${REST_ENDPOINT}" --file-or-folder-id "${FILE_OR_FOLDER_ID}"); [[ -n "${OUTPUT_DIR}" ]] && cmd+=(--output-dir "${OUTPUT_DIR}"); [[ "${JSON}" == "true" ]] && cmd+=(--json); [[ "${DRY_RUN}" == "true" ]] && cmd+=(--dry-run); "${cmd[@]}"; }
install_package() { local cmd=(bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${APP_ID}" --no-update); [[ "${NO_RESTART}" == "true" ]] && cmd+=(--no-restart); "${cmd[@]}"; }
create_index() { ensure_session; if platform_create_index "${SK:-}" "${SPLUNK_URI:-}" "${INDEX}" "512000"; then log "Ensured index '${INDEX}' exists."; else log "ERROR: Failed to ensure index '${INDEX}'."; exit 1; fi; }

warn_if_current_skill_role_unsupported
[[ "${INSTALL}" == "true" ]] && install_package
[[ "${CREATE_INDEX}" == "true" ]] && create_index
[[ "${RENDER}" == "true" ]] && run_render
log "Box add-on step complete. Configure the account, enable inputs, then run validate.sh."

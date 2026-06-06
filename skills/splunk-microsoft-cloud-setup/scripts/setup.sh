#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

O365_ID="4055"
MSCS_ID="3110"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"

INSTALL=false
NO_RESTART=false
CREATE_INDEX=false
RENDER=false
O365_INDEX="o365"
AZURE_INDEX="azure"
ACCOUNT_NAME="msentra"
TENANT_NAME="contoso"
PRODUCTS="o365,mscs"
OUTPUT_DIR=""
SK=""

usage() {
    cat >&2 <<EOF
Microsoft Cloud Add-ons Setup (Office 365 ${O365_ID}, Microsoft Cloud Services ${MSCS_ID})

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                 Render inputs.conf, Entra account runbook, plan, validation SPL (offline)
  --install                Install the selected add-ons from Splunkbase
  --no-restart             Skip restart during package installation
  --create-index           Create the o365 and azure indexes
  --o365-index INDEX       Office 365 / Entra audit index (default: o365)
  --azure-index INDEX      MSCS Azure audit index (default: azure)
  --account-name NAME      Azure app-registration account stanza name (default: msentra)
  --tenant-name NAME       O365 tenant stanza name (default: contoso)
  --products LIST          Add-ons to act on: o365,mscs (default: both)
  --output-dir DIR         Render output directory
  --help                   Show this help

Entra app-registration client secrets are configured in the add-on
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
        --o365-index) require_arg "$1" $# || exit 1; O365_INDEX="$2"; shift 2 ;;
        --azure-index) require_arg "$1" $# || exit 1; AZURE_INDEX="$2"; shift 2 ;;
        --account-name) require_arg "$1" $# || exit 1; ACCOUNT_NAME="$2"; shift 2 ;;
        --tenant-name) require_arg "$1" $# || exit 1; TENANT_NAME="$2"; shift 2 ;;
        --products) require_arg "$1" $# || exit 1; PRODUCTS="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --help|-h) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ "${INSTALL}" == "false" && "${CREATE_INDEX}" == "false" && "${RENDER}" == "false" ]]; then
    RENDER=true
fi

has_product() { [[ ",${PRODUCTS}," == *",$1,"* ]]; }

ensure_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    if ! is_splunk_cloud; then
        SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
    fi
}

run_render() {
    local cmd=(python3 "${RENDER_SCRIPT}" --phase render --o365-index "${O365_INDEX}" --azure-index "${AZURE_INDEX}" --account-name "${ACCOUNT_NAME}" --tenant-name "${TENANT_NAME}" --products "${PRODUCTS}")
    [[ -n "${OUTPUT_DIR}" ]] && cmd+=(--output-dir "${OUTPUT_DIR}")
    "${cmd[@]}"
}

install_one() {
    local app_id="$1"
    local cmd=(bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${app_id}" --no-update)
    [[ "${NO_RESTART}" == "true" ]] && cmd+=(--no-restart)
    "${cmd[@]}"
}

install_packages() {
    has_product o365 && install_one "${O365_ID}"
    has_product mscs && install_one "${MSCS_ID}"
}

create_indexes() {
    ensure_session
    local idx
    local indexes=()
    has_product o365 && indexes+=("${O365_INDEX}")
    has_product mscs && indexes+=("${AZURE_INDEX}")
    for idx in "${indexes[@]}"; do
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
    [[ "${INSTALL}" == "true" ]] && install_packages
    [[ "${CREATE_INDEX}" == "true" ]] && create_indexes
    [[ "${RENDER}" == "true" ]] && run_render
    log "Microsoft cloud add-on step complete. Configure the Entra app registration (account-setup.md), enable inputs, then run validate.sh."
}

main

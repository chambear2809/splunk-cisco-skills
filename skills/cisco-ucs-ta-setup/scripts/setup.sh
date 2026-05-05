#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_cisco-ucs"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
INSTALL=false
NO_RESTART=false
INDEXES_ONLY=false
TEMPLATES_ONLY=false
INDEX="cisco_ucs"
SK=""

usage() {
    cat >&2 <<EOF
Cisco UCS TA Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --install              Install Splunk Add-on for Cisco UCS (2731)
  --no-restart           Skip restart during package installation
  --indexes-only         Create index only
  --templates-only       Configure default UCS templates only
  --index INDEX          Target index (default: cisco_ucs)
  --help                 Show this help
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --templates-only) TEMPLATES_ONLY=true; shift ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

ensure_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

install_package() {
    local cmd=(bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "2731" --no-update)
    [[ "${NO_RESTART}" == "true" ]] && cmd+=(--no-restart)
    "${cmd[@]}"
}

create_index() {
    if ! is_splunk_cloud; then
        ensure_session
    fi
    if platform_create_index "${SK:-}" "${SPLUNK_URI:-}" "${INDEX}" "512000"; then
        log "Ensured index '${INDEX}' exists."
    else
        log "ERROR: Failed to ensure index '${INDEX}'."
        exit 1
    fi
}

set_template() {
    local name="$1" content="$2" description="$3" body
    body=$(form_urlencode_pairs content "${content}" description "${description}") || exit 1
    if rest_set_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "splunk_ta_cisco_ucs_templates" "${name}" "${body}"; then
        log "Configured UCS template ${name}."
    else
        log "ERROR: Failed to configure UCS template ${name}."
        exit 1
    fi
}

configure_templates() {
    ensure_session
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        log "ERROR: ${APP_NAME} is not installed."
        exit 1
    fi
    set_template "UCS_Fault" "faultInst" "Cisco UCS fault events"
    set_template "UCS_Inventory" "equipmentFex,equipmentIOCard,equipmentSwitchCard,equipmentChassis,equipmentPsu,computeBlade,computeRackUnit,fabricDceSwSrvEp,etherPIo,fabricEthLanEp,fabricEthLanPc,fabricEthLanPcEp,fabricVlan,fabricVsan,lsServer,vnicEtherIf,vnicFcIf,storageLocalDisk,firmwareRunning,statsCollectionPolicy" "Cisco UCS inventory class IDs"
    set_template "UCS_Performance" "topSystem,equipmentChassisStats,computeMbPowerStats,computeMbTempStats,processorEnvStats,equipmentPsuStats,adaptorVnicStats,etherErrStats,etherLossStats,etherRxStats,etherPauseStats,etherTxStats,swSystemStats" "Cisco UCS performance class IDs"
}

main() {
    warn_if_current_skill_role_unsupported
    [[ "${INSTALL}" == "true" ]] && install_package
    [[ "${TEMPLATES_ONLY}" != "true" ]] && create_index
    [[ "${INDEXES_ONLY}" != "true" ]] && configure_templates
    log "Cisco UCS setup complete. Use configure_server.sh and configure_task.sh to enable collection."
}

main

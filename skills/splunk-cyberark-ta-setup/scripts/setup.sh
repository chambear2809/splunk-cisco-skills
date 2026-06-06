#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"
INSTALL=false; NO_RESTART=false; CREATE_INDEX=false; RENDER=false; JSON=false; DRY_RUN=false
INDEX="cyberark"; ACCOUNT_NAME="cyberark_epm_prod"; PRODUCTS="epm,epv_pta"; EPM_INPUTS="application_events,inbox_events,admin_audit_logs,account_admin_audit_logs,policy_audit,policy_audit_events,threat_detection,policies_and_computers"; SYSLOG_PORT="514"; OUTPUT_DIR=""; SK=""
usage(){ cat >&2 <<EOF
CyberArk Splunk Add-on Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                 Render EPM inputs, EPV/PTA transport handoff, plan, validation SPL
  --install                Install selected CyberArk add-ons from Splunkbase
  --no-restart             Skip restart during package installation
  --create-index           Create the CyberArk event index
  --index INDEX            Event index (default: cyberark)
  --account-name NAME      CyberArk EPM account stanza name
  --products LIST          Products: epm,epv_pta
  --epm-inputs LIST        EPM inputs to render
  --syslog-port PORT       Transport handoff syslog port (default: 514)
  --output-dir DIR         Render output directory
  --json                   Emit JSON from render script
  --dry-run                Show render targets without writing files
  --help                   Show this help

CyberArk EPM credentials are configured through the add-on account flow, never via this script. EPV/PTA is archived/not-supported and parser-only.
EOF
exit "${1:-0}"; }
while [[ $# -gt 0 ]]; do case "$1" in --render) RENDER=true; shift ;; --install) INSTALL=true; shift ;; --no-restart) NO_RESTART=true; shift ;; --create-index) CREATE_INDEX=true; shift ;; --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;; --account-name) require_arg "$1" $# || exit 1; ACCOUNT_NAME="$2"; shift 2 ;; --products) require_arg "$1" $# || exit 1; PRODUCTS="$2"; shift 2 ;; --epm-inputs) require_arg "$1" $# || exit 1; EPM_INPUTS="$2"; shift 2 ;; --syslog-port) require_arg "$1" $# || exit 1; SYSLOG_PORT="$2"; shift 2 ;; --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;; --json) JSON=true; shift ;; --dry-run) DRY_RUN=true; shift ;; --help|-h) usage ;; *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;; esac; done
[[ "${INSTALL}" == "false" && "${CREATE_INDEX}" == "false" && "${RENDER}" == "false" ]] && RENDER=true
contains(){ [[ ",$1," == *",$2,"* ]]; }
ensure_session(){ load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }; if ! is_splunk_cloud; then SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }; fi; }
run_render(){ local cmd=(python3 "${RENDER_SCRIPT}" --phase render --index "${INDEX}" --account-name "${ACCOUNT_NAME}" --products "${PRODUCTS}" --epm-inputs "${EPM_INPUTS}" --syslog-port "${SYSLOG_PORT}"); [[ -n "${OUTPUT_DIR}" ]] && cmd+=(--output-dir "${OUTPUT_DIR}"); [[ "${JSON}" == "true" ]] && cmd+=(--json); [[ "${DRY_RUN}" == "true" ]] && cmd+=(--dry-run); "${cmd[@]}"; }
install_packages(){ local restart=(); [[ "${NO_RESTART}" == "true" ]] && restart+=(--no-restart); contains "${PRODUCTS}" "epm" && bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id 5160 --no-update "${restart[@]}"; contains "${PRODUCTS}" "epv_pta" && bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id 2891 --no-update "${restart[@]}"; }
create_index(){ ensure_session; if platform_create_index "${SK:-}" "${SPLUNK_URI:-}" "${INDEX}" "512000"; then log "Ensured index '${INDEX}' exists."; else log "ERROR: Failed to ensure index '${INDEX}'."; exit 1; fi; }
warn_if_current_skill_role_unsupported
[[ "${INSTALL}" == "true" ]] && install_packages
[[ "${CREATE_INDEX}" == "true" ]] && create_index
[[ "${RENDER}" == "true" ]] && run_render
log "CyberArk add-on step complete. Configure EPM account or transport, then run validate.sh."

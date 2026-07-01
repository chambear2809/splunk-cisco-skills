#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"
INSTALL=false; NO_RESTART=false; CREATE_INDEX=false; RENDER=false; JSON=false; DRY_RUN=false
INDEX="rsa"; ACCOUNT_NAME="rsa_cas_prod"; PRODUCTS="cas,am"; CAS_ENDPOINTS="adminlog,usereventlog,riskuser"; SYSLOG_PORT="514"; OUTPUT_DIR=""; SK=""
usage(){ cat >&2 <<EOF
RSA SecurID Splunk Add-on Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                 Render CAS inputs, AM transport handoff, plan, validation SPL
  --install                Install selected RSA add-ons from Splunkbase
  --no-restart             Skip restart during package installation
  --create-index           Create the RSA event index
  --index INDEX            Event index (default: rsa)
  --account-name NAME      RSA CAS account stanza name
  --products LIST          Products: cas,am
  --cas-endpoints LIST     CAS endpoints: adminlog,usereventlog,riskuser
  --syslog-port PORT       AM transport handoff syslog port (default: 514)
  --output-dir DIR         Render output directory
  --json                   Emit JSON from render script
  --dry-run                Show render targets without writing files
  --help                   Show this help

RSA CAS credentials are configured through the add-on account flow, never via this script. RSA AM is syslog/parser based.
EOF
exit "${1:-0}"; }
while [[ $# -gt 0 ]]; do case "$1" in --render) RENDER=true; shift ;; --install) INSTALL=true; shift ;; --no-restart) NO_RESTART=true; shift ;; --create-index) CREATE_INDEX=true; shift ;; --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;; --account-name) require_arg "$1" $# || exit 1; ACCOUNT_NAME="$2"; shift 2 ;; --products) require_arg "$1" $# || exit 1; PRODUCTS="$2"; shift 2 ;; --cas-endpoints) require_arg "$1" $# || exit 1; CAS_ENDPOINTS="$2"; shift 2 ;; --syslog-port) require_arg "$1" $# || exit 1; SYSLOG_PORT="$2"; shift 2 ;; --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;; --json) JSON=true; shift ;; --dry-run) DRY_RUN=true; shift ;; --help|-h) usage ;; *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;; esac; done
validate_splunk_index_name "${INDEX}" || exit 1
[[ "${JSON}" != "true" || ( "${INSTALL}" != "true" && "${CREATE_INDEX}" != "true" ) ]] || { echo "ERROR: --json cannot be combined with --install or --create-index." >&2; exit 1; }
IFS=',' read -r -a selected_products <<<"${PRODUCTS}"
[[ "${#selected_products[@]}" -gt 0 ]] || { echo "ERROR: --products must select cas and/or am." >&2; exit 1; }
for product in "${selected_products[@]}"; do case "${product}" in cas|am) ;; *) echo "ERROR: Unsupported RSA SecurID product: ${product}" >&2; exit 1 ;; esac; done
[[ "${INSTALL}" == "false" && "${CREATE_INDEX}" == "false" && "${RENDER}" == "false" ]] && RENDER=true
contains(){ [[ ",$1," == *",$2,"* ]]; }
ensure_session(){ load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }; if ! is_splunk_cloud; then SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }; fi; }
run_render(){ local cmd=(python3 "${RENDER_SCRIPT}" --phase render --index "${INDEX}" --account-name "${ACCOUNT_NAME}" --products "${PRODUCTS}" --cas-endpoints "${CAS_ENDPOINTS}" --syslog-port "${SYSLOG_PORT}"); [[ -n "${OUTPUT_DIR}" ]] && cmd+=(--output-dir "${OUTPUT_DIR}"); [[ "${JSON}" == "true" ]] && cmd+=(--json); [[ "${DRY_RUN}" == "true" ]] && cmd+=(--dry-run); "${cmd[@]}"; }
run_or_print(){ if [[ "${DRY_RUN}" == "true" ]]; then printf 'DRY RUN:'; printf ' %q' "$@"; printf '\n'; else "$@"; fi; }
install_packages(){ local restart=(); [[ "${NO_RESTART}" == "true" ]] && restart+=(--no-restart); contains "${PRODUCTS}" "cas" && run_or_print bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id 5210 --no-update "${restart[@]}"; contains "${PRODUCTS}" "am" && run_or_print bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id 2958 --no-update "${restart[@]}"; return 0; }
create_index(){ if [[ "${DRY_RUN}" == "true" ]]; then log "DRY RUN: create index ${INDEX}"; return 0; fi; ensure_session; if platform_create_index "${SK:-}" "${SPLUNK_URI:-}" "${INDEX}" "512000"; then log "Ensured index '${INDEX}' exists."; else log "ERROR: Failed to ensure index '${INDEX}'."; exit 1; fi; }
warn_if_current_skill_role_unsupported
if [[ "${DRY_RUN}" != "true" && ( "${INSTALL}" == "true" || "${CREATE_INDEX}" == "true" ) ]]; then require_current_skill_role_supported; fi
if [[ "${DRY_RUN}" != "true" && "${INSTALL}" == "true" ]]; then require_splunk_management_target_role; fi
if [[ "${DRY_RUN}" != "true" && "${CREATE_INDEX}" == "true" ]]; then require_index_management_target_role; fi
[[ "${INSTALL}" == "true" ]] && install_packages
[[ "${CREATE_INDEX}" == "true" ]] && create_index
[[ "${RENDER}" == "true" ]] && run_render
log "RSA SecurID add-on step complete. Configure CAS account or AM transport, then run validate.sh."

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
PRODUCT="both"
INSTALL=false
NO_RESTART=false
INDEXES_ONLY=false
MACROS_ONLY=false
ESA_INDEX="email"
WSA_INDEX="netproxy"
SK=""

usage() {
    cat >&2 <<EOF
Cisco Secure Email/Web Gateway Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --product esa|wsa|both       Product to configure (default: both)
  --install                    Install selected Splunkbase add-on(s)
  --no-restart                 Skip restart during package installation
  --indexes-only               Create indexes only
  --macros-only                Configure macros only
  --esa-index INDEX            ESA index (default: email)
  --wsa-index INDEX            WSA index (default: netproxy)
  --help                       Show this help
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --product) require_arg "$1" $# || exit 1; PRODUCT="$2"; shift 2 ;;
        --install) INSTALL=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --macros-only) MACROS_ONLY=true; shift ;;
        --esa-index) require_arg "$1" $# || exit 1; ESA_INDEX="$2"; shift 2 ;;
        --wsa-index) require_arg "$1" $# || exit 1; WSA_INDEX="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

case "${PRODUCT}" in
    esa|wsa|both) ;;
    *) echo "ERROR: --product must be esa, wsa, or both." >&2; exit 1 ;;
esac

want_esa() { [[ "${PRODUCT}" == "esa" || "${PRODUCT}" == "both" ]]; }
want_wsa() { [[ "${PRODUCT}" == "wsa" || "${PRODUCT}" == "both" ]]; }

ensure_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

install_app_id() {
    local app_id="$1" label="$2" cmd
    cmd=(bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${app_id}" --no-update)
    [[ "${NO_RESTART}" == "true" ]] && cmd+=(--no-restart)
    log "Installing ${label} from Splunkbase app ${app_id}..."
    "${cmd[@]}"
}

install_packages() {
    want_esa && install_app_id "1761" "Splunk Add-on for Cisco ESA"
    want_wsa && install_app_id "1747" "Splunk Add-on for Cisco WSA"
}

create_indexes() {
    if ! is_splunk_cloud; then
        ensure_session
    fi
    if want_esa; then
        platform_create_index "${SK:-}" "${SPLUNK_URI:-}" "${ESA_INDEX}" "512000" || { log "ERROR: Failed to ensure index ${ESA_INDEX}."; exit 1; }
        log "Ensured ESA index '${ESA_INDEX}'."
    fi
    if want_wsa; then
        platform_create_index "${SK:-}" "${SPLUNK_URI:-}" "${WSA_INDEX}" "512000" || { log "ERROR: Failed to ensure index ${WSA_INDEX}."; exit 1; }
        log "Ensured WSA index '${WSA_INDEX}'."
    fi
}

set_macro() {
    local app="$1" macro="$2" definition="$3" body
    body=$(form_urlencode_pairs definition "${definition}" iseval "0") || exit 1
    rest_set_conf "${SK}" "${SPLUNK_URI}" "${app}" "macros" "${macro}" "${body}" \
        || { log "ERROR: Failed to set ${macro} in ${app}."; exit 1; }
    log "Configured ${macro} = ${definition}"
}

configure_macros() {
    ensure_session
    if want_esa && rest_check_app "${SK}" "${SPLUNK_URI}" "Splunk_TA_cisco-esa"; then
        set_macro "Splunk_TA_cisco-esa" "Cisco_ESA_Index" "(\"default\",\"${ESA_INDEX}\")"
    elif want_esa; then
        log "WARNING: Splunk_TA_cisco-esa not installed; skipping ESA macro."
    fi
    if want_wsa && rest_check_app "${SK}" "${SPLUNK_URI}" "Splunk_TA_cisco-wsa"; then
        set_macro "Splunk_TA_cisco-wsa" "Cisco_WSA_Index" "(\"default\",\"${WSA_INDEX}\")"
    elif want_wsa; then
        log "WARNING: Splunk_TA_cisco-wsa not installed; skipping WSA macro."
    fi
}

main() {
    warn_if_current_skill_role_unsupported
    [[ "${INSTALL}" == "true" ]] && install_packages
    [[ "${MACROS_ONLY}" != "true" ]] && create_indexes
    [[ "${INDEXES_ONLY}" != "true" ]] && configure_macros
    log "Secure Email/Web Gateway Splunk-side setup complete."
    log "Use render_ingestion_assets.sh or splunk-connect-for-syslog-setup for SC4S/file-monitor handoff."
}

main

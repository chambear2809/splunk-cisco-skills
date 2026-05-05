#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DASHBOARD_APP="cisco_webex_meetings_app_for_splunk"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"

INSTALL=false
NO_RESTART=false
INDEXES_ONLY=false
MACROS_ONLY=false
MEETINGS_INDEX="wx"
CALLING_INDEX="wxc"
CONTACT_CENTER_INDEX="wxcc"
SK=""

usage() {
    cat >&2 <<EOF
Cisco Webex Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --install                         Install Webex Add-on (8365) and Webex App (4992)
  --no-restart                      Skip restart during package installation
  --indexes-only                    Create indexes only
  --macros-only                     Configure Webex App macros only
  --meetings-index INDEX            Meetings/audit/quality index (default: wx)
  --calling-index INDEX             Calling CDR index (default: wxc)
  --contact-center-index INDEX      Contact Center index (default: wxcc)
  --help                            Show this help
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --macros-only) MACROS_ONLY=true; shift ;;
        --meetings-index) require_arg "$1" $# || exit 1; MEETINGS_INDEX="$2"; shift 2 ;;
        --calling-index) require_arg "$1" $# || exit 1; CALLING_INDEX="$2"; shift 2 ;;
        --contact-center-index) require_arg "$1" $# || exit 1; CONTACT_CENTER_INDEX="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

ensure_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

install_app_id() {
    local app_id="$1" label="$2" cmd
    cmd=(bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${app_id}" --no-update)
    if [[ "${NO_RESTART}" == "true" ]]; then
        cmd+=(--no-restart)
    fi
    log "Installing ${label} from Splunkbase app ${app_id}..."
    "${cmd[@]}"
}

install_packages() {
    install_app_id "8365" "Webex Add-on for Splunk"
    install_app_id "4992" "Webex App for Splunk"
}

create_indexes() {
    local idx
    if ! is_splunk_cloud; then
        ensure_session
    fi
    for idx in "${MEETINGS_INDEX}" "${CALLING_INDEX}" "${CONTACT_CENTER_INDEX}"; do
        [[ -n "${idx}" ]] || continue
        if platform_create_index "${SK:-}" "${SPLUNK_URI:-}" "${idx}" "512000"; then
            log "Ensured index '${idx}' exists."
        else
            log "ERROR: Failed to ensure index '${idx}'."
            exit 1
        fi
    done
}

set_macro() {
    local name="$1" definition="$2" body
    body=$(form_urlencode_pairs definition "${definition}" iseval "0") || exit 1
    if rest_set_conf "${SK}" "${SPLUNK_URI}" "${DASHBOARD_APP}" "macros" "${name}" "${body}"; then
        log "Configured macro ${name} = ${definition}"
    else
        log "ERROR: Failed to configure macro ${name}."
        exit 1
    fi
}

configure_macros() {
    ensure_session
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${DASHBOARD_APP}"; then
        log "WARNING: ${DASHBOARD_APP} is not installed; skipping dashboard macros."
        return 0
    fi
    set_macro "webex_meeting" "index=${MEETINGS_INDEX}"
    set_macro "webex_calling" "index=${CALLING_INDEX}"
    set_macro "webex_contact_center" "index=${CONTACT_CENTER_INDEX}"
    set_macro "webex_indexes" "\`webex_meeting\` OR \`webex_calling\` OR \`webex_contact_center\`"
}

main() {
    warn_if_current_skill_role_unsupported
    if [[ "${INSTALL}" == "true" ]]; then
        install_packages
    fi
    if [[ "${MACROS_ONLY}" != "true" ]]; then
        create_indexes
    fi
    if [[ "${INDEXES_ONLY}" != "true" ]]; then
        configure_macros
    fi
    log "Webex setup complete. Use configure_account.sh and configure_inputs.sh for REST collection."
}

main

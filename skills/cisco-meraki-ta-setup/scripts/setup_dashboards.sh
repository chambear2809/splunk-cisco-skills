#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_cisco_meraki"

INDEX_NAME="${1:-meraki}"

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk. Check credentials."; exit 1; }

if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
    log "ERROR: Cisco Meraki TA not found. Install the app first."
    exit 1
fi

log "Configuring meraki_index macro to use index '${INDEX_NAME}'..."

NEW_DEF="index IN(${INDEX_NAME})"
def_encoded=$(_urlencode "${NEW_DEF}")
body="definition=${def_encoded}&iseval=0"

current_def=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "macros" "meraki_index" "definition" 2>/dev/null || true)
if [[ -n "${current_def}" ]] && [[ "${current_def}" == "${NEW_DEF}" ]]; then
    log "  Macro already points to '${INDEX_NAME}' — no change needed"
else
    if rest_set_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "macros" "meraki_index" "${body}"; then
        log "  Updated: meraki_index = ${NEW_DEF}"
    else
        log "ERROR: Failed to set meraki_index macro"
        exit 1
    fi
fi

log ""
log "Dashboard configuration complete."
log ""
log "The Meraki TA includes 32 built-in dashboards:"
log "  Access Points, Air Marshal, Audit, Cameras, Switches,"
log "  Security Appliances, Organizations Security, Devices,"
log "  Device Availability, Device Uplinks, Firmware Upgrades,"
log "  VPN Stats, VPN Statuses, Licenses (4 views),"
log "  Switch Ports, Switch Port Overview, Wireless Ethernet,"
log "  Wireless Packet Loss, Sensor Readings, Assurance Alerts,"
log "  API Request History/Overview/Response Codes,"
log "  Summary: Top Appliances/Clients/Devices/Switches,"
log "  Organization Networks, Organizations"
log ""
log "All dashboards use the 'meraki_index' macro (now set to '${INDEX_NAME}')."

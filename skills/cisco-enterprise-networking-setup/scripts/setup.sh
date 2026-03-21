#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco-catalyst-app"
CATALYST_TA_APP="TA_cisco_catalyst"
ENHANCED_NETFLOW_TA_APP="splunk_app_stream_ipfix_cisco_hsl"

MACROS_ONLY=false
ACCELERATE=false
CUSTOM_INDEXES=""
readonly SAVED_SEARCHES=(
    "cisco_catalyst_location"
    "cisco_catalyst_sdwan_netflow"
    "cisco_catalyst_sdwan_policy"
    "cisco_catalyst_meraki_organization_mapping"
    "cisco_catalyst_meraki_devices_serial_mapping"
)

usage() {
    cat <<EOF
Cisco Enterprise Networking App Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --macros-only              Update macros only
  --accelerate               Enable data model acceleration
  --custom-indexes "a,b,c"   Use custom index list (comma-separated)
  --help                     Show this help

With no flags, runs full setup (macros + saved search enablement).
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --macros-only) MACROS_ONLY=true; shift ;;
        --accelerate) ACCELERATE=true; shift ;;
        --custom-indexes) require_arg "$1" $# || exit 1; CUSTOM_INDEXES="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

check_prereqs() {
    if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME"; then
        log "ERROR: Cisco Enterprise Networking app not found. Install it first."
        exit 1
    fi
    if ! rest_check_app "$SK" "$SPLUNK_URI" "${CATALYST_TA_APP}" 2>/dev/null; then
        log "WARNING: Cisco Catalyst Add-on (${CATALYST_TA_APP}) not found — dashboards may not show Catalyst, ISE, SD-WAN, or Cyber Vision data"
    fi
    if ! rest_check_app "$SK" "$SPLUNK_URI" "${ENHANCED_NETFLOW_TA_APP}" 2>/dev/null; then
        log "WARNING: Optional Cisco Catalyst Enhanced Netflow Add-on (${ENHANCED_NETFLOW_TA_APP}) not found — additional NetFlow-focused dashboards may not show data"
    fi
}

update_macros() {
    log "Updating index macro..."

    local body index_list
    if [[ -n "${CUSTOM_INDEXES}" ]]; then
        index_list=$(echo "${CUSTOM_INDEXES}" | tr ',' '\n' | sed 's/^/"/;s/$/"/' | tr '\n' ',' | sed 's/,$//')
        index_list="index IN (${index_list})"
    else
        index_list='index IN ("catalyst", "ise", "sdwan", "cybervision")'
    fi

    body=$(form_urlencode_pairs \
        definition "${index_list}" \
        description "Definition for all indices where Cisco SDWAN, Cisco ISE, and Cisco Catalyst Center data is stored" \
        iseval "0")
    if ! rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_catalyst_app_index" "${body}"; then
        log "ERROR: Failed to update macro 'cisco_catalyst_app_index'."
        return 1
    fi

    log "  cisco_catalyst_app_index = ${index_list}"
    log "Macro update complete."
}

enable_saved_searches() {
    log "Ensuring lookup-building saved searches are enabled..."

    local disabled search_name
    for search_name in "${SAVED_SEARCHES[@]}"; do
        if ! rest_check_saved_search "$SK" "$SPLUNK_URI" "$APP_NAME" "${search_name}"; then
            log "ERROR: Saved search '${search_name}' not found."
            return 1
        fi

        disabled=$(rest_get_saved_search_value "$SK" "$SPLUNK_URI" "$APP_NAME" "${search_name}" "disabled")
        case "${disabled}" in
            0|false|False|"")
                log "  ${search_name} already enabled"
                ;;
            *)
                if rest_enable_saved_search "$SK" "$SPLUNK_URI" "$APP_NAME" "${search_name}"; then
                    log "  Enabled ${search_name}"
                else
                    log "ERROR: Failed to enable saved search '${search_name}'."
                    return 1
                fi
                ;;
        esac
    done

    log "Saved search enablement complete."
}

enable_acceleration() {
    log "Enabling data model acceleration..."

    local body
    body=$(form_urlencode_pairs acceleration "true" acceleration.earliest_time "-1mon")
    if ! rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "datamodels" "Cisco_Catalyst_App" "${body}"; then
        log "ERROR: Failed to enable data model acceleration for 'Cisco_Catalyst_App'."
        return 1
    fi

    log "  Data model 'Cisco_Catalyst_App' acceleration enabled (earliest: -1mon)"
    log "Acceleration config written."
}

main() {
    warn_if_current_skill_role_unsupported

    check_prereqs

    if $ACCELERATE; then
        enable_acceleration
        log "$(log_platform_restart_guidance "data model changes")"
        if ! $MACROS_ONLY; then
            update_macros
        fi
        exit 0
    fi

    if $MACROS_ONLY; then
        update_macros
        exit 0
    fi

    update_macros
    enable_saved_searches
    log "Setup complete. Dashboards will use data from the configured indexes."
    log "$(log_platform_restart_guidance "saved search or macro changes")"
    log "Tip: Run with --accelerate to enable data model acceleration for production."
}

main

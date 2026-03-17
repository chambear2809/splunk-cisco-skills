#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_cisco_meraki"

INDEXES_ONLY=false
ENABLE_INPUTS=false
ACCOUNT=""
INDEX=""
INPUT_TYPE=""

usage() {
    cat <<EOF
Cisco Meraki TA Setup Automation

Usage: $(basename "$0") [OPTIONS]

Options:
  --indexes-only          Create indexes only
  --enable-inputs         Enable data inputs
  --account NAME          Organization account name for input enablement
  --index INDEX           Target index for inputs (default: meraki)
  --input-type TYPE       Input group: all, core, devices, wireless, summary,
                          api, vpn, licenses, switches, organization, sensor
  --help                  Show this help

With no flags, runs full setup (indexes).
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --enable-inputs) ENABLE_INPUTS=true; shift ;;
        --account) ACCOUNT="$2"; shift 2 ;;
        --index) INDEX="$2"; shift 2 ;;
        --input-type) INPUT_TYPE="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log_live_input_summary() {
    local total enabled disabled
    read -r total enabled disabled <<< "$(rest_get_live_input_counts "${SK}" "${SPLUNK_URI}" "${APP_NAME}")"
    log "Live input status: total=${total}, enabled=${enabled}, disabled=${disabled}"
}

check_prereqs() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk. Check credentials."; exit 1; }
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        log "ERROR: Cisco Meraki TA not found. Install the app first."
        exit 1
    fi
}

create_indexes() {
    log "Creating indexes..."
    if rest_create_index "${SK}" "${SPLUNK_URI}" "meraki" "512000"; then
        log "  Index 'meraki' created or already exists."
    else
        log "ERROR: Failed to create index 'meraki'"
        exit 1
    fi
    log "Index creation complete."
}

add_input() {
    local input_type="$1"
    local input_name="$2"
    local account="$3"
    local index="$4"
    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        index "${index}" \
        organization_name "${account}")
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "cisco_meraki_${input_type}" "${input_name}_${account}" "${body}"
}

enable_core_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling core inputs for account='${account}' index='${index}'..."

    local types=(accesspoints airmarshal audit cameras organizationsecurity securityappliances switches)

    for t in "${types[@]}"; do
        add_input "${t}" "${t}" "${account}" "${index}"
    done
    log "Core inputs enabled (7 inputs)."
}

enable_devices_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling device inputs for account='${account}' index='${index}'..."

    local types=(devices device_availabilities_change_history device_uplink_addresses_by_device power_modules_statuses_by_device firmware_upgrades)

    for t in "${types[@]}"; do
        add_input "${t}" "${t}" "${account}" "${index}"
    done
    log "Device inputs enabled (5 inputs)."
}

enable_wireless_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling wireless inputs for account='${account}' index='${index}'..."

    local types=(
        wireless_devices_ethernet_statuses
        wireless_packet_loss_by_device
        wireless_controller_availabilities_change_history
        wireless_controller_devices_interfaces_usage_history_by_interval
        wireless_controller_devices_interfaces_packets_overview_by_device
        wireless_devices_wireless_controllers_by_device
    )

    for t in "${types[@]}"; do
        add_input "${t}" "${t}" "${account}" "${index}"
    done
    log "Wireless inputs enabled (6 inputs)."
}

enable_summary_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling summary inputs for account='${account}' index='${index}'..."

    local types=(
        summary_appliances_top_by_utilization
        summary_switch_power_history
        summary_top_clients_by_usage
        summary_top_devices_by_usage
        summary_top_switches_by_energy_usage
    )

    for t in "${types[@]}"; do
        add_input "${t}" "${t}" "${account}" "${index}"
    done
    log "Summary inputs enabled (5 inputs)."
}

enable_api_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling API/assurance inputs for account='${account}' index='${index}'..."

    local types=(api_request_history api_request_response_code api_request_overview assurance_alerts)

    for t in "${types[@]}"; do
        add_input "${t}" "${t}" "${account}" "${index}"
    done
    log "API/assurance inputs enabled (4 inputs)."
}

enable_vpn_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling VPN inputs for account='${account}' index='${index}'..."

    local types=(appliance_vpn_stats appliance_vpn_statuses)

    for t in "${types[@]}"; do
        add_input "${t}" "${t}" "${account}" "${index}"
    done
    log "VPN inputs enabled (2 inputs)."
}

enable_licenses_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling license inputs for account='${account}' index='${index}'..."

    local types=(licenses_overview licenses_coterm_licenses licenses_subscription_entitlements licenses_subscriptions)

    for t in "${types[@]}"; do
        add_input "${t}" "${t}" "${account}" "${index}"
    done
    log "License inputs enabled (4 inputs)."
}

enable_switches_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling switch inputs for account='${account}' index='${index}'..."

    local types=(switch_port_overview switch_ports_transceivers_readings_history_by_switch switch_ports_by_switch)

    for t in "${types[@]}"; do
        add_input "${t}" "${t}" "${account}" "${index}"
    done
    log "Switch inputs enabled (3 inputs)."
}

enable_organization_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling organization inputs for account='${account}' index='${index}'..."

    local types=(organization_networks organizations)

    for t in "${types[@]}"; do
        add_input "${t}" "${t}" "${account}" "${index}"
    done
    log "Organization inputs enabled (2 inputs)."
}

enable_sensor_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling sensor inputs for account='${account}' index='${index}'..."

    add_input "sensor_readings_history" "sensor_readings_history" "${account}" "${index}"
    log "Sensor inputs enabled (1 input)."
}

enable_webhook_log_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling webhook log inputs for account='${account}' index='${index}'..."

    add_input "webhook_logs" "webhook_logs" "${account}" "${index}"
    log "Webhook log inputs enabled (1 input)."
}

enable_all_inputs() {
    local account="$1"
    local index="$2"

    enable_core_inputs "${account}" "${index}"
    enable_devices_inputs "${account}" "${index}"
    enable_wireless_inputs "${account}" "${index}"
    enable_summary_inputs "${account}" "${index}"
    enable_api_inputs "${account}" "${index}"
    enable_vpn_inputs "${account}" "${index}"
    enable_licenses_inputs "${account}" "${index}"
    enable_switches_inputs "${account}" "${index}"
    enable_organization_inputs "${account}" "${index}"
    enable_sensor_inputs "${account}" "${index}"
    enable_webhook_log_inputs "${account}" "${index}"

    log "All inputs enabled (39 inputs)."
}

main() {
    check_prereqs

    if $ENABLE_INPUTS; then
        INDEX="${INDEX:-meraki}"
        if [[ -z "${ACCOUNT}" || -z "${INPUT_TYPE}" ]]; then
            log "ERROR: --enable-inputs requires --account and --input-type"
            exit 1
        fi
        case "${INPUT_TYPE}" in
            all) enable_all_inputs "${ACCOUNT}" "${INDEX}" ;;
            core) enable_core_inputs "${ACCOUNT}" "${INDEX}" ;;
            devices) enable_devices_inputs "${ACCOUNT}" "${INDEX}" ;;
            wireless) enable_wireless_inputs "${ACCOUNT}" "${INDEX}" ;;
            summary) enable_summary_inputs "${ACCOUNT}" "${INDEX}" ;;
            api) enable_api_inputs "${ACCOUNT}" "${INDEX}" ;;
            vpn) enable_vpn_inputs "${ACCOUNT}" "${INDEX}" ;;
            licenses) enable_licenses_inputs "${ACCOUNT}" "${INDEX}" ;;
            switches) enable_switches_inputs "${ACCOUNT}" "${INDEX}" ;;
            organization) enable_organization_inputs "${ACCOUNT}" "${INDEX}" ;;
            sensor) enable_sensor_inputs "${ACCOUNT}" "${INDEX}" ;;
            *) log "ERROR: Unknown input type '${INPUT_TYPE}'."; usage ;;
        esac
        log_live_input_summary
        log "Restart Splunk to apply changes."
        exit 0
    fi

    create_indexes
    log "Restart Splunk to apply changes."
}

main

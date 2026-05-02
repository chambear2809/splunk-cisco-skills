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
    cat >&2 <<EOF
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
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --enable-inputs) ENABLE_INPUTS=true; shift ;;
        --account) require_arg "$1" $# || exit 1; ACCOUNT="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --input-type) require_arg "$1" $# || exit 1; INPUT_TYPE="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

log_live_input_summary() {
    local total enabled disabled
    read -r total enabled disabled <<< "$(rest_get_live_input_counts "${SK}" "${SPLUNK_URI}" "${APP_NAME}")"
    log "Live input status: total=${total}, enabled=${enabled}, disabled=${disabled}"
}

ensure_search_api_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk. Check credentials."; exit 1; }
}

check_prereqs() {
    ensure_search_api_session
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        log "ERROR: Cisco Meraki TA not found. Install the app first."
        exit 1
    fi
}

create_indexes() {
    log "Creating indexes..."
    if ! is_splunk_cloud; then
        ensure_search_api_session
    fi
    if platform_create_index "${SK:-}" "${SPLUNK_URI}" "meraki" "512000"; then
        log "  Index 'meraki' created or already exists."
    else
        log "ERROR: Failed to create index 'meraki'"
        return 1
    fi
    log "Index creation complete."
}

ensure_app_visible() {
    ensure_search_api_session
    local visible
    visible=$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/apps/local/${APP_NAME}?output_mode=json" 2>/dev/null \
        | python3 -c "
import json, sys
try: print(json.load(sys.stdin)['entry'][0]['content'].get('visible', True))
except: print('True')
" 2>/dev/null || echo "True")
    if [[ "${visible}" == "False" ]]; then
        log "Setting ${APP_NAME} visible=true..."
        deployment_set_app_visible "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "true" >/dev/null 2>&1 || true
    fi
}

configure_dashboards() {
    local index_name="${1:-meraki}"
    ensure_search_api_session
    log "Configuring dashboard macro 'meraki_index' -> index IN (${index_name})..."
    local new_def="index IN (${index_name})"
    local def_encoded body current_def
    def_encoded=$(_urlencode "${new_def}")
    body="definition=${def_encoded}&iseval=0"
    current_def=$(rest_get_conf_value "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "macros" "meraki_index" "definition" 2>/dev/null || true)
    if [[ -n "${current_def}" ]] && [[ "${current_def}" == "${new_def}" ]]; then
        log "  Macro already set to '${index_name}' — no change needed."
    else
        if rest_set_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "macros" "meraki_index" "${body}"; then
            log "  Updated: meraki_index = ${new_def}"
        else
            log "ERROR: Failed to set meraki_index macro"
            exit 1
        fi
    fi
    log "Dashboard configuration complete."
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

    local types=(
        devices
        devices_availabilities
        device_availabilities_change_history
        device_uplink_addresses_by_device
        devices_uplinks_loss_and_latency
        power_modules_statuses_by_device
        firmware_upgrades
    )

    for t in "${types[@]}"; do
        add_input "${t}" "${t}" "${account}" "${index}"
    done
    log "Device inputs enabled (7 inputs)."
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

    log "All inputs enabled (42 inputs, including webhook_logs)."
}

main() {
    warn_if_current_skill_role_unsupported

    if $ENABLE_INPUTS; then
        check_prereqs
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
            *) log "ERROR: Unknown input type '${INPUT_TYPE}'." >&2; usage 1 ;;
        esac
        log_live_input_summary
        log "$(log_platform_restart_guidance "input changes")"
        exit 0
    fi

    if $INDEXES_ONLY; then
        create_indexes
        log "$(log_platform_restart_guidance "index changes")"
        exit 0
    fi

    create_indexes
    configure_dashboards "meraki"
    ensure_app_visible
    log "$(log_platform_restart_guidance "index and dashboard changes")"

    [[ -t 0 ]] || return 0
    log ""
    read -rp "Would you like to configure a Meraki organization account now? [y/N]: " yn
    case "${yn}" in
        [yY]|[yY][eE][sS]) ;;
        *) return 0 ;;
    esac

    local acct_name org_id region api_key_file auto_idx
    read -rp "Account name (e.g. MY_ORG): " acct_name
    [[ -z "${acct_name}" ]] && { log "ERROR: Account name is required."; return 1; }
    read -rp "Organization ID: " org_id
    [[ -z "${org_id}" ]] && { log "ERROR: Organization ID is required."; return 1; }
    read -rp "Region [global/india/canada/china/fedramp] (default: global): " region
    region="${region:-global}"

    log ""
    log "Write your Meraki Dashboard API key to a temp file:"
    log "  bash skills/shared/scripts/write_secret_file.sh /tmp/meraki_api_key"
    log ""
    read -rp "Path to API key file (default: /tmp/meraki_api_key): " api_key_file
    api_key_file="${api_key_file:-/tmp/meraki_api_key}"
    [[ -f "${api_key_file}" ]] || { log "ERROR: File not found: ${api_key_file}"; return 1; }

    read -rp "Auto-create all inputs? [Y/n]: " auto_yn
    local auto_flag=""
    case "${auto_yn}" in
        [nN]|[nN][oO]) ;;
        *) auto_flag="--auto-inputs" ;;
    esac
    read -rp "Target index for inputs (default: meraki): " auto_idx
    auto_idx="${auto_idx:-meraki}"

    log ""
    bash "${SCRIPT_DIR}/configure_account.sh" \
        --name "${acct_name}" \
        --api-key-file "${api_key_file}" \
        --org-id "${org_id}" \
        --region "${region}" \
        ${auto_flag:+"${auto_flag}"} \
        --index "${auto_idx}"

    rm -f "${api_key_file}" 2>/dev/null || true
    log ""
    log "Run 'bash ${SCRIPT_DIR}/validate.sh' to verify the deployment."
}

main

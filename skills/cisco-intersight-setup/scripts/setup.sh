#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_Cisco_Intersight"

INDEXES_ONLY=false
MACROS_ONLY=false
ENABLE_INPUTS=false
ACCOUNT=""
INDEX=""
INPUT_TYPE=""

usage() {
    cat <<EOF
Cisco Intersight TA Setup Automation

Usage: $(basename "$0") [OPTIONS]

Options:
  --indexes-only          Create indexes only
  --macros-only           Create macros only
  --enable-inputs         Enable data inputs
  --account NAME          Account name for input enablement
  --index INDEX           Target index for inputs
  --input-type TYPE       Input type: audit_alarms, inventory, metrics, all
  --help                  Show this help

With no flags, runs full setup (indexes + macros).
Runs against remote Splunk via REST API (set SPLUNK_URI for non-localhost).
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --macros-only) MACROS_ONLY=true; shift ;;
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
    read -r total enabled disabled <<< "$(rest_get_live_input_counts "$SK" "$SPLUNK_URI" "$APP_NAME")"
    log "Live input status: total=${total}, enabled=${enabled}, disabled=${disabled}"
}

check_prereqs() {
    load_splunk_credentials
    SK=$(get_session_key "${SPLUNK_URI}") || true
    if [[ -z "${SK}" ]]; then
        log "ERROR: Could not authenticate to Splunk"
        exit 1
    fi
    if ! rest_check_app "$SK" "$SPLUNK_URI" "Splunk_TA_Cisco_Intersight"; then
        log "ERROR: Cisco Intersight TA not installed"
        exit 1
    fi
}

create_indexes() {
    log "Creating indexes..."
    if rest_create_index "$SK" "$SPLUNK_URI" "intersight" "512000"; then
        log "  Index 'intersight' created or already exists"
    else
        log "  ERROR: Failed to create index 'intersight'"
        exit 1
    fi
    log "Index creation complete."
}

create_macros() {
    log "Configuring macros..."
    local def_encoded
    def_encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('index IN (intersight)', safe=''))")
    if rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_intersight_index" "definition=${def_encoded}"; then
        log "  Macro 'cisco_intersight_index' configured"
    else
        log "  ERROR: Failed to set macro"
        exit 1
    fi
    log "Macro configuration complete."
}

enable_audit_alarms_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling Audit & Alarms inputs for account='${account}' index='${index}'..."

    local body="global_account=${account}&index=${index}&interval=900&date_input=7&enable_aaa_audit_records=1&enable_alarms=1&acknowledge=1&suppressed=1&info_alarms=1&disabled=0"

    rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "audit_alarms" "${account}_audit_logs" "${body}" && log "  Added: audit_alarms://${account}_audit_logs"
    rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "audit_alarms" "${account}_alarms" "${body}" && log "  Added: audit_alarms://${account}_alarms"

    log "Audit & Alarms inputs enabled (2 inputs)."
}

enable_inventory_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling Inventory inputs for account='${account}' index='${index}'..."

    local body_main="global_account=${account}&index=${index}&interval=1800&disabled=0&inventory=advisories,compute,fabric,network,target,contract,license&enable_compute_bladeidentities=1&enable_server_profiles=1&enable_chassis_profiles=1&enable_switch_cluster_profiles=1&enable_psucontrols=1&enable_processorunits=1&enable_memoryunits=1&enable_tpms=1&enable_storage_virtualdrives=1&enable_fancontrols=1&enable_license_account_license_data=1&enable_license_licenseinfos=1&enable_iocards=1&enable_chassisidentities=1&enable_expandermodules=1&enable_transceivers=1&enable_frus=1&enable_graphicscards=1&enable_supervisorcards=1&enable_switchcards=1&enable_hclstatuses=1&enable_devicecontractinformations=1&enable_advisory_instances=1&enable_advisory_definitions=1&enable_security_advisories=1&enable_chasses=1&enable_rackenclosures=1&enable_rackenclosureslots=1&enable_vnictemplates=1&enable_storage_items=1&enable_storage_physicaldisks=1&enable_equipment_fans=1&enable_equipment_fanmodules=1&enable_equipment_psus=1&enable_equipment_locatorleds=1"
    rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "inventory" "${account}_intersight_inventory" "${body_main}" && log "  Added: inventory://${account}_intersight_inventory"

    local body_ports="global_account=${account}&index=${index}&interval=1800&disabled=0&inventory=ports&enable_ether_hostports=1&enable_ether_networkports=1&enable_ether_physicalports=1&enable_ether_portchannels=1&enable_adapter_hostfcinterfaces=1&enable_fc_physicalports=1&enable_network_vfcs=1&enable_network_vethernets=1&enable_fc_portchannels=1&enable_adapter_hostethinterfaces=1"
    rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "inventory" "${account}_intersight_ports_and_interfaces_inventory" "${body_ports}" && log "  Added: inventory://${account}_intersight_ports_and_interfaces_inventory"

    local body_pools="global_account=${account}&index=${index}&interval=1800&disabled=0&inventory=pools&enable_fcpool_pools=1&enable_ippool_pools=1&enable_iqnpool_pools=1&enable_macpool_pools=1&enable_uuidpool_pools=1&enable_resourcepool_pools=1&enable_compute_rackunitidentities=1&enable_fabric_elementidentities=1"
    rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "inventory" "${account}_intersight_pools_inventory" "${body_pools}" && log "  Added: inventory://${account}_intersight_pools_inventory"

    log "Inventory inputs enabled (3 inputs)."
}

enable_metrics_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling Metrics inputs for account='${account}' index='${index}'..."

    rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "metrics" "${account}_device_metrics" \
        "global_account=${account}&index=${index}&interval=900&disabled=0&metrics=temperature,cpu_utilization,memory,host,fan" && log "  Added: metrics://${account}_device_metrics"

    rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "metrics" "${account}_network_metrics" \
        "global_account=${account}&index=${index}&interval=900&disabled=0&metrics=network" && log "  Added: metrics://${account}_network_metrics"

    log "Metrics inputs enabled (2 inputs)."
}

main() {
    check_prereqs

    if $ENABLE_INPUTS; then
        if [[ -z "${ACCOUNT}" || -z "${INDEX}" || -z "${INPUT_TYPE}" ]]; then
            log "ERROR: --enable-inputs requires --account, --index, and --input-type"
            exit 1
        fi
        case "${INPUT_TYPE}" in
            audit_alarms) enable_audit_alarms_inputs "${ACCOUNT}" "${INDEX}" ;;
            inventory) enable_inventory_inputs "${ACCOUNT}" "${INDEX}" ;;
            metrics) enable_metrics_inputs "${ACCOUNT}" "${INDEX}" ;;
            all)
                enable_audit_alarms_inputs "${ACCOUNT}" "${INDEX}"
                enable_inventory_inputs "${ACCOUNT}" "${INDEX}"
                enable_metrics_inputs "${ACCOUNT}" "${INDEX}"
                ;;
            *) log "ERROR: Unknown input type '${INPUT_TYPE}'. Use: audit_alarms, inventory, metrics, all"; exit 1 ;;
        esac
        log_live_input_summary
        log "Restart Splunk to apply changes."
        exit 0
    fi

    if $MACROS_ONLY; then
        create_macros
        exit 0
    fi

    if $INDEXES_ONLY; then
        create_indexes
        exit 0
    fi

    create_indexes
    create_macros
    log "Setup complete. Restart Splunk to apply changes."
}

main

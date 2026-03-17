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
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk"; exit 1; }
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

    local body
    body=$(form_urlencode_pairs \
        global_account "${account}" \
        index "${index}" \
        interval "900" \
        date_input "7" \
        enable_aaa_audit_records "1" \
        enable_alarms "1" \
        acknowledge "1" \
        suppressed "1" \
        info_alarms "1" \
        disabled "0")

    local failures=0

    if rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "audit_alarms" "${account}_audit_logs" "${body}"; then
        log "  Added: audit_alarms://${account}_audit_logs"
    else
        log "  ERROR: Failed to create audit_alarms://${account}_audit_logs"
        failures=$((failures + 1))
    fi

    if rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "audit_alarms" "${account}_alarms" "${body}"; then
        log "  Added: audit_alarms://${account}_alarms"
    else
        log "  ERROR: Failed to create audit_alarms://${account}_alarms"
        failures=$((failures + 1))
    fi

    if (( failures != 0 )); then
        log "Audit & Alarms input enablement failed for ${failures} input(s)."
        return 1
    fi

    log "Audit & Alarms inputs enabled (2 inputs)."
}

enable_inventory_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling Inventory inputs for account='${account}' index='${index}'..."

    local body_main
    body_main=$(form_urlencode_pairs \
        global_account "${account}" \
        index "${index}" \
        interval "1800" \
        disabled "0" \
        inventory "advisories,compute,fabric,network,target,contract,license")

    local body_ports
    body_ports=$(form_urlencode_pairs \
        global_account "${account}" \
        index "${index}" \
        interval "1800" \
        disabled "0" \
        inventory "ports")

    local body_pools
    body_pools=$(form_urlencode_pairs \
        global_account "${account}" \
        index "${index}" \
        interval "1800" \
        disabled "0" \
        inventory "pools")

    local failures=0

    if rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "inventory" "${account}_intersight_inventory" "${body_main}"; then
        log "  Added: inventory://${account}_intersight_inventory"
    else
        log "  ERROR: Failed to create inventory://${account}_intersight_inventory"
        failures=$((failures + 1))
    fi

    if rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "inventory" "${account}_intersight_ports_and_interfaces_inventory" "${body_ports}"; then
        log "  Added: inventory://${account}_intersight_ports_and_interfaces_inventory"
    else
        log "  ERROR: Failed to create inventory://${account}_intersight_ports_and_interfaces_inventory"
        failures=$((failures + 1))
    fi

    if rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "inventory" "${account}_intersight_pools_inventory" "${body_pools}"; then
        log "  Added: inventory://${account}_intersight_pools_inventory"
    else
        log "  ERROR: Failed to create inventory://${account}_intersight_pools_inventory"
        failures=$((failures + 1))
    fi

    if (( failures != 0 )); then
        log "Inventory input enablement failed for ${failures} input(s)."
        return 1
    fi

    log "Inventory inputs enabled (3 inputs)."
}

enable_metrics_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling Metrics inputs for account='${account}' index='${index}'..."

    local device_body network_body
    device_body=$(form_urlencode_pairs \
        global_account "${account}" \
        index "${index}" \
        interval "900" \
        disabled "0" \
        metrics "temperature,cpu_utilization,memory,host,fan")
    local failures=0
    if rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "metrics" "${account}_device_metrics" \
        "${device_body}"; then
        log "  Added: metrics://${account}_device_metrics"
    else
        log "  ERROR: Failed to create metrics://${account}_device_metrics"
        failures=$((failures + 1))
    fi

    network_body=$(form_urlencode_pairs \
        global_account "${account}" \
        index "${index}" \
        interval "900" \
        disabled "0" \
        metrics "network")
    if rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "metrics" "${account}_network_metrics" \
        "${network_body}"; then
        log "  Added: metrics://${account}_network_metrics"
    else
        log "  ERROR: Failed to create metrics://${account}_network_metrics"
        failures=$((failures + 1))
    fi

    if (( failures != 0 )); then
        log "Metrics input enablement failed for ${failures} input(s)."
        return 1
    fi

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

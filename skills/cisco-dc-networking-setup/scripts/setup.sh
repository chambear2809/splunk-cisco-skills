#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco_dc_networking_app_for_splunk"

INDEXES_ONLY=false
MACROS_ONLY=false
ENABLE_INPUTS=false
ACCOUNT=""
INDEX=""
INPUT_TYPE=""

usage() {
    cat <<EOF
Cisco DC Networking TA Setup Automation

Usage: $(basename "$0") [OPTIONS]

Options:
  --indexes-only          Create indexes only
  --macros-only           Update search macros only
  --enable-inputs         Enable data inputs
  --account NAME          Account name for input enablement
  --index INDEX           Target index for inputs
  --input-type TYPE       Input type: aci, nd, nexus9k
  --help                  Show this help

With no flags, runs full setup (indexes + macros).
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

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

check_prereqs() {
    if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME"; then
        log "ERROR: Cisco DC Networking app not found. Install it first."
        exit 1
    fi
}

create_indexes() {
    log "Creating indexes..."

    rest_create_index "$SK" "$SPLUNK_URI" "cisco_aci" "512000" || true
    rest_create_index "$SK" "$SPLUNK_URI" "cisco_nd" "512000" || true
    rest_create_index "$SK" "$SPLUNK_URI" "cisco_nexus_9k" "512000" || true

    log "Index creation complete."
}

update_macros() {
    log "Updating search macros..."

    local def_aci def_nd def_n9k
    def_aci=$(python3 -c "import urllib.parse; print(urllib.parse.quote('index IN (\"cisco_aci\")', safe=''))")
    def_nd=$(python3 -c "import urllib.parse; print(urllib.parse.quote('index IN (\"cisco_nd\")', safe=''))")
    def_n9k=$(python3 -c "import urllib.parse; print(urllib.parse.quote('index IN (\"cisco_nexus_9k\")', safe=''))")

    rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_dc_aci_index" "definition=${def_aci}" || true
    rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_dc_nd_index" "definition=${def_nd}" || true
    rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_dc_nexus_9k_index" "definition=${def_n9k}" || true

    log "Macros updated: cisco_dc_aci_index, cisco_dc_nd_index, cisco_dc_nexus_9k_index"
}

enable_aci_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling ACI inputs for account='${account}' index='${index}'..."

    local aci_inputs=(
        "cisco_nexus_aci://authentication"
        "cisco_nexus_aci://classInfo_faultInst"
        "cisco_nexus_aci://classInfo_aaaModLR"
        "cisco_nexus_aci://classInfo_fvRsCEpToPathEp"
        "cisco_nexus_aci://fex"
        "cisco_nexus_aci://health_fabricHealthTotal"
        "cisco_nexus_aci://health_fvTenant"
        "cisco_nexus_aci://microsegment"
        "cisco_nexus_aci://stats"
    )

    for input_spec in "${aci_inputs[@]}"; do
        local input_type="${input_spec%%://*}"
        local input_name="${input_spec#*://}"
        local body="disabled=0&apic_account=${account}&index=${index}"
        rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "$input_type" "$input_name" "$body" || true
    done
    log "ACI inputs enabled."
}

enable_nd_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling Nexus Dashboard inputs for account='${account}' index='${index}'..."

    local nd_inputs=(
        "cisco_nexus_dashboard://advisories"
        "cisco_nexus_dashboard://anomalies"
        "cisco_nexus_dashboard://congestion"
        "cisco_nexus_dashboard://endpoints"
        "cisco_nexus_dashboard://fabrics"
        "cisco_nexus_dashboard://switches"
        "cisco_nexus_dashboard://flows"
        "cisco_nexus_dashboard://protocols"
        "cisco_nexus_dashboard://mso_tenant_site_schema"
        "cisco_nexus_dashboard://mso_fabric_policy"
        "cisco_nexus_dashboard://mso_audit_user"
    )

    for input_spec in "${nd_inputs[@]}"; do
        local input_type="${input_spec%%://*}"
        local input_name="${input_spec#*://}"
        local body="disabled=0&nd_account=${account}&index=${index}"
        rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "$input_type" "$input_name" "$body" || true
    done
    log "Nexus Dashboard inputs enabled."
}

enable_nexus9k_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling Nexus 9K inputs for account='${account}' index='${index}'..."

    local n9k_inputs=(
        "cisco_nexus_9k://nxhostname"
        "cisco_nexus_9k://nxversion"
        "cisco_nexus_9k://nxmodule"
        "cisco_nexus_9k://nxinventory"
        "cisco_nexus_9k://nxtemperature"
        "cisco_nexus_9k://nxinterface"
        "cisco_nexus_9k://nxneighbor"
        "cisco_nexus_9k://nxtransceiver"
        "cisco_nexus_9k://nxpower"
        "cisco_nexus_9k://nxresource"
    )

    for input_spec in "${n9k_inputs[@]}"; do
        local input_type="${input_spec%%://*}"
        local input_name="${input_spec#*://}"
        local body="disabled=0&nexus_9k_account=${account}&index=${index}"
        rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "$input_type" "$input_name" "$body" || true
    done
    log "Nexus 9K inputs enabled."
}

main() {
    check_prereqs

    if $ENABLE_INPUTS; then
        if [[ -z "${ACCOUNT}" || -z "${INDEX}" || -z "${INPUT_TYPE}" ]]; then
            log "ERROR: --enable-inputs requires --account, --index, and --input-type"
            exit 1
        fi
        case "${INPUT_TYPE}" in
            aci) enable_aci_inputs "${ACCOUNT}" "${INDEX}" ;;
            nd) enable_nd_inputs "${ACCOUNT}" "${INDEX}" ;;
            nexus9k) enable_nexus9k_inputs "${ACCOUNT}" "${INDEX}" ;;
            *) log "ERROR: Unknown input type '${INPUT_TYPE}'. Use: aci, nd, nexus9k"; exit 1 ;;
        esac
        log_live_input_summary
        log "Restart Splunk to apply changes."
        exit 0
    fi

    if $INDEXES_ONLY; then
        create_indexes
        exit 0
    fi

    if $MACROS_ONLY; then
        update_macros
        exit 0
    fi

    create_indexes
    update_macros
    log "Setup complete. Restart Splunk to apply all changes."
}

main

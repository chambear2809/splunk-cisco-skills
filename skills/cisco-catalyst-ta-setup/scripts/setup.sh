#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="TA_cisco_catalyst"

INDEXES_ONLY=false
ENABLE_INPUTS=false
ACCOUNT=""
INDEX=""
INPUT_TYPE=""

usage() {
    cat <<EOF
Cisco Catalyst TA Setup Automation

Usage: $(basename "$0") [OPTIONS]

Options:
  --indexes-only          Create indexes only
  --enable-inputs         Enable data inputs
  --account NAME          Account name for input enablement
  --index INDEX           Target index for inputs
  --input-type TYPE       Input type: catalyst_center, ise, sdwan, cybervision
  --help                  Show this help

With no flags, runs full setup (indexes).
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --enable-inputs) ENABLE_INPUTS=true; shift ;;
        --account) require_arg "$1" $# || exit 1; ACCOUNT="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --input-type) require_arg "$1" $# || exit 1; INPUT_TYPE="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

log_live_input_summary() {
    local total enabled disabled
    read -r total enabled disabled <<< "$(rest_get_live_input_counts "$SK" "$SPLUNK_URI" "$APP_NAME")"
    log "Live input status: total=${total}, enabled=${enabled}, disabled=${disabled}"
}

ensure_search_api_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

check_prereqs() {
    ensure_search_api_session
    if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME"; then
        log "ERROR: Cisco Catalyst TA not found. Install it first."
        exit 1
    fi
}

create_indexes() {
    log "Creating indexes..."
    local failed=0 idx

    if ! is_splunk_cloud; then
        ensure_search_api_session
    fi

    for idx in catalyst ise sdwan cybervision; do
        if platform_create_index "${SK-}" "$SPLUNK_URI" "${idx}" "512000"; then
            log "  Index '${idx}' created or already exists."
        else
            log "  ERROR: Failed to create index '${idx}'."
            failed=1
        fi
    done

    if (( failed != 0 )); then
        log "Index creation failed."
        return 1
    fi

    log "Index creation complete."
}

enable_catalyst_center_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling Catalyst Center inputs for account='${account}' index='${index}'..."

    local input_types=(
        "cisco_catalyst_dnac_issue"
        "cisco_catalyst_dnac_clienthealth"
        "cisco_catalyst_dnac_devicehealth"
        "cisco_catalyst_dnac_compliance"
        "cisco_catalyst_dnac_networkhealth"
        "cisco_catalyst_dnac_securityadvisory"
        "cisco_catalyst_dnac_client"
        "cisco_catalyst_dnac_audit_logs"
        "cisco_catalyst_dnac_site_topology"
    )
    local input_names=(
        "Issue"
        "Client_Health"
        "Device_Health"
        "Compliance"
        "Network_Health"
        "Security_Advisory"
        "Client"
        "Audit_Logs"
        "Site_Topology"
    )

    local failures=0
    for i in "${!input_types[@]}"; do
        local body
        body=$(form_urlencode_pairs \
            cisco_dna_center_account "${account}" \
            index "${index}" \
            interval "3600" \
            logging_level "INFO")
        if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "${input_types[$i]}" "${input_names[$i]}" "$body"; then
            log "  ERROR: Failed to enable ${input_types[$i]}://${input_names[$i]}"
            failures=$((failures + 1))
        fi
    done

    if (( failures != 0 )); then
        log "Catalyst Center input enablement failed for ${failures} input(s)."
        return 1
    fi

    log "Catalyst Center inputs enabled (9 inputs)."
}

enable_ise_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling ISE inputs for account='${account}' index='${index}'..."

    local body
    body=$(form_urlencode_pairs \
        ise_account "${account}" \
        data_type "security_group_tags,authz_policy_hit,ise_tacacs_rule_hit" \
        index "${index}" \
        interval "3600" \
        logging_level "INFO")
    if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "cisco_catalyst_ise_administrative_input" "ISE_Inputs" "$body"; then
        log "  ERROR: Failed to enable cisco_catalyst_ise_administrative_input://ISE_Inputs"
        return 1
    fi
    log "ISE inputs enabled (1 input with 3 data types)."
}

enable_sdwan_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling SD-WAN inputs for account='${account}' index='${index}'..."

    local body
    body=$(form_urlencode_pairs \
        sdwan_account "${account}" \
        index "${index}" \
        interval "3600" \
        logging_level "INFO")
    if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "cisco_catalyst_sdwan_health" "SDWAN_Health" "$body"; then
        log "  ERROR: Failed to enable cisco_catalyst_sdwan_health://SDWAN_Health"
        return 1
    fi
    if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "cisco_catalyst_sdwan_site_and_tunnel_health" "SDWAN_Site_Tunnel_Health" "$body"; then
        log "  ERROR: Failed to enable cisco_catalyst_sdwan_site_and_tunnel_health://SDWAN_Site_Tunnel_Health"
        return 1
    fi
    log "SD-WAN inputs enabled (2 inputs)."
}

enable_cybervision_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling Cyber Vision inputs for account='${account}' index='${index}'..."

    local input_types=(
        "cisco_catalyst_cybervision_activities"
        "cisco_catalyst_cybervision_components"
        "cisco_catalyst_cybervision_devices"
        "cisco_catalyst_cybervision_events"
        "cisco_catalyst_cybervision_flows"
        "cisco_catalyst_cybervision_vulnerabilities"
    )
    local input_names=(
        "CV_Activities"
        "CV_Components"
        "CV_Devices"
        "CV_Events"
        "CV_Flows"
        "CV_Vulnerabilities"
    )

    local body
    body=$(form_urlencode_pairs \
        cyber_vision_account "${account}" \
        index "${index}" \
        logging_level "INFO" \
        page_size "100")
    local failures=0
    for i in "${!input_types[@]}"; do
        if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "${input_types[$i]}" "${input_names[$i]}" "$body"; then
            log "  ERROR: Failed to enable ${input_types[$i]}://${input_names[$i]}"
            failures=$((failures + 1))
        fi
    done

    if (( failures != 0 )); then
        log "Cyber Vision input enablement failed for ${failures} input(s)."
        return 1
    fi

    log "Cyber Vision inputs enabled (6 inputs)."
}

main() {
    check_prereqs

    if $ENABLE_INPUTS; then
        if [[ -z "${ACCOUNT}" || -z "${INDEX}" || -z "${INPUT_TYPE}" ]]; then
            log "ERROR: --enable-inputs requires --account, --index, and --input-type"
            exit 1
        fi
        case "${INPUT_TYPE}" in
            catalyst_center) enable_catalyst_center_inputs "${ACCOUNT}" "${INDEX}" ;;
            ise) enable_ise_inputs "${ACCOUNT}" "${INDEX}" ;;
            sdwan) enable_sdwan_inputs "${ACCOUNT}" "${INDEX}" ;;
            cybervision) enable_cybervision_inputs "${ACCOUNT}" "${INDEX}" ;;
            *) log "ERROR: Unknown input type '${INPUT_TYPE}'. Use: catalyst_center, ise, sdwan, cybervision"; exit 1 ;;
        esac
        log_live_input_summary
        log "$(log_platform_restart_guidance "input changes")"
        exit 0
    fi

    if $INDEXES_ONLY; then
        create_indexes
        log "Setup complete."
        log "$(log_platform_restart_guidance "index changes")"
        exit 0
    fi

    create_indexes
    log "Setup complete."
    log "$(log_platform_restart_guidance "index changes")"
}

main

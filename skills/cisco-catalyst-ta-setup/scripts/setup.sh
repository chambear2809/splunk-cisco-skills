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
COMMAND_ID=""
INPUT_NAME=""
INTERVAL=""

usage() {
    cat >&2 <<EOF
Cisco Catalyst TA Setup Automation

Usage: $(basename "$0") [OPTIONS]

Options:
  --indexes-only          Create indexes only
  --enable-inputs         Enable data inputs
  --account NAME          Account name for input enablement
  --index INDEX           Target index for inputs
  --input-type TYPE       Input type: catalyst_center, ise, sdwan, cybervision, iosxe_cli
  --command-id ID         Cataloged command ID for iosxe_cli
  --input-name NAME       Optional iosxe_cli input name
  --interval SECONDS      Optional iosxe_cli polling interval override
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
        --command-id) require_arg "$1" $# || exit 1; COMMAND_ID="$2"; shift 2 ;;
        --input-name) require_arg "$1" $# || exit 1; INPUT_NAME="$2"; shift 2 ;;
        --interval) require_arg "$1" $# || exit 1; INTERVAL="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
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
        if [[ -z "${SK:-}" ]]; then
            log "ERROR: ensure_search_api_session did not produce a session key; cannot create indexes."
            return 1
        fi
    fi

    for idx in catalyst ise sdwan cybervision; do
        if platform_create_index "${SK:-}" "$SPLUNK_URI" "${idx}" "512000"; then
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

    local input_specs=(
        "cisco_catalyst_dnac_clienthealth|300|Client_Health"
        "cisco_catalyst_dnac_devicehealth|300|Device_Health"
        "cisco_catalyst_dnac_compliance|900|Compliance"
        "cisco_catalyst_dnac_issue|300|Issue"
        "cisco_catalyst_dnac_networkhealth|300|Network_Health"
        "cisco_catalyst_dnac_securityadvisory|3600|Security_Advisory"
        "cisco_catalyst_dnac_swim|3600|SWIM"
        "cisco_catalyst_dnac_application_traffic|900|Application_Traffic"
        "cisco_catalyst_dnac_audit_logs|300|Audit_Logs"
        "cisco_catalyst_dnac_client|3600|Client"
        "cisco_catalyst_dnac_site_topology|3600|Site_Topology"
    )

    local failures=0 input_spec input_type interval input_name
    for input_spec in "${input_specs[@]}"; do
        IFS="|" read -r input_type interval input_name <<< "${input_spec}"
        local body
        body=$(form_urlencode_pairs \
            cisco_dna_center_account "${account}" \
            index "${index}" \
            interval "${interval}" \
            logging_level "INFO" \
            disabled "0")
        if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "${input_type}" "${input_name}" "$body"; then
            log "  ERROR: Failed to enable ${input_type}://${input_name}"
            failures=$((failures + 1))
        fi
    done

    if (( failures != 0 )); then
        log "Catalyst Center input enablement failed for ${failures} input(s)."
        return 1
    fi

    log "Catalyst Center inputs enabled (11 dedicated inputs)."
    log "Generic endpoint and scheduled-report inputs require explicit endpoint/report selections and were not created."
}

enable_ise_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling ISE inputs for account='${account}' index='${index}'..."

    local input_spec="cisco_catalyst_ise_administrative_input|3600|ISE_Inputs"
    local input_type interval input_name body
    IFS="|" read -r input_type interval input_name <<< "${input_spec}"
    body=$(form_urlencode_pairs \
        ise_account "${account}" \
        data_type "security_group_tags,authz_policy_hit,ise_tacacs_rule_hit" \
        index "${index}" \
        interval "${interval}" \
        logging_level "INFO" \
        disabled "0")
    if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "${input_type}" "${input_name}" "$body"; then
        log "  ERROR: Failed to enable ${input_type}://${input_name}"
        return 1
    fi
    log "ISE inputs enabled (1 input with 3 data types)."
    log "Generic Open API and analytics-report inputs require explicit endpoint/repository selections and were not created."
}

enable_sdwan_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling SD-WAN inputs for account='${account}' index='${index}'..."

    local health_spec="cisco_catalyst_sdwan_health|900|SDWAN_Health"
    local site_tunnel_spec="cisco_catalyst_sdwan_site_and_tunnel_health|3600|SDWAN_Site_Tunnel_Health"
    local audit_spec="cisco_catalyst_sdwan_audit_logs|300|SDWAN_Audit_Logs"
    local energy_spec="cisco_catalyst_sdwan_energy_stats|300|SDWAN_Energy_Stats"
    local input_type interval input_name health_body site_tunnel_body audit_body energy_body
    IFS="|" read -r input_type interval input_name <<< "${health_spec}"
    health_body=$(form_urlencode_pairs \
        sdwan_account "${account}" \
        health_type "utd_health,link_health,sse_tunnel_health" \
        index "${index}" \
        interval "${interval}" \
        logging_level "INFO" \
        disabled "0")
    site_tunnel_body=$(form_urlencode_pairs \
        sdwan_account "${account}" \
        health_type "site_health,tunnel_health,sse_tunnels" \
        index "${index}" \
        interval "3600" \
        logging_level "INFO" \
        disabled "0")
    audit_body=$(form_urlencode_pairs \
        sdwan_account "${account}" \
        index "${index}" \
        interval "300" \
        initial_backfill_days "7" \
        audit_log_details "0" \
        config_difference "0" \
        logging_level "INFO" \
        disabled "0")
    energy_body=$(form_urlencode_pairs \
        sdwan_account "${account}" \
        index "${index}" \
        interval "300" \
        logging_level "INFO" \
        disabled "0")

    if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "${input_type}" "${input_name}" "$health_body"; then
        log "  ERROR: Failed to enable ${input_type}://${input_name}"
        return 1
    fi
    IFS="|" read -r input_type interval input_name <<< "${site_tunnel_spec}"
    if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "${input_type}" "${input_name}" "$site_tunnel_body"; then
        log "  ERROR: Failed to enable ${input_type}://${input_name}"
        return 1
    fi
    IFS="|" read -r input_type interval input_name <<< "${audit_spec}"
    if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "${input_type}" "${input_name}" "$audit_body"; then
        log "  ERROR: Failed to enable ${input_type}://${input_name}"
        return 1
    fi
    IFS="|" read -r input_type interval input_name <<< "${energy_spec}"
    if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "${input_type}" "${input_name}" "$energy_body"; then
        log "  ERROR: Failed to enable ${input_type}://${input_name}"
        return 1
    fi
    log "SD-WAN inputs enabled (4 dedicated inputs)."
    log "SD-WAN API Endpoint Collection inputs require an explicit endpoint and device-scope selection and were not created."
}

enable_cybervision_inputs() {
    local account="$1"
    local index="$2"

    log "Enabling Cyber Vision inputs for account='${account}' index='${index}'..."

    local input_specs=(
        "cisco_catalyst_cybervision_activities|300|CV_Activities"
        "cisco_catalyst_cybervision_components|900|CV_Components"
        "cisco_catalyst_cybervision_devices|900|CV_Devices"
        "cisco_catalyst_cybervision_events|300|CV_Events"
        "cisco_catalyst_cybervision_flows|300|CV_Flows"
        "cisco_catalyst_cybervision_vulnerabilities|900|CV_Vulnerabilities"
    )

    local failures=0 input_spec input_type interval input_name body
    for input_spec in "${input_specs[@]}"; do
        IFS="|" read -r input_type interval input_name <<< "${input_spec}"
        body=$(form_urlencode_pairs \
            cyber_vision_account "${account}" \
            index "${index}" \
            interval "${interval}" \
            logging_level "INFO" \
            page_size "100" \
            disabled "0")
        if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "${input_type}" "${input_name}" "$body"; then
            log "  ERROR: Failed to enable ${input_type}://${input_name}"
            failures=$((failures + 1))
        fi
    done

    if (( failures != 0 )); then
        log "Cyber Vision input enablement failed for ${failures} input(s)."
        return 1
    fi

    log "Cyber Vision inputs enabled (6 inputs)."
    log "Generic Classic API inputs require an explicit endpoint selection and were not created."
}

enable_iosxe_cli_input() {
    local account="$1"
    local index="$2"
    local command_id="$3"
    local input_name="$4"
    local interval="$5"
    local recommended_interval

    case "${command_id}" in
        dspfarm_profile) recommended_interval="900" ;;
        sdwan_bfd_sessions) recommended_interval="300" ;;
        sdwan_bfd_history) recommended_interval="900" ;;
        version|inventory) recommended_interval="3600" ;;
        *)
            log "ERROR: Unknown CLI command ID '${command_id}'. Use: dspfarm_profile, sdwan_bfd_sessions, sdwan_bfd_history, version, inventory"
            return 1
            ;;
    esac

    [[ -n "${input_name}" ]] || input_name="CLI_${command_id}"
    [[ -n "${interval}" ]] || interval="${recommended_interval}"
    if [[ ! "${interval}" =~ ^[0-9]+$ ]] || [[ "${interval}" == "0" ]]; then
        log "ERROR: --interval must be a positive integer"
        return 1
    fi

    log "Enabling Beta IOS-XE CLI input for account='${account}' command_id='${command_id}' index='${index}'..."
    if (( 10#${interval} < 10#${recommended_interval} )); then
        log "  WARN: interval ${interval}s is below the catalog recommendation of ${recommended_interval}s; validate device load before production use."
    fi

    local body
    body=$(form_urlencode_pairs \
        cli_account "${account}" \
        command_id "${command_id}" \
        index "${index}" \
        interval "${interval}" \
        logging_level "INFO" \
        disabled "0")
    if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "cisco_catalyst_cli_command" "${input_name}" "$body"; then
        log "  ERROR: Failed to enable cisco_catalyst_cli_command://${input_name}"
        return 1
    fi

    log "IOS-XE CLI input enabled. This feature remains Beta; verify Test Connection, privilege, output shape, and event delivery."
}

main() {
    warn_if_current_skill_role_unsupported

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
            iosxe_cli)
                if [[ -z "${COMMAND_ID}" ]]; then
                    log "ERROR: --input-type iosxe_cli requires --command-id"
                    exit 1
                fi
                enable_iosxe_cli_input "${ACCOUNT}" "${INDEX}" "${COMMAND_ID}" "${INPUT_NAME}" "${INTERVAL}"
                ;;
            *) log "ERROR: Unknown input type '${INPUT_TYPE}'. Use: catalyst_center, ise, sdwan, cybervision, iosxe_cli"; exit 1 ;;
        esac
        log_live_input_summary
        log "$(log_platform_restart_guidance "input changes")"
        exit 0
    fi

    if $INDEXES_ONLY; then
        create_indexes
        log "Index setup complete; this does not prove account, input, event, or dashboard readiness."
        log "$(log_platform_restart_guidance "index changes")"
        exit 0
    fi

    create_indexes
    log "Index setup complete; run '${SCRIPT_DIR}/validate.sh --completion' after configuring an account and input."
    log "$(log_platform_restart_guidance "index changes")"
}

main

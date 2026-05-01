#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_AppDynamics"

STATUS_METRICS="Application Status~Business Transactions~Tier Node Status~Remote Services Status~Database Status~Server Status~Application Security Status~Web User Experience~Mobile User Experience"
DATABASE_METRICS="custom_metrics~hardware~kpi~performance~server_stats"
HARDWARE_METRICS="cpu~disk~memory~network~system"
SNAPSHOT_TYPES="SLOW~VERY_SLOW~STALL~ERROR~NORMAL"
SECURITY_METRICS="attack_counts~business_risk~vulnerabilities"
DEFAULT_EVENT_FILTERS="POLICY_OPEN_WARNING~POLICY_OPEN_CRITICAL~ANOMALY_OPEN_WARNING~ANOMALY_OPEN_CRITICAL~SLOW~VERY_SLOW~STALL~BUSINESS_ERROR"

INDEXES_ONLY=false
SETTINGS_ONLY=false
ENABLE_INPUTS=false
ACCOUNT=""
INDEX="appdynamics"
INPUT_TYPE=""
ANALYTICS_ACCOUNT=""
QUERY=""
SOURCE_NAME=""
SOURCE_TYPE=""
METRIC_PATHS=""
APPLICATION_LIST=""
EVENT_FILTERS=""
INPUT_NAME=""

usage() {
    cat >&2 <<EOF
Cisco AppDynamics Setup Automation

Usage: $(basename "$0") [OPTIONS]

Options:
  --indexes-only            Create the target index only
  --settings-only           Set the add-on default index only
  --enable-inputs           Enable or create data inputs
  --account NAME            Controller connection name for controller-backed inputs
  --index INDEX             Target index (default: appdynamics)
  --input-type TYPE         Input type: recommended, all, status, database,
                            hardware, snapshots, security, events, audit,
                            licenses, analytics, custom
  --analytics-account NAME  Analytics connection name (required for analytics)
  --query QUERY             Analytics ADQL query (required for analytics)
  --metric-paths LIST       Comma-separated custom metric paths (required for custom)
  --source-name NAME        Source name override for analytics or custom inputs
  --source-type NAME        Source type override for custom inputs
  --application-list RAW    Optional raw application selector value for
                            advanced use; omit to use all active applications
  --event-filters RAW       Optional tilde-delimited event filter override
  --input-name NAME         Optional explicit input stanza name for singular
                            analytics or custom inputs
  --help                    Show this help

With no flags, runs full setup (index + settings + visibility checks).
Runs against remote Splunk via search-tier REST API (set
SPLUNK_SEARCH_API_URI for non-localhost; legacy alias: SPLUNK_URI).
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --settings-only) SETTINGS_ONLY=true; shift ;;
        --enable-inputs) ENABLE_INPUTS=true; shift ;;
        --account) require_arg "$1" $# || exit 1; ACCOUNT="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --input-type) require_arg "$1" $# || exit 1; INPUT_TYPE="$2"; shift 2 ;;
        --analytics-account) require_arg "$1" $# || exit 1; ANALYTICS_ACCOUNT="$2"; shift 2 ;;
        --query) require_arg "$1" $# || exit 1; QUERY="$2"; shift 2 ;;
        --metric-paths) require_arg "$1" $# || exit 1; METRIC_PATHS="$2"; shift 2 ;;
        --source-name) require_arg "$1" $# || exit 1; SOURCE_NAME="$2"; shift 2 ;;
        --source-type) require_arg "$1" $# || exit 1; SOURCE_TYPE="$2"; shift 2 ;;
        --application-list) require_arg "$1" $# || exit 1; APPLICATION_LIST="$2"; shift 2 ;;
        --event-filters) require_arg "$1" $# || exit 1; EVENT_FILTERS="$2"; shift 2 ;;
        --input-name) require_arg "$1" $# || exit 1; INPUT_NAME="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

append_form_pair() {
    local body="$1"
    local key="$2"
    local value="$3"
    local pair

    if [[ -z "${value}" ]]; then
        printf '%s' "${body}"
        return 0
    fi

    pair=$(form_urlencode_pairs "${key}" "${value}") || return 1
    if [[ -n "${body}" ]]; then
        printf '%s&%s' "${body}" "${pair}"
    else
        printf '%s' "${pair}"
    fi
}

log_live_input_summary() {
    local total enabled disabled
    read -r total enabled disabled <<< "$(rest_get_live_input_counts "${SK}" "${SPLUNK_URI}" "${APP_NAME}")"
    log "Live input status: total=${total}, enabled=${enabled}, disabled=${disabled}"
}

ensure_search_api_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

check_prereqs() {
    ensure_search_api_session
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        log "ERROR: ${APP_NAME} not installed. Install the add-on first."
        exit 1
    fi
}

create_indexes() {
    log "Creating indexes..."
    if ! is_splunk_cloud; then
        ensure_search_api_session
    fi
    if platform_create_index "${SK:-}" "${SPLUNK_URI}" "${INDEX}" "512000"; then
        log "  Index '${INDEX}' created or already exists."
    else
        log "ERROR: Failed to create index '${INDEX}'"
        return 1
    fi
    log "Index creation complete."
}

configure_settings() {
    local body

    ensure_search_api_session
    log "Configuring add-on defaults..."
    body=$(form_urlencode_pairs index "${INDEX}") || return 1

    if rest_set_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "splunk_ta_appdynamics_settings" "additional_parameters" "${body}"; then
        log "  Default index set to '${INDEX}'"
    else
        log "ERROR: Failed to update add-on settings"
        return 1
    fi

    log "Settings configuration complete."
}

ensure_app_visible() {
    local visible

    ensure_search_api_session
    visible=$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/apps/local/${APP_NAME}?output_mode=json" 2>/dev/null \
        | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin)['entry'][0]['content'].get('visible', True))
except Exception:
    print('True')
" 2>/dev/null || echo "True")

    if [[ "${visible}" == "False" ]]; then
        log "Setting ${APP_NAME} visible=true..."
        deployment_set_app_visible "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "true" >/dev/null 2>&1 || true
    fi
}

create_named_input() {
    local input_type="$1"
    local input_name="$2"
    local body="$3"

    if rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "${input_type}" "${input_name}" "${body}"; then
        log "  Added: ${input_type}://${input_name}"
    else
        log "  ERROR: Failed to create ${input_type}://${input_name}"
        return 1
    fi
}

enable_status_input() {
    local account="$1"
    local index_name="$2"
    local input_name="${INPUT_NAME:-${account}_status}"
    local body

    log "Enabling High Level Status input for account='${account}' index='${index_name}'..."
    body=$(form_urlencode_pairs \
        type "Status" \
        global_account "${account}" \
        index "${index_name}" \
        interval "300" \
        duration "5" \
        metrics_to_collect "${STATUS_METRICS}" \
        disabled "0") || return 1
    body=$(append_form_pair "${body}" "application_list" "${APPLICATION_LIST}") || return 1
    create_named_input "appdynamics_status" "${input_name}" "${body}"
}

enable_database_input() {
    local account="$1"
    local index_name="$2"
    local input_name="${INPUT_NAME:-${account}_database_metrics}"
    local body

    log "Enabling Database Metrics input for account='${account}' index='${index_name}'..."
    body=$(form_urlencode_pairs \
        type "Database" \
        global_account "${account}" \
        index "${index_name}" \
        interval "300" \
        duration "5" \
        metrics_to_collect "${DATABASE_METRICS}" \
        collect_baselines_radio "default" \
        compress_data_flag "1" \
        disabled "0") || return 1
    create_named_input "appdynamics_database_metrics" "${input_name}" "${body}"
}

enable_hardware_input() {
    local account="$1"
    local index_name="$2"
    local input_name="${INPUT_NAME:-${account}_hardware_metrics}"
    local body

    log "Enabling Hardware Metrics input for account='${account}' index='${index_name}'..."
    body=$(form_urlencode_pairs \
        type "Hardware" \
        global_account "${account}" \
        index "${index_name}" \
        interval "300" \
        duration "5" \
        metrics_to_collect "${HARDWARE_METRICS}" \
        tiernode_radio "tier" \
        collect_baselines_radio "default" \
        compress_data_flag "1" \
        disabled "0") || return 1
    body=$(append_form_pair "${body}" "application_list" "${APPLICATION_LIST}") || return 1
    create_named_input "appdynamics_hardware_metrics" "${input_name}" "${body}"
}

enable_snapshots_input() {
    local account="$1"
    local index_name="$2"
    local input_name="${INPUT_NAME:-${account}_snapshots}"
    local body

    log "Enabling Application Snapshots input for account='${account}' index='${index_name}'..."
    body=$(form_urlencode_pairs \
        type "Snapshots" \
        global_account "${account}" \
        index "${index_name}" \
        interval "300" \
        duration "5" \
        metrics_to_collect "${SNAPSHOT_TYPES}" \
        need_props "1" \
        need_exit_calls "1" \
        first_in_chain "0" \
        archived "0" \
        execution_time_in_milis "0" \
        disabled "0") || return 1
    body=$(append_form_pair "${body}" "application_list" "${APPLICATION_LIST}") || return 1
    create_named_input "appdynamics_application_snapshots" "${input_name}" "${body}"
}

enable_security_input() {
    local account="$1"
    local index_name="$2"
    local input_name="${INPUT_NAME:-${account}_security}"
    local body

    log "Enabling Secure Application input for account='${account}' index='${index_name}'..."
    body=$(form_urlencode_pairs \
        type "Security" \
        global_account "${account}" \
        index "${index_name}" \
        interval "300" \
        duration "5" \
        metrics_to_collect "${SECURITY_METRICS}" \
        disabled "0") || return 1
    body=$(append_form_pair "${body}" "application_list" "${APPLICATION_LIST}") || return 1
    create_named_input "appdynamics_security" "${input_name}" "${body}"
}

enable_events_input() {
    local account="$1"
    local index_name="$2"
    local input_name="${INPUT_NAME:-${account}_events}"
    local filters="${EVENT_FILTERS:-${DEFAULT_EVENT_FILTERS}}"
    local body

    log "Enabling Events input for account='${account}' index='${index_name}'..."
    body=$(form_urlencode_pairs \
        type "Events" \
        global_account "${account}" \
        index "${index_name}" \
        interval "300" \
        duration "5" \
        event_filter "${filters}" \
        disabled "0") || return 1
    body=$(append_form_pair "${body}" "application_list" "${APPLICATION_LIST}") || return 1
    create_named_input "appdynamics_events_policy" "${input_name}" "${body}"
}

enable_audit_input() {
    local account="$1"
    local index_name="$2"
    local input_name="${INPUT_NAME:-${account}_audit}"
    local body

    log "Enabling Controller Audit input for account='${account}' index='${index_name}'..."
    body=$(form_urlencode_pairs \
        type "Audit" \
        global_account "${account}" \
        index "${index_name}" \
        interval "300" \
        duration "5" \
        disabled "0") || return 1
    create_named_input "appdynamics_audit" "${input_name}" "${body}"
}

enable_licenses_input() {
    local account="$1"
    local index_name="$2"
    local input_name="${INPUT_NAME:-${account}_licenses}"
    local body

    log "Enabling License Usage input for account='${account}' index='${index_name}'..."
    body=$(form_urlencode_pairs \
        type "License" \
        global_account "${account}" \
        index "${index_name}" \
        interval "3600" \
        duration "1440" \
        disabled "0") || return 1
    create_named_input "appdynamics_licenses" "${input_name}" "${body}"
}

enable_analytics_input() {
    local index_name="$1"
    local source_name="${SOURCE_NAME:-appdynamics_analytics}"
    local input_name="${INPUT_NAME:-${ANALYTICS_ACCOUNT}_analytics_search}"
    local body

    if [[ -z "${ANALYTICS_ACCOUNT}" || -z "${QUERY}" ]]; then
        log "ERROR: analytics input requires --analytics-account and --query"
        exit 1
    fi

    log "Enabling Analytics Search input for analytics-account='${ANALYTICS_ACCOUNT}' index='${index_name}'..."
    body=$(form_urlencode_pairs \
        type "Analytics" \
        global_account "N/A (Analytics)" \
        analytics_account "${ANALYTICS_ACCOUNT}" \
        index "${index_name}" \
        interval "300" \
        duration "5" \
        query "${QUERY}" \
        source_entry "${source_name}" \
        disabled "0") || return 1
    create_named_input "appdynamics_analytics_api" "${input_name}" "${body}"
}

enable_custom_input() {
    local account="$1"
    local index_name="$2"
    local source_name="${SOURCE_NAME:-appdynamics_custom_metric}"
    local source_type="${SOURCE_TYPE:-appdynamics_custom_data}"
    local input_name="${INPUT_NAME:-${account}_custom_metrics}"
    local body

    if [[ -z "${METRIC_PATHS}" ]]; then
        log "ERROR: custom input requires --metric-paths"
        exit 1
    fi

    log "Enabling Custom Metrics input for account='${account}' index='${index_name}'..."
    body=$(form_urlencode_pairs \
        type "Custom" \
        global_account "${account}" \
        index "${index_name}" \
        interval "300" \
        duration "5" \
        metrics_to_collect "${METRIC_PATHS}" \
        source_entry "${source_name}" \
        source_type_entry "${source_type}" \
        collect_baselines_radio "default" \
        compress_data_flag "1" \
        disabled "0") || return 1
    body=$(append_form_pair "${body}" "application_list" "${APPLICATION_LIST}") || return 1
    create_named_input "appdynamics_custom_metrics" "${input_name}" "${body}"
}

enable_recommended_inputs() {
    local account="$1"
    local index_name="$2"
    local saved_input_name="${INPUT_NAME}"

    INPUT_NAME=""
    enable_status_input "${account}" "${index_name}"
    enable_events_input "${account}" "${index_name}"
    enable_security_input "${account}" "${index_name}"
    enable_audit_input "${account}" "${index_name}"
    enable_licenses_input "${account}" "${index_name}"
    INPUT_NAME="${saved_input_name}"
    log "Recommended inputs enabled (5 inputs)."
}

enable_all_inputs() {
    local account="$1"
    local index_name="$2"
    local saved_input_name="${INPUT_NAME}"

    INPUT_NAME=""
    enable_recommended_inputs "${account}" "${index_name}"
    enable_database_input "${account}" "${index_name}"
    enable_hardware_input "${account}" "${index_name}"
    enable_snapshots_input "${account}" "${index_name}"
    INPUT_NAME="${saved_input_name}"
    log "All standard controller inputs enabled (8 inputs; analytics and custom excluded)."
}

show_dashboard_index_note() {
    if [[ "${INDEX}" != "appdynamics" ]]; then
        log "NOTE: Built-in dashboards default to index=appdynamics."
        log "      Enter '${INDEX}' manually in each dashboard's Index field when viewing the shipped forms."
    fi
}

main() {
    warn_if_current_skill_role_unsupported

    if ${ENABLE_INPUTS}; then
        check_prereqs
        if [[ -z "${INPUT_TYPE}" ]]; then
            log "ERROR: --enable-inputs requires --input-type"
            exit 1
        fi

        case "${INPUT_TYPE}" in
            recommended|all|status|database|hardware|snapshots|security|events|audit|licenses|custom)
                if [[ -z "${ACCOUNT}" ]]; then
                    log "ERROR: --enable-inputs with '${INPUT_TYPE}' requires --account"
                    exit 1
                fi
                ;;
            analytics)
                ;;
            *)
                log "ERROR: Unknown input type '${INPUT_TYPE}'."
                log "Use: recommended, all, status, database, hardware, snapshots, security, events, audit, licenses, analytics, custom"
                exit 1
                ;;
        esac

        case "${INPUT_TYPE}" in
            recommended) enable_recommended_inputs "${ACCOUNT}" "${INDEX}" ;;
            all) enable_all_inputs "${ACCOUNT}" "${INDEX}" ;;
            status) enable_status_input "${ACCOUNT}" "${INDEX}" ;;
            database) enable_database_input "${ACCOUNT}" "${INDEX}" ;;
            hardware) enable_hardware_input "${ACCOUNT}" "${INDEX}" ;;
            snapshots) enable_snapshots_input "${ACCOUNT}" "${INDEX}" ;;
            security) enable_security_input "${ACCOUNT}" "${INDEX}" ;;
            events) enable_events_input "${ACCOUNT}" "${INDEX}" ;;
            audit) enable_audit_input "${ACCOUNT}" "${INDEX}" ;;
            licenses) enable_licenses_input "${ACCOUNT}" "${INDEX}" ;;
            analytics) enable_analytics_input "${INDEX}" ;;
            custom) enable_custom_input "${ACCOUNT}" "${INDEX}" ;;
        esac

        log_live_input_summary
        log "$(log_platform_restart_guidance "input changes")"
        exit 0
    fi

    if ${SETTINGS_ONLY}; then
        check_prereqs
        configure_settings
        show_dashboard_index_note
        exit 0
    fi

    if ${INDEXES_ONLY}; then
        create_indexes
        show_dashboard_index_note
        exit 0
    fi

    check_prereqs
    create_indexes
    configure_settings
    ensure_app_visible
    log "Setup complete."
    show_dashboard_index_note
    log "$(log_platform_restart_guidance "index changes")"

    [[ -t 0 ]] || return 0

    log ""
    read -rp "Would you like to configure an AppDynamics controller connection now? [y/N]: " yn
    case "${yn}" in
        [yY]|[yY][eE][sS]) ;;
        *) return 0 ;;
    esac

    local acct_name controller_url client_name secret_file input_choice
    read -rp "Controller connection name (e.g. PROD): " acct_name
    [[ -z "${acct_name}" ]] && { log "ERROR: Connection name is required."; return 1; }
    read -rp "Controller URL (e.g. https://example.saas.appdynamics.com): " controller_url
    [[ -z "${controller_url}" ]] && { log "ERROR: Controller URL is required."; return 1; }
    read -rp "AppDynamics client name: " client_name
    [[ -z "${client_name}" ]] && { log "ERROR: Client name is required."; return 1; }

    log ""
    log "Write your AppDynamics client secret to a temp file:"
    log "  bash skills/shared/scripts/write_secret_file.sh /tmp/appd_client_secret"
    log ""
    read -rp "Path to client secret file (default: /tmp/appd_client_secret): " secret_file
    secret_file="${secret_file:-/tmp/appd_client_secret}"
    [[ -f "${secret_file}" ]] || { log "ERROR: File not found: ${secret_file}"; return 1; }

    read -rp "Enable inputs now? [recommended/all/none] (default: recommended): " input_choice
    input_choice="${input_choice:-recommended}"

    log ""
    if [[ "${input_choice}" == "none" ]]; then
        bash "${SCRIPT_DIR}/configure_account.sh" \
            --name "${acct_name}" \
            --controller-url "${controller_url}" \
            --client-name "${client_name}" \
            --client-secret-file "${secret_file}" \
            --index "${INDEX}"
    else
        bash "${SCRIPT_DIR}/configure_account.sh" \
            --name "${acct_name}" \
            --controller-url "${controller_url}" \
            --client-name "${client_name}" \
            --client-secret-file "${secret_file}" \
            --create-inputs "${input_choice}" \
            --index "${INDEX}"
    fi

    rm -f "${secret_file}" 2>/dev/null || true

    log ""
    read -rp "Would you like to configure an AppDynamics analytics connection now? [y/N]: " analytics_yn
    case "${analytics_yn}" in
        [yY]|[yY][eE][sS]) ;;
        *) return 0 ;;
    esac

    local analytics_name analytics_global_name analytics_endpoint analytics_secret_file
    local onprem_url analytics_query analytics_source_name

    read -rp "Analytics connection name (e.g. PROD_ANALYTICS): " analytics_name
    [[ -z "${analytics_name}" ]] && { log "ERROR: Analytics connection name is required."; return 1; }
    read -rp "Global analytics account name: " analytics_global_name
    [[ -z "${analytics_global_name}" ]] && { log "ERROR: Global analytics account name is required."; return 1; }
    read -rp "Analytics endpoint (default: https://analytics.api.appdynamics.com, or 'none' for on-prem): " analytics_endpoint
    analytics_endpoint="${analytics_endpoint:-https://analytics.api.appdynamics.com}"
    onprem_url=""
    if [[ "$(printf '%s' "${analytics_endpoint}" | tr '[:upper:]' '[:lower:]')" == "none" ]]; then
        read -rp "On-prem analytics URL: " onprem_url
        [[ -z "${onprem_url}" ]] && { log "ERROR: On-prem analytics URL is required when endpoint is none."; return 1; }
    fi

    log ""
    log "Write your AppDynamics analytics secret to a temp file:"
    log "  bash skills/shared/scripts/write_secret_file.sh /tmp/appd_analytics_secret"
    log ""
    read -rp "Path to analytics secret file (default: /tmp/appd_analytics_secret): " analytics_secret_file
    analytics_secret_file="${analytics_secret_file:-/tmp/appd_analytics_secret}"
    [[ -f "${analytics_secret_file}" ]] || { log "ERROR: File not found: ${analytics_secret_file}"; return 1; }

    read -rp "Create an Analytics Search input now? [y/N]: " analytics_input_yn
    log ""
    if [[ "${analytics_input_yn}" =~ ^([yY]|[yY][eE][sS])$ ]]; then
        read -rp "ADQL query: " analytics_query
        [[ -z "${analytics_query}" ]] && { log "ERROR: Query is required."; return 1; }
        read -rp "Analytics source name (default: appdynamics_analytics): " analytics_source_name
        analytics_source_name="${analytics_source_name:-appdynamics_analytics}"
        declare -a analytics_args=(
            "${SCRIPT_DIR}/configure_analytics.sh"
            --name "${analytics_name}"
            --global-account-name "${analytics_global_name}"
            --analytics-secret-file "${analytics_secret_file}"
            --endpoint "${analytics_endpoint}"
            --query "${analytics_query}"
            --source-name "${analytics_source_name}"
            --index "${INDEX}"
        )
        if [[ -n "${onprem_url}" ]]; then
            analytics_args+=(--onprem-url "${onprem_url}")
        fi
        bash "${analytics_args[@]}"
    else
        declare -a analytics_args=(
            "${SCRIPT_DIR}/configure_analytics.sh"
            --name "${analytics_name}"
            --global-account-name "${analytics_global_name}"
            --analytics-secret-file "${analytics_secret_file}"
            --endpoint "${analytics_endpoint}"
        )
        if [[ -n "${onprem_url}" ]]; then
            analytics_args+=(--onprem-url "${onprem_url}")
        fi
        bash "${analytics_args[@]}"
    fi

    rm -f "${analytics_secret_file}" 2>/dev/null || true
    log ""
    log "Run 'bash ${SCRIPT_DIR}/validate.sh' to verify the deployment."
}

main

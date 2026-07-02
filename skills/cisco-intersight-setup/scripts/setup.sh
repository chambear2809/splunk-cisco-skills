#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/platform_version_helpers.sh"

APP_NAME="Splunk_TA_Cisco_Intersight"
APP_ID="7828"
VERIFIED_APP_VERSION="3.1.1"
PUBLIC_APP_VERSION="3.2.0"

INDEXES_ONLY=false
MACROS_ONLY=false
ENABLE_INPUTS=false
ACCOUNT=""
INDEX=""
INPUT_TYPE=""
APP_VERSION="${SPLUNK_APP_VERSION:-}"
TARGET_SPLUNK_VERSION="${SPLUNK_TARGET_VERSION:-}"
ACCEPT_UNSUPPORTED_PLATFORM="${SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM:-false}"

resolve_configuration_target_version() {
    local raw="${TARGET_SPLUNK_VERSION:-}"
    if [[ -z "${raw}" ]]; then
        if is_splunk_cloud; then
            raw="$(spv_cloud_doc_train_default)"
        else
            raw="$(spv_enterprise_default)"
        fi
    fi
    if [[ ! "${raw}" =~ ^([0-9]+)\.([0-9]+)(\.[0-9]+)?$ ]]; then
        log "ERROR: Target Splunk version '${raw}' must use MAJOR.MINOR or MAJOR.MINOR.PATCH."
        return 1
    fi
    TARGET_SPLUNK_VERSION="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}"
    export SPLUNK_TARGET_VERSION="${TARGET_SPLUNK_VERSION}"
    export SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM="${ACCEPT_UNSUPPORTED_PLATFORM}"
}

require_configuration_version_compatible() {
    local selected_version="${1:-}"
    local version_source="${2:-selected package}"

    [[ "${TARGET_SPLUNK_VERSION}" == "10.5" ]] || return 0
    if [[ "${selected_version}" == "${VERIFIED_APP_VERSION}" ]]; then
        log "Compatibility preflight passed: ${version_source} ${APP_NAME} (app ID ${APP_ID}) ${VERIFIED_APP_VERSION} is repo-verified for Splunk 10.5."
        return 0
    fi
    if [[ "${ACCEPT_UNSUPPORTED_PLATFORM}" == "true" ]]; then
        log "WARNING: Explicit vendor-approved override accepted for ${version_source} ${APP_NAME} (app ID ${APP_ID}) ${selected_version:-unknown} on Splunk ${TARGET_SPLUNK_VERSION}."
        return 0
    fi

    log "ERROR: ${version_source} ${APP_NAME} ${selected_version:-unknown} is not the repo-verified Splunk 10.5 package (${VERIFIED_APP_VERSION})."
    if [[ "${selected_version}" == "${PUBLIC_APP_VERSION}" ]]; then
        log "The public ${PUBLIC_APP_VERSION} release does not advertise Splunk 10.5 compatibility."
    fi
    log "Refusing configuration before any REST mutation. Pass --accept-unsupported-platform only with documented vendor approval for this exact package and stack."
    return 1
}

preflight_configuration_platform() {
    resolve_configuration_target_version || return 1
    if [[ "${TARGET_SPLUNK_VERSION}" == "10.5" && -n "${APP_VERSION}" ]]; then
        require_configuration_version_compatible "${APP_VERSION}" "selected"
        return $?
    fi
    if [[ "${TARGET_SPLUNK_VERSION}" == "10.5" ]]; then
        log "INFO: No --app-version supplied; the installed ${APP_NAME} version will be read and verified before any REST mutation."
    fi
}

verify_installed_package_before_mutation() {
    local installed_version
    [[ "${TARGET_SPLUNK_VERSION}" == "10.5" ]] || return 0
    installed_version="$(rest_get_app_version "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || true)"
    require_configuration_version_compatible "${installed_version}" "installed"
}

usage() {
    cat >&2 <<EOF
Cisco Intersight TA Setup Automation

Usage: $(basename "$0") [OPTIONS]

Options:
  --indexes-only          Create indexes only
  --macros-only           Create macros only
  --enable-inputs         Enable data inputs
  --account NAME          Account name for input enablement
  --index INDEX           Target index for inputs
  --input-type TYPE       Input type: audit_alarms, inventory, metrics, all
  --app-version VERSION   Installed package version being configured
                          (default contract: repo-verified ${VERIFIED_APP_VERSION})
  --target-splunk-version V
                          Target Splunk MAJOR.MINOR[.PATCH]
  --accept-unsupported-platform
                          Allow an unverified package/version combination only
                          with documented vendor approval
  --help                  Show this help

With no flags, runs full setup (indexes + macros).
Runs against remote Splunk via search-tier REST API (set
SPLUNK_SEARCH_API_URI for non-localhost; legacy alias: SPLUNK_URI).
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --macros-only) MACROS_ONLY=true; shift ;;
        --enable-inputs) ENABLE_INPUTS=true; shift ;;
        --account) require_arg "$1" $# || exit 1; ACCOUNT="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --input-type) require_arg "$1" $# || exit 1; INPUT_TYPE="$2"; shift 2 ;;
        --app-version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --target-splunk-version) require_arg "$1" $# || exit 1; TARGET_SPLUNK_VERSION="$2"; shift 2 ;;
        --accept-unsupported-platform) ACCEPT_UNSUPPORTED_PLATFORM=true; shift ;;
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
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk"; exit 1; }
}

check_prereqs() {
    ensure_search_api_session
    if ! rest_check_app "$SK" "$SPLUNK_URI" "Splunk_TA_Cisco_Intersight"; then
        log "ERROR: Cisco Intersight TA not installed"
        exit 1
    fi
    verify_installed_package_before_mutation || exit 1
}

create_indexes() {
    log "Creating indexes..."
    if ! is_splunk_cloud; then
        ensure_search_api_session
    fi
    if platform_create_index "${SK:-}" "$SPLUNK_URI" "intersight" "512000"; then
        log "  Index 'intersight' created or already exists"
    else
        log "  ERROR: Failed to create index 'intersight'"
        return 1
    fi
    log "Index creation complete."
}

ensure_app_visible() {
    ensure_search_api_session
    log "Ensuring ${APP_NAME} is visible..."
    deployment_set_app_visible "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "true" \
        || { log "ERROR: Failed to make ${APP_NAME} visible."; return 1; }
}

create_macros() {
    log "Configuring macros..."
    local def_encoded
    def_encoded=$(_urlencode 'index IN (intersight)')
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

    local audit_body alarms_body
    audit_body=$(form_urlencode_pairs \
        global_account "${account}" \
        index "${index}" \
        interval "900" \
        date_input "7" \
        enable_aaa_audit_records "1" \
        enable_alarms "0" \
        acknowledge "0" \
        suppressed "0" \
        info_alarms "0" \
        disabled "0")
    alarms_body=$(form_urlencode_pairs \
        global_account "${account}" \
        index "${index}" \
        interval "900" \
        date_input "7" \
        enable_aaa_audit_records "0" \
        enable_alarms "1" \
        acknowledge "1" \
        suppressed "1" \
        info_alarms "1" \
        disabled "0")

    local failures=0

    if rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "audit_alarms" "${account}_audit_logs" "${audit_body}"; then
        log "  Added: audit_alarms://${account}_audit_logs"
    else
        log "  ERROR: Failed to create audit_alarms://${account}_audit_logs"
        failures=$((failures + 1))
    fi

    if rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "audit_alarms" "${account}_alarms" "${alarms_body}"; then
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
    preflight_configuration_platform || exit 1
    warn_if_current_skill_role_unsupported
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
        log "$(log_platform_restart_guidance "input changes")"
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
    ensure_app_visible
    log "Index/macro setup complete; onboarding remains incomplete until account, input, event, and dashboard validation passes."
    log "$(log_platform_restart_guidance "index or macro changes")"

    [[ -t 0 ]] || return 0
    log ""
    read -rp "Would you like to configure an Intersight account now? [y/N]: " yn
    case "${yn}" in
        [yY]|[yY][eE][sS]) ;;
        *) return 0 ;;
    esac

    local acct_name client_id hostname secret_file
    read -rp "Account name (e.g. CVF_Intersight): " acct_name
    [[ -z "${acct_name}" ]] && { log "ERROR: Account name is required."; return 1; }
    read -rp "Intersight hostname (default: intersight.com): " hostname
    hostname="${hostname:-intersight.com}"
    read -rp "OAuth2 Client ID: " client_id
    [[ -z "${client_id}" ]] && { log "ERROR: Client ID is required."; return 1; }

    log ""
    log "Write your OAuth2 Client Secret to a temp file:"
    log "  bash skills/shared/scripts/write_secret_file.sh /tmp/client_secret"
    log ""
    read -rp "Path to client secret file (default: /tmp/client_secret): " secret_file
    secret_file="${secret_file:-/tmp/client_secret}"
    [[ -f "${secret_file}" ]] || { log "ERROR: File not found: ${secret_file}"; return 1; }

    read -rp "Enable default inputs after account creation? [Y/n]: " defaults_yn
    local defaults_flag=""
    case "${defaults_yn}" in
        [nN]|[nN][oO]) ;;
        *) defaults_flag="--create-defaults" ;;
    esac

    log ""
    bash "${SCRIPT_DIR}/configure_account.sh" \
        --name "${acct_name}" \
        --hostname "${hostname}" \
        --client-id "${client_id}" \
        --client-secret-file "${secret_file}" \
        ${defaults_flag:+"${defaults_flag}"}

    rm -f "${secret_file}" 2>/dev/null || true
    log ""
    log "Run 'bash ${SCRIPT_DIR}/validate.sh --completion' to prove deployment completion."
}

main

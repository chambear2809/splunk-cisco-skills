#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/platform_version_helpers.sh"

APP_NAME="cisco-catalyst-app"
APP_ID="7539"
VERIFIED_APP_VERSION="3.1.0"
PUBLIC_APP_VERSION="3.2.0"
CATALYST_TA_APP="TA_cisco_catalyst"
ENHANCED_NETFLOW_TA_APP="splunk_app_stream_ipfix_cisco_hsl"
SOURCETYPE_MACRO_DEFINITION='sourcetype IN ("cisco:ise*", "cisco:sdwan*", "cisco:dnac*", "cisco:catalyst:center:*", "stream:netflow", "cisco:cybervision:*", "meraki:*", "cisco:ios", "cisco:thousandeyes:*")'

MACROS_ONLY=false
ACCELERATE=false
CUSTOM_INDEXES=""
APP_VERSION="${SPLUNK_APP_VERSION:-}"
TARGET_SPLUNK_VERSION="${SPLUNK_TARGET_VERSION:-}"
ACCEPT_UNSUPPORTED_PLATFORM="${SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM:-false}"
readonly SAVED_SEARCHES=(
    "cisco_catalyst_location"
    "cisco_catalyst_sdwan_netflow"
    "cisco_catalyst_sdwan_policy"
    "cisco_catalyst_meraki_organization_mapping"
    "cisco_catalyst_meraki_devices_serial_mapping"
)

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
Cisco Enterprise Networking App Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --macros-only              Update macros only
  --accelerate               Enable data model acceleration
  --custom-indexes "a,b,c"   Use custom index list (comma-separated). Each index
                             must match Splunk's index name rules: only ASCII
                             letters, digits, underscore, and hyphen, 1-80 chars.
  --app-version VERSION      Installed package version being configured
                             (default contract: repo-verified ${VERIFIED_APP_VERSION})
  --target-splunk-version V  Target Splunk MAJOR.MINOR[.PATCH]
  --accept-unsupported-platform
                             Allow an unverified package/version combination only
                             with documented vendor approval
  --help                     Show this help

With no flags, runs full setup (macros + saved search enablement).
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --macros-only) MACROS_ONLY=true; shift ;;
        --accelerate) ACCELERATE=true; shift ;;
        --custom-indexes) require_arg "$1" $# || exit 1; CUSTOM_INDEXES="$2"; shift 2 ;;
        --app-version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --target-splunk-version) require_arg "$1" $# || exit 1; TARGET_SPLUNK_VERSION="$2"; shift 2 ;;
        --accept-unsupported-platform) ACCEPT_UNSUPPORTED_PLATFORM=true; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

preflight_configuration_platform || exit 1
load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

check_prereqs() {
    if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME"; then
        log "ERROR: Cisco Enterprise Networking app not found. Install it first."
        exit 1
    fi
    verify_installed_package_before_mutation || exit 1
    if ! rest_check_app "$SK" "$SPLUNK_URI" "${CATALYST_TA_APP}" 2>/dev/null; then
        log "WARNING: Cisco Catalyst Add-on (${CATALYST_TA_APP}) not found — dashboards may not show Catalyst, ISE, SD-WAN, or Cyber Vision data"
    fi
    if ! rest_check_app "$SK" "$SPLUNK_URI" "${ENHANCED_NETFLOW_TA_APP}" 2>/dev/null; then
        log "WARNING: Optional Cisco Catalyst Enhanced Netflow Add-on (${ENHANCED_NETFLOW_TA_APP}) not found — additional NetFlow-focused dashboards may not show data"
    fi
}

update_macros() {
    log "Updating dashboard macros..."

    local body index_list idx
    if [[ -n "${CUSTOM_INDEXES}" ]]; then
        # Strict allowlist: Splunk index names are ASCII letters/digits/_/- (length 1..80).
        # Reject anything else to prevent SPL injection through the macro definition.
        IFS=',' read -ra _custom_idx_parts <<<"${CUSTOM_INDEXES}"
        for idx in "${_custom_idx_parts[@]}"; do
            if [[ ! "${idx}" =~ ^[A-Za-z0-9_-]{1,80}$ ]]; then
                log "ERROR: --custom-indexes value '${idx}' is not a valid Splunk index name."
                log "  Allowed characters: A-Z a-z 0-9 _ - ; length 1-80; comma-separated."
                return 1
            fi
        done
        index_list=$(printf '%s\n' "${_custom_idx_parts[@]}" | sed 's/^/"/;s/$/"/' | tr '\n' ',' | sed 's/,$//')
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

    body=$(form_urlencode_pairs \
        definition "${SOURCETYPE_MACRO_DEFINITION}" \
        description "Current SCAN-aligned Cisco sourcetypes used by Enterprise Networking dashboards" \
        iseval "0")
    if ! rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_catalyst_app_sourcetypes" "${body}"; then
        log "ERROR: Failed to update macro 'cisco_catalyst_app_sourcetypes'."
        return 1
    fi

    log "  cisco_catalyst_app_sourcetypes = ${SOURCETYPE_MACRO_DEFINITION}"
    log "Macro updates complete."
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
    log "Dashboard prerequisites configured; run '${SCRIPT_DIR}/validate.sh --completion' to prove views and data are ready."
    log "$(log_platform_restart_guidance "saved search or macro changes")"
    log "Tip: Run with --accelerate to enable data model acceleration for production."
}

main

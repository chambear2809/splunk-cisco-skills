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
CLASSINFO_INPUT=""
CLASSINFO_CLASSES=""
CLASSINFO_PRESET=""
CLASSINFO_INTERVAL="300"
DRY_RUN=false

# Application Atlas preset: ACI fabric links, host LLDP neighbors, and the
# contract objects that the shipped classInfo inputs do not collect cleanly.
ADM_CLASSINFO_INPUT="classInfo_adm"
ADM_CLASSINFO_CLASSES="fabricLink lldpAdjEp vzBrCP vzSubj vzRsSubjFiltAtt vzEntry l3extInstP l3extSubnet"
ADM_POLICY_CLASSINFO_INPUT="classInfo_adm_policy"
ADM_POLICY_CLASSINFO_CLASSES="fvCtx fvAEPg fvEPg fvESg vzAny vzRsAnyToCons vzRsAnyToProv vzRsAnyToConsIf vzInTerm vzOutTerm vzTaboo fvRsProtBy vzRsSubjGraphAtt"

# Shipped default ACI stanzas (default/inputs.conf); a custom classInfo input
# must not overwrite their class lists.
SHIPPED_ACI_INPUTS=(
    authentication classInfo_faultInst classInfo_aaaModLR classInfo_fvRsCEpToPathEp
    fex health_fabricHealthTotal health_fvTenant microsegment stats
)

usage() {
    cat >&2 <<EOF
Cisco DC Networking TA Setup Automation

Usage: $(basename "$0") [OPTIONS]

Options:
  --indexes-only          Create indexes only
  --macros-only           Update search macros only
  --enable-inputs         Enable data inputs
  --account NAME          Account name for input enablement
  --index INDEX           Target index for inputs
  --input-type TYPE       Input type: aci, nd, nexus9k
  --classinfo-input NAME  Create or update a custom ACI classInfo input
  --classinfo-classes "C1 C2"
                          Space-separated APIC classes for --classinfo-input
  --classinfo-preset NAME Use a documented preset instead of
                          --classinfo-input/--classinfo-classes
                          (application-atlas or adm: input classInfo_adm;
                          adm-policy: input classInfo_adm_policy)
  --interval SECONDS      Polling interval for the custom input (default: 300)
  --dry-run               With a custom classInfo input, print the planned
                          stanza without contacting Splunk
  --help                  Show this help

With no flags, runs full setup (indexes + macros).
A custom classInfo input requires --account and --index.
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
        --classinfo-input) require_arg "$1" $# || exit 1; CLASSINFO_INPUT="$2"; shift 2 ;;
        --classinfo-classes) require_arg "$1" $# || exit 1; CLASSINFO_CLASSES="$2"; shift 2 ;;
        --classinfo-preset) require_arg "$1" $# || exit 1; CLASSINFO_PRESET="$2"; shift 2 ;;
        --interval) require_arg "$1" $# || exit 1; CLASSINFO_INTERVAL="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
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
        log "ERROR: Cisco DC Networking app not found. Install it first."
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

    for idx in cisco_aci cisco_nd cisco_nexus_9k; do
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

update_macros() {
    log "Updating search macros..."

    local def_aci def_nd def_n9k
    def_aci=$(_urlencode 'index IN ("cisco_aci")')
    def_nd=$(_urlencode 'index IN ("cisco_nd")')
    def_n9k=$(_urlencode 'index IN ("cisco_nexus_9k")')

    if ! rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_dc_aci_index" "definition=${def_aci}"; then
        log "ERROR: Failed to update macro 'cisco_dc_aci_index'."
        return 1
    fi
    if ! rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_dc_nd_index" "definition=${def_nd}"; then
        log "ERROR: Failed to update macro 'cisco_dc_nd_index'."
        return 1
    fi
    if ! rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_dc_n9k_index" "definition=${def_n9k}"; then
        log "ERROR: Failed to update macro 'cisco_dc_n9k_index'."
        return 1
    fi

    log "Macros updated: cisco_dc_aci_index, cisco_dc_nd_index, cisco_dc_n9k_index"
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

    local failures=0
    for input_spec in "${aci_inputs[@]}"; do
        local input_type="${input_spec%%://*}"
        local input_name="${input_spec#*://}"
        local body
        body=$(form_urlencode_pairs \
            disabled "0" \
            apic_account "${account}" \
            index "${index}")
        if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "$input_type" "$input_name" "$body"; then
            log "  ERROR: Failed to enable ${input_type}://${input_name}"
            failures=$((failures + 1))
        fi
    done

    if (( failures != 0 )); then
        log "ACI input enablement failed for ${failures} input(s)."
        return 1
    fi

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

    local failures=0
    for input_spec in "${nd_inputs[@]}"; do
        local input_type="${input_spec%%://*}"
        local input_name="${input_spec#*://}"
        local body
        body=$(form_urlencode_pairs \
            disabled "0" \
            nd_account "${account}" \
            index "${index}")
        if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "$input_type" "$input_name" "$body"; then
            log "  ERROR: Failed to enable ${input_type}://${input_name}"
            failures=$((failures + 1))
        fi
    done

    if (( failures != 0 )); then
        log "Nexus Dashboard input enablement failed for ${failures} input(s)."
        return 1
    fi

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

    local failures=0
    for input_spec in "${n9k_inputs[@]}"; do
        local input_type="${input_spec%%://*}"
        local input_name="${input_spec#*://}"
        local body
        body=$(form_urlencode_pairs \
            disabled "0" \
            nexus_9k_account "${account}" \
            index "${index}")
        if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "$input_type" "$input_name" "$body"; then
            log "  ERROR: Failed to enable ${input_type}://${input_name}"
            failures=$((failures + 1))
        fi
    done

    if (( failures != 0 )); then
        log "Nexus 9K input enablement failed for ${failures} input(s)."
        return 1
    fi

    log "Nexus 9K inputs enabled."
}

resolve_classinfo_request() {
    if [[ -n "${CLASSINFO_PRESET}" ]]; then
        if [[ -n "${CLASSINFO_INPUT}" || -n "${CLASSINFO_CLASSES}" ]]; then
            log "ERROR: --classinfo-preset cannot be combined with --classinfo-input or --classinfo-classes."
            return 1
        fi
        case "${CLASSINFO_PRESET}" in
            application-atlas|adm)
                CLASSINFO_INPUT="${ADM_CLASSINFO_INPUT}"
                CLASSINFO_CLASSES="${ADM_CLASSINFO_CLASSES}"
                ;;
            adm-policy)
                CLASSINFO_INPUT="${ADM_POLICY_CLASSINFO_INPUT}"
                CLASSINFO_CLASSES="${ADM_POLICY_CLASSINFO_CLASSES}"
                ;;
            *)
                log "ERROR: Unknown --classinfo-preset '${CLASSINFO_PRESET}'. Use: application-atlas (alias adm), adm-policy"
                return 1
                ;;
        esac
    fi
    if [[ -z "${CLASSINFO_INPUT}" || -z "${CLASSINFO_CLASSES}" ]]; then
        log "ERROR: A custom classInfo input requires --classinfo-input and --classinfo-classes, or --classinfo-preset."
        return 1
    fi
    if [[ -z "${ACCOUNT}" || -z "${INDEX}" ]]; then
        log "ERROR: A custom classInfo input requires --account and --index."
        return 1
    fi
    # Account, input name, class list, interval and index patterns mirror the
    # TA's globalConfig.json validators for ACI accounts and cisco_nexus_aci
    # inputs; apic_account accepts a comma-separated account list.
    if [[ ! "${ACCOUNT}" =~ ^[A-Za-z][A-Za-z0-9_]{0,49}(,[A-Za-z][A-Za-z0-9_]{0,49})*$ ]]; then
        log "ERROR: --account must be one or more comma-separated ACI account names (letter first, then letters, digits or underscores; max 50 each)."
        return 1
    fi
    if [[ ! "${CLASSINFO_INPUT}" =~ ^[A-Za-z][A-Za-z0-9_]{0,99}$ ]]; then
        log "ERROR: --classinfo-input must start with a letter and contain only letters, digits or underscores (max 100)."
        return 1
    fi
    local shipped
    for shipped in "${SHIPPED_ACI_INPUTS[@]}"; do
        if [[ "${CLASSINFO_INPUT}" == "${shipped}" ]]; then
            log "ERROR: '${CLASSINFO_INPUT}' is a shipped default input; choose a new name so its class list is not overwritten."
            return 1
        fi
    done
    local normalized="" class classes=()
    read -r -a classes <<< "${CLASSINFO_CLASSES}"
    if (( ${#classes[@]} == 0 )); then
        log "ERROR: --classinfo-classes must list at least one APIC class."
        return 1
    fi
    for class in "${classes[@]}"; do
        if [[ ! "${class}" =~ ^[A-Za-z0-9_-]+$ ]]; then
            log "ERROR: APIC class names may contain only letters, digits, underscores and hyphens."
            return 1
        fi
        case " ${normalized} " in
            *" ${class} "*) ;;
            *) normalized="${normalized:+${normalized} }${class}" ;;
        esac
    done
    if [[ -z "${normalized}" ]]; then
        log "ERROR: --classinfo-classes must list at least one APIC class."
        return 1
    fi
    CLASSINFO_CLASSES="${normalized}"
    if [[ ! "${CLASSINFO_INTERVAL}" =~ ^[1-9][0-9]*$ ]]; then
        log "ERROR: --interval must be a positive integer number of seconds."
        return 1
    fi
    if [[ ! "${INDEX}" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$ ]]; then
        log "ERROR: --index must begin with a letter or digit and contain only letters, digits, underscores or hyphens (max 80)."
        return 1
    fi
}

render_classinfo_stanza() {
    cat <<EOF
[cisco_nexus_aci://${CLASSINFO_INPUT}]
apic_account = ${ACCOUNT}
apic_input_type = classInfo
apic_arguments = ${CLASSINFO_CLASSES}
interval = ${CLASSINFO_INTERVAL}
index = ${INDEX}
disabled = 0
EOF
}

apply_classinfo_input() {
    log "Creating or updating cisco_nexus_aci://${CLASSINFO_INPUT} for account='${ACCOUNT}' index='${INDEX}'..."
    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        apic_account "${ACCOUNT}" \
        apic_input_type "classInfo" \
        apic_arguments "${CLASSINFO_CLASSES}" \
        interval "${CLASSINFO_INTERVAL}" \
        index "${INDEX}")
    if ! rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "cisco_nexus_aci" "${CLASSINFO_INPUT}" "$body"; then
        log "ERROR: Failed to create or enable cisco_nexus_aci://${CLASSINFO_INPUT}"
        return 1
    fi
    log "Custom classInfo input enabled: cisco_nexus_aci://${CLASSINFO_INPUT} (${CLASSINFO_CLASSES})"
}

main() {
    warn_if_current_skill_role_unsupported

    if [[ -n "${CLASSINFO_INPUT}${CLASSINFO_CLASSES}${CLASSINFO_PRESET}" ]]; then
        if $ENABLE_INPUTS || $INDEXES_ONLY || $MACROS_ONLY; then
            log "ERROR: A custom classInfo input cannot be combined with --enable-inputs, --indexes-only or --macros-only."
            exit 1
        fi
        resolve_classinfo_request || exit 1
        if $DRY_RUN; then
            log "Dry run: planned inputs.conf stanza for app ${APP_NAME} (no changes made):"
            render_classinfo_stanza
            exit 0
        fi
        check_prereqs
        apply_classinfo_input || exit 1
        log_live_input_summary
        log "$(log_platform_restart_guidance "input changes")"
        log "Validate with: ${SCRIPT_DIR}/validate.sh --classinfo-input ${CLASSINFO_INPUT} --index ${INDEX}"
        exit 0
    fi
    if $DRY_RUN; then
        log "ERROR: --dry-run is supported only with a custom classInfo input."
        exit 1
    fi

    if $ENABLE_INPUTS; then
        check_prereqs
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
        log "$(log_platform_restart_guidance "input changes")"
        exit 0
    fi

    if $INDEXES_ONLY; then
        create_indexes
        exit 0
    fi

    if $MACROS_ONLY; then
        check_prereqs
        update_macros
        exit 0
    fi

    check_prereqs
    create_indexes
    update_macros
    log "Index/macro setup complete; run '${SCRIPT_DIR}/validate.sh --completion' after configuring an account and input."
    log "$(log_platform_restart_guidance "index or macro changes")"
}

main

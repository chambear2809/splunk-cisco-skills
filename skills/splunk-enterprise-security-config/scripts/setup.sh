#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="SplunkEnterpriseSecuritySuite"
VALIDATE_SCRIPT="${VALIDATE_SCRIPT:-${SCRIPT_DIR}/validate.sh}"
ENGINE="${ENGINE:-${SCRIPT_DIR}/es_config_engine.py}"

DO_SET_LOOKUP_ORDER=false
DO_SET_MANAGED_ROLES=false
DO_CREATE_CORE_INDEXES=false
DO_CREATE_UEBA_INDEXES=false
DO_CREATE_PCI_INDEXES=false
DO_CREATE_EXPOSURE_INDEXES=false
DO_CREATE_MISSION_CONTROL_INDEXES=false
DO_CREATE_DLX_INDEXES=false
DO_VALIDATE=false
ANY_OPERATION=false
BASELINE=false
ALL_INDEXES=false

MANAGED_ROLES=""
MAX_SIZE_MB="512000"
ENABLE_DMS=()
DISABLE_DMS=()
SPEC_PATH=""
MODE="preview"
MODE_SET=false
APPLY=false
OUTPUT_PATH=""
STOP_ON_ERROR=false
STRICT=false
SK=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Enterprise Security Configuration

Usage: $(basename "$0") [OPTIONS]

Operations:
  --set-lookup-order                Set limits.conf [lookup] enforce_auto_lookup_order=true
  --set-managed-roles ROLES         Comma-separated managed roles for App Permissions Manager
  --create-core-indexes             Create core ES indexes via platform index helper
  --create-ueba-indexes             Create UEBA/behavioral analytics indexes
  --create-pci-indexes              Create PCI indexes
  --create-exposure-indexes         Create exposure analytics indexes
  --create-mission-control-indexes  Create Mission Control indexes bundled with ES 8.x
  --create-dlx-indexes              Create detection lifecycle/confidence indexes
  --enable-dm NAME                  Enable dm_accel_settings://NAME
  --disable-dm NAME                 Disable acceleration for dm_accel_settings://NAME
  --baseline                        Apply baseline flags: lookup order, managed roles, all indexes, validate
  --all-indexes                     Create all ES index groups
  --spec PATH                       Declarative ES YAML/JSON spec
  --mode preview|apply|validate|inventory|export
                                    Declarative workflow mode (default: preview)
  --apply                           Required for declarative apply mode
  --validate                        Run validation after changes
  (no flags)                        Run validation only

Options:
  --max-size-mb N                   maxTotalDataSizeMB for new indexes (default: 512000)
  --output PATH                     Write declarative workflow JSON output to a file
  --stop-on-error                   Halt declarative apply on first failed action (no rollback)
  --strict                          Fail fast on unknown top-level YAML sections (typo guard)
  --help                            Show this help text

Examples:
  $(basename "$0") --set-lookup-order --set-managed-roles ess_analyst,ess_user --validate
  $(basename "$0") --create-core-indexes --create-mission-control-indexes --create-exposure-indexes --max-size-mb 1024000 --validate
  $(basename "$0") --enable-dm Authentication --enable-dm Network_Traffic --validate
  $(basename "$0") --spec skills/splunk-enterprise-security-config/templates/es-config.example.yaml
  $(basename "$0") --spec es-config.yaml --apply --validate

EOF
    exit "${exit_code}"
}

set_operation() {
    ANY_OPERATION=true
    case "$1" in
        lookup-order) DO_SET_LOOKUP_ORDER=true ;;
        managed-roles) DO_SET_MANAGED_ROLES=true ;;
        core-indexes) DO_CREATE_CORE_INDEXES=true ;;
        ueba-indexes) DO_CREATE_UEBA_INDEXES=true ;;
        pci-indexes) DO_CREATE_PCI_INDEXES=true ;;
        exposure-indexes) DO_CREATE_EXPOSURE_INDEXES=true ;;
        mission-control-indexes) DO_CREATE_MISSION_CONTROL_INDEXES=true ;;
        dlx-indexes) DO_CREATE_DLX_INDEXES=true ;;
        validate) DO_VALIDATE=true ;;
    esac
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --set-lookup-order) set_operation lookup-order; shift ;;
        --set-managed-roles)
            require_arg "$1" $# || exit 1
            MANAGED_ROLES="$2"
            set_operation managed-roles
            shift 2
            ;;
        --create-core-indexes) set_operation core-indexes; shift ;;
        --create-ueba-indexes) set_operation ueba-indexes; shift ;;
        --create-pci-indexes) set_operation pci-indexes; shift ;;
        --create-exposure-indexes) set_operation exposure-indexes; shift ;;
        --create-mission-control-indexes) set_operation mission-control-indexes; shift ;;
        --create-dlx-indexes) set_operation dlx-indexes; shift ;;
        --baseline) BASELINE=true; ANY_OPERATION=true; shift ;;
        --all-indexes) ALL_INDEXES=true; ANY_OPERATION=true; shift ;;
        --spec)
            require_arg "$1" $# || exit 1
            SPEC_PATH="$2"
            ANY_OPERATION=true
            shift 2
            ;;
        --mode)
            require_arg "$1" $# || exit 1
            MODE="$2"
            MODE_SET=true
            ANY_OPERATION=true
            shift 2
            ;;
        --apply)
            APPLY=true
            ANY_OPERATION=true
            shift
            ;;
        --output)
            require_arg "$1" $# || exit 1
            OUTPUT_PATH="$2"
            shift 2
            ;;
        --stop-on-error) STOP_ON_ERROR=true; ANY_OPERATION=true; shift ;;
        --strict) STRICT=true; ANY_OPERATION=true; shift ;;
        --enable-dm)
            require_arg "$1" $# || exit 1
            ENABLE_DMS+=("$2")
            ANY_OPERATION=true
            shift 2
            ;;
        --disable-dm)
            require_arg "$1" $# || exit 1
            DISABLE_DMS+=("$2")
            ANY_OPERATION=true
            shift 2
            ;;
        --max-size-mb)
            require_arg "$1" $# || exit 1
            MAX_SIZE_MB="$2"
            shift 2
            ;;
        --validate) set_operation validate; shift ;;
        --help|-h) usage 0 ;;
        *)
            log "ERROR: Unknown option '$1'"
            usage 1
            ;;
    esac
done

case "${MAX_SIZE_MB}" in
    ''|*[!0-9]*)
        log "ERROR: --max-size-mb must be an integer."
        exit 1
        ;;
esac

case "${MODE}" in
    preview|apply|validate|inventory|export) ;;
    *)
        log "ERROR: --mode must be preview, apply, validate, inventory, or export."
        exit 1
        ;;
esac

if [[ "${APPLY}" == "true" ]]; then
    if [[ "${MODE_SET}" == "true" && "${MODE}" != "apply" ]]; then
        log "ERROR: --apply cannot be combined with --mode ${MODE}."
        exit 1
    fi
    MODE="apply"
fi

if [[ "${MODE}" == "apply" && "${APPLY}" != "true" ]]; then
    log "ERROR: Declarative apply mode requires --apply."
    exit 1
fi

run_declarative_workflow() {
    local args=("--mode" "${MODE}")
    if [[ -n "${SPEC_PATH}" ]]; then
        args+=("--spec" "${SPEC_PATH}")
    fi
    if [[ -n "${OUTPUT_PATH}" ]]; then
        args+=("--output" "${OUTPUT_PATH}")
    fi
    if [[ "${STOP_ON_ERROR}" == "true" ]]; then
        args+=("--stop-on-error")
    fi
    if [[ "${STRICT}" == "true" ]]; then
        args+=("--strict")
    fi
    python3 "${ENGINE}" "${args[@]}" || return $?
}

# Detect imperative shortcuts so we can run them after the declarative phase
# instead of silently dropping them when --spec/--mode/--apply are also set.
# --stop-on-error/--strict are declarative modifiers, not imperative work, so
# they do NOT trigger the imperative phase on their own.
imperative_phase_requested() {
    [[ "${BASELINE}" == "true" ]] && return 0
    [[ "${ALL_INDEXES}" == "true" ]] && return 0
    [[ "${DO_SET_LOOKUP_ORDER}" == "true" ]] && return 0
    [[ "${DO_SET_MANAGED_ROLES}" == "true" ]] && return 0
    [[ "${DO_CREATE_CORE_INDEXES}" == "true" ]] && return 0
    [[ "${DO_CREATE_UEBA_INDEXES}" == "true" ]] && return 0
    [[ "${DO_CREATE_PCI_INDEXES}" == "true" ]] && return 0
    [[ "${DO_CREATE_EXPOSURE_INDEXES}" == "true" ]] && return 0
    [[ "${DO_CREATE_MISSION_CONTROL_INDEXES}" == "true" ]] && return 0
    [[ "${DO_CREATE_DLX_INDEXES}" == "true" ]] && return 0
    if (( ${#ENABLE_DMS[@]} > 0 )); then return 0; fi
    if (( ${#DISABLE_DMS[@]} > 0 )); then return 0; fi
    return 1
}

DECLARATIVE_REQUESTED=false
if [[ -n "${SPEC_PATH}" || "${MODE_SET}" == "true" || -n "${OUTPUT_PATH}" || "${APPLY}" == "true" ]]; then
    DECLARATIVE_REQUESTED=true
fi

if [[ "${DECLARATIVE_REQUESTED}" == "true" ]]; then
    if imperative_phase_requested; then
        log "INFO: Running declarative phase first; imperative flags will run afterward in the same invocation."
    fi
    run_declarative_workflow || exit $?
    if ! imperative_phase_requested; then
        if [[ "${MODE}" == "apply" && "${DO_VALIDATE}" == "true" ]]; then
            bash "${VALIDATE_SCRIPT}"
        fi
        exit 0
    fi
    log "INFO: Declarative phase complete; running imperative phase next."
fi

if [[ "${BASELINE}" == "true" ]]; then
    DO_SET_LOOKUP_ORDER=true
    DO_SET_MANAGED_ROLES=true
    ALL_INDEXES=true
    DO_VALIDATE=true
    if [[ -z "${MANAGED_ROLES}" ]]; then
        MANAGED_ROLES="ess_analyst,ess_user"
    fi
fi

if [[ "${ALL_INDEXES}" == "true" ]]; then
    DO_CREATE_CORE_INDEXES=true
    DO_CREATE_UEBA_INDEXES=true
    DO_CREATE_PCI_INDEXES=true
    DO_CREATE_EXPOSURE_INDEXES=true
    DO_CREATE_MISSION_CONTROL_INDEXES=true
    DO_CREATE_DLX_INDEXES=true
fi

if [[ "${ANY_OPERATION}" == "false" ]]; then
    DO_VALIDATE=true
fi

ensure_session() {
    if [[ -n "${SK}" ]]; then
        return 0
    fi
    load_splunk_credentials || {
        log "ERROR: Splunk credentials are required."
        exit 1
    }
    warn_if_current_skill_role_unsupported
    SK="$(get_session_key "${SPLUNK_URI}")" || {
        log "ERROR: Could not authenticate to Splunk REST API."
        exit 1
    }
}

ensure_es_installed() {
    ensure_session
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null; then
        log "ERROR: ${APP_NAME} is not installed. Run splunk-enterprise-security-install first."
        exit 1
    fi
}

set_lookup_order() {
    local body
    body="$(form_urlencode_pairs enforce_auto_lookup_order "true")" || exit 1
    log "Setting limits.conf [lookup] enforce_auto_lookup_order=true"
    rest_set_global_conf "limits" "lookup" "${body}"
}

rest_set_global_conf() {
    local conf="$1" stanza="$2" body="$3"
    local create_body encoded_stanza http_code response

    if type deployment_should_manage_search_config_via_bundle >/dev/null 2>&1 \
        && deployment_should_manage_search_config_via_bundle; then
        deployment_bundle_set_conf_for_current_target "${APP_NAME}" "${conf}" "${stanza}" "${body}"
        return $?
    fi

    encoded_stanza="$(_urlencode "${stanza}")"
    response="$(splunk_curl_post "${SK}" "${body}" \
        "${SPLUNK_URI}/services/configs/conf-${conf}/${encoded_stanza}" \
        -w '\n%{http_code}' 2>/dev/null || echo "000")"
    http_code="$(printf '%s\n' "${response}" | tail -1)"
    [[ "${http_code}" == "200" ]] && return 0

    create_body="$(form_urlencode_pairs name "${stanza}")" || return 1
    if [[ -n "${body}" ]]; then
        create_body="${create_body}&${body}"
    fi
    response="$(splunk_curl_post "${SK}" "${create_body}" \
        "${SPLUNK_URI}/services/configs/conf-${conf}" \
        -w '\n%{http_code}' 2>/dev/null || echo "000")"
    http_code="$(printf '%s\n' "${response}" | tail -1)"
    case "${http_code}" in
        200|201|409) return 0 ;;
        *)
            log "ERROR: Set global conf-${conf}/${stanza} failed (HTTP ${http_code})."
            return 1
            ;;
    esac
}

set_managed_roles() {
    local body
    if [[ -z "${MANAGED_ROLES}" ]]; then
        log "ERROR: --set-managed-roles requires a comma-separated role list."
        exit 1
    fi
    body="$(form_urlencode_pairs managed_roles "${MANAGED_ROLES}" disabled "0")" || exit 1
    log "Setting ES App Permissions Manager managed roles to: ${MANAGED_ROLES}"
    rest_set_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" \
        "app_permissions_manager://enforce_es_permissions" "${body}"
}

create_index_if_missing() {
    local idx="$1"
    if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
        log "Index '${idx}' already exists"
        return 0
    fi
    log "Creating index '${idx}' with maxTotalDataSizeMB=${MAX_SIZE_MB}"
    platform_create_index "${SK}" "${SPLUNK_URI}" "${idx}" "${MAX_SIZE_MB}" "event"
}

create_indexes() {
    local idx
    for idx in "$@"; do
        create_index_if_missing "${idx}"
    done
}

normalize_dm_name() {
    local raw="$1"
    raw="${raw#dm_accel_settings://}"
    printf '%s' "${raw// /_}"
}

set_dm_acceleration() {
    local raw_name="$1" enabled="$2" dm_name stanza body
    dm_name="$(normalize_dm_name "${raw_name}")"
    stanza="dm_accel_settings://${dm_name}"
    body="$(form_urlencode_pairs acceleration "${enabled}" disabled "0")" || exit 1
    log "Setting ${stanza} acceleration=${enabled}"
    rest_set_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "${stanza}" "${body}"
}

CORE_INDEXES=(
    audit_summary
    ba_test
    cim_modactions
    cms_main
    endpoint_summary
    gia_summary
    ioc
    notable
    notable_summary
    risk
    sequenced_events
    threat_activity
    whois
)

UEBA_INDEXES=(
    ers
    ueba_summaries
    ubaroute
    ueba
)

PCI_INDEXES=(
    pci
    pci_posture_summary
    pci_summary
)

EXPOSURE_INDEXES=(
    ea_sources
    ea_discovery
    ea_analytics
)

MISSION_CONTROL_INDEXES=(
    mc_aux_incidents
    mc_artifacts
    mc_investigations
    mc_events
    mc_incidents_backup
    kvcollection_retention_archive
)

DLX_INDEXES=(
    dlx_confidence
    dlx_kpi
)

log "=== Splunk Enterprise Security Configuration ==="
log ""

ensure_es_installed

if [[ "${DO_SET_LOOKUP_ORDER}" == "true" ]]; then
    set_lookup_order
fi

if [[ "${DO_SET_MANAGED_ROLES}" == "true" ]]; then
    set_managed_roles
fi

if [[ "${DO_CREATE_CORE_INDEXES}" == "true" ]]; then
    create_indexes "${CORE_INDEXES[@]}"
fi

if [[ "${DO_CREATE_UEBA_INDEXES}" == "true" ]]; then
    create_indexes "${UEBA_INDEXES[@]}"
fi

if [[ "${DO_CREATE_PCI_INDEXES}" == "true" ]]; then
    create_indexes "${PCI_INDEXES[@]}"
fi

if [[ "${DO_CREATE_EXPOSURE_INDEXES}" == "true" ]]; then
    create_indexes "${EXPOSURE_INDEXES[@]}"
fi

if [[ "${DO_CREATE_MISSION_CONTROL_INDEXES}" == "true" ]]; then
    create_indexes "${MISSION_CONTROL_INDEXES[@]}"
fi

if [[ "${DO_CREATE_DLX_INDEXES}" == "true" ]]; then
    create_indexes "${DLX_INDEXES[@]}"
fi

for dm in "${ENABLE_DMS[@]}"; do
    set_dm_acceleration "${dm}" "true"
done

for dm in "${DISABLE_DMS[@]}"; do
    set_dm_acceleration "${dm}" "false"
done

if [[ "${DO_VALIDATE}" == "true" ]]; then
    bash "${VALIDATE_SCRIPT}"
fi

log ""
log "Splunk Enterprise Security configuration workflow complete."

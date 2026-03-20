#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="CiscoSecurityCloud"
INPUT_TYPE=""
INPUT_NAME=""
CREATE_INDEX=true
DISABLED_FLAG="0"
SK=""

PARAM_KEYS=()
PARAM_VALUES=()

usage() {
    cat <<EOF
Cisco Security Cloud Input Configuration

Usage: $(basename "$0") [OPTIONS]

Required:
  --input-type TYPE          One of the supported input types from reference.md
  --name NAME                Input stanza name

Options:
  --set KEY VALUE            Set a non-secret field (repeatable)
  --secret-file KEY PATH     Read a secret field value from PATH (repeatable)
  --disable                  Create or update the stanza as disabled
  --no-create-index          Do not auto-create the target index
  --help                     Show this help

Example:
  $(basename "$0") \\
    --input-type sbg_xdr_input \\
    --name XDR_Default \\
    --set region us \\
    --set auth_method client_id \\
    --set client_id example-client-id \\
    --set xdr_import_time_range "7 days ago" \\
    --set interval 300 \\
    --set index cisco_xdr \\
    --secret-file refresh_token /tmp/xdr_refresh_token
EOF
    exit 0
}

append_param() {
    local key="$1" value="$2" i
    for i in "${!PARAM_KEYS[@]}"; do
        if [[ "${PARAM_KEYS[$i]}" == "${key}" ]]; then
            PARAM_VALUES[$i]="${value}"
            return 0
        fi
    done
    PARAM_KEYS+=("${key}")
    PARAM_VALUES+=("${value}")
}

get_param() {
    local key="$1" i
    for i in "${!PARAM_KEYS[@]}"; do
        if [[ "${PARAM_KEYS[$i]}" == "${key}" ]]; then
            printf '%s' "${PARAM_VALUES[$i]}"
            return 0
        fi
    done
    return 1
}

validate_param_key() {
    local key="$1"
    if [[ ! "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
        log "ERROR: Invalid field name '${key}'."
        exit 1
    fi
    case "${key}" in
        name|disabled)
            log "ERROR: Field '${key}' is managed by dedicated flags."
            exit 1
            ;;
    esac
}

required_fields_for_type() {
    case "${1:-}" in
        sbg_duo_input) echo "api_host index interval" ;;
        cisco_sma_input) echo "api_host interval index after" ;;
        sbg_xdr_input) echo "region auth_method client_id xdr_import_time_range interval index" ;;
        sbg_sfw_syslog_input) echo "type port sourcetype event_types index interval" ;;
        sbg_sfw_asa_syslog_input) echo "type port sourcetype event_types index interval" ;;
        sbg_fw_estreamer_input) echo "fmc_host fmc_port estreamer_import_time_range event_types index interval" ;;
        sbg_multicloud_defense_input) echo "interval index" ;;
        sbg_sfw_api_input) echo "fmc_host username index interval" ;;
        sbg_etd_input) echo "client_id etd_region etd_import_time_range interval index" ;;
        sbg_sna_input) echo "ip_address domain_id username interval index" ;;
        sbg_se_input) echo "api_host client_id se_import_time_range event_types groups interval sourcetype index" ;;
        sbg_cvi_input) echo "api_host interval index" ;;
        sbg_cii_input) echo "index interval cii_client_id cii_api_url cii_token_url cii_audience integration_method hec_url" ;;
        sbg_cii_aws_s3_input) echo "index cii_client_id cii_api_url cii_token_url cii_audience integration_method s3_bucket_url s3_bucket_region" ;;
        sbg_ai_defense_input) echo "interval index" ;;
        sbg_isovalent_input) echo "interval sourcetype index" ;;
        sbg_isovalent_edge_processor_input) echo "interval sourcetype index" ;;
        sbg_nvm_input) echo "interval index" ;;
        sbg_sw_input) echo "type port index interval" ;;
        *)
            log "ERROR: Unsupported input type '${1}'."
            exit 1
            ;;
    esac
}

ensure_required_fields() {
    local field missing=()
    for field in $(required_fields_for_type "${INPUT_TYPE}"); do
        if ! get_param "${field}" >/dev/null; then
            missing+=("${field}")
        fi
    done

    if (( ${#missing[@]} > 0 )); then
        log "ERROR: Missing required fields for ${INPUT_TYPE}: ${missing[*]}"
        exit 1
    fi
}

build_form_body() {
    local include_name="$1"
    local args=() i
    if [[ "${include_name}" == "true" ]]; then
        args+=(name "${INPUT_NAME}")
    fi
    for i in "${!PARAM_KEYS[@]}"; do
        args+=("${PARAM_KEYS[$i]}" "${PARAM_VALUES[$i]}")
    done
    args+=(disabled "${DISABLED_FLAG}")
    form_urlencode_pairs "${args[@]}"
}

ensure_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --input-type) require_arg "$1" $# || exit 1; INPUT_TYPE="$2"; shift 2 ;;
        --name) require_arg "$1" $# || exit 1; INPUT_NAME="$2"; shift 2 ;;
        --set)
            require_arg "$1" $# || exit 1
            if [[ $# -lt 3 ]]; then
                log "ERROR: Option '--set' requires KEY and VALUE."
                exit 1
            fi
            validate_param_key "$2"
            append_param "$2" "$3"
            shift 3
            ;;
        --secret-file)
            require_arg "$1" $# || exit 1
            if [[ $# -lt 3 ]]; then
                log "ERROR: Option '--secret-file' requires KEY and PATH."
                exit 1
            fi
            validate_param_key "$2"
            append_param "$2" "$(read_secret_file "$3")"
            shift 3
            ;;
        --disable) DISABLED_FLAG="1"; shift ;;
        --no-create-index) CREATE_INDEX=false; shift ;;
        --help) usage ;;
        *) log "Unknown option: $1"; usage ;;
    esac
done

[[ -n "${INPUT_TYPE}" ]] || { log "ERROR: --input-type is required."; exit 1; }
[[ -n "${INPUT_NAME}" ]] || { log "ERROR: --name is required."; exit 1; }
required_fields_for_type "${INPUT_TYPE}" >/dev/null
ensure_required_fields

ensure_session
if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null; then
    log "ERROR: ${APP_NAME} is not installed. Install Cisco Security Cloud first."
    exit 1
fi

index_name="$(get_param index || true)"
if [[ -n "${index_name}" && "${CREATE_INDEX}" == "true" ]]; then
    if platform_create_index "${SK}" "${SPLUNK_URI}" "${index_name}" "512000"; then
        log "Index '${index_name}' created or already exists."
    else
        log "ERROR: Failed to create index '${index_name}'."
        exit 1
    fi
fi

endpoint="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/${APP_NAME}_${INPUT_TYPE}"
create_body="$(build_form_body true)"
update_body="$(build_form_body false)"

if ! rest_create_or_update_account "${SK}" "${endpoint}" "${INPUT_NAME}" "${create_body}" "${update_body}" >/dev/null; then
    log "ERROR: Failed to create or update ${INPUT_TYPE} '${INPUT_NAME}'."
    exit 1
fi

log "Configured ${INPUT_TYPE} '${INPUT_NAME}' in ${APP_NAME}."
if [[ "${DISABLED_FLAG}" == "1" ]]; then
    log "Input state: disabled"
else
    log "Input state: enabled"
fi

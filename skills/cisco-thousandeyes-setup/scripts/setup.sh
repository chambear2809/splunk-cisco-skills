#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="ta_cisco_thousandeyes"
HEC_TOKEN_NAME="thousandeyes"
DEFAULT_INDEXES=(thousandeyes_metrics thousandeyes_traces thousandeyes_events thousandeyes_activity thousandeyes_alerts thousandeyes_pathvis)

INDEXES_ONLY=false
HEC_ONLY=false
ENABLE_INPUTS=false
ACCOUNT=""
ACCOUNT_GROUP=""
INDEX=""
INPUT_TYPE=""
HEC_TOKEN=""

usage() {
    cat <<EOF
Cisco ThousandEyes App Setup Automation

Usage: $(basename "$0") [OPTIONS]

Options:
  --indexes-only          Create indexes only
  --hec-only              Verify/create HEC token only
  --enable-inputs         Enable data inputs
  --account EMAIL         ThousandEyes user account (email)
  --account-group NAME    ThousandEyes account group name
  --index INDEX           Target index for polling inputs
  --input-type TYPE       Input group: all, metrics, traces, events, activity, alerts
  --hec-token NAME        HEC token name (default: thousandeyes)
  --help                  Show this help

With no flags, runs full setup (HEC + indexes).
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --hec-only) HEC_ONLY=true; shift ;;
        --enable-inputs) ENABLE_INPUTS=true; shift ;;
        --account) ACCOUNT="$2"; shift 2 ;;
        --account-group) ACCOUNT_GROUP="$2"; shift 2 ;;
        --index) INDEX="$2"; shift 2 ;;
        --input-type) INPUT_TYPE="$2"; shift 2 ;;
        --hec-token) HEC_TOKEN="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

HEC_TOKEN="${HEC_TOKEN:-${HEC_TOKEN_NAME}}"

log_live_input_summary() {
    local total enabled disabled
    read -r total enabled disabled <<< "$(rest_get_live_input_counts "${SK}" "${SPLUNK_URI}" "${APP_NAME}")"
    log "Live input status: total=${total}, enabled=${enabled}, disabled=${disabled}"
}

ensure_search_api_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    prefer_current_cloud_search_api_uri
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk. Check credentials."; exit 1; }
}

check_prereqs() {
    ensure_search_api_session
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        log "ERROR: ThousandEyes app not found. Install the app first."
        exit 1
    fi
}

detect_hec_target() {
    if is_splunk_cloud; then
        local stack="${SPLUNK_CLOUD_STACK:-}"
        if [[ -n "${stack}" ]]; then
            if _is_staging_splunk_cloud_host "${SPLUNK_URI:-}"; then
                printf 'https://http-inputs-%s.stg.splunkcloud.com:443' "${stack}"
            else
                printf 'https://http-inputs-%s.splunkcloud.com:443' "${stack}"
            fi
            return 0
        fi
    fi
    local host
    host=$(splunk_host_from_uri "${SPLUNK_URI}")
    printf 'https://%s:8088' "${host}"
}

_ACS_HEC_CMD_GROUP=""
acs_hec_command_group() {
    if [[ -n "${_ACS_HEC_CMD_GROUP}" ]]; then
        printf '%s' "${_ACS_HEC_CMD_GROUP}"
        return 0
    fi
    if acs_command hec-token list --count 1 >/dev/null 2>&1; then
        _ACS_HEC_CMD_GROUP="hec-token"
    else
        _ACS_HEC_CMD_GROUP="http-event-collectors"
    fi
    printf '%s' "${_ACS_HEC_CMD_GROUP}"
}

cloud_get_hec_token_state() {
    local token_name="$1" cmd_group hec_list
    cmd_group="$(acs_hec_command_group)"

    if [[ "${cmd_group}" == "hec-token" ]]; then
        hec_list=$(acs_command hec-token list --count 100 2>/dev/null | acs_extract_http_response_json || echo "{}")
    else
        hec_list=$(acs_command http-event-collectors list 2>/dev/null | acs_extract_http_response_json || echo "{}")
    fi

    printf '%s' "${hec_list}" | python3 -c "
import json, sys
target = sys.argv[1]
try:
    data = json.load(sys.stdin)
    collectors = (
        data.get('http-event-collectors')
        or data.get('http_event_collectors')
        or data.get('tokens')
        or []
    )
    for collector in collectors:
        spec = collector.get('spec', {}) if isinstance(collector, dict) else {}
        name = spec.get('name') or collector.get('name', '')
        if name != target:
            continue
        disabled = str(spec.get('disabled', collector.get('disabled', False))).strip().lower()
        if disabled in ('1', 'true'):
            print('disabled', end='')
        else:
            print('enabled', end='')
        raise SystemExit(0)
    print('missing', end='')
except Exception:
    print('unknown', end='')
" "${token_name}" 2>/dev/null || echo "unknown"
}

cloud_create_hec_token_via_acs() {
    local token_name="$1" cmd_group indexes_csv
    cmd_group="$(acs_hec_command_group)"

    if [[ "${cmd_group}" == "hec-token" ]]; then
        local -a create_cmd=(hec-token create --name "${token_name}" --default-index "thousandeyes_metrics")
        local idx
        for idx in "${DEFAULT_INDEXES[@]}"; do
            create_cmd+=(--allowed-indexes "${idx}")
        done
        acs_command "${create_cmd[@]}" >/dev/null 2>&1
    else
        indexes_csv=$(IFS=,; echo "${DEFAULT_INDEXES[*]}")
        acs_command http-event-collectors create \
            --name "${token_name}" \
            --allowed-indexes "${indexes_csv}" \
            --default-index "thousandeyes_metrics" \
            --disabled false \
            >/dev/null 2>&1
    fi
}

rest_create_hec_token() {
    local token_name="$1" indexes_str body resp hec_code
    indexes_str=$(IFS=,; echo "${DEFAULT_INDEXES[*]}")
    body=$(form_urlencode_pairs \
        name "${token_name}" \
        index "thousandeyes_metrics" \
        indexes "${indexes_str}" \
        disabled "false") || return 1
    resp=$(splunk_curl_post "${SK}" "${body}" \
        "${SPLUNK_URI}/services/data/inputs/http?output_mode=json" \
        -w '\n%{http_code}' 2>/dev/null)
    hec_code=$(echo "${resp}" | tail -1)
    case "${hec_code}" in
        201|200|409) return 0 ;;
        *) return 1 ;;
    esac
}

ensure_hec_token() {
    local token_name="${1:-${HEC_TOKEN}}" state
    log "Checking HEC token '${token_name}'..."

    if is_splunk_cloud; then
        acs_prepare_context || { log "ERROR: ACS context required for Cloud HEC management."; exit 1; }
        state="$(cloud_get_hec_token_state "${token_name}" 2>/dev/null || echo "unknown")"
        case "${state}" in
            enabled|disabled)
                log "  HEC token '${token_name}' already exists in Splunk Cloud."
                return 0
                ;;
        esac

        log "  Creating HEC token '${token_name}' via ACS..."
        if cloud_create_hec_token_via_acs "${token_name}"; then
            state="$(cloud_get_hec_token_state "${token_name}" 2>/dev/null || echo "unknown")"
            case "${state}" in
                enabled|disabled)
                    log "  HEC token '${token_name}' created via ACS."
                    return 0
                    ;;
            esac
        fi

        log "  ACS HEC token management could not confirm '${token_name}'. Trying search-tier REST..."
        ensure_search_api_session
        state="$(rest_get_hec_token_state "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "unknown")"
        case "${state}" in
            enabled|disabled)
                log "  HEC token '${token_name}' already exists."
                return 0
                ;;
        esac

        log "  Creating HEC token '${token_name}' via REST..."
        if rest_create_hec_token "${token_name}"; then
            state="$(rest_get_hec_token_state "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "unknown")"
            case "${state}" in
                enabled|disabled)
                    log "  HEC token '${token_name}' created via REST."
                    return 0
                    ;;
            esac
        fi

        log "ERROR: Failed to verify or create HEC token '${token_name}'."
        exit 1
    else
        ensure_search_api_session
        state="$(rest_get_hec_token_state "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "unknown")"
        if [[ "${state}" == "enabled" || "${state}" == "disabled" ]]; then
            log "  HEC token '${token_name}' already exists."
            return 0
        fi

        log "  Creating HEC token '${token_name}' via REST..."
        if rest_create_hec_token "${token_name}"; then
            state="$(rest_get_hec_token_state "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "unknown")"
            if [[ "${state}" == "enabled" || "${state}" == "disabled" ]]; then
                log "  HEC token '${token_name}' created via REST."
                return 0
            fi
        fi

        log "ERROR: Failed to create HEC token '${token_name}'."
        exit 1
    fi
}

create_indexes() {
    log "Creating indexes..."
    if ! is_splunk_cloud; then
        ensure_search_api_session
    fi
    for idx in "${DEFAULT_INDEXES[@]}"; do
        if platform_create_index "${SK-}" "${SPLUNK_URI}" "${idx}" "512000"; then
            log "  Index '${idx}' created or already exists."
        else
            log "ERROR: Failed to create index '${idx}'"
            exit 1
        fi
    done
    log "Index creation complete."
}

enable_metrics_inputs() {
    local account="$1" acc_group="$2" hec_token="$3"
    local hec_target
    hec_target=$(detect_hec_target)

    log "Enabling metrics stream input for account='${account}'..."
    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        thousandeyes_user "${account}" \
        thousandeyes_acc_group "${acc_group}" \
        hec_target "${hec_target}" \
        hec_token "${hec_token}" \
        test_index "thousandeyes_metrics")
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "test_metrics_stream" "metrics_${account}" "${body}"
    log "  Metrics stream input enabled."
}

enable_traces_inputs() {
    local account="$1" acc_group="$2" hec_token="$3"
    local hec_target
    hec_target=$(detect_hec_target)

    log "Enabling traces stream input for account='${account}'..."
    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        thousandeyes_user "${account}" \
        thousandeyes_acc_group "${acc_group}" \
        hec_target "${hec_target}" \
        hec_token "${hec_token}" \
        test_index "thousandeyes_traces")
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "test_traces_stream" "traces_${account}" "${body}"
    log "  Traces stream input enabled."
}

enable_events_inputs() {
    local account="$1" acc_group="$2"
    local idx="${INDEX:-thousandeyes_events}"

    log "Enabling events polling input for account='${account}'..."
    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        thousandeyes_user "${account}" \
        thousandeyes_acc_group "${acc_group}" \
        index "${idx}" \
        interval "3600")
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "event" "events_${account}" "${body}"
    log "  Events polling input enabled (interval: 3600s)."
}

enable_activity_inputs() {
    local account="$1" acc_group="$2" hec_token="$3"
    local hec_target
    hec_target=$(detect_hec_target)

    log "Enabling activity logs stream input for account='${account}'..."
    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        thousandeyes_user "${account}" \
        thousandeyes_acc_group "${acc_group}" \
        hec_target "${hec_target}" \
        hec_token "${hec_token}" \
        activity_index "thousandeyes_activity")
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "activity_logs_stream" "activity_${account}" "${body}"
    log "  Activity logs stream input enabled."
}

enable_alerts_inputs() {
    local account="$1" acc_group="$2" hec_token="$3"
    local hec_target
    hec_target=$(detect_hec_target)

    log "Enabling alerts stream input for account='${account}'..."
    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        thousandeyes_user "${account}" \
        thousandeyes_acc_group "${acc_group}" \
        hec_target "${hec_target}" \
        hec_token "${hec_token}" \
        alerts_index "thousandeyes_alerts")
    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" \
        "alerts_stream" "alerts_${account}" "${body}"
    log "  Alerts stream input enabled."
}

enable_all_inputs() {
    local account="$1" acc_group="$2" hec_token="$3"
    enable_metrics_inputs "${account}" "${acc_group}" "${hec_token}"
    enable_traces_inputs "${account}" "${acc_group}" "${hec_token}"
    enable_events_inputs "${account}" "${acc_group}"
    enable_activity_inputs "${account}" "${acc_group}" "${hec_token}"
    enable_alerts_inputs "${account}" "${acc_group}" "${hec_token}"
    log "All inputs enabled (5 inputs)."
}

main() {
    if $ENABLE_INPUTS; then
        check_prereqs
        if [[ -z "${ACCOUNT}" || -z "${INPUT_TYPE}" ]]; then
            log "ERROR: --enable-inputs requires --account and --input-type"
            exit 1
        fi
        if [[ -z "${ACCOUNT_GROUP}" ]]; then
            log "ERROR: --enable-inputs requires --account-group"
            exit 1
        fi
        case "${INPUT_TYPE}" in
            all) enable_all_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" "${HEC_TOKEN}" ;;
            metrics) enable_metrics_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" "${HEC_TOKEN}" ;;
            traces) enable_traces_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" "${HEC_TOKEN}" ;;
            events) enable_events_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" ;;
            activity) enable_activity_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" "${HEC_TOKEN}" ;;
            alerts) enable_alerts_inputs "${ACCOUNT}" "${ACCOUNT_GROUP}" "${HEC_TOKEN}" ;;
            *) log "ERROR: Unknown input type '${INPUT_TYPE}'."; usage ;;
        esac
        log_live_input_summary
        log "$(log_platform_restart_guidance "input changes")"
        exit 0
    fi

    if $HEC_ONLY; then
        if is_splunk_cloud; then
            ensure_hec_token "${HEC_TOKEN}"
        else
            ensure_search_api_session
            ensure_hec_token "${HEC_TOKEN}"
        fi
        exit 0
    fi

    if $INDEXES_ONLY; then
        create_indexes
        log "$(log_platform_restart_guidance "index changes")"
        exit 0
    fi

    if is_splunk_cloud; then
        ensure_hec_token "${HEC_TOKEN}"
    else
        ensure_search_api_session
        ensure_hec_token "${HEC_TOKEN}"
    fi
    create_indexes
    log "$(log_platform_restart_guidance "setup changes")"
}

main

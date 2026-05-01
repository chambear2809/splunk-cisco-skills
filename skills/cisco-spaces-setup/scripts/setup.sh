#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="ta_cisco_spaces"
DEFAULT_INDEX="cisco_spaces"

INDEXES_ONLY=false
ENABLE_INPUTS=false
STREAM=""
INDEX=""

usage() {
    cat >&2 <<EOF
Cisco Spaces TA Setup Automation

Usage: $(basename "$0") [OPTIONS]

Options:
  --indexes-only          Create indexes only
  --enable-inputs         Enable firehose data input
  --stream NAME           Meta stream name for input enablement
  --index INDEX           Target index for inputs (default: ${DEFAULT_INDEX})
  --help                  Show this help

With no flags, runs full setup (index + visibility).
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --enable-inputs) ENABLE_INPUTS=true; shift ;;
        --stream) require_arg "$1" $# || exit 1; STREAM="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

ensure_search_api_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk. Check credentials."; exit 1; }
}

check_prereqs() {
    ensure_search_api_session
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        log "ERROR: Cisco Spaces TA not found. Install the app first."
        exit 1
    fi
}

create_indexes() {
    local index="${INDEX:-${DEFAULT_INDEX}}"
    log "Creating indexes..."
    if ! is_splunk_cloud; then
        ensure_search_api_session
    fi
    if platform_create_index "${SK:-}" "${SPLUNK_URI}" "${index}" "512000"; then
        log "  Index '${index}' created or already exists."
    else
        log "ERROR: Failed to create index '${index}'"
        return 1
    fi
    log "Index creation complete."
}

ensure_app_visible() {
    ensure_search_api_session
    local visible
    visible=$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/apps/local/${APP_NAME}?output_mode=json" 2>/dev/null \
        | python3 -c "
import json, sys
try: print(json.load(sys.stdin)['entry'][0]['content'].get('visible', True))
except: print('True')
" 2>/dev/null || echo "True")
    if [[ "${visible}" == "False" ]]; then
        log "Setting ${APP_NAME} visible=true..."
        deployment_set_app_visible "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "true" >/dev/null 2>&1 || true
    fi
}

enable_firehose_input() {
    local stream_name="$1"
    local index="$2"

    log "Creating firehose input for stream='${stream_name}' index='${index}'..."

    local body
    body=$(form_urlencode_pairs \
        disabled "0" \
        index "${index}" \
        interval "300" \
        stream "${stream_name}")

    rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "cisco_spaces_firehose" "firehose_${stream_name}" "${body}"
    log "Firehose input 'firehose_${stream_name}' created."
}

main() {
    warn_if_current_skill_role_unsupported

    if $ENABLE_INPUTS; then
        check_prereqs
        INDEX="${INDEX:-${DEFAULT_INDEX}}"
        if [[ -z "${STREAM}" ]]; then
            log "ERROR: --enable-inputs requires --stream"
            exit 1
        fi
        enable_firehose_input "${STREAM}" "${INDEX}"
        log "$(log_platform_restart_guidance "input changes")"
        exit 0
    fi

    if $INDEXES_ONLY; then
        create_indexes
        log "$(log_platform_restart_guidance "index changes")"
        exit 0
    fi

    create_indexes
    ensure_app_visible
    log "$(log_platform_restart_guidance "index changes")"

    if [[ ! -t 0 ]]; then
        log "Non-interactive mode: skipping meta stream configuration prompt."
        log "To configure a stream, re-run with: --enable-inputs --stream NAME"
        return 0
    fi
    log ""
    read -rp "Would you like to configure a Cisco Spaces meta stream now? [y/N]: " yn
    case "${yn}" in
        [yY]|[yY][eE][sS]) ;;
        *) return 0 ;;
    esac

    local stream_name region token_file auto_idx location_updates
    read -rp "Stream name (e.g. production): " stream_name
    [[ -z "${stream_name}" ]] && { log "ERROR: Stream name is required."; return 1; }
    read -rp "Region [io/eu/sg]: " region
    [[ -z "${region}" ]] && { log "ERROR: Region is required."; return 1; }

    log ""
    log "Write your Cisco Spaces activation token to a temp file:"
    log "  bash skills/shared/scripts/write_secret_file.sh /tmp/spaces_token"
    log ""
    read -rp "Path to activation token file (default: /tmp/spaces_token): " token_file
    token_file="${token_file:-/tmp/spaces_token}"
    [[ -f "${token_file}" ]] || { log "ERROR: File not found: ${token_file}"; return 1; }

    read -rp "Record device location updates? [y/N]: " loc_yn
    case "${loc_yn}" in
        [yY]|[yY][eE][sS]) location_updates="--location-updates" ;;
        *) location_updates="" ;;
    esac

    read -rp "Auto-create firehose input? [Y/n]: " auto_yn
    local auto_flag=""
    case "${auto_yn}" in
        [nN]|[nN][oO]) ;;
        *) auto_flag="--auto-inputs" ;;
    esac
    read -rp "Target index for inputs (default: ${DEFAULT_INDEX}): " auto_idx
    auto_idx="${auto_idx:-${DEFAULT_INDEX}}"

    log ""
    hbs_append_cleanup_trap "rm -f $(printf '%q' "${token_file}") 2>/dev/null || true" EXIT INT TERM
    bash "${SCRIPT_DIR}/configure_stream.sh" \
        --name "${stream_name}" \
        --token-file "${token_file}" \
        --region "${region}" \
        ${location_updates:+"${location_updates}"} \
        ${auto_flag:+"${auto_flag}"} \
        --index "${auto_idx}"
    log ""
    log "Run 'bash ${SCRIPT_DIR}/validate.sh' to verify the deployment."
}

main

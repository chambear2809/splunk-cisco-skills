#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco-catalyst-app"

MACROS_ONLY=false
ACCELERATE=false
CUSTOM_INDEXES=""

usage() {
    cat <<EOF
Cisco Enterprise Networking App Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --macros-only              Update macros only
  --accelerate               Enable data model acceleration
  --custom-indexes "a,b,c"   Use custom index list (comma-separated)
  --help                     Show this help

With no flags, runs full setup (macros + saved search enablement).
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --macros-only) MACROS_ONLY=true; shift ;;
        --accelerate) ACCELERATE=true; shift ;;
        --custom-indexes) CUSTOM_INDEXES="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

check_prereqs() {
    if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME"; then
        log "ERROR: Cisco Enterprise Networking app not found. Install it first."
        exit 1
    fi
    if ! rest_check_app "$SK" "$SPLUNK_URI" "TA_cisco_catalyst" 2>/dev/null; then
        log "WARNING: Cisco Catalyst TA not found — dashboards may not show data"
    fi
}

update_macros() {
    log "Updating index macro..."

    local index_list def_encoded
    if [[ -n "${CUSTOM_INDEXES}" ]]; then
        index_list=$(echo "${CUSTOM_INDEXES}" | tr ',' '\n' | sed 's/^/"/;s/$/"/' | tr '\n' ',' | sed 's/,$//')
        index_list="index IN (${index_list})"
    else
        index_list='index IN ("catalyst", "ise", "sdwan", "cybervision")'
    fi

    def_encoded=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "${index_list}")
    rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_catalyst_app_index" "definition=${def_encoded}&description=Definition%20for%20all%20indices%20where%20Cisco%20SDWAN%2C%20Cisco%20ISE%2C%20and%20Cisco%20Catalyst%20Center%20data%20is%20stored&iseval=0" || true

    log "  cisco_catalyst_app_index = ${index_list}"
    log "Macro update complete."
}

enable_acceleration() {
    log "Enabling data model acceleration..."

    rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "datamodels" "Cisco_Catalyst_App" "acceleration=true&acceleration.earliest_time=-1mon" || true

    log "  Data model 'Cisco_Catalyst_App' acceleration enabled (earliest: -1mon)"
    log "Acceleration config written."
}

main() {
    check_prereqs

    if $ACCELERATE; then
        enable_acceleration
        log "Restart Splunk to apply changes."
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
    log "Setup complete. Restart Splunk to apply changes. Dashboards will use data from the configured indexes."
    log "Tip: Run with --accelerate to enable data model acceleration for production."
}

main

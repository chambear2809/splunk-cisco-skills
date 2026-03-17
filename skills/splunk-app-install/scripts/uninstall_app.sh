#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
APP_NAME=""

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Accept flags for non-interactive use; anything missing gets prompted
while [[ $# -gt 0 ]]; do
    case "$1" in
        --app-name) APP_NAME="$2"; shift 2 ;;
        --help)
            cat <<EOF
Uninstall a Splunk App (interactive)

Usage: $(basename "$0") [OPTIONS]

Optional flags (skip the corresponding prompt):
  --app-name NAME    Name of the app to remove

Credentials are read from the project-root credentials file automatically.
Run: bash ${SCRIPT_DIR}/../../shared/scripts/setup_credentials.sh
EOF
            exit 0 ;;
        *) log "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=== Splunk App Uninstaller ==="
echo ""

load_splunk_credentials

SK=$(get_session_key "${SPLUNK_URI}")

if [[ -z "${APP_NAME}" ]]; then
    echo ""
    echo "Fetching installed apps..."
    response=$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/apps/local?output_mode=json&count=0" 2>/dev/null)

    app_list=()
    while IFS= read -r app_name; do
        [[ -n "${app_name}" ]] && app_list+=("${app_name}")
    done < <(echo "${response}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get('entry', [])
    names = sorted(e.get('name', '') for e in entries)
    for n in names:
        print(n)
except Exception:
    pass
" 2>/dev/null)

    if [[ ${#app_list[@]} -gt 0 ]]; then
        echo ""
        echo "Installed apps:"
        for i in "${!app_list[@]}"; do
            printf "  %d) %s\n" $((i + 1)) "${app_list[$i]}"
        done
        echo ""
        read -rp "Select a number, or type the app name: " choice

        if [[ "${choice}" =~ ^[0-9]+$ ]] && [[ "${choice}" -ge 1 ]] && [[ "${choice}" -le ${#app_list[@]} ]]; then
            APP_NAME="${app_list[$((choice - 1))]}"
        else
            APP_NAME="${choice}"
        fi
    else
        read -rp "Enter the app name to uninstall: " APP_NAME
    fi

    if [[ -z "${APP_NAME}" ]]; then
        log "ERROR: No app name specified"
        exit 1
    fi
fi

echo ""
read -rp "Remove app '${APP_NAME}'? This cannot be undone. [y/N]: " confirm
case "${confirm}" in
    [yY]|[yY][eE][sS]) ;;
    *) log "Cancelled."; exit 0 ;;
esac

log "Checking if app '${APP_NAME}' exists..."
check_response=$(splunk_curl "${SK}" -o /dev/null -w "%{http_code}" \
    "${SPLUNK_URI}/services/apps/local/${APP_NAME}?output_mode=json" 2>/dev/null || echo "000")

if [[ "${check_response}" -ne 200 ]]; then
    log "ERROR: App '${APP_NAME}' not found (HTTP ${check_response})"
    exit 1
fi

log "Removing app '${APP_NAME}'..."
delete_response=$(splunk_curl "${SK}" -w "\n%{http_code}" \
    -X DELETE "${SPLUNK_URI}/services/apps/local/${APP_NAME}?output_mode=json" 2>/dev/null || true)

http_code=$(echo "${delete_response}" | tail -1)
body=$(printf '%s\n' "${delete_response}" | sed '$d')

if [[ "${http_code}" -eq 200 ]]; then
    log "SUCCESS: App '${APP_NAME}' has been removed"
    log ""
    log "Note: The app directory may still exist at:"
    log "  ${SPLUNK_HOME}/etc/apps/${APP_NAME}/"
    log "Restart Splunk to apply changes."
else
    log "ERROR: Failed to remove app '${APP_NAME}' (HTTP ${http_code})"
    error_msg=$(echo "${body}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    msgs = data.get('messages', [])
    for m in msgs:
        print(m.get('text', ''))
except Exception:
    pass
" 2>/dev/null || true)
    if [[ -n "${error_msg}" ]]; then
        log "  ${error_msg}"
    fi
    exit 1
fi

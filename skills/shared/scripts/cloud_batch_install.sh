#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/credential_helpers.sh"

REGISTRY_FILE="${_PROJECT_ROOT}/skills/shared/app_registry.json"

usage() {
    cat <<EOF
Batch-install Splunkbase apps on Splunk Cloud via ACS.

Installs all specified apps with --no-restart batching, then triggers a single
ACS restart at the end. Uses the app registry for license-ack URLs.

Usage: $(basename "$0") [OPTIONS] <app_id> [app_id...]

Options:
  --version VER        Version to install (applies to all; blank = latest)
  --no-restart         Skip the final ACS restart
  --help               Show this help

Example:
  $(basename "$0") 7777 7828 5580
EOF
    exit 0
}

APP_IDS=()
APP_VERSION=""
RESTART=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) APP_VERSION="$2"; shift 2 ;;
        --no-restart) RESTART=false; shift ;;
        --help) usage ;;
        --*) log "Unknown option: $1"; usage ;;
        *) APP_IDS+=("$1"); shift ;;
    esac
done

if (( ${#APP_IDS[@]} == 0 )); then
    log "ERROR: At least one Splunkbase app ID is required."
    usage
fi

if ! is_splunk_cloud; then
    log "ERROR: This script is for Splunk Cloud only."
    exit 1
fi

resolve_license_ack() {
    local app_id="$1"
    if [[ -f "${REGISTRY_FILE}" ]]; then
        python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    if str(app.get('splunkbase_id', '')) == sys.argv[2]:
        print(app.get('license_ack_url', ''), end='')
        break
" "${REGISTRY_FILE}" "${app_id}" 2>/dev/null || true
    fi
}

resolve_app_name() {
    local app_id="$1"
    if [[ -f "${REGISTRY_FILE}" ]]; then
        python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    if str(app.get('splunkbase_id', '')) == sys.argv[2]:
        print(app.get('app_name', ''), end='')
        break
" "${REGISTRY_FILE}" "${app_id}" 2>/dev/null || true
    fi
}

verify_app_identity() {
    local sk="$1" uri="$2" app_name="$3"
    local actual_id
    actual_id=$(splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app_name}/configs/conf-app/package?output_mode=json" \
        2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data['entry'][0]['content'].get('id', ''), end='')
except Exception:
    print('', end='')
" 2>/dev/null || true)

    if [[ -z "${actual_id}" ]]; then
        log "  WARNING: Could not verify identity of ${app_name} (REST query failed)."
        return 1
    elif [[ "${actual_id}" != "${app_name}" ]]; then
        log "  WARNING: App directory '${app_name}' contains '${actual_id}' files."
        log "           ACS deployment may be corrupted. Uninstall and reinstall individually."
        return 1
    fi
    return 0
}

acs_prepare_context || exit 1

log "=== Cloud Batch Install ==="
log "Apps: ${APP_IDS[*]}"
log ""

failures=0
for app_id in "${APP_IDS[@]}"; do
    log "Installing Splunkbase app ID ${app_id}..."

    license_ack="$(resolve_license_ack "${app_id}")"

    declare -a cmd=(apps install splunkbase --splunkbase-id "${app_id}")
    [[ -n "${APP_VERSION}" ]] && cmd+=(--version "${APP_VERSION}")
    [[ -n "${license_ack}" ]] && cmd+=(--acs-licensing-ack "${license_ack}")
    cloud_requires_local_scope && cmd+=(--scope local)

    set +e
    output=$(acs_command "${cmd[@]}" 2>&1)
    rc=$?
    set -e

    if (( rc == 0 )); then
        log "  Installed app ID ${app_id}."
    elif printf '%s' "${output}" | grep -q '"statusCode": 409' 2>/dev/null; then
        log "  App ID ${app_id} already installed (skipped)."
    else
        log "  ERROR: Failed to install app ID ${app_id} (rc=${rc})."
        [[ -n "${output}" ]] && log "  ${output}"
        failures=$((failures + 1))
    fi
done

if (( failures > 0 )); then
    log ""
    log "WARNING: ${failures} app(s) failed to install."
fi

if ${RESTART}; then
    log ""
    log "Checking if ACS restart is required..."
    cloud_restart_if_required 900
    log "Stack is Ready."
fi

log ""
log "--- Verifying app identity ---"
load_splunk_credentials 2>/dev/null || true
verify_sk=$(get_session_key "${SPLUNK_URI}" 2>/dev/null || true)
if [[ -n "${verify_sk}" ]]; then
    verify_failures=0
    for app_id in "${APP_IDS[@]}"; do
        expected_name="$(resolve_app_name "${app_id}")"
        if [[ -z "${expected_name}" ]]; then
            continue
        fi
        if ! verify_app_identity "${verify_sk}" "${SPLUNK_URI}" "${expected_name}"; then
            verify_failures=$((verify_failures + 1))
        else
            log "  ${expected_name}: OK"
        fi
    done
    if (( verify_failures > 0 )); then
        log ""
        log "WARNING: ${verify_failures} app(s) may have corrupted deployments."
        log "Uninstall the affected apps and reinstall them individually."
    fi
else
    log "  Skipped (no search-tier REST access)."
fi

log ""
log "=== Batch install complete ==="

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
APP_NAME=""
RESTART_SPLUNK=true
ASSUME_YES=false
ACCEPT_REST_FALLBACK=false
CLOUD_VERIFY_ATTEMPTS=""
CLOUD_VERIFY_INTERVAL=""
CLOUD_EVIDENCE_FILE=""

# Accept flags for non-interactive use; anything missing gets prompted
while [[ $# -gt 0 ]]; do
    case "$1" in
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --no-restart) RESTART_SPLUNK=false; shift ;;
        --yes|--force|--non-interactive) ASSUME_YES=true; shift ;;
        --accept-rest-fallback) ACCEPT_REST_FALLBACK=true; shift ;;
        --verify-attempts) require_arg "$1" $# || exit 1; CLOUD_VERIFY_ATTEMPTS="$2"; shift 2 ;;
        --verify-interval) require_arg "$1" $# || exit 1; CLOUD_VERIFY_INTERVAL="$2"; shift 2 ;;
        --evidence-file) require_arg "$1" $# || exit 1; CLOUD_EVIDENCE_FILE="$2"; shift 2 ;;
        --help)
            cat <<EOF
Uninstall a Splunk App (interactive)

Usage: $(basename "$0") [OPTIONS]

Optional flags (skip the corresponding prompt):
  --app-name NAME    Name of the app to remove
  --no-restart       Skip the automatic restart after uninstall
  --yes              Skip the destructive-action confirmation prompt
                     (aliases: --force, --non-interactive). Requires --app-name.
  --accept-rest-fallback
                     Cloud only: separately authorize a direct search-tier
                     REST DELETE after ACS leaves the exact app present.
  --verify-attempts N Cloud only: bounded ACS/REST probes per phase.
  --verify-interval N Cloud only: seconds between bounded probes.
  --evidence-file PATH
                     Cloud only: private JSON result/recovery evidence path.

Credentials are read from the project-root credentials file automatically.
Run: bash ${SCRIPT_DIR}/../../shared/scripts/setup_credentials.sh
EOF
            exit 0 ;;
        *) log "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ "${ASSUME_YES}" == "true" && -z "${APP_NAME}" ]]; then
    log "ERROR: --yes requires --app-name (refusing to auto-confirm an unspecified app)."
    exit 1
fi

restart_splunk_or_exit() {
    : "${RESTART_SPLUNK}"  # Consumed by app_restart_splunk_or_exit.
    app_restart_splunk_or_exit "${SK}" "${SPLUNK_URI}" "$1" \
        "Restart manually before relying on the uninstall state." || exit 1
}

app_lookup_http_code() {
    local sk="$1" uri="$2" app="$3"
    local encoded_app
    encoded_app=$(_urlencode "${app}") || { printf '%s' "000"; return 0; }
    splunk_curl "${sk}" --connect-timeout 5 --max-time 15 -o /dev/null -w "%{http_code}" \
        "${uri}/services/apps/local/${encoded_app}?output_mode=json" 2>/dev/null || echo "000"
}

DELETE_HTTP_CODE=""
DELETE_BODY=""
DELETE_INCOMPLETE_BUT_ABSENT=false

delete_app_via_rest() {
    local sk="$1" uri="$2" app="$3"
    local delete_response delete_rc encoded_app http_code body post_delete_check

    DELETE_HTTP_CODE=""
    DELETE_BODY=""
    DELETE_INCOMPLETE_BUT_ABSENT=false

    encoded_app=$(_urlencode "${app}") || return 1

    delete_response=""
    delete_rc=0
    set +e
    delete_response=$(splunk_curl "${sk}" --connect-timeout 10 --max-time 60 -w "\n%{http_code}" \
        -X DELETE "${uri}/services/apps/local/${encoded_app}?output_mode=json" 2>/dev/null)
    delete_rc=$?
    set -e

    http_code=$(echo "${delete_response}" | tail -1)
    body=$(printf '%s\n' "${delete_response}" | sed '$d')

    if [[ -z "${http_code}" ]] || (( delete_rc != 0 )) || [[ "${http_code}" == "000" ]]; then
        post_delete_check="$(app_lookup_http_code "${sk}" "${uri}" "${app}")"
        if [[ "${post_delete_check}" -eq 404 ]]; then
            DELETE_INCOMPLETE_BUT_ABSENT=true
            http_code="200"
            body=""
        elif [[ -z "${http_code}" ]]; then
            http_code="000"
        fi
    fi

    DELETE_HTTP_CODE="${http_code}"
    DELETE_BODY="${body}"
}

validate_app_name() {
    if [[ -z "${APP_NAME}" || "${APP_NAME}" == "." || "${APP_NAME}" == ".." || ! "${APP_NAME}" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
        log "ERROR: App name '${APP_NAME}' is not a safe concrete app identifier."
        exit 1
    fi
}

echo "=== Splunk App Uninstaller ==="
echo ""

if is_splunk_cloud; then
    acs_prepare_context || exit 1

    if [[ -z "${APP_NAME}" ]]; then
        echo ""
        echo "Fetching installed apps from Splunk Cloud..."
        response=$(acs_apps_list_all_json | acs_extract_http_response_json)

        app_list=()
        while IFS= read -r app_name; do
            [[ -n "${app_name}" ]] && app_list+=("${app_name}")
        done < <(printf '%s' "${response}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    names = sorted((app.get('name') or app.get('appID') or '') for app in data.get('apps', []))
    for name in names:
        if name:
            print(name)
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

    validate_app_name

    batch_args=()
    [[ "${ASSUME_YES}" == "true" ]] && batch_args+=(--yes)
    [[ "${RESTART_SPLUNK}" == "false" ]] && batch_args+=(--no-restart)
    [[ "${ACCEPT_REST_FALLBACK}" == "true" ]] && batch_args+=(--accept-rest-fallback)
    [[ -n "${CLOUD_VERIFY_ATTEMPTS}" ]] && batch_args+=(--verify-attempts "${CLOUD_VERIFY_ATTEMPTS}")
    [[ -n "${CLOUD_VERIFY_INTERVAL}" ]] && batch_args+=(--verify-interval "${CLOUD_VERIFY_INTERVAL}")
    [[ -n "${CLOUD_EVIDENCE_FILE}" ]] && batch_args+=(--evidence-file "${CLOUD_EVIDENCE_FILE}")
    log "Delegating Cloud removal to the ACS-authoritative batch uninstall state machine."
    exec bash "${SCRIPT_DIR}/../../shared/scripts/cloud_batch_uninstall.sh" \
        "${batch_args[@]}" "${APP_NAME}"
fi

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }

SK=$(get_session_key "${SPLUNK_URI}") || {
    log "ERROR: Failed to obtain a Splunk session key for ${SPLUNK_URI}."
    log "Check SPLUNK_USER/SPLUNK_PASS in the credentials file and management URL connectivity."
    exit 1
}
if [[ -z "${SK}" ]]; then
    log "ERROR: Splunk session key was empty for ${SPLUNK_URI}; cannot continue."
    exit 1
fi

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

validate_app_name

if [[ "${ASSUME_YES}" == "true" ]]; then
    log "Non-interactive mode (--yes): removing app '${APP_NAME}' without prompting."
else
    echo ""
    read -rp "Remove app '${APP_NAME}'? This cannot be undone. [y/N]: " confirm
    case "${confirm}" in
        [yY]|[yY][eE][sS]) ;;
        *) log "Cancelled."; exit 0 ;;
    esac
fi

log "Checking if app '${APP_NAME}' exists..."
check_response="$(app_lookup_http_code "${SK}" "${SPLUNK_URI}" "${APP_NAME}")"

if [[ "${check_response}" -ne 200 ]]; then
    log "ERROR: App '${APP_NAME}' not found (HTTP ${check_response})"
    exit 1
fi

log "Removing app '${APP_NAME}'..."
if deployment_should_use_bundle_for_current_target; then
    bundle_kind=""
    bundle_kind="$(deployment_bundle_kind_for_current_target)"
    case "${bundle_kind}" in
        shc)
            log "Using search-head-cluster deployer bundle removal."
            ;;
        idxc)
            log "Using indexer-cluster manager bundle removal."
            ;;
    esac

    if ! deployment_uninstall_app_via_bundle "${APP_NAME}"; then
        log "ERROR: Bundle-managed app removal failed."
        exit 1
    fi

    if deployment_bundle_app_exists_for_current_target "${APP_NAME}"; then
        log "ERROR: Bundle-managed app removal could not be verified on the control plane for '${APP_NAME}'."
        exit 1
    fi

    delete_check="$(app_lookup_http_code "${SK}" "${SPLUNK_URI}" "${APP_NAME}")"
    if [[ "${delete_check}" != "404" ]]; then
        log "WARNING: Bundle removal completed, but current-target REST verification returned HTTP ${delete_check} for '${APP_NAME}'."
        log "WARNING: The cluster may still be applying the updated bundle state."
    fi

    DELETE_HTTP_CODE="200"
    DELETE_BODY=""
    DELETE_INCOMPLETE_BUT_ABSENT=false
else
    delete_app_via_rest "${SK}" "${SPLUNK_URI}" "${APP_NAME}"
fi
http_code="${DELETE_HTTP_CODE:-000}"
body="${DELETE_BODY:-}"

if ${DELETE_INCOMPLETE_BUT_ABSENT}; then
    log "WARNING: DELETE request did not finish cleanly, but the app is no longer present."
fi

if [[ "${http_code}" -eq 200 || "${http_code}" -eq 204 ]]; then
    log "Removal request for '${APP_NAME}' was accepted."
    log ""
    log "Note: The app directory may still exist at:"
    log "  ${SPLUNK_HOME}/etc/apps/${APP_NAME}/"
    restart_splunk_or_exit "app removal"
    post_delete_code="$(app_lookup_http_code "${SK}" "${SPLUNK_URI}" "${APP_NAME}")"
    if [[ "${post_delete_code}" != "404" ]]; then
        log "ERROR: App '${APP_NAME}' is still present or could not be verified after removal (HTTP ${post_delete_code})."
        log "HANDOFF: Confirm bundle propagation/search-tier state before treating uninstall as complete."
        exit 1
    fi
    log "SUCCESS: App '${APP_NAME}' removal was verified."
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

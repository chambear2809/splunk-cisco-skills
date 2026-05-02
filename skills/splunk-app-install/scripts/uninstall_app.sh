#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
APP_NAME=""
RESTART_SPLUNK=true

# Accept flags for non-interactive use; anything missing gets prompted
while [[ $# -gt 0 ]]; do
    case "$1" in
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --no-restart) RESTART_SPLUNK=false; shift ;;
        --help)
            cat <<EOF
Uninstall a Splunk App (interactive)

Usage: $(basename "$0") [OPTIONS]

Optional flags (skip the corresponding prompt):
  --app-name NAME    Name of the app to remove
  --no-restart       Skip the automatic restart after uninstall

Credentials are read from the project-root credentials file automatically.
Run: bash ${SCRIPT_DIR}/../../shared/scripts/setup_credentials.sh
EOF
            exit 0 ;;
        *) log "Unknown option: $1"; exit 1 ;;
    esac
done

restart_splunk_or_exit() {
    : "${RESTART_SPLUNK}"  # Consumed by app_restart_splunk_or_exit.
    app_restart_splunk_or_exit "${SK}" "${SPLUNK_URI}" "$1" \
        "Restart manually before relying on the uninstall state." || exit 1
}

cloud_restart_or_exit() {
    : "${RESTART_SPLUNK}"  # Consumed by cloud_app_restart_or_exit.
    cloud_app_restart_or_exit "$1" \
        "Run 'acs status current-stack' and restart if required before relying on the uninstall state." || exit 1
}

refresh_cloud_verify_session() {
    SK_VERIFY=""

    load_splunk_credentials 2>/dev/null || return 1
    if [[ -z "${SPLUNK_URI:-}" ]] || [[ "${SPLUNK_URI}" != *".splunkcloud.com"* ]]; then
        return 1
    fi
    SK_VERIFY=$(get_session_key "${SPLUNK_URI}" 2>/dev/null || true)
    [[ -n "${SK_VERIFY}" ]]
}

app_lookup_http_code() {
    local sk="$1" uri="$2" app="$3"
    splunk_curl "${sk}" --connect-timeout 5 --max-time 15 -o /dev/null -w "%{http_code}" \
        "${uri}/services/apps/local/${app}?output_mode=json" 2>/dev/null || echo "000"
}

DELETE_HTTP_CODE=""
DELETE_BODY=""
DELETE_INCOMPLETE_BUT_ABSENT=false

delete_app_via_rest() {
    local sk="$1" uri="$2" app="$3"
    local delete_response delete_rc http_code body post_delete_check

    DELETE_HTTP_CODE=""
    DELETE_BODY=""
    DELETE_INCOMPLETE_BUT_ABSENT=false

    delete_response=""
    delete_rc=0
    set +e
    delete_response=$(splunk_curl "${sk}" --connect-timeout 10 --max-time 60 -w "\n%{http_code}" \
        -X DELETE "${uri}/services/apps/local/${app}?output_mode=json" 2>/dev/null)
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

    echo ""
    read -rp "Remove app '${APP_NAME}'? This cannot be undone. [y/N]: " confirm
    case "${confirm}" in
        [yY]|[yY][eE][sS]) ;;
        *) log "Cancelled."; exit 0 ;;
    esac

    log "Checking if app '${APP_NAME}' exists in Splunk Cloud..."
    if ! acs_command apps describe "${APP_NAME}" >/dev/null 2>&1; then
        log "ERROR: App '${APP_NAME}' not found in Splunk Cloud."
        exit 1
    fi

    log "Removing app '${APP_NAME}' from Splunk Cloud via ACS..."
    acs_uninstall_output=""
    acs_uninstall_rc=0
    if cloud_requires_local_scope; then
        set +e
        acs_uninstall_output=$(acs_command apps uninstall "${APP_NAME}" --scope local 2>&1)
        acs_uninstall_rc=$?
        set -e
    else
        set +e
        acs_uninstall_output=$(acs_command apps uninstall "${APP_NAME}" 2>&1)
        acs_uninstall_rc=$?
        set -e
    fi

    if (( acs_uninstall_rc == 0 )); then
        log "ACS uninstall accepted for '${APP_NAME}'."
    else
        log "WARNING: ACS uninstall returned rc=${acs_uninstall_rc} for '${APP_NAME}'."
        if [[ -n "${acs_uninstall_output}" ]]; then
            printf '%s\n' "${acs_uninstall_output}" >&2
        fi
    fi

    cloud_restart_or_exit "app removal"

    cloud_uninstall_rest_fallback_needed=false
    if refresh_cloud_verify_session; then
        if rest_check_app "${SK_VERIFY}" "${SPLUNK_URI}" "${APP_NAME}"; then
            log "WARNING: ACS reported success but the app is still present on the search tier."
            cloud_uninstall_rest_fallback_needed=true
        fi
    else
        log "WARNING: Could not verify search-tier app state after ACS uninstall."
    fi

    if ${cloud_uninstall_rest_fallback_needed}; then
        log "Attempting direct search-tier REST DELETE as fallback..."
        delete_app_via_rest "${SK_VERIFY}" "${SPLUNK_URI}" "${APP_NAME}"
        delete_code="${DELETE_HTTP_CODE:-000}"
        if ${DELETE_INCOMPLETE_BUT_ABSENT}; then
            log "WARNING: Search-tier REST DELETE did not finish cleanly, but the app is no longer present."
        fi
        case "${delete_code}" in
            200)
                log "Search-tier REST DELETE succeeded (HTTP ${delete_code})."
                cloud_restart_or_exit "search-tier app removal"
                ;;
            404)
                log "App already absent from search tier (HTTP 404)."
                ;;
            *)
                log "WARNING: Search-tier REST DELETE returned HTTP ${delete_code}. Manual cleanup may be required."
                ;;
        esac
    fi

    if refresh_cloud_verify_session; then
        if rest_check_app "${SK_VERIFY}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null; then
            log "ERROR: App '${APP_NAME}' is still present on the search tier after uninstall attempts."
            log "On Victoria stacks with SHC, a direct REST DELETE on each member followed by an ACS restart may be required."
            exit 1
        fi
        log "SUCCESS: App '${APP_NAME}' has been removed from Splunk Cloud."
        exit 0
    fi

    if (( acs_uninstall_rc == 0 )); then
        log "WARNING: ACS uninstall completed, but search-tier verification is unavailable."
    else
        log "ERROR: ACS uninstall failed and search-tier verification is unavailable."
        exit 1
    fi
    exit 0
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

echo ""
read -rp "Remove app '${APP_NAME}'? This cannot be undone. [y/N]: " confirm
case "${confirm}" in
    [yY]|[yY][eE][sS]) ;;
    *) log "Cancelled."; exit 0 ;;
esac

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
    log "SUCCESS: App '${APP_NAME}' has been removed"
    log ""
    log "Note: The app directory may still exist at:"
    log "  ${SPLUNK_HOME}/etc/apps/${APP_NAME}/"
    restart_splunk_or_exit "app removal"
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

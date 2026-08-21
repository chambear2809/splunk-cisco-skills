#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/platform_version_helpers.sh"

APP_NAME="CiscoSecurityCloud"
APP_LABEL="Cisco Security Cloud"
APP_ID="7404"
VERIFIED_APP_VERSION="3.6.10"
PACKAGE_PATTERN="cisco-security-cloud_*"
SETTINGS_CONF="ciscosecuritycloud_settings"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
PROJECT_TA_DIR="${SCRIPT_DIR}/../../../splunk-ta"
TA_CACHE="${TA_CACHE:-${PROJECT_TA_DIR}}"

INSTALL_APP=false
RESTART_SPLUNK=true
SET_LOG_LEVEL=""
SK=""
APP_VERSION="${SPLUNK_APP_VERSION:-}"
TARGET_SPLUNK_VERSION="${SPLUNK_TARGET_VERSION:-}"
ACCEPT_UNSUPPORTED_PLATFORM="${SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM:-false}"

resolve_configuration_target_version() {
    local raw="${TARGET_SPLUNK_VERSION:-}"
    if [[ -z "${raw}" ]]; then
        if is_splunk_cloud; then
            raw="$(spv_cloud_doc_train_default)"
        else
            raw="$(spv_enterprise_default)"
        fi
    fi
    if [[ ! "${raw}" =~ ^([0-9]+)\.([0-9]+)(\.[0-9]+)?$ ]]; then
        log "ERROR: Target Splunk version '${raw}' must use MAJOR.MINOR or MAJOR.MINOR.PATCH."
        return 1
    fi
    TARGET_SPLUNK_VERSION="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}"
    export SPLUNK_TARGET_VERSION="${TARGET_SPLUNK_VERSION}"
    export SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM="${ACCEPT_UNSUPPORTED_PLATFORM}"
}

require_configuration_version_compatible() {
    local selected_version="${1:-}"
    local version_source="${2:-selected package}"

    [[ "${TARGET_SPLUNK_VERSION}" == "10.5" ]] || return 0
    if [[ "${selected_version}" == "${VERIFIED_APP_VERSION}" ]]; then
        log "Compatibility preflight passed: ${version_source} ${APP_NAME} ${VERIFIED_APP_VERSION} is repo-verified for Splunk 10.5."
        return 0
    fi
    if [[ "${ACCEPT_UNSUPPORTED_PLATFORM}" == "true" ]]; then
        log "WARNING: Explicit vendor-approved override accepted for ${version_source} ${APP_NAME} ${selected_version:-unknown} on Splunk ${TARGET_SPLUNK_VERSION}."
        return 0
    fi

    log "ERROR: ${version_source} ${APP_NAME} ${selected_version:-unknown} is not the repo-verified Splunk 10.5 package (${VERIFIED_APP_VERSION})."
    log "Refusing configuration before any REST mutation. Pass --accept-unsupported-platform only with documented vendor approval for this exact package and stack."
    return 1
}

preflight_configuration_platform() {
    resolve_configuration_target_version || return 1
    if [[ "${TARGET_SPLUNK_VERSION}" == "10.5" && -n "${APP_VERSION}" ]]; then
        require_configuration_version_compatible "${APP_VERSION}" "selected"
        return $?
    fi
    if [[ "${TARGET_SPLUNK_VERSION}" == "10.5" ]]; then
        if $INSTALL_APP; then
            log "INFO: No --app-version supplied; the shared installer will select repo-verified ${VERIFIED_APP_VERSION}, and the installed version will be read before any post-install REST mutation."
        else
            log "INFO: No --app-version supplied; the installed ${APP_NAME} version will be read and verified before any REST mutation."
        fi
    fi
}

verify_installed_package_before_mutation() {
    local installed_version
    [[ "${TARGET_SPLUNK_VERSION}" == "10.5" ]] || return 0
    if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null; then
        log "ERROR: ${APP_LABEL} is not installed; cannot verify a package version before mutation."
        return 1
    fi
    installed_version="$(rest_get_app_version "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || true)"
    require_configuration_version_compatible "${installed_version}" "installed"
}

usage() {
    cat >&2 <<EOF
Cisco Security Cloud Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --install                  Install the app first
  --set-log-level LEVEL      Set app logging level (DEBUG|INFO|WARN|ERROR|CRITICAL)
  --no-restart               Skip restart when --install is used
  --app-version VERSION      Package version to install/configure
                             (default contract: repo-verified ${VERIFIED_APP_VERSION})
  --target-splunk-version V  Target Splunk MAJOR.MINOR[.PATCH]
  --accept-unsupported-platform
                             Allow an unverified package/version combination only
                             with documented vendor approval
  --help                     Show this help

With no flags, reports installation status and current logging settings.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL_APP=true; shift ;;
        --set-log-level) require_arg "$1" $# || exit 1; SET_LOG_LEVEL="$2"; shift 2 ;;
        --no-restart) RESTART_SPLUNK=false; shift ;;
        --app-version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --target-splunk-version) require_arg "$1" $# || exit 1; TARGET_SPLUNK_VERSION="$2"; shift 2 ;;
        --accept-unsupported-platform) ACCEPT_UNSUPPORTED_PLATFORM=true; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_log_level() {
    case "${1:-}" in
        DEBUG|INFO|WARN|ERROR|CRITICAL) return 0 ;;
        "") return 0 ;;
        *)
            log "ERROR: Invalid log level '${1}'. Use DEBUG, INFO, WARN, ERROR, or CRITICAL."
            exit 1
            ;;
    esac
}

find_local_package() {
    python3 -c "
import fnmatch
import sys
from pathlib import Path

pattern = sys.argv[1].lower()
seen = set()
for raw_dir in sys.argv[2:]:
    directory = Path(raw_dir)
    if not directory.is_dir():
        continue
    for child in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_file():
            continue
        name = child.name.lower()
        if not (name.endswith('.tgz') or name.endswith('.spl') or name.endswith('.tar.gz')):
            continue
        resolved = str(child.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        if fnmatch.fnmatch(name, pattern):
            print(resolved, end='')
            raise SystemExit(0)
" "${PACKAGE_PATTERN}" "${PROJECT_TA_DIR}" "${TA_CACHE}" 2>/dev/null || true
}

ensure_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

install_app_package() {
    local package_path
    local -a install_args=(--target-splunk-version "${TARGET_SPLUNK_VERSION}")
    [[ -n "${APP_VERSION}" ]] && install_args+=(--app-version "${APP_VERSION}")
    [[ "${ACCEPT_UNSUPPORTED_PLATFORM}" == "true" ]] && install_args+=(--accept-unsupported-platform)
    [[ "${RESTART_SPLUNK}" == "false" ]] && install_args+=(--no-restart)

    ensure_session
    if rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME"; then
        log "${APP_LABEL} already installed — skipping install."
        return 0
    fi

    log "Trying Splunkbase install for ${APP_LABEL} (app ID ${APP_ID}); the shared installer selects repo-verified ${VERIFIED_APP_VERSION} unless --app-version is explicit."
    if bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${APP_ID}" --no-update "${install_args[@]}"; then
        return 0
    fi
    log "Splunkbase install failed for ${APP_LABEL}; falling back to local package."

    package_path="$(find_local_package)"
    if [[ -z "${package_path}" ]]; then
        log "ERROR: No local package matching ${PACKAGE_PATTERN} found in ${PROJECT_TA_DIR} or ${TA_CACHE}."
        exit 1
    fi

    log "Installing ${APP_LABEL} from ${package_path}..."
    bash "${APP_INSTALL_SCRIPT}" --source local --file "${package_path}" --no-update "${install_args[@]}"
}

set_logging_level() {
    local body
    validate_log_level "${SET_LOG_LEVEL}"
    [[ -n "${SET_LOG_LEVEL}" ]] || return 0

    body=$(form_urlencode_pairs loglevel "${SET_LOG_LEVEL}")
    if ! rest_set_conf "$SK" "$SPLUNK_URI" "$APP_NAME" "${SETTINGS_CONF}" "logging" "${body}"; then
        log "ERROR: Failed to update ${SETTINGS_CONF}.conf logging stanza."
        exit 1
    fi
    log "Set ${APP_NAME} log level to ${SET_LOG_LEVEL}."
    log "$(log_platform_restart_guidance "settings changes")"
}

report_status() {
    local version current_level
    if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null; then
        log "ERROR: ${APP_LABEL} is not installed. Re-run with --install or install app ID ${APP_ID} first."
        exit 1
    fi

    version=$(rest_get_app_version "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || echo "unknown")
    current_level=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "${SETTINGS_CONF}" "logging" "loglevel" 2>/dev/null || true)

    log "Installed app: ${APP_NAME} (version: ${version})"
    if [[ "${TARGET_SPLUNK_VERSION}" == "10.5" && "${version}" != "${VERIFIED_APP_VERSION}" ]]; then
        log "WARNING: Installed ${APP_NAME} ${version} is not the repo-verified Splunk 10.5 package (${VERIFIED_APP_VERSION})."
        log "Status reporting is read-only; any later mutation requires a supported version or a documented vendor-approved --accept-unsupported-platform override."
    fi
    if [[ -n "${current_level}" ]]; then
        log "Current log level: ${current_level}"
    else
        log "Current log level: not configured"
    fi
    log "Use configure_product.sh to run one product-specific setup flow."
    log "Use configure_input.sh only for advanced or unsupported edge cases."
}

main() {
    if $INSTALL_APP || [[ -n "${SET_LOG_LEVEL}" ]]; then
        preflight_configuration_platform || exit 1
    else
        resolve_configuration_target_version || exit 1
    fi
    warn_if_current_skill_role_unsupported

    validate_log_level "${SET_LOG_LEVEL}"

    if $INSTALL_APP; then
        install_app_package
    fi

    ensure_session
    if $INSTALL_APP || [[ -n "${SET_LOG_LEVEL}" ]]; then
        verify_installed_package_before_mutation || exit 1
    fi
    set_logging_level
    report_status
}

main

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco-cloud-security"
APP_LABEL="Cisco Secure Access App for Splunk"
APP_ID="5558"
PACKAGE_PATTERN="cisco-secure-access-app-for-splunk_*"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
PROJECT_TA_DIR="${SCRIPT_DIR}/../../../splunk-ta"
TA_CACHE="${TA_CACHE:-${PROJECT_TA_DIR}}"

INSTALL_APP=false
RESTART_SPLUNK=true
SK=""

usage() {
    cat <<EOF
Cisco Secure Access Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --install                  Install the app first
  --no-restart               Skip restart when --install is used
  --help                     Show this help

With no flags, reports installation status and reminds you to run configure_account.sh.
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL_APP=true; shift ;;
        --no-restart) RESTART_SPLUNK=false; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

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

resolve_latest_version() {
    _set_splunkbase_curl_tls_args || return 0
    # shellcheck disable=SC2154  # _tls_verify_args is populated by _set_splunkbase_curl_tls_args.
    curl -s ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} \
        "https://splunkbase.splunk.com/api/v1/app/${APP_ID}/release/" 2>/dev/null \
        | python3 -c "
import json
import sys
try:
    releases = json.load(sys.stdin)
    if isinstance(releases, list) and releases:
        print(releases[0].get('name', ''), end='')
except Exception:
    pass
" 2>/dev/null || true
}

ensure_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

install_app_package() {
    local version package_path

    ensure_session
    if rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME"; then
        log "${APP_LABEL} already installed — skipping install."
        return 0
    fi

    version="$(resolve_latest_version)"
    if [[ -n "${version}" ]]; then
        log "Trying Splunkbase install for ${APP_LABEL} (app ID ${APP_ID}, version ${version})..."
        if [[ "${RESTART_SPLUNK}" == "true" ]]; then
            if bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${APP_ID}" --app-version "${version}" --no-update; then
                return 0
            fi
        else
            if bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${APP_ID}" --app-version "${version}" --no-update --no-restart; then
                return 0
            fi
        fi
        log "Splunkbase install failed for ${APP_LABEL}; falling back to local package."
    else
        log "WARNING: Could not resolve the latest Splunkbase version for app ID ${APP_ID}; using local fallback if available."
    fi

    package_path="$(find_local_package)"
    if [[ -z "${package_path}" ]]; then
        log "ERROR: No local package matching ${PACKAGE_PATTERN} found in ${PROJECT_TA_DIR} or ${TA_CACHE}."
        exit 1
    fi

    log "Installing ${APP_LABEL} from ${package_path}..."
    if [[ "${RESTART_SPLUNK}" == "true" ]]; then
        bash "${APP_INSTALL_SCRIPT}" --source local --file "${package_path}" --no-update
    else
        bash "${APP_INSTALL_SCRIPT}" --source local --file "${package_path}" --no-update --no-restart
    fi
}

report_status() {
    local version
    if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null; then
        log "ERROR: ${APP_LABEL} is not installed. Re-run with --install or install app ID ${APP_ID} first."
        exit 1
    fi

    version=$(rest_get_app_version "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || echo "unknown")
    log "Installed app: ${APP_NAME} (version: ${version})"
    log "Use configure_account.sh to create or update one Secure Access org account."
    log "Then use configure_settings.sh to bootstrap app terms, dashboard settings, and optional Cloudlock or destination-list features."
}

main() {
    warn_if_current_skill_role_unsupported

    if $INSTALL_APP; then
        install_app_package
    fi

    ensure_session
    report_status
}

main

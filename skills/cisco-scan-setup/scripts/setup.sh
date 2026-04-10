#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="splunk-cisco-app-navigator"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
PACKAGE_GLOB="splunk-cisco-app-navigator-*.tar.gz"

DO_SYNC=false
NO_RESTART=false

usage() {
    cat >&2 <<EOF
Splunk Cisco App Navigator (SCAN) Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --sync          Trigger initial catalog sync from S3 after install
  --no-restart    Skip automatic restart guidance
  --help          Show this help

With no flags, installs the app and verifies the product catalog.
Use --sync to also pull the latest products.conf and Splunkbase
lookup from S3 (requires outbound HTTPS to is4s.s3.amazonaws.com).
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sync) DO_SYNC=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

ensure_search_api_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk. Check credentials."; exit 1; }
}

find_scan_package() {
    local pkg
    pkg=$(compgen -G "${REPO_ROOT}/splunk-ta/${PACKAGE_GLOB}" 2>/dev/null | sort -V | tail -1 || true)
    if [[ -z "${pkg}" ]]; then
        log "ERROR: No SCAN package matching ${PACKAGE_GLOB} found in splunk-ta/"
        exit 1
    fi
    echo "${pkg}"
}

install_app() {
    local package
    package="$(find_scan_package)"
    log "Installing ${APP_NAME} from ${package}..."

    local install_flags=(--source local --file "${package}")
    if $NO_RESTART; then
        install_flags+=(--no-restart)
    fi

    bash "${APP_INSTALL_SCRIPT}" "${install_flags[@]}"
}

ensure_app_visible() {
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

verify_products_conf() {
    log "Verifying product catalog via REST..."
    local count
    count=$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/configs/conf-products?output_mode=json&count=0" 2>/dev/null \
        | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(len(d.get('entry', [])))
except Exception:
    print(0)
" 2>/dev/null || echo "0")

    if [[ "${count}" -gt 0 ]]; then
        log "  Product catalog loaded: ${count} product stanzas"
    else
        log "WARNING: Product catalog returned 0 stanzas — check app installation"
    fi
}

verify_lookup() {
    log "Verifying Splunkbase lookup..."
    local http_code
    http_code=$(splunk_curl "${SK}" --connect-timeout 5 --max-time 15 \
        "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/transforms/lookups/scan_splunkbase_apps?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")

    if [[ "${http_code}" == "200" ]]; then
        log "  Lookup 'scan_splunkbase_apps' found"
    else
        log "WARNING: Lookup 'scan_splunkbase_apps' not accessible (HTTP ${http_code})"
    fi
}

run_catalog_sync() {
    log "Running catalog sync (synccatalog)..."
    local result
    result=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
        "| synccatalog dryrun=false" "status" 2>/dev/null || echo "unknown")
    log "  synccatalog result: ${result}"

    log "Running Splunkbase lookup sync (synclookup)..."
    local lookup_result
    lookup_result=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
        "| synclookup input_csv=splunkbase_assets/splunkbase_apps.csv.gz output_csv=scan_splunkbase_apps.csv.gz" \
        "status" 2>/dev/null || echo "error")
    if [[ "${lookup_result}" == "error" ]] || [[ "${lookup_result}" == "0" ]]; then
        log "WARNING: synclookup may have failed — check synclookup.log on the search head"
    else
        log "  synclookup result: ${lookup_result}"
    fi
}

main() {
    warn_if_current_skill_role_unsupported

    ensure_search_api_session

    if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        local version
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}")
        log "${APP_NAME} already installed (version: ${version})"
    else
        install_app
        ensure_search_api_session
        if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
            log "ERROR: App installation failed — ${APP_NAME} not found after install"
            exit 1
        fi
        log "${APP_NAME} installed successfully"
    fi

    ensure_app_visible
    verify_products_conf
    verify_lookup

    if $DO_SYNC; then
        run_catalog_sync
    fi

    if ! $NO_RESTART; then
        log "$(log_platform_restart_guidance "app installation")"
    fi

    log ""
    log "Setup complete. Run 'bash ${SCRIPT_DIR}/validate.sh' to verify the deployment."
}

main

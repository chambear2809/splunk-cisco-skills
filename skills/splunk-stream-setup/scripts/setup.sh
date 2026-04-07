#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PROJECT_TA_DIR="${SCRIPT_DIR}/../../../splunk-ta"
TA_CACHE="${TA_CACHE:-${PROJECT_TA_DIR}}"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
REGISTRY_FILE="${REGISTRY_FILE:-${SCRIPT_DIR}/../../shared/app_registry.json}"

INSTALL=false
INDEXES_ONLY=false
CONFIGURE_STREAMFWD=false
FULL_SETUP=false
LEGACY_ALL_IN_ONE=false

IP_ADDR=""
PORT="8889"
SPLUNK_WEB_URL=""
SSL_VERIFY="false"
NETFLOW_IP=""
NETFLOW_PORT=""
NETFLOW_DECODER="netflow"
STREAM_SETUP_ROLE=""

usage() {
    cat >&2 <<EOF
Splunk Stream Setup Automation

Usage: $(basename "$0") [OPTIONS]

Operations:
  --install                Install missing Stream apps (Splunkbase first, local fallback)
  --indexes-only           Create indexes only
  --configure-streamfwd    Configure the stream forwarder
  --legacy-all-in-one      Allow the legacy no-role install fallback
  (no flags)               Full setup: install + indexes + configure

Stream Forwarder Options (used with --configure-streamfwd or full setup):
  --ip-addr IP             IP address for streamfwd to bind to
  --port PORT              Port for streamfwd (default: 8889)
  --splunk-web-url URL     Splunk Web URL (e.g. https://host:8000)
  --ssl-verify true|false  SSL certificate verification (default: false)

NetFlow Options (optional):
  --netflow-ip IP          NetFlow receiver bind IP (e.g. 0.0.0.0)
  --netflow-port PORT      NetFlow receiver port (e.g. 9995)
  --netflow-decoder TYPE   Flow decoder: netflow, sflow (default: netflow)

Environment:
  SPLUNK_SEARCH_API_URI    Search-tier REST URI (legacy alias: SPLUNK_URI)
  TA_CACHE                 Local fallback cache for app packages (default: project-root splunk-ta/)

Splunk credentials are read from the project-root credentials file automatically.
Run: bash ${SCRIPT_DIR}/../../shared/scripts/setup_credentials.sh
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL=true; shift ;;
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --configure-streamfwd) CONFIGURE_STREAMFWD=true; shift ;;
        --legacy-all-in-one) LEGACY_ALL_IN_ONE=true; shift ;;
        --ip-addr) require_arg "$1" $# || exit 1; IP_ADDR="$2"; shift 2 ;;
        --port) require_arg "$1" $# || exit 1; PORT="$2"; shift 2 ;;
        --splunk-web-url) require_arg "$1" $# || exit 1; SPLUNK_WEB_URL="$2"; shift 2 ;;
        --ssl-verify) require_arg "$1" $# || exit 1; SSL_VERIFY="$2"; shift 2 ;;
        --netflow-ip) require_arg "$1" $# || exit 1; NETFLOW_IP="$2"; shift 2 ;;
        --netflow-port) require_arg "$1" $# || exit 1; NETFLOW_PORT="$2"; shift 2 ;;
        --netflow-decoder) require_arg "$1" $# || exit 1; NETFLOW_DECODER="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

if ! $INSTALL && ! $INDEXES_ONLY && ! $CONFIGURE_STREAMFWD; then
    FULL_SETUP=true
fi

_get_session_key() {
    load_splunk_credentials || return 1
    SK=$(get_session_key "${SPLUNK_URI}") || return 1
}

check_connectivity() {
    _get_session_key || return 1
    local http_code
    http_code=$(splunk_curl "${SK}" "${SPLUNK_URI}/services/server/info?output_mode=json" -o /dev/null -w '%{http_code}' 2>/dev/null) || true
    if [[ "${http_code}" != "200" ]]; then
        log "ERROR: Cannot connect to Splunk at ${SPLUNK_URI}. Check SPLUNK_SEARCH_API_URI/SPLUNK_URI and credentials."
        return 1
    fi
    return 0
}

lookup_splunkbase_id() {
    local app_name="$1"
    [[ -f "${REGISTRY_FILE}" ]] || return 0
    python3 -c "
import json, sys

target_app = sys.argv[1]
registry_path = sys.argv[2]

with open(registry_path, encoding='utf-8') as handle:
    registry = json.load(handle)

for app in registry.get('apps', []):
    if app.get('skill') == 'splunk-stream-setup' and app.get('app_name') == target_app:
        print(app.get('splunkbase_id', ''), end='')
        break
" "${app_name}" "${REGISTRY_FILE}" 2>/dev/null || true
}

stream_setup_role() {
    if [[ -n "${STREAM_SETUP_ROLE:-}" ]]; then
        printf '%s' "${STREAM_SETUP_ROLE}"
        return 0
    fi

    STREAM_SETUP_ROLE="$(resolve_splunk_target_role 2>/dev/null || true)"
    printf '%s' "${STREAM_SETUP_ROLE}"
}

stream_role_supports_forwarder_actions() {
    case "${1:-}" in
        ""|heavy-forwarder|universal-forwarder)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

stream_preflight_role_checks() {
    local role

    role="$(stream_setup_role)"
    [[ -n "${role}" ]] || return 0

    if $FULL_SETUP; then
        log "ERROR: Full Stream setup spans multiple runtime roles and should not run against a role-scoped target (${role})."
        log "Use --install, --indexes-only, and --configure-streamfwd as separate role-specific runs."
        exit 1
    fi

    if $CONFIGURE_STREAMFWD && ! stream_role_supports_forwarder_actions "${role}"; then
        log "ERROR: Stream forwarder configuration belongs on a heavy or universal forwarder, not role '${role}'."
        log "Point the run at the forwarder management endpoint or override the role for the forwarder-side target."
        exit 1
    fi
}

stream_role_support_for_app() {
    local app_name="${1:-}"
    local role="${2:-}"

    [[ -n "${app_name}" && -n "${role}" ]] || return 0
    shared_registry_app_role_support_by_name "${app_name}" "${role}"
}

stream_install_targets() {
    local role="${1:-}"
    local -a selected_apps=()
    local support app_name
    local -a all_apps=(
        "splunk_app_stream"
        "Splunk_TA_stream"
        "Splunk_TA_stream_wire_data"
    )

    if [[ -z "${role}" ]]; then
        if [[ "${LEGACY_ALL_IN_ONE}" != "true" ]]; then
            log "ERROR: Stream app installation requires a declared deployment role." >&2
            log "Set SPLUNK_TARGET_ROLE for the target, or pass --legacy-all-in-one to keep the old compatibility behavior." >&2
            return 1
        fi
        printf '%s\n' "${all_apps[@]}"
        return 0
    fi

    for app_name in "${all_apps[@]}"; do
        support="$(stream_role_support_for_app "${app_name}" "${role}")"
        if [[ -z "${support}" ]]; then
            if [[ "${LEGACY_ALL_IN_ONE}" == "true" ]]; then
                log "WARNING: Stream role metadata is unavailable for '${app_name}' on role '${role}'. Falling back to the legacy all-in-one install set." >&2
                printf '%s\n' "${all_apps[@]}"
                return 0
            fi
            log "ERROR: Stream role metadata is unavailable for '${app_name}' on role '${role}'." >&2
            log "ERROR: Fix the role metadata or rerun with --legacy-all-in-one for the old compatibility behavior." >&2
            return 1
        fi
        if [[ "${support}" != "none" ]]; then
            selected_apps+=("${app_name}")
        fi
    done

    if (( ${#selected_apps[@]} == 0 )); then
        log "ERROR: No Splunk Stream packages are modeled for role '${role}'." >&2
        return 1
    fi

    printf '%s\n' "${selected_apps[@]}"
}

stream_package_path() {
    case "${1:-}" in
        splunk_app_stream)
            printf '%s' "${TA_CACHE}/splunk-app-for-stream_816.tgz"
            ;;
        Splunk_TA_stream)
            printf '%s' "${TA_CACHE}/splunk-add-on-for-stream-forwarders_816.tgz"
            ;;
        Splunk_TA_stream_wire_data)
            printf '%s' "${TA_CACHE}/splunk-add-on-for-stream-wire-data_816.tgz"
            ;;
    esac
}

install_app_with_fallback() {
    local pkg_file="$1"
    local app_name="$2"
    local app_id

    if rest_check_app "${SK}" "${SPLUNK_URI}" "${app_name}"; then
        log "  ${app_name} already installed — skipping"
        return 0
    fi

    app_id="$(lookup_splunkbase_id "${app_name}")"
    if [[ -n "${app_id}" ]]; then
        log "  Trying Splunkbase install for ${app_name} (app ID ${app_id})..."
        if bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "${app_id}" --no-update --no-restart; then
            log "  ${app_name} installation completed via Splunkbase."
            return 0
        fi
        log "  Splunkbase install failed for ${app_name}; falling back to local package."
    else
        log "  WARNING: No Splunkbase ID found for ${app_name}; falling back to local package."
    fi

    if [[ ! -f "${pkg_file}" ]]; then
        log "  ERROR: Package not found: ${pkg_file}"
        return 1
    fi

    log "  Installing ${app_name} from ${pkg_file} via splunk-app-install..."
    if bash "${APP_INSTALL_SCRIPT}" --source local --file "${pkg_file}" --no-update --no-restart; then
        log "  ${app_name} installation completed from local package."
    else
        log "  ERROR: Failed to install ${app_name} from ${pkg_file}"
        return 1
    fi
}

install_apps() {
    local role app_name install_targets_output

    log "=== Installing Splunk Stream Apps ==="
    _get_session_key || exit 1

    role="$(stream_setup_role)"
    if [[ -n "${role}" ]]; then
        log "Active deployment role: ${role}"
    elif [[ "${LEGACY_ALL_IN_ONE}" == "true" ]]; then
        log "No deployment role declared; using the explicit legacy all-in-one Stream install set."
    else
        log "No deployment role declared for Stream app installation."
    fi

    install_targets_output="$(stream_install_targets "${role}")" || exit 1
    while IFS= read -r app_name || [[ -n "${app_name}" ]]; do
        [[ -n "${app_name}" ]] || continue
        install_app_with_fallback \
            "$(stream_package_path "${app_name}")" \
            "${app_name}"
    done <<< "${install_targets_output}"

    log "App installation complete."
}

create_indexes() {
    log "=== Creating Indexes ==="
    local session_key="${SK-}"
    load_splunk_connection_settings || exit 1
    if ! is_splunk_cloud; then
        _get_session_key || exit 1
        session_key="${SK}"
    fi

    if platform_create_index "${session_key}" "${SPLUNK_URI}" "netflow" "512000"; then
        log "  Index 'netflow' created or already exists."
    else
        log "  ERROR: Failed to create index 'netflow'."
        return 1
    fi
    if platform_create_index "${session_key}" "${SPLUNK_URI}" "stream" "512000"; then
        log "  Index 'stream' created or already exists."
    else
        log "  ERROR: Failed to create index 'stream'."
        return 1
    fi

    log "Index creation complete."
}

configure_streamfwd() {
    local role

    log "=== Configuring Stream Forwarder ==="
    role="$(stream_setup_role)"
    if ! stream_role_supports_forwarder_actions "${role}"; then
        log "ERROR: Stream forwarder configuration belongs on a heavy or universal forwarder, not role '${role:-unknown}'."
        log "Point the run at the forwarder management endpoint or override the role for the forwarder-side target."
        exit 1
    fi

    _get_session_key || exit 1

    if [[ -z "${IP_ADDR}" ]]; then
        read -rp "Stream forwarder IP address: " IP_ADDR
    fi
    if [[ -z "${SPLUNK_WEB_URL}" ]]; then
        read -rp "Splunk Web URL (e.g. https://host:8000): " SPLUNK_WEB_URL
    fi

    local streamfwd_body
    streamfwd_body=$(form_urlencode_pairs port "${PORT}" ipAddr "${IP_ADDR}")
    if [[ -n "${NETFLOW_IP}" && -n "${NETFLOW_PORT}" ]]; then
        log "  Adding NetFlow receiver (${NETFLOW_IP}:${NETFLOW_PORT}, decoder=${NETFLOW_DECODER})..."
        streamfwd_body="${streamfwd_body}&$(form_urlencode_pairs \
            netflowReceiver.0.ip "${NETFLOW_IP}" \
            netflowReceiver.0.port "${NETFLOW_PORT}" \
            netflowReceiver.0.decoder "${NETFLOW_DECODER}")"
    fi

    log "  Setting streamfwd.conf (ipAddr=${IP_ADDR}, port=${PORT})..."
    if ! rest_set_conf "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "streamfwd" "streamfwd" "${streamfwd_body}"; then
        log "  ERROR: Failed to update streamfwd.conf settings."
        exit 1
    fi

    local inputs_body stream_app_location
    stream_app_location="${SPLUNK_WEB_URL}/en-us/custom/splunk_app_stream/"
    inputs_body=$(form_urlencode_pairs \
        splunk_stream_app_location "${stream_app_location}" \
        stream_forwarder_id "" \
        disabled "0" \
        sslVerifyServerCert "${SSL_VERIFY}")
    log "  Setting inputs.conf (stream_app_location=${stream_app_location})..."
    if ! rest_set_conf "${SK}" "${SPLUNK_URI}" "Splunk_TA_stream" "inputs" "streamfwd://streamfwd" \
        "${inputs_body}"; then
        log "  ERROR: Failed to update streamfwd input settings."
        exit 1
    fi

    log "Stream forwarder configuration complete."
}

stream_cloud_guard() {
    if ! is_splunk_cloud; then
        return 0
    fi

    log "ERROR: Splunk Stream on Splunk Cloud is a hybrid deployment."
    log "The cloud search-tier app is managed on the Splunk Cloud stack, while Splunk_TA_stream runs on forwarders under your control."
    log "This script's --install and --configure-streamfwd actions target one runtime role at a time and are not safe against the Cloud search tier."
    log "Use --indexes-only against the Splunk Cloud stack, and run forwarder-side Stream configuration against the forwarder management endpoint."
    log "If your credentials file contains both Cloud and forwarder targets, interactive runs will prompt when needed. For non-interactive runs, use SPLUNK_PLATFORM=enterprise as an override."
    exit 1
}

main() {
    warn_if_current_skill_role_unsupported

    if is_splunk_cloud; then
        if $INSTALL || $CONFIGURE_STREAMFWD || $FULL_SETUP; then
            stream_cloud_guard
        fi
    fi

    stream_preflight_role_checks

    if is_splunk_cloud && $INDEXES_ONLY; then
        create_indexes
        log "$(log_platform_restart_guidance "index changes")"
        exit 0
    fi

    if ! check_connectivity; then
        exit 1
    fi

    if $INDEXES_ONLY; then
        create_indexes
        log "$(log_platform_restart_guidance "index changes")"
        exit 0
    fi

    if $INSTALL; then
        install_apps
        log "$(log_platform_restart_guidance "app changes")"
        exit 0
    fi

    if $CONFIGURE_STREAMFWD; then
        configure_streamfwd
        log "$(log_platform_restart_guidance "stream forwarder changes")"
        exit 0
    fi

    if $FULL_SETUP; then
        install_apps
        create_indexes
        configure_streamfwd
        log ""
        log "=== Full setup complete ==="
        log "$(log_platform_restart_guidance "app or index changes")"
        log "Then enable protocol streams with configure_streams.sh."
    fi
}

main

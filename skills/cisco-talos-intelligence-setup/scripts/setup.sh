#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_Talos_Intelligence"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
INSTALL=false
NO_RESTART=false
SUPPORT_PREFLIGHT_ONLY=false
INDEX="talos_intelligence"
ENABLE_IP_BLACKLIST=false
SK=""

usage() {
    cat >&2 <<EOF
Cisco Talos Intelligence Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --install                    Install app from Splunkbase ID 7557
  --no-restart                 Skip restart during package installation
  --support-preflight-only     Check ES Cloud support posture and exit
  --index INDEX                Collection alert-action index (default: talos_intelligence)
  --enable-ip-blacklist        Enable packaged Talos IP blacklist threatlist
  --help                       Show this help
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --support-preflight-only) SUPPORT_PREFLIGHT_ONLY=true; shift ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --enable-ip-blacklist) ENABLE_IP_BLACKLIST=true; shift ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

ensure_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

version_at_least() {
    python3 - "$1" "$2" <<'PY'
import re
import sys

def parts(value):
    nums = [int(x) for x in re.findall(r"\d+", value)]
    return nums + [0] * (4 - len(nums))

sys.exit(0 if parts(sys.argv[1]) >= parts(sys.argv[2]) else 1)
PY
}

is_fedramp_target() {
    local value
    value="${SPLUNK_CLOUD_STACK:-} ${SPLUNK_CLOUD_SEARCH_HEAD:-} ${SPLUNK_URI:-} ${SPLUNK_HOST:-} ${ACS_SERVER:-}"
    value="${value,,}"
    [[ "${value}" == *fedramp* || "${value}" == *splunkcloudgc.com* || "${value}" == *".gov."* ]]
}

support_preflight() {
    local failures=0 es_version
    ensure_session

    if is_splunk_cloud; then
        log "Confirmed Splunk Cloud target for Talos ES Cloud workflow."
    else
        log "ERROR: Talos Intelligence is documented for Splunk Enterprise Security Cloud only."
        failures=$((failures + 1))
    fi

    if is_fedramp_target; then
        log "ERROR: Talos Intelligence is not supported for FedRAMP/GovCloud targets."
        failures=$((failures + 1))
    else
        log "Confirmed target does not look like a FedRAMP/GovCloud stack."
    fi

    if rest_check_app "${SK}" "${SPLUNK_URI}" "SplunkEnterpriseSecuritySuite"; then
        es_version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "SplunkEnterpriseSecuritySuite" 2>/dev/null || echo "unknown")
        if [[ "${es_version}" == "unknown" ]]; then
            log "ERROR: Enterprise Security is installed but its version could not be determined."
            failures=$((failures + 1))
        elif version_at_least "${es_version}" "7.3.2"; then
            log "Confirmed Enterprise Security version ${es_version} meets the 7.3.2+ Talos baseline."
        else
            log "ERROR: Enterprise Security ${es_version} is below the 7.3.2+ Talos baseline."
            failures=$((failures + 1))
        fi
    else
        log "ERROR: SplunkEnterpriseSecuritySuite is required for Talos Intelligence."
        failures=$((failures + 1))
    fi

    (( failures == 0 ))
}

install_package() {
    local cmd=(bash "${APP_INSTALL_SCRIPT}" --source splunkbase --app-id "7557" --no-update)
    [[ "${NO_RESTART}" == "true" ]] && cmd+=(--no-restart)
    "${cmd[@]}"
}

create_index() {
    if ! is_splunk_cloud; then
        ensure_session
    fi
    platform_create_index "${SK:-}" "${SPLUNK_URI:-}" "${INDEX}" "512000" \
        || { log "ERROR: Failed to ensure index ${INDEX}."; exit 1; }
    log "Ensured Talos collection index '${INDEX}'."
}

configure_threatlist_state() {
    ensure_session
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        log "ERROR: ${APP_NAME} is not installed."
        exit 1
    fi
    local disabled="1"
    [[ "${ENABLE_IP_BLACKLIST}" == "true" ]] && disabled="0"
    body=$(form_urlencode_pairs disabled "${disabled}") || exit 1
    rest_set_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "threatlist://talos_intelligence_ip_blacklist" "${body}" \
        || { log "ERROR: Failed to set Talos IP blacklist threatlist state."; exit 1; }
    if [[ "${ENABLE_IP_BLACKLIST}" == "true" ]]; then
        log "Enabled Talos IP blacklist threatlist."
    else
        log "Confirmed Talos IP blacklist threatlist remains disabled by default."
    fi
}

main() {
    warn_if_current_skill_role_unsupported
    if [[ "${SUPPORT_PREFLIGHT_ONLY}" == "true" ]]; then
        support_preflight
        exit $?
    fi
    support_preflight || exit 1
    [[ "${INSTALL}" == "true" ]] && install_package
    create_index
    configure_threatlist_state
    log "Talos setup complete. Run validate.sh to check ES Cloud/service-account readiness."
}

main

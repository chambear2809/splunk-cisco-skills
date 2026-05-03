#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-agent-management-rendered"

MODE="both"
PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
SERVERCLASS_NAME="all_linux_forwarders"
DEPLOYMENT_APP_NAME="ZZZ_cisco_skills_forwarder_base"
APP_SOURCE_DIR=""
WHITELIST="*"
BLACKLIST=""
FILTER_TYPE="whitelist"
MACHINE_TYPES_FILTER=""
RESTART_SPLUNKD="false"
CLIENT_RESTART_SPLUNKD="true"
STATE_ON_CLIENT="enabled"
AGENT_MANAGER_URI=""
CLIENT_NAME=""
PHONE_HOME_INTERVAL="60"
# shellcheck disable=SC2016 # keep literal $SPLUNK_HOME for deploymentclient.conf
REPOSITORY_LOCATION='$SPLUNK_HOME/etc/apps'
REPOSITORY_LOCATION_POLICY="rejectAlways"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Agent Management Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --mode agent-manager|deployment-client|both
  --phase render|preflight|apply|status|all
  --apply
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --serverclass-name NAME
  --deployment-app-name NAME
  --app-source-dir PATH
  --whitelist CSV
  --blacklist CSV
  --filter-type whitelist|blacklist
  --machine-types-filter VALUE
  --restart-splunkd true|false           # serverclass setting (server side)
  --client-restart-splunkd true|false    # whether apply-deployment-client.sh restarts splunkd locally (default: true)
  --state-on-client enabled|disabled|noop
  --agent-manager-uri URI
  --client-name NAME
  --phone-home-interval SECONDS
  --repository-location PATH
  --repository-location-policy acceptSplunkHome|acceptAlways|rejectAlways
  --help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode) require_arg "$1" $# || exit 1; MODE="$2"; shift 2 ;;
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --serverclass-name) require_arg "$1" $# || exit 1; SERVERCLASS_NAME="$2"; shift 2 ;;
        --deployment-app-name) require_arg "$1" $# || exit 1; DEPLOYMENT_APP_NAME="$2"; shift 2 ;;
        --app-source-dir) require_arg "$1" $# || exit 1; APP_SOURCE_DIR="$2"; shift 2 ;;
        --whitelist) require_arg "$1" $# || exit 1; WHITELIST="$2"; shift 2 ;;
        --blacklist) require_arg "$1" $# || exit 1; BLACKLIST="$2"; shift 2 ;;
        --filter-type) require_arg "$1" $# || exit 1; FILTER_TYPE="$2"; shift 2 ;;
        --machine-types-filter) require_arg "$1" $# || exit 1; MACHINE_TYPES_FILTER="$2"; shift 2 ;;
        --restart-splunkd) require_arg "$1" $# || exit 1; RESTART_SPLUNKD="$2"; shift 2 ;;
        --client-restart-splunkd) require_arg "$1" $# || exit 1; CLIENT_RESTART_SPLUNKD="$2"; shift 2 ;;
        --state-on-client) require_arg "$1" $# || exit 1; STATE_ON_CLIENT="$2"; shift 2 ;;
        --agent-manager-uri) require_arg "$1" $# || exit 1; AGENT_MANAGER_URI="$2"; shift 2 ;;
        --client-name) require_arg "$1" $# || exit 1; CLIENT_NAME="$2"; shift 2 ;;
        --phone-home-interval) require_arg "$1" $# || exit 1; PHONE_HOME_INTERVAL="$2"; shift 2 ;;
        --repository-location) require_arg "$1" $# || exit 1; REPOSITORY_LOCATION="$2"; shift 2 ;;
        --repository-location-policy) require_arg "$1" $# || exit 1; REPOSITORY_LOCATION_POLICY="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

validate_args() {
    validate_choice "${MODE}" agent-manager deployment-client both
    validate_choice "${PHASE}" render preflight apply status all
    validate_choice "${FILTER_TYPE}" whitelist blacklist
    validate_choice "${RESTART_SPLUNKD}" true false
    validate_choice "${CLIENT_RESTART_SPLUNKD}" true false
    validate_choice "${STATE_ON_CLIENT}" enabled disabled noop
    validate_choice "${REPOSITORY_LOCATION_POLICY}" acceptSplunkHome acceptAlways rejectAlways
    if [[ "${JSON_OUTPUT}" == "true" && "${DRY_RUN}" != "true" && ( "${PHASE}" != "render" || "${APPLY}" == "true" ) ]]; then
        log "ERROR: --json is supported only for render-only or --dry-run workflows."
        exit 1
    fi
    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
}

build_renderer_args() {
    RENDER_ARGS=(
        --mode "${MODE}"
        --output-dir "${OUTPUT_DIR}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --serverclass-name "${SERVERCLASS_NAME}"
        --deployment-app-name "${DEPLOYMENT_APP_NAME}"
        --app-source-dir "${APP_SOURCE_DIR}"
        --whitelist "${WHITELIST}"
        --blacklist "${BLACKLIST}"
        --filter-type "${FILTER_TYPE}"
        --machine-types-filter "${MACHINE_TYPES_FILTER}"
        --restart-splunkd "${RESTART_SPLUNKD}"
        --client-restart-splunkd "${CLIENT_RESTART_SPLUNKD}"
        --state-on-client "${STATE_ON_CLIENT}"
        --agent-manager-uri "${AGENT_MANAGER_URI}"
        --client-name "${CLIENT_NAME}"
        --phone-home-interval "${PHONE_HOME_INTERVAL}"
        --repository-location "${REPOSITORY_LOCATION}"
        --repository-location-policy "${REPOSITORY_LOCATION_POLICY}"
    )
}

render_dir() {
    printf '%s/agent-management' "${OUTPUT_DIR}"
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

run_rendered_script() {
    local script_name="$1"
    local dir
    dir="$(render_dir)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./${script_name})"
        return 0
    fi
    if [[ ! -x "${dir}/${script_name}" ]]; then
        log "ERROR: Rendered script is missing or not executable: ${dir}/${script_name}"
        exit 1
    fi
    (cd "${dir}" && "./${script_name}")
}

run_apply() {
    case "${MODE}" in
        agent-manager) run_rendered_script apply-agent-manager.sh ;;
        deployment-client) run_rendered_script apply-deployment-client.sh ;;
        both)
            run_rendered_script apply-agent-manager.sh
            run_rendered_script apply-deployment-client.sh
            ;;
    esac
}

main() {
    validate_args
    build_renderer_args
    if [[ "${DRY_RUN}" == "true" ]]; then
        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            exec python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
        fi
        python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
        exit 0
    fi
    case "${PHASE}" in
        render)
            render_assets
            if [[ "${APPLY}" == "true" ]]; then
                run_apply
            fi
            ;;
        preflight) render_assets; run_rendered_script preflight.sh ;;
        apply) render_assets; run_apply ;;
        status) run_rendered_script status.sh ;;
        all) render_assets; run_rendered_script preflight.sh; run_apply; run_rendered_script status.sh ;;
    esac
}

main "$@"

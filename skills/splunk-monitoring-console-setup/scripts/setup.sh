#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-monitoring-console-rendered"

MODE="distributed"
PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
ENABLE_AUTO_CONFIG="true"
ENABLE_FORWARDER_MONITORING="false"
FORWARDER_CRON="*/15 * * * *"
ENABLE_PLATFORM_ALERTS="false"
PLATFORM_ALERTS="Abnormal State of Indexer Processor,Near Critical Disk Usage,Saturated Event-Processing Queues,Search Peer Not Responding,Total License Usage Near Daily Quota"
SEARCH_PEERS=""
SEARCH_PEER_SCHEME="https"
SEARCH_GROUPS=""
DEFAULT_SEARCH_GROUP=""
PEER_USERNAME=""
RESTART_SPLUNK="true"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Monitoring Console Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --mode standalone|distributed
  --phase render|preflight|apply|status|all
  --apply
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --enable-auto-config true|false
  --enable-forwarder-monitoring true|false
  --forwarder-cron CRON
  --enable-platform-alerts true|false
  --platform-alerts CSV
  --search-peers HOST:PORT[,HOST:PORT]
  --search-peer-scheme https|http
  --search-groups 'NAME=HOST:PORT|HOST:PORT[;NAME=HOST:PORT]'
  --default-search-group NAME
  --peer-username USER
  --restart-splunk true|false
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
        --enable-auto-config) require_arg "$1" $# || exit 1; ENABLE_AUTO_CONFIG="$2"; shift 2 ;;
        --enable-forwarder-monitoring) require_arg "$1" $# || exit 1; ENABLE_FORWARDER_MONITORING="$2"; shift 2 ;;
        --forwarder-cron) require_arg "$1" $# || exit 1; FORWARDER_CRON="$2"; shift 2 ;;
        --enable-platform-alerts) require_arg "$1" $# || exit 1; ENABLE_PLATFORM_ALERTS="$2"; shift 2 ;;
        --platform-alerts) require_arg "$1" $# || exit 1; PLATFORM_ALERTS="$2"; shift 2 ;;
        --search-peers) require_arg "$1" $# || exit 1; SEARCH_PEERS="$2"; shift 2 ;;
        --search-peer-scheme) require_arg "$1" $# || exit 1; SEARCH_PEER_SCHEME="$2"; shift 2 ;;
        --search-groups) require_arg "$1" $# || exit 1; SEARCH_GROUPS="$2"; shift 2 ;;
        --default-search-group) require_arg "$1" $# || exit 1; DEFAULT_SEARCH_GROUP="$2"; shift 2 ;;
        --peer-username) require_arg "$1" $# || exit 1; PEER_USERNAME="$2"; shift 2 ;;
        --restart-splunk) require_arg "$1" $# || exit 1; RESTART_SPLUNK="$2"; shift 2 ;;
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
    validate_choice "${MODE}" standalone distributed
    validate_choice "${PHASE}" render preflight apply status all
    validate_choice "${ENABLE_AUTO_CONFIG}" true false
    validate_choice "${ENABLE_FORWARDER_MONITORING}" true false
    validate_choice "${ENABLE_PLATFORM_ALERTS}" true false
    validate_choice "${SEARCH_PEER_SCHEME}" https http
    validate_choice "${RESTART_SPLUNK}" true false
    if [[ -n "${SEARCH_PEERS}" && -z "${PEER_USERNAME}" ]]; then
        log "ERROR: --peer-username is required when --search-peers is supplied."
        exit 1
    fi
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
        --enable-auto-config "${ENABLE_AUTO_CONFIG}"
        --enable-forwarder-monitoring "${ENABLE_FORWARDER_MONITORING}"
        --forwarder-cron "${FORWARDER_CRON}"
        --enable-platform-alerts "${ENABLE_PLATFORM_ALERTS}"
        --platform-alerts "${PLATFORM_ALERTS}"
        --search-peers "${SEARCH_PEERS}"
        --search-peer-scheme "${SEARCH_PEER_SCHEME}"
        --search-groups "${SEARCH_GROUPS}"
        --default-search-group "${DEFAULT_SEARCH_GROUP}"
        --peer-username "${PEER_USERNAME}"
        --restart-splunk "${RESTART_SPLUNK}"
    )
}

render_dir() {
    printf '%s/monitoring-console' "${OUTPUT_DIR}"
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" "${extra_args[@]}"
}

run_rendered_script() {
    local script_name="$1" dir
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
                run_rendered_script apply.sh
            fi
            ;;
        preflight) render_assets; run_rendered_script preflight.sh ;;
        apply) render_assets; run_rendered_script apply.sh; run_rendered_script add-search-peers.sh ;;
        status) run_rendered_script status.sh ;;
        all) render_assets; run_rendered_script preflight.sh; run_rendered_script apply.sh; run_rendered_script add-search-peers.sh; run_rendered_script status.sh ;;
    esac
}

main "$@"

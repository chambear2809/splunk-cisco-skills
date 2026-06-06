#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-cim-data-model-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
APP_NAME="ZZZ_cisco_skills_cim_accel"
MODELS="Authentication,Network_Traffic,Web,Endpoint"
ACCELERATION="true"
EARLIEST_TIME="-7d@d"
BACKFILL_TIME=""
MAX_CONCURRENT=""
SUMMARY_RANGE="-24h"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk CIM Data-Model Management

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|apply|rebuild|status|audit
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --app-name NAME
  --models CSV|all
  --acceleration true|false
  --earliest-time TOKEN
  --backfill-time TOKEN
  --max-concurrent N
  --summary-range TOKEN
  --help

Phases other than 'render' first render assets, then run the matching rendered
script against splunkd (authenticate interactively when prompted).
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --models) require_arg "$1" $# || exit 1; MODELS="$2"; shift 2 ;;
        --acceleration) require_arg "$1" $# || exit 1; ACCELERATION="$2"; shift 2 ;;
        --earliest-time) require_arg "$1" $# || exit 1; EARLIEST_TIME="$2"; shift 2 ;;
        --backfill-time) require_arg "$1" $# || exit 1; BACKFILL_TIME="$2"; shift 2 ;;
        --max-concurrent) require_arg "$1" $# || exit 1; MAX_CONCURRENT="$2"; shift 2 ;;
        --summary-range) require_arg "$1" $# || exit 1; SUMMARY_RANGE="$2"; shift 2 ;;
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
    validate_choice "${PHASE}" render apply rebuild status audit
    validate_choice "${ACCELERATION}" true false
    if [[ "${JSON_OUTPUT}" == "true" && "${PHASE}" != "render" && "${DRY_RUN}" != "true" ]]; then
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
        --output-dir "${OUTPUT_DIR}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --app-name "${APP_NAME}"
        --models "${MODELS}"
        --acceleration "${ACCELERATION}"
        --earliest-time "${EARLIEST_TIME}"
        --backfill-time "${BACKFILL_TIME}"
        --max-concurrent "${MAX_CONCURRENT}"
        --summary-range "${SUMMARY_RANGE}"
    )
}

render_dir() {
    printf '%s/cim' "${OUTPUT_DIR}"
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
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
        render) render_assets ;;
        apply) render_assets; run_rendered_script apply.sh ;;
        rebuild) render_assets; run_rendered_script rebuild.sh ;;
        status) render_assets; run_rendered_script status.sh ;;
        audit) render_assets; run_rendered_script audit.sh ;;
    esac
}

main "$@"

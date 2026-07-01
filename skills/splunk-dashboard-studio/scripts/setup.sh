#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-dashboard-studio-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
TITLE=""
DESCRIPTION=""
DASHBOARD_ID=""
APP="search"
OWNER="nobody"
THEME="light"
LAYOUT="grid"
DEFAULT_EARLIEST="-24h@h"
DEFAULT_LATEST="now"
PANELS_FILE=""
PANELS=()

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Platform Dashboard Studio

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|apply|status
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --title TEXT            (required)
  --description TEXT
  --dashboard-id NAME
  --app APP
  --owner USER|nobody
  --theme light|dark
  --layout grid|absolute
  --default-earliest TOKEN
  --default-latest TOKEN
  --panel "Title::type::content"   (repeatable; types: table,single,line,area,column,bar,pie,markdown)
  --panels-file PATH
  --help
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
        --title) require_arg "$1" $# || exit 1; TITLE="$2"; shift 2 ;;
        --description) require_arg "$1" $# || exit 1; DESCRIPTION="$2"; shift 2 ;;
        --dashboard-id) require_arg "$1" $# || exit 1; DASHBOARD_ID="$2"; shift 2 ;;
        --app) require_arg "$1" $# || exit 1; APP="$2"; shift 2 ;;
        --owner) require_arg "$1" $# || exit 1; OWNER="$2"; shift 2 ;;
        --theme) require_arg "$1" $# || exit 1; THEME="$2"; shift 2 ;;
        --layout) require_arg "$1" $# || exit 1; LAYOUT="$2"; shift 2 ;;
        --default-earliest) require_arg "$1" $# || exit 1; DEFAULT_EARLIEST="$2"; shift 2 ;;
        --default-latest) require_arg "$1" $# || exit 1; DEFAULT_LATEST="$2"; shift 2 ;;
        --panel) require_arg "$1" $# || exit 1; PANELS+=("$2"); shift 2 ;;
        --panels-file) require_arg "$1" $# || exit 1; PANELS_FILE="$2"; shift 2 ;;
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
    validate_choice "${PHASE}" render apply status
    validate_choice "${THEME}" light dark
    validate_choice "${LAYOUT}" grid absolute
    if [[ -z "${TITLE}" ]]; then
        log "ERROR: --title is required."
        exit 1
    fi
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
        --title "${TITLE}"
        --description "${DESCRIPTION}"
        --dashboard-id "${DASHBOARD_ID}"
        --app "${APP}"
        --owner "${OWNER}"
        --theme "${THEME}"
        --layout "${LAYOUT}"
        --default-earliest "${DEFAULT_EARLIEST}"
        --default-latest "${DEFAULT_LATEST}"
    )
    [[ -n "${PANELS_FILE}" ]] && RENDER_ARGS+=(--panels-file "${PANELS_FILE}")
    local p
    for p in ${PANELS[@]+"${PANELS[@]}"}; do
        RENDER_ARGS+=(--panel "${p}")
    done
}

render_dir() {
    printf '%s/dashboard-studio' "${OUTPUT_DIR}"
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
        status) render_assets; run_rendered_script status.sh ;;
    esac
}

main "$@"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-kvstore-admin-rendered"

DEPLOYMENT="standalone"
PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
ARCHIVE_NAME="kvstore_backup"
RESTORE_ARCHIVE_NAME=""
STORAGE_ENGINE="unset"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk KV Store Administration

Usage: $(basename "$0") [OPTIONS]

Options:
  --deployment standalone|shc
  --phase render|status|backup|restore|migrate|resync
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --archive-name NAME
  --restore-archive-name NAME
  --storage-engine unset|wiredTiger
  --help

Phases other than 'render' first render assets, then run the matching rendered
script (which authenticates against splunkd and may prompt for confirmation).
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --deployment) require_arg "$1" $# || exit 1; DEPLOYMENT="$2"; shift 2 ;;
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --archive-name) require_arg "$1" $# || exit 1; ARCHIVE_NAME="$2"; shift 2 ;;
        --restore-archive-name) require_arg "$1" $# || exit 1; RESTORE_ARCHIVE_NAME="$2"; shift 2 ;;
        --storage-engine) require_arg "$1" $# || exit 1; STORAGE_ENGINE="$2"; shift 2 ;;
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
    validate_choice "${DEPLOYMENT}" standalone shc
    validate_choice "${PHASE}" render status backup restore migrate resync
    validate_choice "${STORAGE_ENGINE}" unset wiredTiger
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
        --deployment "${DEPLOYMENT}"
        --output-dir "${OUTPUT_DIR}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --archive-name "${ARCHIVE_NAME}"
        --restore-archive-name "${RESTORE_ARCHIVE_NAME}"
        --storage-engine "${STORAGE_ENGINE}"
    )
}

render_dir() {
    printf '%s/kvstore' "${OUTPUT_DIR}"
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
        status) render_assets; run_rendered_script status.sh ;;
        backup) render_assets; run_rendered_script backup.sh ;;
        restore) render_assets; run_rendered_script restore.sh ;;
        migrate) render_assets; run_rendered_script migrate.sh ;;
        resync) render_assets; run_rendered_script resync.sh ;;
    esac
}

main "$@"

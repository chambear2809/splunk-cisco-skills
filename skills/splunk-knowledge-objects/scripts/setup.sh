#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-knowledge-objects-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
APP_NAME="ZZZ_cisco_skills_governance"
APP_CONTEXT="search"
OBJECT_TYPES="savedsearches,macros,lookups,eventtypes,tags,fieldextractions"
REASSIGN_OWNER="admin"
SHARE_LEVEL="app"
ACL_ENDPOINT=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Knowledge-Object Governance

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|inventory|audit|apply|reassign
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --app-name NAME
  --app-context APP
  --object-types CSV|all
  --reassign-owner USER
  --share-level app|global
  --acl-endpoint PATH      (required for --phase reassign)
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
        --app-context) require_arg "$1" $# || exit 1; APP_CONTEXT="$2"; shift 2 ;;
        --object-types) require_arg "$1" $# || exit 1; OBJECT_TYPES="$2"; shift 2 ;;
        --reassign-owner) require_arg "$1" $# || exit 1; REASSIGN_OWNER="$2"; shift 2 ;;
        --share-level) require_arg "$1" $# || exit 1; SHARE_LEVEL="$2"; shift 2 ;;
        --acl-endpoint) require_arg "$1" $# || exit 1; ACL_ENDPOINT="$2"; shift 2 ;;
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
    validate_choice "${PHASE}" render inventory audit apply reassign
    validate_choice "${SHARE_LEVEL}" app global
    if [[ "${PHASE}" == "reassign" && -z "${ACL_ENDPOINT}" && "${DRY_RUN}" != "true" ]]; then
        log "ERROR: --phase reassign requires --acl-endpoint."
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
        --app-name "${APP_NAME}"
        --app-context "${APP_CONTEXT}"
        --object-types "${OBJECT_TYPES}"
        --reassign-owner "${REASSIGN_OWNER}"
        --share-level "${SHARE_LEVEL}"
    )
}

render_dir() {
    printf '%s/knowledge-objects' "${OUTPUT_DIR}"
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

run_rendered_script() {
    local script_name="$1"; shift
    local dir
    dir="$(render_dir)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./${script_name} $*)"
        return 0
    fi
    if [[ ! -x "${dir}/${script_name}" ]]; then
        log "ERROR: Rendered script is missing or not executable: ${dir}/${script_name}"
        exit 1
    fi
    (cd "${dir}" && "./${script_name}" "$@")
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
        inventory) render_assets; run_rendered_script inventory.sh ;;
        audit) render_assets; run_rendered_script audit.sh ;;
        apply) render_assets; run_rendered_script apply.sh ;;
        reassign) render_assets; run_rendered_script reassign.sh "${ACL_ENDPOINT}" ;;
    esac
}

main "$@"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-secure-gateway-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
PLATFORM="enterprise"
REGION="default"
DEPLOYMENT_NAME="Splunk Secure Gateway"
MDM="false"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Secure Gateway / Mobile

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|enable|register|status
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --platform cloud|enterprise
  --region default|us-east-1|eu-central-1|eu-west-1|eu-west-2|ap-southeast-2
  --deployment-name NAME
  --mdm true|false
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
        --platform) require_arg "$1" $# || exit 1; PLATFORM="$2"; shift 2 ;;
        --region) require_arg "$1" $# || exit 1; REGION="$2"; shift 2 ;;
        --deployment-name) require_arg "$1" $# || exit 1; DEPLOYMENT_NAME="$2"; shift 2 ;;
        --mdm) require_arg "$1" $# || exit 1; MDM="$2"; shift 2 ;;
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
    validate_choice "${PHASE}" render preflight enable register status
    validate_choice "${PLATFORM}" cloud enterprise
    validate_choice "${REGION}" default us-east-1 eu-central-1 eu-west-1 eu-west-2 ap-southeast-2
    validate_choice "${MDM}" true false
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
        --platform "${PLATFORM}"
        --region "${REGION}"
        --deployment-name "${DEPLOYMENT_NAME}"
        --mdm "${MDM}"
    )
}

render_dir() {
    printf '%s/secure-gateway' "${OUTPUT_DIR}"
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
        preflight) render_assets; run_rendered_script connectivity-preflight.sh ;;
        enable) render_assets; run_rendered_script enable.sh ;;
        register) render_assets; run_rendered_script register.sh ;;
        status) render_assets; run_rendered_script status.sh ;;
    esac
}

main "$@"

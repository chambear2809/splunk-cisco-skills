#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-license-manager-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
LICENSE_MANAGER_URI=""
LICENSE_MANAGER_HOST=""
LICENSE_MANAGER_SSH_USER="splunk"
LICENSE_FILES=""
LICENSE_GROUP="Enterprise"
POOL_SPECS=""
PEER_HOSTS=""
PEER_SSH_USER="splunk"
APPLY_TARGET="all"
COLOCATED_WITH="dedicated"
RESTART_SPLUNK="true"
ADMIN_PASSWORD_FILE=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk License Manager Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|apply|status|validate|all
  --apply
  --dry-run
  --json
  --output-dir PATH
  --license-manager-uri URI
  --license-manager-host HOST
  --license-manager-ssh-user USER
  --license-files CSV
  --license-group Enterprise|Forwarder|Free|Trial|Download-Trial
  --pool-spec SPEC                 (repeatable; key=value comma-separated; pools separated by '|' or newline when passed once)
  --peer-hosts CSV
  --peer-ssh-user USER
  --apply-target manager|peers|all
  --colocated-with cluster-manager|monitoring-console|deployment-server|shc-deployer|search-head|indexer|dedicated
  --restart-splunk true|false
  --admin-password-file PATH
  --help

Examples:
  $(basename "$0") --license-manager-uri https://lm01:8089 --license-files /etc/splunk/enterprise.lic \\
                   --pool-spec name=ent_main,stack_id=enterprise,quota=MAX --peer-hosts idx01,idx02
  $(basename "$0") --phase apply --apply-target peers --license-manager-uri https://lm01:8089 \\
                   --peer-hosts idx01,idx02 --admin-password-file /tmp/splunk_admin_password

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --license-manager-uri) require_arg "$1" $# || exit 1; LICENSE_MANAGER_URI="$2"; shift 2 ;;
        --license-manager-host) require_arg "$1" $# || exit 1; LICENSE_MANAGER_HOST="$2"; shift 2 ;;
        --license-manager-ssh-user) require_arg "$1" $# || exit 1; LICENSE_MANAGER_SSH_USER="$2"; shift 2 ;;
        --license-files) require_arg "$1" $# || exit 1; LICENSE_FILES="$2"; shift 2 ;;
        --license-group) require_arg "$1" $# || exit 1; LICENSE_GROUP="$2"; shift 2 ;;
        --pool-spec)
            require_arg "$1" $# || exit 1
            if [[ -n "${POOL_SPECS}" ]]; then
                POOL_SPECS+=$'\n'
            fi
            POOL_SPECS+="$2"
            shift 2
            ;;
        --peer-hosts) require_arg "$1" $# || exit 1; PEER_HOSTS="$2"; shift 2 ;;
        --peer-ssh-user) require_arg "$1" $# || exit 1; PEER_SSH_USER="$2"; shift 2 ;;
        --apply-target) require_arg "$1" $# || exit 1; APPLY_TARGET="$2"; shift 2 ;;
        --colocated-with) require_arg "$1" $# || exit 1; COLOCATED_WITH="$2"; shift 2 ;;
        --restart-splunk) require_arg "$1" $# || exit 1; RESTART_SPLUNK="$2"; shift 2 ;;
        --admin-password-file) require_arg "$1" $# || exit 1; ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
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
    validate_choice "${PHASE}" render preflight apply status validate all
    validate_choice "${LICENSE_GROUP}" Enterprise Forwarder Free Trial Download-Trial
    validate_choice "${APPLY_TARGET}" manager peers all
    validate_choice "${RESTART_SPLUNK}" true false
    if [[ -z "${LICENSE_MANAGER_URI}" ]]; then
        log "ERROR: --license-manager-uri is required."
        exit 1
    fi
    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
    if [[ -n "${ADMIN_PASSWORD_FILE}" ]]; then
        export SPLUNK_ADMIN_PASSWORD_FILE="${ADMIN_PASSWORD_FILE}"
    fi
}

build_renderer_args() {
    RENDER_ARGS=(
        --output-dir "${OUTPUT_DIR}"
        --license-manager-uri "${LICENSE_MANAGER_URI}"
        --license-manager-host "${LICENSE_MANAGER_HOST}"
        --license-manager-ssh-user "${LICENSE_MANAGER_SSH_USER}"
        --license-files "${LICENSE_FILES}"
        --license-group "${LICENSE_GROUP}"
        --pool-specs "${POOL_SPECS}"
        --peer-hosts "${PEER_HOSTS}"
        --peer-ssh-user "${PEER_SSH_USER}"
        --apply-target "${APPLY_TARGET}"
        --colocated-with "${COLOCATED_WITH}"
        --restart-splunk "${RESTART_SPLUNK}"
    )
}

render_dir() {
    printf '%s/license' "${OUTPUT_DIR}"
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

run_rendered() {
    local rel="$1" dir
    dir="$(render_dir)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./${rel})"
        return 0
    fi
    if [[ ! -x "${dir}/${rel}" ]]; then
        log "ERROR: Rendered script is missing or not executable: ${dir}/${rel}"
        exit 1
    fi
    (cd "${dir}" && "./${rel}")
}

apply_manager() {
    run_rendered manager/install-licenses.sh
    run_rendered manager/activate-group.sh
    run_rendered manager/apply-pools.sh
}

apply_peers() {
    local dir
    dir="$(render_dir)"
    shopt -s nullglob
    for host_dir in "${dir}/peers"/*/; do
        local host
        host="$(basename "${host_dir%/}")"
        run_rendered "peers/${host}/configure-peer.sh"
    done
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
                case "${APPLY_TARGET}" in
                    manager) apply_manager ;;
                    peers) apply_peers ;;
                    all) apply_manager; apply_peers ;;
                esac
            fi
            ;;
        preflight) render_assets; log "Preflight: review ${OUTPUT_DIR}/license/ before apply." ;;
        apply)
            render_assets
            case "${APPLY_TARGET}" in
                manager) apply_manager ;;
                peers) apply_peers ;;
                all) apply_manager; apply_peers ;;
            esac
            ;;
        status|validate) render_assets; run_rendered validate.sh ;;
        all) render_assets; apply_manager; apply_peers; run_rendered validate.sh ;;
    esac
}

main "$@"

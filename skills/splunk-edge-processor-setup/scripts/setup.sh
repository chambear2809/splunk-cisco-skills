#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-edge-processor-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""

EP_CONTROL_PLANE="cloud"
EP_TENANT_URL=""
EP_NAME="prod-ep"
EP_TLS_MODE="none"
EP_TLS_SERVER_CERT=""
EP_TLS_SERVER_KEY=""
EP_TLS_CA_CERT=""
EP_INSTANCES=""
EP_TARGET_DAILY_GB="50"
EP_SOURCE_TYPES=""
EP_DESTINATIONS=""
EP_DEFAULT_DESTINATION=""
EP_PIPELINES=""
EP_INSTALL_DIR="/opt/splunk-edge"
EP_SERVICE_USER="splunkedge"
EP_SERVICE_CGROUP="splunkedge"
EP_API_TOKEN_FILE_ARG=""
EP_INSTANCE_TOKEN_FILE_ARG=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Edge Processor Setup

Usage: $(basename "$0") [OPTIONS]

Phases:
  render | preflight | apply | install-instance | uninstall-instance |
  status | validate | all

Options:
  --output-dir PATH
  --ep-control-plane cloud|enterprise
  --ep-tenant-url URL
  --ep-name NAME
  --ep-tls-mode none|tls|mtls
  --ep-tls-server-cert PATH
  --ep-tls-server-key PATH
  --ep-tls-ca-cert PATH
  --ep-instances "host=mode,..."   (mode: systemd|nosystemd|docker)
  --ep-target-daily-gb N
  --ep-source-types CSV
  --ep-destinations "name=type=s2s;host=...;port=...,name2=..."
  --ep-default-destination NAME
  --ep-pipelines "name=partition=Keep;sourcetype=val;spl2_file=path;destination=name,..."
  --ep-install-dir PATH
  --ep-service-user USER
  --ep-service-cgroup GROUP
  --ep-api-token-file PATH
  --ep-instance-token-file PATH
  --apply
  --dry-run
  --json
  --help

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
        --ep-control-plane) require_arg "$1" $# || exit 1; EP_CONTROL_PLANE="$2"; shift 2 ;;
        --ep-tenant-url) require_arg "$1" $# || exit 1; EP_TENANT_URL="$2"; shift 2 ;;
        --ep-name) require_arg "$1" $# || exit 1; EP_NAME="$2"; shift 2 ;;
        --ep-tls-mode) require_arg "$1" $# || exit 1; EP_TLS_MODE="$2"; shift 2 ;;
        --ep-tls-server-cert) require_arg "$1" $# || exit 1; EP_TLS_SERVER_CERT="$2"; shift 2 ;;
        --ep-tls-server-key) require_arg "$1" $# || exit 1; EP_TLS_SERVER_KEY="$2"; shift 2 ;;
        --ep-tls-ca-cert) require_arg "$1" $# || exit 1; EP_TLS_CA_CERT="$2"; shift 2 ;;
        --ep-instances) require_arg "$1" $# || exit 1; EP_INSTANCES="$2"; shift 2 ;;
        --ep-target-daily-gb) require_arg "$1" $# || exit 1; EP_TARGET_DAILY_GB="$2"; shift 2 ;;
        --ep-source-types) require_arg "$1" $# || exit 1; EP_SOURCE_TYPES="$2"; shift 2 ;;
        --ep-destinations) require_arg "$1" $# || exit 1; EP_DESTINATIONS="$2"; shift 2 ;;
        --ep-default-destination) require_arg "$1" $# || exit 1; EP_DEFAULT_DESTINATION="$2"; shift 2 ;;
        --ep-pipelines) require_arg "$1" $# || exit 1; EP_PIPELINES="$2"; shift 2 ;;
        --ep-install-dir) require_arg "$1" $# || exit 1; EP_INSTALL_DIR="$2"; shift 2 ;;
        --ep-service-user) require_arg "$1" $# || exit 1; EP_SERVICE_USER="$2"; shift 2 ;;
        --ep-service-cgroup) require_arg "$1" $# || exit 1; EP_SERVICE_CGROUP="$2"; shift 2 ;;
        --ep-api-token-file) require_arg "$1" $# || exit 1; EP_API_TOKEN_FILE_ARG="$2"; shift 2 ;;
        --ep-instance-token-file) require_arg "$1" $# || exit 1; EP_INSTANCE_TOKEN_FILE_ARG="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

if [[ -z "${EP_TENANT_URL}" ]]; then
    log "ERROR: --ep-tenant-url is required."
    exit 1
fi

if [[ -n "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
else
    OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
fi

if [[ -n "${EP_API_TOKEN_FILE_ARG}" ]]; then
    export EP_API_TOKEN_FILE="${EP_API_TOKEN_FILE_ARG}"
fi
if [[ -n "${EP_INSTANCE_TOKEN_FILE_ARG}" ]]; then
    export EP_INSTANCE_TOKEN_FILE="${EP_INSTANCE_TOKEN_FILE_ARG}"
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --ep-control-plane "${EP_CONTROL_PLANE}"
    --ep-tenant-url "${EP_TENANT_URL}"
    --ep-name "${EP_NAME}"
    --ep-tls-mode "${EP_TLS_MODE}"
    --ep-tls-server-cert "${EP_TLS_SERVER_CERT}"
    --ep-tls-server-key "${EP_TLS_SERVER_KEY}"
    --ep-tls-ca-cert "${EP_TLS_CA_CERT}"
    --ep-instances "${EP_INSTANCES}"
    --ep-target-daily-gb "${EP_TARGET_DAILY_GB}"
    --ep-source-types "${EP_SOURCE_TYPES}"
    --ep-destinations "${EP_DESTINATIONS}"
    --ep-default-destination "${EP_DEFAULT_DESTINATION}"
    --ep-pipelines "${EP_PIPELINES}"
    --ep-install-dir "${EP_INSTALL_DIR}"
    --ep-service-user "${EP_SERVICE_USER}"
    --ep-service-cgroup "${EP_SERVICE_CGROUP}"
)

render_dir() { printf '%s' "${OUTPUT_DIR}"; }

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
            run_rendered control-plane/apply-objects.sh
        fi
        ;;
    preflight) render_assets; log "Preflight: review ${OUTPUT_DIR}/ before apply." ;;
    apply) render_assets; run_rendered control-plane/apply-objects.sh ;;
    install-instance)
        render_assets
        for host_dir in "$(render_dir)/host"/*/; do
            host="$(basename "${host_dir%/}")"
            for installer in install-with-systemd.sh install-without-systemd.sh install-docker.sh; do
                if [[ -x "${host_dir}${installer}" ]]; then
                    run_rendered "host/${host}/${installer}"
                fi
            done
        done
        ;;
    uninstall-instance)
        render_assets
        for host_dir in "$(render_dir)/host"/*/; do
            host="$(basename "${host_dir%/}")"
            run_rendered "host/${host}/uninstall.sh"
        done
        ;;
    status|validate) render_assets; run_rendered validate.sh ;;
    all)
        render_assets
        run_rendered control-plane/apply-objects.sh
        run_rendered validate.sh
        ;;
    *) log "ERROR: Unknown phase '${PHASE}'"; usage 1 ;;
esac

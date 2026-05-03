#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-soar-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""

SOAR_PLATFORM="onprem-single"
SOAR_HOME="/opt/soar"
SOAR_HTTPS_PORT="8443"
SOAR_PORT_FORWARD="false"
SOAR_HOSTNAME=""
SOAR_TGZ=""
SOAR_FIPS="auto"
SOAR_HOSTS=""
SOAR_SSH_USER="splunk"
EXTERNAL_PG=""
EXTERNAL_GLUSTER=""
EXTERNAL_ES=""
LOAD_BALANCER=""
SOAR_TENANT_URL=""
SOAR_CLOUD_ADMIN_EMAIL=""
AUTOMATION_BROKER=""
SOAR_AUTOMATION_TOKEN_FILE=""
SPLUNK_SIDE_APPS="app_for_soar=true,app_for_soar_export=true"
ES_INTEGRATION_READINESS="true"
AUTH_FILE=""
CA_CERT_FILE=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk SOAR Setup

Usage: $(basename "$0") [OPTIONS]

Phases: render preflight apply onprem-single onprem-cluster cloud-onboard automation-broker splunk-side-apps es-integration status validate all

Options:
  --output-dir PATH
  --soar-platform onprem-single|onprem-cluster|cloud
  --soar-home PATH
  --soar-https-port PORT
  --soar-port-forward true|false
  --soar-hostname HOST
  --soar-tgz PATH
  --file PATH
  --soar-fips auto|require|disable
  --soar-hosts CSV
  --soar-ssh-user USER
  --external-pg "k=v,..."
  --external-gluster CSV
  --external-es CSV
  --load-balancer HOST
  --soar-tenant-url URL
  --soar-cloud-admin-email EMAIL
  --automation-broker "k=v,..."
  --automation-broker-plan
  --broker-runtime docker|podman
  --soar-automation-token-file PATH
  --splunk-side-apps "app_for_soar=true,..."
  --install-export-app
  --es-integration-readiness true|false
  --soar-url URL
  --auth-file PATH
  --ca-cert-file PATH
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
        --soar-platform) require_arg "$1" $# || exit 1; SOAR_PLATFORM="$2"; shift 2 ;;
        --soar-home) require_arg "$1" $# || exit 1; SOAR_HOME="$2"; shift 2 ;;
        --soar-https-port) require_arg "$1" $# || exit 1; SOAR_HTTPS_PORT="$2"; shift 2 ;;
        --soar-port-forward) require_arg "$1" $# || exit 1; SOAR_PORT_FORWARD="$2"; shift 2 ;;
        --soar-hostname) require_arg "$1" $# || exit 1; SOAR_HOSTNAME="$2"; shift 2 ;;
        --soar-tgz|--file) require_arg "$1" $# || exit 1; SOAR_TGZ="$2"; shift 2 ;;
        --soar-fips) require_arg "$1" $# || exit 1; SOAR_FIPS="$2"; shift 2 ;;
        --soar-hosts) require_arg "$1" $# || exit 1; SOAR_HOSTS="$2"; shift 2 ;;
        --soar-ssh-user) require_arg "$1" $# || exit 1; SOAR_SSH_USER="$2"; shift 2 ;;
        --external-pg) require_arg "$1" $# || exit 1; EXTERNAL_PG="$2"; shift 2 ;;
        --external-gluster) require_arg "$1" $# || exit 1; EXTERNAL_GLUSTER="$2"; shift 2 ;;
        --external-es) require_arg "$1" $# || exit 1; EXTERNAL_ES="$2"; shift 2 ;;
        --load-balancer) require_arg "$1" $# || exit 1; LOAD_BALANCER="$2"; shift 2 ;;
        --soar-tenant-url|--soar-url) require_arg "$1" $# || exit 1; SOAR_TENANT_URL="$2"; shift 2 ;;
        --soar-cloud-admin-email) require_arg "$1" $# || exit 1; SOAR_CLOUD_ADMIN_EMAIL="$2"; shift 2 ;;
        --automation-broker) require_arg "$1" $# || exit 1; AUTOMATION_BROKER="$2"; shift 2 ;;
        --soar-automation-token-file|--automation-token-file) require_arg "$1" $# || exit 1; SOAR_AUTOMATION_TOKEN_FILE="$2"; shift 2 ;;
        --automation-broker-plan)
            [[ -n "${AUTOMATION_BROKER}" ]] || AUTOMATION_BROKER="runtime=docker,image_source=dockerhub"
            shift
            ;;
        --broker-runtime)
            require_arg "$1" $# || exit 1
            if [[ -n "${AUTOMATION_BROKER}" ]]; then
                AUTOMATION_BROKER="${AUTOMATION_BROKER},runtime=$2"
            else
                AUTOMATION_BROKER="runtime=$2,image_source=dockerhub"
            fi
            shift 2
            ;;
        --splunk-side-apps) require_arg "$1" $# || exit 1; SPLUNK_SIDE_APPS="$2"; shift 2 ;;
        --install-export-app) SPLUNK_SIDE_APPS="${SPLUNK_SIDE_APPS},app_for_soar_export=true"; shift ;;
        --es-integration-readiness) require_arg "$1" $# || exit 1; ES_INTEGRATION_READINESS="$2"; shift 2 ;;
        --auth-file) require_arg "$1" $# || exit 1; AUTH_FILE="$2"; shift 2 ;;
        --ca-cert-file) require_arg "$1" $# || exit 1; CA_CERT_FILE="$2"; shift 2 ;;
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

if [[ -n "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
else
    OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
fi
if [[ -n "${SOAR_AUTOMATION_TOKEN_FILE}" ]]; then
    SOAR_AUTOMATION_TOKEN_FILE="$(resolve_abs_path "${SOAR_AUTOMATION_TOKEN_FILE}")"
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --soar-platform "${SOAR_PLATFORM}"
    --soar-home "${SOAR_HOME}"
    --soar-https-port "${SOAR_HTTPS_PORT}"
    --soar-port-forward "${SOAR_PORT_FORWARD}"
    --soar-hostname "${SOAR_HOSTNAME}"
    --soar-tgz "${SOAR_TGZ}"
    --soar-fips "${SOAR_FIPS}"
    --soar-hosts "${SOAR_HOSTS}"
    --soar-ssh-user "${SOAR_SSH_USER}"
    --external-pg "${EXTERNAL_PG}"
    --external-gluster "${EXTERNAL_GLUSTER}"
    --external-es "${EXTERNAL_ES}"
    --load-balancer "${LOAD_BALANCER}"
    --soar-tenant-url "${SOAR_TENANT_URL}"
    --soar-cloud-admin-email "${SOAR_CLOUD_ADMIN_EMAIL}"
    --automation-broker "${AUTOMATION_BROKER}"
    --splunk-side-apps "${SPLUNK_SIDE_APPS}"
    --es-integration-readiness "${ES_INTEGRATION_READINESS}"
    --auth-file "${AUTH_FILE}"
    --ca-cert-file "${CA_CERT_FILE}"
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

require_soar_automation_inputs() {
    if [[ -z "${SOAR_TENANT_URL}" ]]; then
        log "ERROR: --soar-tenant-url is required for ${PHASE}."
        exit 1
    fi
    if [[ -z "${SOAR_AUTOMATION_TOKEN_FILE}" ]]; then
        log "ERROR: --soar-automation-token-file is required for ${PHASE}."
        exit 1
    fi
    if [[ ! -s "${SOAR_AUTOMATION_TOKEN_FILE}" ]]; then
        log "ERROR: --soar-automation-token-file must point to a readable, non-empty file."
        exit 1
    fi
    export SOAR_TENANT_URL SOAR_AUTOMATION_TOKEN_FILE
}

if [[ "${DRY_RUN}" == "true" ]]; then
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        exec python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
    fi
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
    exit 0
fi

if [[ "${APPLY}" == "true" && "${PHASE}" == "render" ]]; then
    PHASE="apply"
fi

case "${PHASE}" in
    render) render_assets ;;
    preflight) render_assets; log "Preflight: review ${OUTPUT_DIR}/ before apply." ;;
    onprem-single|apply)
        render_assets
        if [[ "${SOAR_PLATFORM}" == "onprem-single" || "${PHASE}" == "onprem-single" ]]; then
            run_rendered onprem-single/prepare-system.sh
            run_rendered onprem-single/install-soar.sh
        elif [[ "${SOAR_PLATFORM}" == "onprem-cluster" ]]; then
            run_rendered onprem-cluster/make-cluster-node.sh
        elif [[ "${SOAR_PLATFORM}" == "cloud" ]]; then
            log "SOAR Cloud is Splunk-managed. Follow cloud/onboarding-checklist.md."
        fi
        ;;
    onprem-cluster) render_assets; run_rendered onprem-cluster/make-cluster-node.sh ;;
    cloud-onboard) render_assets; log "Open ${OUTPUT_DIR}/cloud/onboarding-checklist.md and follow each step." ;;
    automation-broker)
        require_soar_automation_inputs
        render_assets
        run_rendered automation-broker/preflight.sh
        run_rendered automation-broker/install.sh
        ;;
    splunk-side-apps)
        render_assets
        # install-app-for-soar-export.sh is the modern packaging of the legacy
        # "Splunk Add-on for Phantom" (TA-phantom); there is no separate
        # install-ta-phantom.sh script.
        for app in install-app-for-soar.sh install-app-for-soar-export.sh; do
            if [[ -x "$(render_dir)/splunk-side/${app}" ]]; then
                run_rendered "splunk-side/${app}"
            fi
        done
        ;;
    es-integration)
        require_soar_automation_inputs
        render_assets
        run_rendered splunk-side/configure-phantom-endpoint.sh
        ;;
    status|validate) render_assets; run_rendered validate.sh ;;
    all)
        render_assets
        case "${SOAR_PLATFORM}" in
            onprem-single) run_rendered onprem-single/prepare-system.sh; run_rendered onprem-single/install-soar.sh ;;
            onprem-cluster) run_rendered onprem-cluster/make-cluster-node.sh ;;
            cloud) log "SOAR Cloud is Splunk-managed. Follow cloud/onboarding-checklist.md." ;;
        esac
        run_rendered validate.sh
        ;;
    *) log "ERROR: Unknown phase '${PHASE}'"; usage 1 ;;
esac

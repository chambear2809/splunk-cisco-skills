#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
VALIDATOR="${SCRIPT_DIR}/validate.sh"
DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-db-connect-rendered"

DO_RENDER=false
DO_VALIDATE=false
DO_PREFLIGHT=false
DO_INSTALL_APPS=false
ACCEPT_INSTALL=false
JSON_OUTPUT=false
SPEC=""
OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk DB Connect Setup

Usage: $(basename "$0") [OPTIONS]

Render and preflight:
  --render                         Render DB Connect handoff assets
  --validate                       Validate rendered assets after render
  --preflight                      Validate the spec and print a read-only summary
  --spec PATH                      YAML/JSON spec (required)
  --output-dir PATH                Render output directory (default: splunk-db-connect-rendered)

Explicit install handoff:
  --install-apps                   Render and run install/install-apps.sh
  --accept-install                 Required with --install-apps

Other:
  --json                           Emit renderer JSON for render/preflight
  --help

Examples:
  $(basename "$0") --preflight --spec skills/splunk-db-connect-setup/template.example

  $(basename "$0") --render --validate \\
    --spec skills/splunk-db-connect-setup/template.example \\
    --output-dir splunk-db-connect-rendered

  $(basename "$0") --install-apps --accept-install \\
    --spec my-db-connect.yaml --output-dir splunk-db-connect-rendered

Direct secret flags such as --password, --secret, --token, --api-key, and
--private-key are rejected. Use *_file or *_ref fields in the spec.
EOF
    exit "${exit_code}"
}

reject_secret_flag() {
    log "ERROR: Direct secret values are not accepted. Use *_file or *_ref fields in the spec."
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) DO_RENDER=true; shift ;;
        --validate) DO_VALIDATE=true; shift ;;
        --preflight) DO_PREFLIGHT=true; shift ;;
        --install-apps) DO_INSTALL_APPS=true; shift ;;
        --accept-install) ACCEPT_INSTALL=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --spec) require_arg "$1" $# || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --password|--secret|--token|--api-key|--private-key|--client-secret) reject_secret_flag ;;
        --password=*|--secret=*|--token=*|--api-key=*|--private-key=*|--client-secret=*) reject_secret_flag ;;
        --help) usage 0 ;;
        *) log "ERROR: Unknown option: $1"; usage 1 ;;
    esac
done

if [[ -z "${SPEC}" ]]; then
    log "ERROR: --spec is required."
    usage 1
fi

if [[ ! -f "${SPEC}" ]]; then
    log "ERROR: Spec file not found: ${SPEC}"
    exit 1
fi

if [[ "${DO_INSTALL_APPS}" == true && "${ACCEPT_INSTALL}" != true ]]; then
    log "ERROR: --install-apps requires --accept-install."
    exit 1
fi

if [[ "${DO_RENDER}" == false && "${DO_VALIDATE}" == false && "${DO_PREFLIGHT}" == false && "${DO_INSTALL_APPS}" == false ]]; then
    log "ERROR: Choose --preflight, --render, --validate, or --install-apps."
    usage 1
fi

renderer_args=(--spec "${SPEC}" --output-dir "${OUTPUT_DIR}")
if [[ "${JSON_OUTPUT}" == true ]]; then
    renderer_args+=(--json)
fi
if [[ "${DO_INSTALL_APPS}" == true ]]; then
    renderer_args+=(--install-requested)
fi

if [[ "${DO_PREFLIGHT}" == true ]]; then
    python3 "${RENDERER}" --preflight "${renderer_args[@]}"
fi

if [[ "${DO_RENDER}" == true || "${DO_VALIDATE}" == true || "${DO_INSTALL_APPS}" == true ]]; then
    python3 "${RENDERER}" "${renderer_args[@]}"
fi

if [[ "${DO_VALIDATE}" == true ]]; then
    bash "${VALIDATOR}" --output-dir "${OUTPUT_DIR}"
fi

if [[ "${DO_INSTALL_APPS}" == true ]]; then
    install_script="${OUTPUT_DIR}/splunk-db-connect/install/install-apps.sh"
    if [[ ! -x "${install_script}" ]]; then
        log "ERROR: Rendered install script is missing or not executable: ${install_script}"
        exit 1
    fi
    log "Delegating package installation to splunk-app-install via ${install_script}"
    bash "${install_script}"
fi

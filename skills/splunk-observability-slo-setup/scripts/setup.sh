#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

OUTPUT_DIR="${PROJECT_ROOT}/../splunk-observability-slo-rendered"
REALM="${SPLUNK_O11Y_REALM:-us0}"
NAME="Service SLO"
SERVICE=""
ENVIRONMENT_NAME="prod"
TARGET="99.9"
WINDOW="30d"
SLI_SOURCE="apm_service"
JSON_OUTPUT=false

usage() {
    cat <<'EOF'
Splunk Observability SLO Setup

Usage:
  bash skills/splunk-observability-slo-setup/scripts/setup.sh --render [options]

Options:
  --render             Render assets
  --json               Emit JSON render output
  --output-dir DIR     Render output directory
  --realm REALM        Observability realm
  --name NAME          SLO name
  --service SERVICE    Service name for SLI context
  --environment ENV    Environment
  --target PERCENT     Objective target percentage
  --window WINDOW      Compliance window, such as 30d
  --sli-source SOURCE  apm_service, endpoint, custom_metric, or synthetics
  --help               Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --name) require_arg "$1" "$#" || exit 1; NAME="$2"; shift 2 ;;
        --service) require_arg "$1" "$#" || exit 1; SERVICE="$2"; shift 2 ;;
        --environment) require_arg "$1" "$#" || exit 1; ENVIRONMENT_NAME="$2"; shift 2 ;;
        --target) require_arg "$1" "$#" || exit 1; TARGET="$2"; shift 2 ;;
        --window) require_arg "$1" "$#" || exit 1; WINDOW="$2"; shift 2 ;;
        --sli-source) require_arg "$1" "$#" || exit 1; SLI_SOURCE="$2"; shift 2 ;;
        --token|--access-token|--api-token|--o11y-token|--sf-token)
            reject_secret_arg "$1" "the downstream Observability API token-file option"
            exit 1
            ;;
        --token=*|--access-token=*|--api-token=*|--o11y-token=*|--sf-token=*)
            reject_secret_arg "${1%%=*}" "the downstream Observability API token-file option"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

args=(--surface slo --output-dir "${OUTPUT_DIR}" --realm "${REALM}" --name "${NAME}" --service "${SERVICE}" --environment "${ENVIRONMENT_NAME}" --target "${TARGET}" --window "${WINDOW}" --sli-source "${SLI_SOURCE}")
[[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
python3 "${SCRIPT_DIR}/render_assets.py" "${args[@]}"

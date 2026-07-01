#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

OUTPUT_DIR="${PROJECT_ROOT}/../splunk-observability-synthetics-rendered"
REALM="${SPLUNK_O11Y_REALM:-us0}"
NAME="Synthetic test"
KIND="browser"
URL=""
FREQUENCY="5"
LOCATION="aws-us-east-1"
RUN_NOW=false
JSON_OUTPUT=false
APPLY=false
DRY_RUN=false
TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"

usage() {
    cat <<'EOF'
Splunk Observability Synthetics Setup

Usage:
  bash skills/splunk-observability-synthetics-setup/scripts/setup.sh --render [options]

Options:
  --render                 Render assets
  --apply                  Render, validate, and apply through native-ops
  --dry-run                With --apply, print API actions without calls
  --json                   Emit JSON render output
  --output-dir DIR         Render output directory
  --realm REALM            Observability realm
  --name NAME              Test name
  --kind KIND              browser, api, http, ssl, or port
  --url URL                Target URL or endpoint
  --frequency MINUTES      Test frequency in minutes
  --location LOCATION      Synthetic location ID; repeat by editing rendered spec
  --run-now                Add run-now intent for an existing test ID
  --token-file PATH        Observability API token file for live apply
  --help                   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) shift ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --name) require_arg "$1" "$#" || exit 1; NAME="$2"; shift 2 ;;
        --kind) require_arg "$1" "$#" || exit 1; KIND="$2"; shift 2 ;;
        --url) require_arg "$1" "$#" || exit 1; URL="$2"; shift 2 ;;
        --frequency) require_arg "$1" "$#" || exit 1; FREQUENCY="$2"; shift 2 ;;
        --location) require_arg "$1" "$#" || exit 1; LOCATION="$2"; shift 2 ;;
        --run-now) RUN_NOW=true; shift ;;
        --token-file) require_arg "$1" "$#" || exit 1; TOKEN_FILE="$2"; shift 2 ;;
        --token|--access-token|--api-token|--o11y-token|--sf-token)
            reject_secret_arg "$1" "--token-file on splunk-observability-native-ops"
            exit 1
            ;;
        --token=*|--access-token=*|--api-token=*|--o11y-token=*|--sf-token=*)
            reject_secret_arg "${1%%=*}" "--token-file on splunk-observability-native-ops"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

args=(--surface synthetics --output-dir "${OUTPUT_DIR}" --realm "${REALM}" --name "${NAME}" --kind "${KIND}" --frequency "${FREQUENCY}" --location "${LOCATION}")
[[ -n "${URL}" ]] && args+=(--url "${URL}")
[[ "${RUN_NOW}" == "true" ]] && args+=(--run-now)
[[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
python3 "${SCRIPT_DIR}/render_assets.py" "${args[@]}"

if [[ "${APPLY}" == "true" ]]; then
    delegate_args=(--apply)
    [[ "${DRY_RUN}" == "true" ]] && delegate_args+=(--dry-run)
    [[ -n "${TOKEN_FILE}" ]] && delegate_args+=(--token-file "${TOKEN_FILE}")
    bash "${OUTPUT_DIR}/delegate-native-ops.sh" "${delegate_args[@]}"
fi

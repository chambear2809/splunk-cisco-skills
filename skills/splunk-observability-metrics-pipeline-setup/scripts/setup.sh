#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

OUTPUT_DIR="${PROJECT_ROOT}/../splunk-observability-metrics-pipeline-rendered"
REALM="${SPLUNK_O11Y_REALM:-us0}"
NAME="Metric pipeline review"
METRIC="service.request.duration"
ACTION="aggregate"
DIMENSIONS="service.name,deployment.environment"
JSON_OUTPUT=false

usage() {
    cat <<'EOF'
Splunk Observability Metrics Pipeline Setup

Usage:
  bash skills/splunk-observability-metrics-pipeline-setup/scripts/setup.sh --render [options]

Options:
  --render             Render assets
  --json               Emit JSON render output
  --output-dir DIR     Render output directory
  --realm REALM        Observability realm
  --name NAME          Workflow name
  --metric METRIC      Metric name or pattern
  --action ACTION      review, drop, archive, route, or aggregate
  --dimensions LIST    Comma-separated dimensions to keep/review
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
        --metric) require_arg "$1" "$#" || exit 1; METRIC="$2"; shift 2 ;;
        --action) require_arg "$1" "$#" || exit 1; ACTION="$2"; shift 2 ;;
        --dimensions) require_arg "$1" "$#" || exit 1; DIMENSIONS="$2"; shift 2 ;;
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

args=(--surface mpm --output-dir "${OUTPUT_DIR}" --realm "${REALM}" --name "${NAME}" --metric "${METRIC}" --action "${ACTION}" --dimensions "${DIMENSIONS}")
[[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
python3 "${SCRIPT_DIR}/render_assets.py" "${args[@]}"

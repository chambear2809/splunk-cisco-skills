#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
PHASE="render"
PROFILE="unix-linux"
CATALOG=""
OUTPUT_DIR=""
EVENT_INDEX="os"
METRICS_INDEX="os_metrics"
HEC_TOKEN_NAME="linux_collectd_hec"
TCP_PORT="2104"
JSON_OUTPUT=false
STRICT=false
DRY_RUN=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Supported Add-ons Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase list|coverage|resolve|render|install-command|readiness-command
  --profile NAME_OR_ALIAS
  --catalog PATH
  --output-dir PATH
  --event-index NAME
  --metrics-index NAME
  --hec-token-name NAME
  --tcp-port PORT
  --json
  --strict
  --dry-run
  --help

Examples:
  $(basename "$0") --phase list --json
  $(basename "$0") --phase coverage --json
  $(basename "$0") --profile Splunk_TA_nix --phase resolve --json
  $(basename "$0") --profile linux-collectd --phase render --event-index os --metrics-index os_metrics

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --profile|--product|--addon) require_arg "$1" $# || exit 1; PROFILE="$2"; shift 2 ;;
        --catalog) require_arg "$1" $# || exit 1; CATALOG="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --event-index) require_arg "$1" $# || exit 1; EVENT_INDEX="$2"; shift 2 ;;
        --metrics-index) require_arg "$1" $# || exit 1; METRICS_INDEX="$2"; shift 2 ;;
        --hec-token-name) require_arg "$1" $# || exit 1; HEC_TOKEN_NAME="$2"; shift 2 ;;
        --tcp-port) require_arg "$1" $# || exit 1; TCP_PORT="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --strict) STRICT=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help|-h) usage 0 ;;
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

main() {
    validate_choice "${PHASE}" list coverage resolve render install-command readiness-command
    local args=(
        --phase "${PHASE}"
        --profile "${PROFILE}"
        --event-index "${EVENT_INDEX}"
        --metrics-index "${METRICS_INDEX}"
        --hec-token-name "${HEC_TOKEN_NAME}"
        --tcp-port "${TCP_PORT}"
    )
    [[ -n "${CATALOG}" ]] && args+=(--catalog "${CATALOG}")
    [[ -n "${OUTPUT_DIR}" ]] && args+=(--output-dir "${OUTPUT_DIR}")
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
    [[ "${STRICT}" == "true" ]] && args+=(--strict)
    [[ "${DRY_RUN}" == "true" ]] && args+=(--dry-run)

    python3 "${RENDERER}" "${args[@]}"
}

main "$@"

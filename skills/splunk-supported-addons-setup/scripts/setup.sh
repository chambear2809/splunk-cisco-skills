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
EXECUTE=false

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
  --execute     Execute the routed install/readiness command for the selected phase
  --help

Examples:
  $(basename "$0") --phase list --json
  $(basename "$0") --phase coverage --json
  $(basename "$0") --profile Splunk_TA_nix --phase resolve --json
  $(basename "$0") --profile linux-collectd --phase render --event-index os --metrics-index os_metrics
  $(basename "$0") --profile Cisco ASA --execute --dry-run
  $(basename "$0") --profile Cisco ASA --execute

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
        --execute) EXECUTE=true; shift ;;
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
    if [[ "${EXECUTE}" == "true" && "${PHASE}" == "render" ]]; then
        PHASE="install-command"
    fi
    validate_choice "${PHASE}" list coverage resolve render install-command readiness-command
    if [[ "${EXECUTE}" == "true" ]]; then
        validate_choice "${PHASE}" install-command readiness-command
        if [[ "${JSON_OUTPUT}" == "true" && "${DRY_RUN}" != "true" ]]; then
            log "ERROR: --json with --execute is supported only with --dry-run."
            exit 1
        fi
    fi
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

    if [[ "${EXECUTE}" == "true" ]]; then
        local payload
        local command=()
        payload="$(python3 "${RENDERER}" "${args[@]}" --json)"
        while IFS= read -r -d '' item; do
            command+=("${item}")
        done < <(
            PAYLOAD="${payload}" python3 - <<'PY'
import json
import os
import sys

payload = json.loads(os.environ["PAYLOAD"])
command = payload.get("command") or []
if not isinstance(command, list) or not command:
    raise SystemExit("missing command in router payload")
for item in command:
    sys.stdout.buffer.write(str(item).encode("utf-8") + b"\0")
PY
        )
        if [[ "${#command[@]}" -eq 0 ]]; then
            log "ERROR: Router did not return an executable command."
            exit 1
        fi
        if [[ "${DRY_RUN}" == "true" ]]; then
            if [[ "${JSON_OUTPUT}" == "true" ]]; then
                PAYLOAD="${payload}" python3 - <<'PY'
import json
import os
import sys

payload = json.loads(os.environ["PAYLOAD"])
payload["dry_run"] = True
payload["would_execute"] = payload.get("command", [])
json.dump(payload, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
PY
            else
                log "DRY RUN: routed command"
                printf '  '
                printf '%q ' "${command[@]}"
                printf '\n'
            fi
            exit 0
        fi
        exec "${command[@]}"
    fi

    python3 "${RENDERER}" "${args[@]}"
}

main "$@"

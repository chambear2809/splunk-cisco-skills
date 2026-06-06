#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-ddaa-archive-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
INDEX=""
SEARCHABLE_DAYS=""
ARCHIVAL_RETENTION_DAYS=""
INDEX_TYPE="event"
ACCEPT_ARCHIVE_RETENTION=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Cloud DDAA Archive Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|apply|status|all
  --apply | --dry-run | --json
  --output-dir PATH
  --index NAME                      (required)
  --searchable-days N               (required; DDAS searchable retention)
  --archival-retention-days N       (required; total retention incl. searchable; <= 3650)
  --index-type event|metric
  --accept-archive-retention        (required to apply archival retention via ACS)
  --help

Restore and disable are Splunk Web operations (no ACS API); see the rendered
restore-runbook.md and disable-runbook.md.

Examples:
  $(basename "$0") --index netfw --searchable-days 90 --archival-retention-days 365
  $(basename "$0") --phase apply --index netfw --searchable-days 90 \\
    --archival-retention-days 365 --accept-archive-retention

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
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --searchable-days) require_arg "$1" $# || exit 1; SEARCHABLE_DAYS="$2"; shift 2 ;;
        --archival-retention-days) require_arg "$1" $# || exit 1; ARCHIVAL_RETENTION_DAYS="$2"; shift 2 ;;
        --index-type) require_arg "$1" $# || exit 1; INDEX_TYPE="$2"; shift 2 ;;
        --accept-archive-retention) ACCEPT_ARCHIVE_RETENTION=true; shift ;;
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
    validate_choice "${PHASE}" render preflight apply status all
    validate_choice "${INDEX_TYPE}" event metric
    [[ -n "${INDEX}" ]] || { log "ERROR: --index is required."; exit 1; }
    [[ -n "${SEARCHABLE_DAYS}" ]] || { log "ERROR: --searchable-days is required."; exit 1; }
    [[ -n "${ARCHIVAL_RETENTION_DAYS}" ]] || { log "ERROR: --archival-retention-days is required."; exit 1; }
    if [[ "${JSON_OUTPUT}" == "true" && "${DRY_RUN}" != "true" && ( "${PHASE}" != "render" || "${APPLY}" == "true" ) ]]; then
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
        --index "${INDEX}"
        --searchable-days "${SEARCHABLE_DAYS}"
        --archival-retention-days "${ARCHIVAL_RETENTION_DAYS}"
        --index-type "${INDEX_TYPE}"
    )
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

apply_live() {
    if [[ "${ACCEPT_ARCHIVE_RETENTION}" != "true" ]]; then
        log "ERROR: Setting DDAA archival retention changes durable storage policy."
        log "       Re-run with --accept-archive-retention to apply via ACS."
        exit 1
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would run 'acs indexes create|update --name ${INDEX} --searchable-days ${SEARCHABLE_DAYS} --splunk-archival-retention-days ${ARCHIVAL_RETENTION_DAYS}'."
        return 0
    fi
    if ! acs_cli_available; then
        log "ERROR: The acs CLI is required for DDAA apply. Install it and configure the stack."
        exit 1
    fi
    acs_prepare_context || { log "ERROR: Could not prepare ACS context for the stack."; exit 1; }
    if cloud_check_index "${INDEX}"; then
        log "Updating DDAA archival retention for existing index ${INDEX}..."
        acs_command indexes update --name "${INDEX}" \
            --splunk-archival-retention-days "${ARCHIVAL_RETENTION_DAYS}" >/dev/null
    else
        log "Creating index ${INDEX} with DDAA archival retention..."
        acs_command indexes create --name "${INDEX}" \
            --data-type "${INDEX_TYPE}" \
            --searchable-days "${SEARCHABLE_DAYS}" \
            --splunk-archival-retention-days "${ARCHIVAL_RETENTION_DAYS}" >/dev/null
    fi
    log "DDAA archival retention set for ${INDEX}: ${ARCHIVAL_RETENTION_DAYS} days (searchable ${SEARCHABLE_DAYS})."
    acs_command indexes describe "${INDEX}" 2>/dev/null || true
}

run_status() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: acs indexes describe ${INDEX}"
        return 0
    fi
    if acs_cli_available; then
        acs_prepare_context || true
        acs_command indexes describe "${INDEX}" 2>/dev/null || true
    else
        log "acs CLI not available; install it to describe index ${INDEX}."
    fi
}

main() {
    validate_args
    build_renderer_args
    if [[ "${DRY_RUN}" == "true" ]]; then
        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
        else
            python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
            [[ "${PHASE}" == "apply" || "${PHASE}" == "all" ]] && apply_live
        fi
        exit 0
    fi
    case "${PHASE}" in
        render)
            render_assets
            [[ "${APPLY}" == "true" ]] && apply_live
            ;;
        preflight) render_assets ;;
        apply) render_assets; apply_live ;;
        status) render_assets; run_status ;;
        all) render_assets; apply_live; run_status ;;
    esac
}

main "$@"

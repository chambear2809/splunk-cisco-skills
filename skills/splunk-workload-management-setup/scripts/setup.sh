#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-workload-management-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
PROFILE="balanced"
SPLUNK_HOME_VALUE="/opt/splunk"
APP_NAME="ZZZ_cisco_skills_workload_management"
ENABLE_WORKLOAD_MANAGEMENT=false
ENABLE_ADMISSION_RULES=false
SEARCH_CPU=""
INGEST_CPU=""
MISC_CPU=""
DEFAULT_SEARCH_POOL="search_standard"
CRITICAL_SEARCH_POOL="search_critical"
INGEST_POOL="ingest_default"
MISC_POOL="misc_default"
CRITICAL_ROLE="admin"
LONG_RUNNING_RUNTIME="10m"
LONG_RUNNING_ACTION="abort"
ADMISSION_ALLTIME_ACTION="filter"
ADMISSION_EXEMPT_ROLE="admin"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Workload Management Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|apply|status|all
  --apply
  --dry-run
  --json
  --output-dir PATH
  --profile balanced|search-priority|ingest-protect|custom
  --splunk-home PATH
  --app-name NAME
  --enable-workload-management
  --enable-admission-rules
  --search-cpu N
  --ingest-cpu N
  --misc-cpu N
  --default-search-pool NAME
  --critical-search-pool NAME
  --ingest-pool NAME
  --misc-pool NAME
  --critical-role ROLE
  --long-running-runtime 10m
  --long-running-action none|alert|abort|move
  --admission-alltime-action disabled|filter
  --admission-exempt-role ROLE
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
        --profile) require_arg "$1" $# || exit 1; PROFILE="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --enable-workload-management) ENABLE_WORKLOAD_MANAGEMENT=true; shift ;;
        --enable-admission-rules) ENABLE_ADMISSION_RULES=true; shift ;;
        --search-cpu) require_arg "$1" $# || exit 1; SEARCH_CPU="$2"; shift 2 ;;
        --ingest-cpu) require_arg "$1" $# || exit 1; INGEST_CPU="$2"; shift 2 ;;
        --misc-cpu) require_arg "$1" $# || exit 1; MISC_CPU="$2"; shift 2 ;;
        --default-search-pool) require_arg "$1" $# || exit 1; DEFAULT_SEARCH_POOL="$2"; shift 2 ;;
        --critical-search-pool) require_arg "$1" $# || exit 1; CRITICAL_SEARCH_POOL="$2"; shift 2 ;;
        --ingest-pool) require_arg "$1" $# || exit 1; INGEST_POOL="$2"; shift 2 ;;
        --misc-pool) require_arg "$1" $# || exit 1; MISC_POOL="$2"; shift 2 ;;
        --critical-role) require_arg "$1" $# || exit 1; CRITICAL_ROLE="$2"; shift 2 ;;
        --long-running-runtime) require_arg "$1" $# || exit 1; LONG_RUNNING_RUNTIME="$2"; shift 2 ;;
        --long-running-action) require_arg "$1" $# || exit 1; LONG_RUNNING_ACTION="$2"; shift 2 ;;
        --admission-alltime-action) require_arg "$1" $# || exit 1; ADMISSION_ALLTIME_ACTION="$2"; shift 2 ;;
        --admission-exempt-role) require_arg "$1" $# || exit 1; ADMISSION_EXEMPT_ROLE="$2"; shift 2 ;;
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
    validate_choice "${PROFILE}" balanced search-priority ingest-protect custom
    validate_choice "${LONG_RUNNING_ACTION}" none alert abort move
    validate_choice "${ADMISSION_ALLTIME_ACTION}" disabled filter
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
        --profile "${PROFILE}"
        --output-dir "${OUTPUT_DIR}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --app-name "${APP_NAME}"
        --search-cpu "${SEARCH_CPU}"
        --ingest-cpu "${INGEST_CPU}"
        --misc-cpu "${MISC_CPU}"
        --default-search-pool "${DEFAULT_SEARCH_POOL}"
        --critical-search-pool "${CRITICAL_SEARCH_POOL}"
        --ingest-pool "${INGEST_POOL}"
        --misc-pool "${MISC_POOL}"
        --critical-role "${CRITICAL_ROLE}"
        --long-running-runtime "${LONG_RUNNING_RUNTIME}"
        --long-running-action "${LONG_RUNNING_ACTION}"
        --admission-alltime-action "${ADMISSION_ALLTIME_ACTION}"
        --admission-exempt-role "${ADMISSION_EXEMPT_ROLE}"
    )
    if [[ "${ENABLE_WORKLOAD_MANAGEMENT}" == "true" ]]; then
        RENDER_ARGS+=(--enable-workload-management)
    fi
    if [[ "${ENABLE_ADMISSION_RULES}" == "true" ]]; then
        RENDER_ARGS+=(--enable-admission-rules)
    fi
}

render_dir() {
    printf '%s/workload-management' "${OUTPUT_DIR}"
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

run_rendered_script() {
    local script_name="$1" dir
    dir="$(render_dir)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./${script_name})"
        return 0
    fi
    if [[ ! -x "${dir}/${script_name}" ]]; then
        log "ERROR: Rendered script is missing or not executable: ${dir}/${script_name}"
        exit 1
    fi
    (cd "${dir}" && "./${script_name}")
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
                run_rendered_script apply.sh
            fi
            ;;
        preflight) render_assets; run_rendered_script preflight.sh ;;
        apply) render_assets; run_rendered_script apply.sh ;;
        status) run_rendered_script status.sh ;;
        all) render_assets; run_rendered_script preflight.sh; run_rendered_script apply.sh; run_rendered_script status.sh ;;
    esac
}

main "$@"

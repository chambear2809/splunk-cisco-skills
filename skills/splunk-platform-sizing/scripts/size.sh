#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

ENGINE="${SCRIPT_DIR}/size_engine.py"
DEFAULT_RENDER_DIR_NAME="splunk-platform-sizing-rendered"

DAILY_INGEST_GB=""
RETENTION_DAYS="90"
WORKLOAD_PROFILE="core"
SEARCH_DENSITY="medium"
CONCURRENT_SEARCHES=""
CONCURRENT_USERS=""
HA=false
REPLICATION_FACTOR=""
SEARCH_FACTOR=""
MULTISITE=false
SITES="2"
SMARTSTORE=false
GROWTH_PCT="15"
DEPLOYMENT_TARGET="auto"
OUTPUT_DIR=""
JSON_OUTPUT=false
DRY_RUN=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Platform Sizing

Usage: $(basename "$0") --daily-ingest-gb N [OPTIONS]

Required:
  --daily-ingest-gb N            Daily ingest volume in GB/day

Use case:
  --retention-days N             Searchable retention in days (default: 90)
  --workload-profile PROFILE     core|es|itsi|es_itsi (default: core)
  --search-density DENSITY       light|medium|dense (default: medium)
  --concurrent-searches N        Peak concurrent searches (overrides users)
  --concurrent-users N           Concurrent users (estimates searches)
  --ha                           Require high availability (clustering)
  --replication-factor N         Indexer replication factor (clustered)
  --search-factor N              Indexer search factor (clustered)
  --multisite                    Multisite (geo-distributed) indexer cluster
  --sites N                      Site count with --multisite (default: 2)
  --smartstore                   Use SmartStore remote object storage
  --growth-pct N                 Growth headroom percent (default: 15)

Output:
  --deployment-target TARGET     auto|standalone|distributed|sok|pod|cloud
  --output-dir PATH              Render dir (default: ./${DEFAULT_RENDER_DIR_NAME})
  --json                         Print sizing JSON to stdout
  --dry-run                      Compute and print, write no files
  --help                         Show this help

Examples:
  $(basename "$0") --daily-ingest-gb 80 --retention-days 30
  $(basename "$0") --daily-ingest-gb 500 --workload-profile es --ha
  $(basename "$0") --daily-ingest-gb 1200 --workload-profile es_itsi --ha \\
    --deployment-target sok --smartstore

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --daily-ingest-gb) require_arg "$1" $# || exit 1; DAILY_INGEST_GB="$2"; shift 2 ;;
        --retention-days) require_arg "$1" $# || exit 1; RETENTION_DAYS="$2"; shift 2 ;;
        --workload-profile) require_arg "$1" $# || exit 1; WORKLOAD_PROFILE="$2"; shift 2 ;;
        --search-density) require_arg "$1" $# || exit 1; SEARCH_DENSITY="$2"; shift 2 ;;
        --concurrent-searches) require_arg "$1" $# || exit 1; CONCURRENT_SEARCHES="$2"; shift 2 ;;
        --concurrent-users) require_arg "$1" $# || exit 1; CONCURRENT_USERS="$2"; shift 2 ;;
        --ha) HA=true; shift ;;
        --replication-factor) require_arg "$1" $# || exit 1; REPLICATION_FACTOR="$2"; shift 2 ;;
        --search-factor) require_arg "$1" $# || exit 1; SEARCH_FACTOR="$2"; shift 2 ;;
        --multisite) MULTISITE=true; shift ;;
        --sites) require_arg "$1" $# || exit 1; SITES="$2"; shift 2 ;;
        --smartstore) SMARTSTORE=true; shift ;;
        --growth-pct) require_arg "$1" $# || exit 1; GROWTH_PCT="$2"; shift 2 ;;
        --deployment-target) require_arg "$1" $# || exit 1; DEPLOYMENT_TARGET="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
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

if [[ -z "${DAILY_INGEST_GB}" ]]; then
    log "ERROR: --daily-ingest-gb is required."
    usage 1
fi

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
else
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
fi

ENGINE_ARGS=(
    --daily-ingest-gb "${DAILY_INGEST_GB}"
    --retention-days "${RETENTION_DAYS}"
    --workload-profile "${WORKLOAD_PROFILE}"
    --search-density "${SEARCH_DENSITY}"
    --sites "${SITES}"
    --growth-pct "${GROWTH_PCT}"
    --deployment-target "${DEPLOYMENT_TARGET}"
)
[[ -n "${CONCURRENT_SEARCHES}" ]] && ENGINE_ARGS+=(--concurrent-searches "${CONCURRENT_SEARCHES}")
[[ -n "${CONCURRENT_USERS}" ]] && ENGINE_ARGS+=(--concurrent-users "${CONCURRENT_USERS}")
[[ -n "${REPLICATION_FACTOR}" ]] && ENGINE_ARGS+=(--replication-factor "${REPLICATION_FACTOR}")
[[ -n "${SEARCH_FACTOR}" ]] && ENGINE_ARGS+=(--search-factor "${SEARCH_FACTOR}")
[[ "${HA}" == "true" ]] && ENGINE_ARGS+=(--ha)
[[ "${MULTISITE}" == "true" ]] && ENGINE_ARGS+=(--multisite)
[[ "${SMARTSTORE}" == "true" ]] && ENGINE_ARGS+=(--smartstore)
[[ "${JSON_OUTPUT}" == "true" ]] && ENGINE_ARGS+=(--json)

if [[ "${DRY_RUN}" == "true" ]]; then
    ENGINE_ARGS+=(--dry-run)
else
    ENGINE_ARGS+=(--output-dir "${OUTPUT_DIR}")
fi

exec python3 "${ENGINE}" "${ENGINE_ARGS[@]}"

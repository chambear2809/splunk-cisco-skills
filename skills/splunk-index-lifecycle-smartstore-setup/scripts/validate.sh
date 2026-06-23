#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DEFAULT_RENDER_DIR_NAME="splunk-smartstore-rendered"
OUTPUT_DIR=""
JSON_OUTPUT=false
LIVE=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Index Lifecycle / SmartStore Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --output-dir PATH
  --live
  --json
  --help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
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

json_array() {
    python3 - "$@" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1:]), end="")
PY
}

metadata_value() {
    local path="$1" key="$2" default="$3"
    python3 - "$path" "$key" "$default" <<'PY'
import json
import sys
path, key, default = sys.argv[1:4]
try:
    data = json.load(open(path, encoding="utf-8"))
except Exception:
    print(default, end="")
    raise SystemExit(0)
print(data.get(key, default), end="")
PY
}

if [[ -n "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
else
    OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
fi

render_dir="${OUTPUT_DIR}/smartstore"
metadata="${render_dir}/metadata.json"
operation="$(metadata_value "${metadata}" operation smartstore)"

common_required=(
    README.md
    metadata.json
    index-lifecycle-report.md
    index-lifecycle-report.json
    index-dependency-report.md
    index-dependency-report.json
    collection-searches.spl
    collect-evidence.sh
    retention-change-plan.md
    destructive-action-plan.md
)
smartstore_required=(
    indexes.conf.template
    server.conf
    limits.conf
    preflight.sh
    apply-cluster-manager.sh
    apply-standalone-indexer.sh
    status.sh
)
lifecycle_required=(
    retention-indexes.conf.template
    indexes-disable.conf.template
    acs-index-update-payload.json
    apply-retention-enterprise.sh
    apply-retention-cloud.sh
    apply-disable-index.sh
    apply-delete-index.sh
    apply-clean-data.sh
    archive-handoff.sh
    restore-handoff.sh
    restore-handoff.md
    peer-cleanup-runbook.md
)

required=("${common_required[@]}" "${lifecycle_required[@]}")
if [[ "${operation}" == "smartstore" ]]; then
    required+=("${smartstore_required[@]}")
else
    required+=(status.sh preflight.sh)
fi

missing=()
for file in "${required[@]}"; do
    [[ -f "${render_dir}/${file}" ]] || missing+=("${file}")
done

ok=true
(( ${#missing[@]} == 0 )) || ok=false

if [[ "${operation}" == "smartstore" && -f "${render_dir}/indexes.conf.template" ]]; then
    if ! grep -q "storageType = remote" "${render_dir}/indexes.conf.template"; then
        missing+=("indexes.conf.template remote volume")
        ok=false
    fi
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    printf '{"target":"index-lifecycle","operation":"%s","render_dir":"%s","ok":%s,"missing":%s}\n' "${operation}" "${render_dir}" "${ok}" "$(json_array "${missing[@]}")"
else
    if [[ "${ok}" == "true" ]]; then
        log "Rendered index lifecycle assets are present under ${render_dir}."
    else
        log "ERROR: Missing or invalid index lifecycle assets under ${render_dir}: ${missing[*]}"
    fi
fi

[[ "${ok}" == "true" ]] || exit 1

if [[ "${LIVE}" == "true" ]]; then
    (cd "${render_dir}" && ./status.sh)
fi

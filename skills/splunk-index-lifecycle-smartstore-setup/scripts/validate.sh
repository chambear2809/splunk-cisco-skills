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

if [[ "${JSON_OUTPUT}" == "true" && "${LIVE}" == "true" ]]; then
    log "ERROR: --json and --live cannot be combined because live status output is not a single JSON document."
    exit 1
fi

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

if [[ -n "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
else
    OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
fi

render_dir="${OUTPUT_DIR}/smartstore"
metadata="${render_dir}/metadata.json"
operation="unknown"
metadata_error=""
if [[ -f "${metadata}" ]]; then
    if ! operation="$(python3 - "${metadata}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if path.is_symlink():
    raise SystemExit("metadata.json must not be a symlink")
data = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(data, dict):
    raise SystemExit("metadata.json must contain a JSON object")
operation = data.get("operation")
if not isinstance(operation, str) or not operation:
    raise SystemExit("metadata.json is missing a string operation")
print(operation, end="")
PY
)"; then
        metadata_error="metadata.json invalid JSON or schema"
    fi
fi

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
[[ -z "${metadata_error}" ]] || missing+=("${metadata_error}")
for file in "${required[@]}"; do
    [[ -f "${render_dir}/${file}" ]] || missing+=("${file}")
done

for file in metadata.json index-lifecycle-report.json index-dependency-report.json acs-index-update-payload.json; do
    path="${render_dir}/${file}"
    [[ -f "${path}" ]] || continue
    if ! python3 - "${path}" <<'PY' >/dev/null
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if path.is_symlink():
    raise SystemExit(1)
value = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(value, dict):
    raise SystemExit(1)
PY
    then
        missing+=("${file} valid JSON object")
    fi
done

for file in preflight.sh status.sh collect-evidence.sh apply-cluster-manager.sh apply-standalone-indexer.sh apply-retention-enterprise.sh apply-retention-cloud.sh apply-disable-index.sh apply-delete-index.sh apply-clean-data.sh archive-handoff.sh restore-handoff.sh; do
    path="${render_dir}/${file}"
    [[ -f "${path}" ]] || continue
    if ! bash -n "${path}"; then
        missing+=("${file} shell syntax")
    fi
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
    python3 - "${operation}" "${render_dir}" "${ok}" "${missing[@]}" <<'PY'
import json
import sys

operation, render_dir, ok, *missing = sys.argv[1:]
print(json.dumps({
    "target": "index-lifecycle",
    "operation": operation,
    "render_dir": render_dir,
    "ok": ok == "true",
    "missing": missing,
}, sort_keys=True))
PY
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

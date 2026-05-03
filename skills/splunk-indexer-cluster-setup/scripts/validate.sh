#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DEFAULT_RENDER_DIR_NAME="splunk-indexer-cluster-rendered"
OUTPUT_DIR=""
LIVE=false
JSON_OUTPUT=false
ADMIN_PASSWORD_FILE=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Indexer Cluster Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --output-dir PATH
  --admin-password-file PATH    (only required for --live)
  --live
  --json
  --help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --admin-password-file) require_arg "$1" $# || exit 1; ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
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

if [[ -n "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
else
    OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
fi

render_dir="${OUTPUT_DIR}/cluster"
required=(
    README.md metadata.json validate.sh
    bootstrap/sequenced-bootstrap.sh
    bundle/validate.sh bundle/status.sh bundle/apply.sh bundle/apply-skip-validation.sh bundle/rollback.sh
    restart/rolling-restart.sh restart/searchable-rolling-restart.sh restart/force-searchable.sh
    maintenance/enable.sh maintenance/disable.sh
    peer-ops/offline-fast.sh peer-ops/offline-enforce-counts.sh peer-ops/remove-peer.sh peer-ops/extend-restart-timeout.sh
    migration/single-to-multisite.sh migration/replace-manager.sh migration/decommission-site.sh migration/move-peer-to-site.sh migration/migrate-non-clustered.sh
)
missing=()
for file in "${required[@]}"; do
    [[ -f "${render_dir}/${file}" ]] || missing+=("${file}")
done

if (( ${#missing[@]} > 0 )); then
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        python3 - "${render_dir}" "${missing[@]}" <<'PY'
import json, sys
print(json.dumps({"status": "FAIL", "render_dir": sys.argv[1], "missing": sys.argv[2:]}))
PY
    else
        echo "FAIL: Missing rendered files in ${render_dir}: ${missing[*]}" >&2
    fi
    exit 1
fi

if [[ "${LIVE}" == "true" ]]; then
    if [[ -n "${ADMIN_PASSWORD_FILE}" ]]; then
        export SPLUNK_ADMIN_PASSWORD_FILE="${ADMIN_PASSWORD_FILE}"
    fi
    (cd "${render_dir}" && ./validate.sh)
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    python3 - "${render_dir}" "${required[@]}" <<'PY'
import json, sys
print(json.dumps({"status": "PASS", "render_dir": sys.argv[1], "files": sys.argv[2:]}))
PY
else
    echo "PASS: ${#required[@]} rendered files present in ${render_dir}"
fi

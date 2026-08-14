#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
OUTPUT_DIR="${PROJECT_ROOT}/galileo-on-prem-rendered"
JSON=false

usage() {
    cat <<'EOF'
Galileo On-Prem Kubernetes parent packet validation

Usage:
  bash skills/galileo-on-prem-kubernetes-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Exact bundle directory or an output root containing exactly one bundle
  --json             Emit a machine-readable validation result
  --help             Show help

Validation is offline and read-only. It verifies the closed artifact set,
regular-file types, permissions, hashes, normalized spec, matrix/source hashes,
coverage arrays, and bundle identity. It regenerates every JSON and Markdown
artifact plus the manifest from normalized inputs and referenced local-file
evidence. It does not query a cluster or imply deployment health.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "$1 requires a value"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --json) JSON=true; shift ;;
        --help|-h) usage; exit 0 ;;
        --apply|--install|--upgrade|--rollback|--uninstall|--delete|--execute|--purge)
            die "$1 is forbidden by this offline validator"
            ;;
        *) die "unknown option: $1" ;;
    esac
done

args=(--validate-path "${OUTPUT_DIR}")
[[ "${JSON}" != "true" ]] || args+=(--json)
python3 "${SCRIPT_DIR}/render_router.py" "${args[@]}"

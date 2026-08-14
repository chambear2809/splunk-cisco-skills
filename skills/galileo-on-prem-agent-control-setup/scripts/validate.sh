#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'EOF'
Galileo On-Prem Agent Control bundle validation

Usage:
  bash skills/galileo-on-prem-agent-control-setup/scripts/validate.sh --output-dir DIR

Options:
  --output-dir DIR          Rendered immutable bundle
  --galileo-console-url URL Accepted for shared Galileo intake compatibility;
                           the bundle's recorded URL remains authoritative
  --help                    Show help
EOF
}

OUTPUT_DIR=""
if [[ $# -eq 0 ]]; then usage; exit 0; fi
while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) [[ $# -ge 2 ]] || { echo "ERROR: --output-dir requires a value" >&2; exit 2; }; OUTPUT_DIR="$2"; shift 2 ;;
        --galileo-console-url) [[ $# -ge 2 ]] || { echo "ERROR: --galileo-console-url requires a value" >&2; exit 2; }; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done
[[ -n "${OUTPUT_DIR}" ]] || { echo "ERROR: --output-dir is required" >&2; exit 2; }
exec python3 "${SCRIPT_DIR}/render_bundle.py" --validate-output "${OUTPUT_DIR}"

#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
usage() { cat <<'EOF'
Galileo On-Prem Luna Studio bundle validation
Usage: bash skills/galileo-on-prem-luna-studio-setup/scripts/validate.sh --output-dir DIR
Options:
  --output-dir DIR
  --galileo-console-url URL   Accepted for shared Galileo intake compatibility
  --help
EOF
}
OUTPUT_DIR=""; if [[ $# -eq 0 ]]; then usage; exit 0; fi
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir) [[ $# -ge 2 ]] || exit 2; OUTPUT_DIR="$2"; shift 2 ;;
    --galileo-console-url) [[ $# -ge 2 ]] || exit 2; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ -n "${OUTPUT_DIR}" ]] || { echo "ERROR: --output-dir is required" >&2; exit 2; }
exec python3 "${SCRIPT_DIR}/render_bundle.py" --validate-output "${OUTPUT_DIR}"

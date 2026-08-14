#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
usage() { cat <<'EOF'
Galileo On-Prem Air-Gap bundle validation
Usage: bash skills/galileo-on-prem-air-gap-setup/scripts/validate.sh --output-dir DIR --galileo-console-url URL
Options: --output-dir DIR --galileo-console-url URL --help
EOF
}
OUTPUT=""; CONSOLE=""; if [[ $# -eq 0 ]]; then usage; exit 0; fi
while [[ $# -gt 0 ]]; do case "$1" in
  --output-dir) [[ $# -ge 2 ]] || exit 2; OUTPUT="$2"; shift 2 ;;
  --galileo-console-url) [[ $# -ge 2 ]] || exit 2; CONSOLE="$2"; shift 2 ;;
  --help|-h) usage; exit 0 ;;
  *) echo "ERROR: unknown option: $1" >&2; exit 2 ;;
esac; done
[[ -n "${OUTPUT}" ]] || { echo "ERROR: --output-dir is required" >&2; exit 2; }
[[ -n "${CONSOLE}" ]] || { echo "ERROR: --galileo-console-url is required" >&2; exit 2; }
exec python3 "${SCRIPT_DIR}/supply_chain.py" --verify --bundle "${OUTPUT}" --galileo-console-url "${CONSOLE}"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
Usage: bash skills/splunk-microsoft-exchange-ta-setup/scripts/validate.sh [--index INDEX]

Offline validation checks renderer/list support and package metadata. Live
ingestion validation is emitted in validation-searches.spl.
EOF
    exit 0
fi

INDEX="msexchange"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --index) INDEX="$2"; shift 2 ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done

python3 "${SCRIPT_DIR}/render_assets.py" --phase list --products exchange --json >/dev/null
python3 "${SCRIPT_DIR}/render_assets.py" --phase render --products exchange --index "${INDEX}" --dry-run --json >/dev/null
echo "PASS: Microsoft Exchange supported add-on renderer is valid"

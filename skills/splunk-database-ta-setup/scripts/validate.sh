#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
Usage: bash skills/splunk-database-ta-setup/scripts/validate.sh [--index INDEX] [--live|--completion]

Offline validation checks renderer/list support and package metadata. Live
ingestion validation is emitted in validation-searches.spl.
This validator fails closed if live/completion validation is requested.
EOF
    exit 0
fi

INDEX="database"
LIVE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --index) [[ $# -ge 2 ]] || { echo "ERROR: --index requires a value" >&2; exit 1; }; INDEX="$2"; shift 2 ;;
        --live|--completion|--strict) LIVE=true; shift ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ "${LIVE}" == "true" ]]; then echo "ERROR: live completion probing is not implemented; run validation-searches.spl and capture evidence." >&2; exit 2; fi

python3 "${SCRIPT_DIR}/render_assets.py" --phase list --products mssql,mysql,oracle --index "${INDEX}" --json >/dev/null
python3 "${SCRIPT_DIR}/render_assets.py" --phase render --products mssql --index "${INDEX}" --dry-run --json >/dev/null
echo "PASS: database supported add-ons renderer is valid"

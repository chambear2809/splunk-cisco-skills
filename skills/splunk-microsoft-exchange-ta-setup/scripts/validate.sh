#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
Usage: bash skills/splunk-microsoft-exchange-ta-setup/scripts/validate.sh [--index INDEX] [--live|--completion]

Offline validation checks renderer/list support and package metadata. Live
ingestion validation is emitted in validation-searches.spl.
This validator fails closed if live/completion validation is requested.
EOF
    exit 0
fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

INDEX="msexchange"
LIVE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --live|--completion|--strict) LIVE=true; shift ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ "${LIVE}" == "true" ]]; then echo "ERROR: live completion probing is not implemented; run validation-searches.spl and capture evidence." >&2; exit 2; fi

python3 "${SCRIPT_DIR}/render_assets.py" --phase list --products exchange --json >/dev/null
python3 "${SCRIPT_DIR}/render_assets.py" --phase render --products exchange --index "${INDEX}" --dry-run --json >/dev/null
echo "PASS: Microsoft Exchange supported add-on renderer is valid"

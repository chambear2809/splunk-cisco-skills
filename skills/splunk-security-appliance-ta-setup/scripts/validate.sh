#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
Usage: bash skills/splunk-security-appliance-ta-setup/scripts/validate.sh [--index INDEX]

Offline validation checks renderer/list support and package metadata. Live
ingestion validation is emitted in validation-searches.spl.
EOF
    exit 0
fi

INDEX="endpoint"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --index) INDEX="$2"; shift 2 ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done

python3 "${SCRIPT_DIR}/render_assets.py" --phase list --products carbon_black,symantec_endpoint_protection --json >/dev/null
python3 "${SCRIPT_DIR}/render_assets.py" --phase render --products carbon_black --index "${INDEX}" --dry-run --json >/dev/null
echo "PASS: security appliance supported add-ons renderer is valid"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CATALOG_PATH="${SCRIPT_DIR}/../catalog.json"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Security Portfolio Catalog Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --catalog PATH  Override catalog.json path
  --help          Show this help
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --catalog)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "ERROR: --catalog requires a path." >&2
                usage 1
            fi
            CATALOG_PATH="$2"
            shift 2
            ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

python3 - "${CATALOG_PATH}" "${REPO_ROOT}" <<'PY'
import json
import sys
from pathlib import Path

catalog_path = Path(sys.argv[1])
repo_root = Path(sys.argv[2])
catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
statuses = set(catalog.get("statuses", []))
errors = []

required_products = {
    "enterprise-security",
    "security-essentials",
    "soar",
    "uba",
    "attack-analyzer",
    "asset-risk-intelligence",
}
entries = {entry["key"]: entry for entry in catalog.get("entries", [])}
missing = sorted(required_products - set(entries))
if missing:
    errors.append(f"missing required product keys: {', '.join(missing)}")

for entry in entries.values():
    status = entry.get("status")
    if status not in statuses:
        errors.append(f"{entry['key']} has unknown status {status!r}")
    for skill in entry.get("route", []):
        if not skill.startswith("splunk-"):
            continue
        skill_path = repo_root / "skills" / skill / "SKILL.md"
        if not skill_path.exists():
            errors.append(f"{entry['key']} routes to missing skill {skill}")

if errors:
    for error in errors:
        print(f"FAIL: {error}")
    raise SystemExit(1)

print(f"PASS: {len(entries)} security portfolio entries validated")
PY

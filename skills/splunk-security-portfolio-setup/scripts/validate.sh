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
required_current_es_routes = {
    "es-essentials-edition",
    "es-premier-edition",
    "es-native-soar",
    "es-ai-assistant",
    "automated-threat-analysis",
    "federated-analytics",
}
raw_entries = catalog.get("entries", [])
entries = {entry["key"]: entry for entry in raw_entries}
if len(entries) != len(raw_entries):
    errors.append("catalog keys must be unique")
missing = sorted((required_products | required_current_es_routes) - set(entries))
if missing:
    errors.append(f"missing required security portfolio keys: {', '.join(missing)}")

identity_owners = {}
for entry in entries.values():
    status = entry.get("status")
    if status not in statuses:
        errors.append(f"{entry['key']} has unknown status {status!r}")
    identities = [entry.get("key", ""), entry.get("name", ""), *entry.get("aliases", [])]
    for identity in identities:
        normalized = " ".join(
            "".join(character.lower() if character.isalnum() else " " for character in identity).split()
        )
        if not normalized:
            errors.append(f"{entry['key']} has an empty normalized identity")
            continue
        previous_owner = identity_owners.get(normalized)
        if previous_owner and previous_owner != entry["key"]:
            errors.append(
                f"normalized identity {normalized!r} is shared by "
                f"{previous_owner} and {entry['key']}"
            )
        identity_owners[normalized] = entry["key"]
    for skill in entry.get("route", []):
        if not skill.startswith("splunk-"):
            continue
        skill_path = repo_root / "skills" / skill / "SKILL.md"
        if not skill_path.exists():
            errors.append(f"{entry['key']} routes to missing skill {skill}")

for key in {"es-essentials-edition", "es-premier-edition", "automated-threat-analysis"}:
    source_urls = entries.get(key, {}).get("source_urls", [])
    if not source_urls or any(
        not source_url.startswith("https://help.splunk.com/") for source_url in source_urls
    ):
        errors.append(f"{key} must cite at least one official help.splunk.com source")

if errors:
    for error in errors:
        print(f"FAIL: {error}")
    raise SystemExit(1)

print(f"PASS: {len(entries)} security portfolio entries validated")
PY

python3 "${SCRIPT_DIR}/render_reference_table.py" \
    --catalog "${CATALOG_PATH}" \
    --reference "${SCRIPT_DIR}/../reference.md" \
    --check

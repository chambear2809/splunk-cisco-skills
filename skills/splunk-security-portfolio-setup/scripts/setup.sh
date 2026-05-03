#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CATALOG_PATH="${SCRIPT_DIR}/../catalog.json"

PRODUCT_QUERY=""
LIST_PRODUCTS=false
DRY_RUN=false
JSON_OUTPUT=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Security Portfolio Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --product NAME        Product, capability, or associated app to resolve
  --list-products       List the security portfolio coverage matrix
  --dry-run             Show the routed workflow without changing Splunk
  --json                Emit machine-readable JSON with --dry-run or --list-products
  --catalog PATH        Override catalog.json path
  --help                Show this help
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --product)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "ERROR: --product requires a value." >&2
                usage 1
            fi
            PRODUCT_QUERY="$2"
            shift 2
            ;;
        --list-products) LIST_PRODUCTS=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
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

if [[ ! -f "${CATALOG_PATH}" ]]; then
    echo "ERROR: Catalog not found: ${CATALOG_PATH}" >&2
    exit 1
fi

if [[ "${LIST_PRODUCTS}" != "true" && -z "${PRODUCT_QUERY}" ]]; then
    echo "ERROR: --product is required unless --list-products is used." >&2
    usage 1
fi

python3 - "${CATALOG_PATH}" "${PRODUCT_QUERY}" "${LIST_PRODUCTS}" "${DRY_RUN}" "${JSON_OUTPUT}" <<'PY'
import json
import sys

catalog_path, query, list_products, dry_run, json_output = sys.argv[1:6]
list_products = list_products == "true"
dry_run = dry_run == "true"
json_output = json_output == "true"

with open(catalog_path, encoding="utf-8") as handle:
    catalog = json.load(handle)

entries = catalog.get("entries", [])

def norm(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else " " for ch in value).split()

def score(entry, query_tokens):
    fields = [entry.get("name", ""), entry.get("key", ""), *entry.get("aliases", [])]
    best = 0
    for field in fields:
        tokens = norm(field)
        if not tokens:
            continue
        if tokens == query_tokens:
            best = max(best, 100)
        elif all(token in tokens for token in query_tokens):
            best = max(best, 80)
        elif any(token in tokens for token in query_tokens):
            best = max(best, 10)
    return best

def route_command(entry):
    if entry.get("route_command"):
        return entry["route_command"]
    route = entry.get("route", [])
    if not route:
        return []
    skill = route[0]
    if entry.get("status") in {"first_class", "existing_skill", "partial"} and skill.startswith("splunk-"):
        return ["bash", f"skills/{skill}/scripts/setup.sh", "--dry-run", *entry.get("route_args", [])]
    if skill == "splunk-app-install" and entry.get("splunkbase_ids"):
        # When the catalog entry lists multiple Splunkbase IDs (e.g. PCI has
        # both 1143 and 2897), the install_app.sh CLI only takes a single
        # --app-id. We pick the first as the canonical install target; the
        # alternates surface in the JSON / text payload so operators know to
        # consider them. The text renderer prints them under "Splunkbase IDs".
        return [
            "bash",
            "skills/splunk-app-install/scripts/install_app.sh",
            "--source",
            "splunkbase",
            "--app-id",
            entry["splunkbase_ids"][0],
        ]
    return []


def alternate_splunkbase_ids(entry):
    """Return any IDs beyond the first that the router cannot route through
    `install_app.sh` directly, so callers can present them as alternatives."""
    ids = entry.get("splunkbase_ids", [])
    return ids[1:] if len(ids) > 1 else []

if list_products:
    payload = {
        "ok": True,
        "last_verified": catalog.get("last_verified"),
        "entries": entries,
    }
    if json_output:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(f"Splunk security coverage last verified: {payload['last_verified']}")
        for entry in entries:
            ids = ",".join(entry.get("splunkbase_ids", [])) or "N/A"
            route = ",".join(entry.get("route", [])) or "N/A"
            print(f"- {entry['name']}: {entry['status']} | route={route} | splunkbase={ids}")
    raise SystemExit(0)

query_tokens = norm(query)
ranked = sorted(((score(entry, query_tokens), entry) for entry in entries), reverse=True, key=lambda item: item[0])
if not ranked or ranked[0][0] <= 0:
    payload = {
        "ok": False,
        "query": query,
        "error": "No matching security portfolio entry found.",
        "last_verified": catalog.get("last_verified"),
    }
    if json_output:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(payload["error"])
    raise SystemExit(2)

entry = ranked[0][1]
alternates = alternate_splunkbase_ids(entry)
payload = {
    "ok": True,
    "dry_run": dry_run,
    "query": query,
    "last_verified": catalog.get("last_verified"),
    "entry": entry,
    "route_command": route_command(entry),
    "alternate_splunkbase_ids": alternates,
}

if json_output:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
else:
    print(f"Resolved: {entry['name']}")
    print(f"Status: {entry['status']}")
    print(f"Route: {', '.join(entry.get('route', [])) or 'N/A'}")
    print(f"Splunkbase IDs: {', '.join(entry.get('splunkbase_ids', [])) or 'N/A'}")
    print(f"Notes: {entry.get('notes', '')}")
    if payload["route_command"]:
        print("Suggested command:")
        print("  " + " ".join(payload["route_command"]))
    if alternates:
        print("Alternate Splunkbase IDs (re-run with --app-id <id> to install instead):")
        for alt in alternates:
            print(f"  - {alt}")
PY

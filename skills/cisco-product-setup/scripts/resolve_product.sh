#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CATALOG_PATH="${SCRIPT_DIR}/../catalog.json"

LIST_PRODUCTS=false
JSON_OUTPUT=false
SHOW_PRODUCT=false
QUERY=""

usage() {
    local exit_code="${1:-0}"
    local target=1
    [[ "${exit_code}" -ne 0 ]] && target=2
    cat >&"${target}" <<EOF
Cisco Product Resolver

Usage: $(basename "$0") [OPTIONS] [QUERY]

Options:
  --list-products          List catalog products and automation states
  --json                   Emit machine-readable JSON
  --show-product           Emit a human summary (default)
  --catalog PATH           Override catalog.json path
  --help                   Show this help
EOF
    exit "${exit_code}"
}

# shellcheck disable=SC2034
while [[ $# -gt 0 ]]; do
    case "$1" in
        --list-products) LIST_PRODUCTS=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --show-product) SHOW_PRODUCT=true; shift ;;
        --catalog)
            if [[ $# -lt 2 ]]; then
                echo "ERROR: --catalog requires a path argument" >&2
                usage 1
            fi
            CATALOG_PATH="$2"; shift 2 ;;
        --help) usage 0 ;;
        --*)
            echo "Unknown option: $1" >&2
            usage 1
            ;;
        *)
            if [[ -n "${QUERY}" ]]; then
                echo "ERROR: Only one product query is allowed." >&2
                exit 1
            fi
            QUERY="$1"
            shift
            ;;
    esac
done

if ! ${LIST_PRODUCTS} && [[ -z "${QUERY}" ]]; then
    usage
fi

python3 - "${CATALOG_PATH}" "${QUERY}" "$(${JSON_OUTPUT} && echo true || echo false)" "$(${LIST_PRODUCTS} && echo true || echo false)" <<'PY'
import json
import re
import sys
from pathlib import Path

catalog_path = Path(sys.argv[1])
query = sys.argv[2]
json_output = sys.argv[3] == "true"
list_products = sys.argv[4] == "true"

if not catalog_path.is_file():
    raise SystemExit(f"Catalog not found: {catalog_path}")

catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
products = catalog.get("products", [])


def normalize(value: str) -> str:
    lowered = value.lower().replace("&", " and ").replace("_", " ")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


if list_products:
    if json_output:
        print(json.dumps({"products": products}, indent=2, sort_keys=True))
    else:
        for product in products:
            print(
                "\t".join(
                    [
                        product["id"],
                        product["display_name"],
                        product["automation_state"],
                        product.get("primary_skill", ""),
                    ]
                )
            )
    raise SystemExit(0)


query_norm = normalize(query)
exact = []
fuzzy = []
for product in products:
    terms = product.get("normalized_search_terms", [])
    if query_norm in terms:
        exact.append(product)
        continue
    if any(query_norm and query_norm in term for term in terms):
        fuzzy.append(product)

status = "not_found"
matches = []
if len(exact) == 1:
    status = "resolved"
    matches = exact
elif len(exact) > 1:
    status = "ambiguous"
    matches = exact
elif len(fuzzy) == 1:
    status = "resolved"
    matches = fuzzy
elif len(fuzzy) > 1:
    status = "ambiguous"
    matches = fuzzy

payload = {
    "status": status,
    "query": query,
    "matches": matches,
}

if json_output:
    print(json.dumps(payload, indent=2, sort_keys=True))
else:
    if status == "resolved":
        product = matches[0]
        print(f"Product: {product['display_name']}")
        print(f"ID: {product['id']}")
        print(f"State: {product['automation_state']}")
        if product.get("primary_skill"):
            print(f"Primary skill: {product['primary_skill']}")
        if product.get("companion_skills"):
            print("Companion skills: " + ", ".join(product["companion_skills"]))
        if product.get("dashboards"):
            print("Dashboards: " + ", ".join(product["dashboards"]))
        if product.get("manual_gap_reason"):
            print(f"Reason: {product['manual_gap_reason']}")
        if product.get("notes"):
            print(f"Notes: {product['notes']}")
    elif status == "ambiguous":
        print(f"Ambiguous product query: {query}")
        for product in matches:
            print(f"- {product['display_name']} [{product['id']}]")
    else:
        print(f"Product not found: {query}")

if status == "resolved":
    raise SystemExit(0)
if status == "ambiguous":
    raise SystemExit(2)
raise SystemExit(1)
PY

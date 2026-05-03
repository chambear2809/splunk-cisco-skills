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


def display_aliases(display_name: str) -> list[str]:
    aliases = [display_name]
    no_parens = re.sub(r"\s*\([^)]*\)", "", display_name).strip()
    if no_parens and no_parens != display_name:
        aliases.append(no_parens)
    for match in re.findall(r"\(([^)]+)\)", display_name):
        aliases.append(match.strip())
        for piece in re.split(r"[/,]", match):
            piece = piece.strip()
            if piece:
                aliases.append(piece)
    return aliases


def state_rank(product: dict) -> int:
    state = product.get("automation_state", "")
    return {
        "automated": 0,
        "manual_gap": 1,
        "unsupported_roadmap": 2,
        "unsupported_legacy": 3,
    }.get(state, 4)


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
ranked_matches = []
for product in products:
    terms = product.get("normalized_search_terms", [])
    display_terms = {normalize(alias) for alias in display_aliases(product.get("display_name", ""))}
    alias_terms = {normalize(alias) for alias in product.get("aliases", [])}
    product_id = str(product.get("id", ""))
    score = None

    if query == product_id or query_norm == normalize(product_id):
        score = 0
    elif query_norm in display_terms:
        score = 1
    elif query_norm in alias_terms:
        score = 2
    elif query_norm in terms:
        score = 3
    elif any(query_norm and query_norm in term for term in terms):
        score = 4

    if score is not None:
        ranked_matches.append((score, state_rank(product), product))

status = "not_found"
matches = []
if ranked_matches:
    ranked_matches.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2].get("display_name", "").lower(),
            item[2].get("id", ""),
        )
    )
    best_score = ranked_matches[0][0]
    best_state_rank = ranked_matches[0][1]
    matches = [
        product
        for score, product_state_rank, product in ranked_matches
        if score == best_score and product_state_rank == best_state_rank
    ]
    status = "resolved" if len(matches) == 1 else "ambiguous"

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

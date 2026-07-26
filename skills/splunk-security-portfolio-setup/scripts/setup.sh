#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CATALOG_PATH="${SCRIPT_DIR}/../catalog.json"

PRODUCT_QUERY=""
LIST_PRODUCTS=false
DRY_RUN=false
JSON_OUTPUT=false
EXECUTE=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Security Portfolio Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --product NAME        Product, capability, or associated app to resolve
  --list-products       List the security portfolio coverage matrix
  --dry-run             Show the routed workflow without changing Splunk
  --execute             Execute only an exact, unique product identity
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
        --execute) EXECUTE=true; shift ;;
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
if [[ "${EXECUTE}" == "true" && "${LIST_PRODUCTS}" == "true" ]]; then
    echo "ERROR: --execute cannot be combined with --list-products." >&2
    exit 1
fi
if [[ "${EXECUTE}" == "true" && "${JSON_OUTPUT}" == "true" && "${DRY_RUN}" != "true" ]]; then
    echo "ERROR: --json with --execute is supported only with --dry-run." >&2
    exit 1
fi

python3 - "${CATALOG_PATH}" "${PRODUCT_QUERY}" "${LIST_PRODUCTS}" "${DRY_RUN}" "${JSON_OUTPUT}" "${EXECUTE}" <<'PY'
import json
from pathlib import Path
import re
import subprocess
import sys

catalog_path, query, list_products, dry_run, json_output, execute = sys.argv[1:7]
list_products = list_products == "true"
dry_run = dry_run == "true"
json_output = json_output == "true"
execute = execute == "true"

with open(catalog_path, encoding="utf-8") as handle:
    catalog = json.load(handle)
repo_root = Path(catalog_path).resolve().parents[2]

entries = catalog.get("entries", [])
FUZZY_MIN_SCORE = 70

def norm(value: str):
    return "".join(ch.lower() if ch.isalnum() else " " for ch in value).split()

def normalized_identity(value: str) -> str:
    return " ".join(norm(value))

def identity_fields(entry):
    return [entry.get("key", ""), entry.get("name", ""), *entry.get("aliases", [])]

def fuzzy_score(entry, query_tokens):
    query_set = set(query_tokens)
    best_score = 0
    best_identity = ""
    for field in identity_fields(entry):
        field_tokens = norm(field)
        field_set = set(field_tokens)
        if not field_set:
            continue
        overlap = query_set & field_set
        if not overlap:
            continue
        query_coverage = len(overlap) / len(query_set)
        field_coverage = len(overlap) / len(field_set)
        candidate_score = round(100 * ((0.6 * query_coverage) + (0.4 * field_coverage)))
        # A single shared token such as "security", "app", or "cloud" is not
        # enough to infer a product identity safely. Single-token identities
        # still work through the exact-match path.
        if len(overlap) == 1:
            candidate_score = min(candidate_score, 49)
        if candidate_score > best_score:
            best_score = candidate_score
            best_identity = field
    return best_score, best_identity

def ranked_candidates(query_tokens):
    ranked = []
    for entry in entries:
        candidate_score, identity = fuzzy_score(entry, query_tokens)
        if candidate_score > 0:
            ranked.append(
                {
                    "score": candidate_score,
                    "key": entry["key"],
                    "name": entry["name"],
                    "matched_identity": identity,
                    "entry": entry,
                }
            )
    return sorted(ranked, key=lambda candidate: (-candidate["score"], candidate["key"]))

def public_candidates(candidates, limit=5):
    return [
        {
            "key": candidate["key"],
            "name": candidate["name"],
            "score": candidate["score"],
            "matched_identity": candidate["matched_identity"],
        }
        for candidate in candidates[:limit]
    ]

def emit_resolution_error(message, candidates=None):
    payload = {
        "ok": False,
        "query": query,
        "error": message,
        "last_verified": catalog.get("last_verified"),
        "candidates": public_candidates(candidates or []),
    }
    if json_output:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(message, file=sys.stderr)
        if payload["candidates"]:
            print("Ranked candidates:", file=sys.stderr)
            for candidate in payload["candidates"]:
                print(
                    f"  - {candidate['name']} ({candidate['key']}): "
                    f"score={candidate['score']}",
                    file=sys.stderr,
                )
    raise SystemExit(2)

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


def command_is_mutating(command):
    if not command:
        return False
    if any(arg in {"--dry-run", "--render"} for arg in command):
        return False
    if "--mode" in command:
        mode_index = command.index("--mode")
        if mode_index + 1 >= len(command) or command[mode_index + 1] != "apply":
            return False
    if "--phase" in command:
        phase_index = command.index("--phase")
        if phase_index + 1 >= len(command):
            return False
        if command[phase_index + 1] in {"render", "list", "coverage", "resolve", "preview", "preflight", "status", "validate"}:
            return False
    return True


def executable_route_command(entry):
    command = list(entry.get("action_command", []))
    return command if command_is_mutating(command) else []


def setup_help(skill: str) -> str:
    setup = repo_root / "skills" / skill / "scripts" / "setup.sh"
    if not setup.is_file():
        return ""
    result = subprocess.run(
        ["bash", str(setup), "--help"],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return result.stdout


def setup_supports_flag(help_text: str, flag: str) -> bool:
    return re.search(rf"(^|[\s,|]){re.escape(flag)}($|[\s,|])", help_text) is not None


def action_command(entry):
    if entry.get("action_command"):
        return executable_route_command(entry)
    if entry.get("route_command"):
        # Suggested render/preview commands are not automatically promoted to
        # mutations. Catalog entries need an explicit reviewed action_command.
        return []

    route = entry.get("route", [])
    if not route:
        return route_command(entry)

    skill = route[0]
    if skill == "splunk-soar-setup":
        # SOAR needs an explicit phase and topology. A bare --apply defaults to
        # an on-premises server install and is never a safe router inference.
        return []
    setup = repo_root / "skills" / skill / "scripts" / "setup.sh"
    if not setup.is_file():
        return []

    command = ["bash", f"skills/{skill}/scripts/setup.sh"]
    help_text = setup_help(skill)
    route_args = entry.get("route_args", [])
    selected_action = False
    if setup_supports_flag(help_text, "--all"):
        command.append("--all")
        selected_action = True
    elif setup_supports_flag(help_text, "--install"):
        command.append("--install")
        selected_action = True
    elif setup_supports_flag(help_text, "--apply"):
        command.append("--apply")
        selected_action = True
    elif setup_supports_flag(help_text, "--phase") and "apply" in help_text:
        command.extend(["--phase", "apply"])
        selected_action = True
    if not selected_action:
        return []
    command.extend(route_args)
    return command if command_is_mutating(command) else []


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
query_identity = " ".join(query_tokens)
exact_matches = []
for candidate_entry in entries:
    matched_identities = [
        identity
        for identity in identity_fields(candidate_entry)
        if normalized_identity(identity) == query_identity
    ]
    if matched_identities:
        exact_matches.append((candidate_entry, matched_identities[0]))

if len(exact_matches) > 1:
    duplicate_candidates = [
        {
            "score": 100,
            "key": candidate_entry["key"],
            "name": candidate_entry["name"],
            "matched_identity": identity,
            "entry": candidate_entry,
        }
        for candidate_entry, identity in exact_matches
    ]
    emit_resolution_error(
        "Ambiguous exact security portfolio identity; use a unique catalog key.",
        duplicate_candidates,
    )

if exact_matches:
    entry, matched_identity = exact_matches[0]
    match_type = "exact"
    match_score = 100
else:
    ranked = ranked_candidates(query_tokens)
    if not ranked:
        emit_resolution_error("No matching security portfolio entry found.")
    top_score = ranked[0]["score"]
    if top_score < FUZZY_MIN_SCORE:
        emit_resolution_error(
            f"No high-confidence security portfolio match found "
            f"(minimum score: {FUZZY_MIN_SCORE}).",
            ranked,
        )
    tied = [candidate for candidate in ranked if candidate["score"] == top_score]
    if len(tied) > 1:
        emit_resolution_error(
            "Ambiguous security portfolio query; use an exact catalog key, name, or alias.",
            ranked,
        )
    entry = ranked[0]["entry"]
    matched_identity = ranked[0]["matched_identity"]
    match_type = "fuzzy"
    match_score = ranked[0]["score"]

alternates = alternate_splunkbase_ids(entry)
resolved_action_command = (
    action_command(entry) if not execute or match_type == "exact" else []
)
payload = {
    "ok": True,
    "dry_run": dry_run,
    "execute": execute,
    "query": query,
    "last_verified": catalog.get("last_verified"),
    "match": {
        "type": match_type,
        "score": match_score,
        "identity": matched_identity,
    },
    "entry": entry,
    "route_command": route_command(entry),
    "action_command": resolved_action_command,
    "alternate_splunkbase_ids": alternates,
}

if execute:
    if match_type != "exact":
        payload["ok"] = False
        payload["error"] = (
            "Execution requires an exact, unique catalog key, product name, or alias; "
            "fuzzy matches are preview-only."
        )
        if json_output:
            json.dump(payload, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
        else:
            print(payload["error"], file=sys.stderr)
        raise SystemExit(2)
    command = payload["action_command"]
    if not command:
        payload["ok"] = False
        payload["error"] = "No executable route is available for this entry."
        if json_output:
            json.dump(payload, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
        else:
            print(payload["error"], file=sys.stderr)
        raise SystemExit(2)
    if dry_run:
        payload["would_execute"] = command
        if json_output:
            json.dump(payload, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
        else:
            print("DRY RUN: routed command")
            print("  " + " ".join(command))
        raise SystemExit(0)
    completed = subprocess.run(command, cwd=repo_root)
    raise SystemExit(completed.returncode)

if json_output:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
else:
    print(f"Resolved: {entry['name']}")
    print(f"Match: {match_type} (score={match_score}, identity={matched_identity})")
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

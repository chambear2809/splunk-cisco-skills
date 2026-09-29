#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<'EOF'
Splunk Agent Observability task planner

Usage:
  bash scripts/setup.sh --help
  bash scripts/setup.sh --plan [--feature ID | --object ID [--operation create|update|delete|verify]] [--deployment saas|on-premises]
  bash scripts/setup.sh --validate

--plan renders a feature boundary or an object-specific action from the tracked
matrices. With no --feature or --object, it lists feature and object IDs.
Use the skill instructions to perform the task with the approved live MCP,
SDK, API, UI, or repository interface, then validate it.
--validate runs offline feature-matrix checks. This script never contacts or
changes a Splunk environment.
EOF
}

mode="--plan"
feature=""
object=""
operation=""
deployment=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --plan|--validate) mode="$1"; shift ;;
        --feature)
            [[ $# -ge 2 ]] || { printf 'ERROR: --feature requires an ID\n' >&2; exit 1; }
            feature="$2"; shift 2 ;;
        --object)
            [[ $# -ge 2 ]] || { printf 'ERROR: --object requires an ID\n' >&2; exit 1; }
            object="$2"; shift 2 ;;
        --operation)
            [[ $# -ge 2 ]] || { printf 'ERROR: --operation requires a value\n' >&2; exit 1; }
            operation="$2"; shift 2 ;;
        --deployment)
            [[ $# -ge 2 ]] || { printf 'ERROR: --deployment requires a value\n' >&2; exit 1; }
            deployment="$2"; shift 2 ;;
        *) printf 'ERROR: unsupported option: %s\n' "$1" >&2; usage >&2; exit 1 ;;
    esac
done
if [[ "${mode}" == "--validate" ]]; then
    [[ -z "${feature}" && -z "${object}" && -z "${operation}" && -z "${deployment}" ]] || { printf 'ERROR: --validate takes no feature/object/operation/deployment\n' >&2; exit 1; }
    exec bash "${SCRIPT_DIR}/validate.sh"
fi
if [[ -n "${feature}" && -n "${object}" ]]; then
    printf 'ERROR: choose either --feature or --object\n' >&2
    exit 1
fi
if [[ -n "${operation}" && -z "${object}" ]]; then
    printf 'ERROR: --operation requires --object\n' >&2
    exit 1
fi
if [[ -n "${operation}" && "${operation}" != "create" && "${operation}" != "update" && "${operation}" != "delete" && "${operation}" != "verify" ]]; then
    printf 'ERROR: operation must be create, update, delete, or verify\n' >&2
    exit 1
fi
if [[ -n "${deployment}" && "${deployment}" != "saas" && "${deployment}" != "on-premises" ]]; then
    printf 'ERROR: deployment must be saas or on-premises\n' >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    printf 'ERROR: Python 3 is required to render a task plan.\n' >&2
    exit 1
fi
bash "${SCRIPT_DIR}/validate.sh" >/dev/null

python3 - "${SKILL_DIR}/references/product-feature-matrix.json" "${SKILL_DIR}/references/object-action-matrix.json" "${feature}" "${object}" "${operation}" "${deployment}" <<'PY'
import json
import sys
from pathlib import Path

matrix = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
objects = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
feature_id, object_id, operation, deployment = sys.argv[3:7]
print("Splunk Agent Observability task plan")
print(f"Product scope: {matrix['product_area']}")
print(f"Coverage rows: {matrix['feature_count']}")
print(f"Object action rows: {len(objects['objects'])}")
if deployment:
    print(f"Target deployment: {deployment} (verify tenant entitlement and release)")
if not feature_id and not object_id:
    print("\nAvailable feature IDs:")
    for row in matrix["features"]:
        print(f"- {row['id']} [{row['status']}]")
    print("\nAvailable object IDs:")
    for row in objects["objects"]:
        print(f"- {row['id']} [{row['deployment']}]")
    raise SystemExit(0)
if object_id:
    row = next((item for item in objects["objects"] if item["id"] == object_id), None)
    if row is None:
        print(f"ERROR: unknown object ID: {object_id}", file=sys.stderr)
        raise SystemExit(1)
    if deployment and row["deployment"] not in (deployment, "both", "verify"):
        print(f"ERROR: {object_id} is documented for {row['deployment']}, not {deployment}", file=sys.stderr)
        raise SystemExit(1)
    print(f"\nSelected object: {row['id']} [{row['deployment']}]")
    if row["deployment"] == "verify":
        print("Deployment gate: confirm this REST/UI feature is exposed by the target tenant before mutation.")
    if row.get("risk") == "destructive_organization_wide":
        print("Risk gate: organization-wide deletion. An inventory or create-all request does not authorize this action; require a separate exact-filter deletion request.")
    for action in ((operation,) if operation else ("create", "update", "delete", "verify")):
        print(f"{action.title()}: {row[action]}")
    if row.get("variants"):
        print("Documented variants or policy dimensions (verify tenant availability):")
        for variant in row["variants"]:
            if isinstance(variant, dict):
                print(f"- {variant['name']}: {variant['source_url']}")
            else:
                print(f"- {variant}")
    print("Official sources:")
    for url in [row["source_url"], *row.get("source_urls", [])]:
        print(f"- {url}")
    if operation and row[operation].startswith(("not-documented:", "not-applicable:")):
        print("Execution gate: no documented action for this operation. Inspect the live tenant for an approved path and record a gap if absent; do not infer a route.")
        raise SystemExit(2)
    print("Execution gate: read the linked current schema/UI, inventory exact target and permissions, perform the requested documented action, then read back state. A public route alone is not tenant proof.")
    raise SystemExit(0)
row = next((item for item in matrix["features"] if item["id"] == feature_id), None)
if row is None:
    print(f"ERROR: unknown feature ID: {feature_id}", file=sys.stderr)
    raise SystemExit(1)
if deployment and row.get("deployments") and deployment not in row["deployments"]:
    print(f"ERROR: {feature_id} is documented for {', '.join(row['deployments'])}, not {deployment}", file=sys.stderr)
    raise SystemExit(1)
if deployment and row.get("object_ids") and all(
    next(item for item in objects["objects"] if item["id"] == linked_id)["deployment"] not in (deployment, "both", "verify")
    for linked_id in row["object_ids"]
):
    print(f"ERROR: no linked object action for {feature_id} is available in {deployment}", file=sys.stderr)
    raise SystemExit(1)
print(f"\nSelected feature: {row['name']} [{row['status']}]")
print(f"Action boundary: {row['automation_boundary']}")
print(f"Validation evidence: {row['validation_evidence']}")
if row.get("object_ids"):
    print("Related object action plans:")
    for linked_id in row["object_ids"]:
        linked = next(item for item in objects["objects"] if item["id"] == linked_id)
        if deployment and linked["deployment"] not in (deployment, "both", "verify"):
            print(f"- {linked_id} [{linked['deployment']}]: excluded from {deployment} validation")
        else:
            print(f"- {linked_id} [{linked['deployment']}]: {linked['create']}")
print("Official sources:")
for url in [row["source_url"], *row.get("source_urls", [])]:
    print(f"- {url}")
print("\nWorkflow:")
for step in (
    "Identify SaaS, on-premises, or the adjacent legacy/AI-infrastructure product.",
    "Confirm tenant entitlement, release, target project/Agent Stream, and permissions.",
    "Inspect the feature source and live tool/API schema; stage changes and review data/cost effects.",
    "Apply only the requested supported action, then validate with sanitized evidence.",
    "Report changed identifiers, validation results, and any account/support handoff.",
):
    print(f"- {step}")
PY

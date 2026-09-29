#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<'EOF'
Splunk Agent Observability Setup offline validation

Usage:
  bash scripts/validate.sh [--help]

Validates the tracked feature and object-action matrices, source URL shape,
reference links, and coverage boundaries. Does not contact or change a Splunk
environment.
EOF
}

if [[ $# -gt 0 ]]; then
    case "$1" in
        --help|-h) usage; exit 0 ;;
        *) printf 'ERROR: unsupported option: %s\n' "$1" >&2; usage >&2; exit 1 ;;
    esac
fi
if ! command -v python3 >/dev/null 2>&1; then
    printf 'ERROR: Python 3 is required for offline validation.\n' >&2
    exit 1
fi

python3 - "${SKILL_DIR}" <<'PY'
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

skill = Path(sys.argv[1])
matrix_path = skill / "references/product-feature-matrix.json"
objects_path = skill / "references/object-action-matrix.json"
try:
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    objects = json.loads(objects_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    print(f"ERROR: cannot read feature matrix {matrix_path}: {exc}", file=sys.stderr)
    raise SystemExit(1)
if not isinstance(matrix, dict):
    print(f"ERROR: feature matrix must be a JSON object: {matrix_path}", file=sys.stderr)
    raise SystemExit(1)
errors = []
if not isinstance(objects, dict):
    print(f"ERROR: object matrix must be a JSON object: {objects_path}", file=sys.stderr)
    raise SystemExit(1)

if matrix.get("schema_version") != 1:
    errors.append("matrix schema_version must be 1")
if matrix.get("product_area") != "Splunk Agent Observability SaaS and on-premises product workflows":
    errors.append("matrix product_area does not match the coverage contract")
features = matrix.get("features")
if not isinstance(features, list) or not features:
    errors.append("matrix features must be a nonempty list")
    features = []
if matrix.get("feature_count") != len(features):
    errors.append(f"feature_count is {matrix.get('feature_count')!r}, found {len(features)} rows")

allowed_statuses = set(matrix.get("supported_statuses", []))
seen = set()
for index, row in enumerate(features, start=1):
    label = f"feature row {index}"
    if not isinstance(row, dict):
        errors.append(f"{label} must be an object")
        continue
    feature_id = str(row.get("id", ""))
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", feature_id):
        errors.append(f"{label} has invalid id {feature_id!r}")
    if feature_id in seen:
        errors.append(f"duplicate feature id: {feature_id}")
    seen.add(feature_id)
    for field in ("name", "automation_boundary", "validation_evidence", "source_url"):
        if not str(row.get(field, "")).strip():
            errors.append(f"{feature_id}: missing {field}")
    if row.get("status") not in allowed_statuses:
        errors.append(f"{feature_id}: undeclared status {row.get('status')!r}")
    if row.get("deployments") and (
        not isinstance(row["deployments"], list)
        or not set(row["deployments"]) <= {"saas", "on-premises"}
    ):
        errors.append(f"{feature_id}: invalid deployment list")
    if "splunk-agent-observability-setup" not in row.get("owners", []):
        errors.append(f"{feature_id}: missing canonical skill owner")
    url = str(row.get("source_url", ""))
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "agent-observability-docs.splunk.com",
        "docs.agentcontrol.dev",
        "help.splunk.com",
    }:
        errors.append(f"{feature_id}: source must use an approved official HTTPS host")

for url in matrix.get("source_urls", []):
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or parsed.hostname not in {
        "agent-observability-docs.splunk.com",
        "docs.agentcontrol.dev",
        "help.splunk.com",
    }:
        errors.append(f"matrix has unapproved source URL: {url}")
declared_urls = set(matrix.get("source_urls", []))
for row in features:
    if not isinstance(row, dict):
        continue
    for url in [row.get("source_url"), *row.get("source_urls", [])]:
        if url and url not in declared_urls:
            errors.append(f"{row.get('id', '<unknown>')}: source URL missing from matrix source_urls: {url}")

if objects.get("schema_version") != 1:
    errors.append("object matrix schema_version must be 1")
object_rows = objects.get("objects")
if not isinstance(object_rows, list) or not object_rows:
    errors.append("object matrix objects must be a nonempty list")
    object_rows = []
api_groups = objects.get("api_reference_groups")
if not isinstance(api_groups, list) or len(api_groups) != len(set(api_groups)):
    errors.append("object matrix api_reference_groups must be a unique list")
    api_groups = []
object_ids = set()
covered_groups = set()
for index, row in enumerate(object_rows, start=1):
    if not isinstance(row, dict):
        errors.append(f"object row {index} must be an object")
        continue
    object_id = str(row.get("id", ""))
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", object_id) or object_id in object_ids:
        errors.append(f"object row {index} has invalid or duplicate id {object_id!r}")
    object_ids.add(object_id)
    if row.get("deployment") not in {"both", "saas", "on-premises", "verify"}:
        errors.append(f"{object_id}: invalid deployment")
    if row.get("risk") not in (None, "destructive_organization_wide"):
        errors.append(f"{object_id}: invalid risk gate")
    if row.get("risk") == "destructive_organization_wide" and not str(row.get("create", "")).startswith("not-applicable:"):
        errors.append(f"{object_id}: organization-wide deletion cannot be a create-all action")
    for action in ("create", "update", "delete", "verify"):
        value = str(row.get(action, ""))
        allowed = ("documented:", "documented in", "not-applicable:", "not-documented:")
        if not value.startswith(allowed) and action != "verify":
            errors.append(f"{object_id}: {action} must state documented, not-applicable, or not-documented action")
        if action == "verify" and not value.strip():
            errors.append(f"{object_id}: verify must be nonempty")
    groups = row.get("api_groups")
    if not isinstance(groups, list):
        errors.append(f"{object_id}: api_groups must be a list")
    else:
        covered_groups.update(groups)
        for group in groups:
            if group not in api_groups:
                errors.append(f"{object_id}: unknown API group {group!r}")
    for url in [row.get("source_url"), *row.get("source_urls", [])]:
        parsed = urlparse(str(url))
        if parsed.scheme != "https" or parsed.hostname not in {
            "agent-observability-docs.splunk.com", "docs.agentcontrol.dev", "help.splunk.com"
        }:
            errors.append(f"{object_id}: source must use an approved official HTTPS host")
    for variant in row.get("variants", []):
        if isinstance(variant, dict):
            if not variant.get("name") or not str(variant.get("source_url", "")).startswith("https://agent-observability-docs.splunk.com/"):
                errors.append(f"{object_id}: invalid documented variant")
        elif not isinstance(variant, str) or not variant:
            errors.append(f"{object_id}: invalid variant")
if set(api_groups) != covered_groups:
    errors.append(f"unmapped API reference groups: {sorted(set(api_groups) - covered_groups)}")

for row in features:
    if not isinstance(row, dict):
        continue
    if row.get("status") == "direct_apply" and not row.get("object_ids"):
        errors.append(f"{row['id']}: direct_apply feature lacks object action mapping")
    for object_id in row.get("object_ids", []):
        if object_id not in object_ids:
            errors.append(f"{row['id']}: unknown object ID {object_id!r}")

reference = (skill / "reference.md").read_text(encoding="utf-8")
skill_doc = (skill / "SKILL.md").read_text(encoding="utf-8")
if "product-feature-matrix.json" not in skill_doc:
    errors.append("SKILL.md must identify the feature matrix as the coverage source")
if "object-action-matrix.json" not in skill_doc:
    errors.append("SKILL.md must identify the object matrix as the action source")
for index, url in enumerate(matrix.get("source_urls", []), start=1):
    if url not in reference and url not in skill_doc:
        errors.append(f"matrix source URL {index} is not present in the skill references")

if errors:
    print("Splunk Agent Observability validation failed:")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)

print(f"Splunk Agent Observability offline validation passed ({len(features)} feature rows; {len(object_rows)} object action rows; {len(api_groups)} API groups mapped).")
PY

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/cisco-data-fabric-rendered"

usage() {
    cat <<'EOF'
Cisco Data Fabric Setup validation

Usage:
  bash skills/cisco-data-fabric-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --help             Show this help

Validates artifact structure, feature/product/provider completeness, lifecycle
and automation status separation, source evidence, owner skill references,
toggle consistency, and secret hygiene. It does not query a live tenant.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

[[ -d "${OUTPUT_DIR}" ]] || { log "ERROR: Rendered output directory not found: ${OUTPUT_DIR}"; exit 1; }

check_file() {
    [[ -f "$1" ]] || { log "ERROR: Missing $1"; exit 1; }
}

check_exec() {
    [[ -x "$1" ]] || { log "ERROR: Missing executable $1"; exit 1; }
}

for rel in \
    .cisco-data-fabric-setup \
    metadata.json \
    apply-plan.json \
    coverage-report.json \
    coverage-report.md \
    product-matrix.json \
    product-matrix.md \
    availability-matrix.md \
    source-ledger.json \
    gap-register.json \
    gap-register.md \
    doctor-report.md \
    handoff.md \
    architecture/layer-model.md \
    data-management/pipeline-readiness.md \
    federation/target-matrix.md \
    storage-catalog/tiering-and-catalog-readiness.md \
    ai/activation-readiness.md \
    governance/trust-readiness.md \
    experience/cross-domain-handoff.md
do
    check_file "${OUTPUT_DIR}/${rel}"
done

for section in data-management federation storage-catalog ai-activation context-governance experience; do
    check_exec "${OUTPUT_DIR}/scripts/execute-${section}.sh"
done
check_exec "${OUTPUT_DIR}/scripts/execute-selected.sh"

python3 - "${OUTPUT_DIR}/coverage-report.json" "${OUTPUT_DIR}/product-matrix.json" "${OUTPUT_DIR}/source-ledger.json" "${OUTPUT_DIR}/apply-plan.json" "${OUTPUT_DIR}/gap-register.json" "${OUTPUT_DIR}/metadata.json" "${PROJECT_ROOT}" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

coverage_path, products_path, sources_path, plan_path, gaps_path, metadata_path, repo_root = map(Path, sys.argv[1:])
coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
products = json.loads(products_path.read_text(encoding="utf-8"))
sources = json.loads(sources_path.read_text(encoding="utf-8"))
plan = json.loads(plan_path.read_text(encoding="utf-8"))
gaps = json.loads(gaps_path.read_text(encoding="utf-8"))
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

allowed_repo = {
    "delegated_apply", "delegated_render", "render", "ui_handoff",
    "validation", "not_applicable",
}
allowed_stages = {
    "architecture", "ga", "available",
    "controlled_availability", "alpha", "feature_preview", "roadmap",
    "deprecated", "version_dependent",
}
required = {
    "key", "layer", "title", "product_stage", "repo_status", "owner",
    "platforms", "access_requirement", "source_url", "source_type", "source_version",
    "retrieved_at", "boundary",
}
rows = coverage.get("coverage")
if not isinstance(rows, list) or not rows:
    raise SystemExit("coverage report must contain rows")
keys = []
for index, row in enumerate(rows):
    missing = required - set(row)
    if missing:
        raise SystemExit(f"coverage row {index} missing {sorted(missing)}")
    if row["repo_status"] not in allowed_repo:
        raise SystemExit(f"coverage row {index} invalid repo_status {row['repo_status']}")
    if row["product_stage"] not in allowed_stages:
        raise SystemExit(f"coverage row {index} invalid product_stage {row['product_stage']}")
    if row["repo_status"] == "delegated_apply" and row["product_stage"] in {"alpha", "feature_preview", "roadmap", "deprecated"}:
        raise SystemExit(f"coverage row {row['key']} cannot apply lifecycle {row['product_stage']}")
    if not row["source_url"].startswith("https://"):
        raise SystemExit(f"coverage row {row['key']} has non-HTTPS source")
    keys.append(row["key"])
if len(keys) != len(set(keys)):
    raise SystemExit("duplicate coverage keys")

required_keys = {
    "cdf_architecture", "data_inputs", "edge_processor", "ingest_processor",
    "spl2_pipelines", "automated_field_extraction",
    "guided_onboarding_auto_schematization", "ingest_monitoring", "fss2s",
    "federated_s3", "federated_azure", "federated_databricks",
    "federated_snowflake", "federated_ddss",
    "federated_amazon_security_lake", "aws_glue_catalog",
    "iceberg_rest_catalog", "splunk_native_dataset_catalog",
    "delta_lake_table_format", "iceberg_table_format",
    "legacy_fss3_migration", "splunk_index", "machine_data_lake",
    "global_catalog", "machine_data_lake_catalog", "promote_s3",
    "knowledge_graph", "business_context", "ai_toolkit", "cdtsm",
    "ctsm_open_model", "splunk_agent_builder", "splunk_mcp_server",
    "agent_builder_connections", "agent_builder_aiagent",
    "agent_builder_run_history",
    "mcp_auth_tool_controls", "ai_canvas_splunk",
    "ai_canvas_splunk_limits",
    "cloud_control_studio_agent_builder", "cisco_sal_boundary",
}
missing = sorted(required_keys - set(keys))
if missing:
    raise SystemExit(f"missing required capability keys: {missing}")

by_key = {row["key"]: row for row in rows}
for key in ("federated_s3", "federated_amazon_security_lake"):
    if by_key[key]["product_stage"] != "ga":
        raise SystemExit(f"{key} lifecycle must remain GA")
    if by_key[key]["access_requirement"] in {"", "none"}:
        raise SystemExit(f"{key} must retain its separate activation/entitlement requirement")

product_rows = products.get("products")
if not isinstance(product_rows, list) or not product_rows:
    raise SystemExit("product matrix must contain products")
product_keys = {row.get("key") for row in product_rows}
for key in {"cisco_data_fabric", "machine_data_lake", "catalog", "ctsm", "agent_builder", "mcp_server", "cloud_control", "cisco_sal"}:
    if key not in product_keys:
        raise SystemExit(f"missing product key {key}")

source_rows = sources.get("sources")
if not isinstance(source_rows, list) or not source_rows:
    raise SystemExit("source ledger must contain sources")
claim_ids = [row.get("claim_id") for row in source_rows]
if len(claim_ids) != len(set(claim_ids)):
    raise SystemExit("duplicate source claim IDs")
for row in source_rows:
    for field in ("claim_id", "title", "url", "source_type", "source_version", "retrieved_at"):
        if not row.get(field):
            raise SystemExit(f"source row missing {field}")

expected_sections = {
    "data-management", "federation", "storage-catalog", "ai-activation",
    "context-governance", "experience",
}
sections = {row.get("name") for row in plan.get("sections", [])}
if sections != expected_sections:
    raise SystemExit(f"apply-plan sections mismatch: {sorted(sections)}")
for section in plan["sections"]:
    if section["name"] in {"storage-catalog", "experience"} and section.get("handoff_only") is not True:
        raise SystemExit(f"{section['name']} must be handoff-only")
    commands = section.get("commands")
    if not isinstance(commands, list):
        raise SystemExit(f"{section['name']} commands must be a list")
    for command in commands:
        if not isinstance(command, list) or not command:
            raise SystemExit(f"{section['name']} command must be argv")
        text = " ".join(command)
        if "splunk-ingest-processor-setup" in text:
            raise SystemExit("parent must not invoke Ingest Processor with canned defaults")
        if any(flag in command for flag in ("--token", "--password", "--api-key", "--client-secret", "--private-key")):
            raise SystemExit(f"secret flag in command: {command}")

ai_commands = [
    command
    for section in plan["sections"]
    if section.get("name") == "ai-activation"
    for command in section.get("commands", [])
    if "skills/splunk-ai-ml-toolkit-setup/scripts/setup.sh" in command
]
deployment = str(metadata.get("deployment", ""))
expected_platform = {
    "cloud": "cloud",
    "splunk-cloud": "cloud",
    "splunk-cloud-platform": "cloud",
    "enterprise": "enterprise",
    "splunk-enterprise": "enterprise",
}.get(deployment.lower().replace("_", "-"))
ai_toolkit_enabled = any(
    row.get("key") == "ai_toolkit" and row.get("repo_status") != "not_applicable"
    for row in rows
)
if expected_platform and ai_toolkit_enabled and not ai_commands:
    raise SystemExit("AI Toolkit is enabled but no platform-aware child command was rendered")
for command in ai_commands:
    if "--platform" not in command or command[command.index("--platform") + 1] != expected_platform:
        raise SystemExit("AI Toolkit child command must propagate the target platform")
    if "--splunk-version" not in command or command[command.index("--splunk-version") + 1] != str(metadata.get("version", "")):
        raise SystemExit("AI Toolkit child command must propagate the target Splunk version")

for field in ("secret_values_rendered", "direct_cdf_api_mutation"):
    if metadata.get(field) is not False:
        raise SystemExit(f"metadata {field} must be false")
if metadata.get("cdf_is_architecture") is not True:
    raise SystemExit("metadata must classify CDF as architecture")

gap_rows = gaps.get("gaps")
if not isinstance(gap_rows, list):
    raise SystemExit("gap-register.json must contain a gaps list")
for index, gap in enumerate(gap_rows):
    if gap.get("severity") not in {"info", "warning", "error"}:
        raise SystemExit(f"gap row {index} has invalid severity")
    if not gap.get("key") or not gap.get("message"):
        raise SystemExit(f"gap row {index} is missing key/message")
blocking = sum(1 for gap in gap_rows if gap["severity"] == "error")
if gaps.get("blocking_error_count") != blocking:
    raise SystemExit("gap-register blocking_error_count mismatch")
if metadata.get("blocking_gap_count") != blocking:
    raise SystemExit("metadata blocking_gap_count mismatch")

owner_pattern = re.compile(r"\b(?:cisco|splunk)-[a-z0-9-]+\b")
for row in rows:
    for owner in owner_pattern.findall(row["owner"]):
        if owner in {"cisco-data-fabric-setup"}:
            continue
        if not (repo_root / "skills" / owner).is_dir():
            raise SystemExit(f"coverage owner skill does not exist: {owner}")
PY

for term in \
    "Amazon S3" \
    "Microsoft Azure" \
    "Azure Databricks" \
    "Snowflake" \
    "DDSS" \
    "Amazon Security Lake"
do
    grep -Fq "${term}" "${OUTPUT_DIR}/federation/target-matrix.md" || {
        log "ERROR: Federation matrix missing ${term}"
        exit 1
    }
done

if grep -RIE -- '(Authorization:[[:space:]]*(Splunk|Bearer)[[:space:]]+[A-Za-z0-9._=-]{12,}|DIRECT_SECRET|SHOULD_NOT_RENDER)' "${OUTPUT_DIR}" >/dev/null 2>&1; then
    log "ERROR: Rendered output appears to contain a concrete secret."
    exit 1
fi

log "Cisco Data Fabric rendered assets passed structural and semantic validation."

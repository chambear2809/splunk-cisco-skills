#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/galileo-platform-rendered"

usage() {
    cat <<'EOF'
Galileo Platform Setup validation

Usage:
  bash skills/galileo-platform-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ ! -d "${OUTPUT_DIR}" ]]; then
    log "ERROR: Rendered output directory not found: ${OUTPUT_DIR}"
    exit 1
fi

check_file() {
    local path="$1"
    [[ -f "${path}" ]] || { log "ERROR: Missing ${path}"; exit 1; }
}

check_exec() {
    local path="$1"
    [[ -x "${path}" ]] || { log "ERROR: Missing executable ${path}"; exit 1; }
}

check_file "${OUTPUT_DIR}/apply-plan.json"
check_file "${OUTPUT_DIR}/coverage-report.json"
check_file "${OUTPUT_DIR}/handoff.md"
check_file "${OUTPUT_DIR}/readiness/readiness-report.json"
check_exec "${OUTPUT_DIR}/readiness/healthcheck.sh"
check_file "${OUTPUT_DIR}/lifecycle/object-lifecycle-manifest.example.json"
check_file "${OUTPUT_DIR}/lifecycle/product-coverage-matrix.json"
check_file "${OUTPUT_DIR}/lifecycle/product-coverage-matrix.md"
check_file "${OUTPUT_DIR}/runtime/python-opentelemetry-env.sh"
check_file "${OUTPUT_DIR}/runtime/python-galileo-protect.py"
check_file "${OUTPUT_DIR}/evaluate/evaluate-assets.yaml"
check_file "${OUTPUT_DIR}/splunk-platform/hec-event-sample.json"
check_file "${OUTPUT_DIR}/splunk-platform/export-records-request.json"
check_file "${OUTPUT_DIR}/otel/collector-galileo-fanout.yaml"
check_exec "${OUTPUT_DIR}/scripts/apply-readiness.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-object-lifecycle.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-observe-export.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-observe-runtime.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-protect-runtime.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-evaluate-assets.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-splunk-hec.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-splunk-otlp.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-otel-collector.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-dashboards.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-detectors.sh"

python3 - "${OUTPUT_DIR}/apply-plan.json" "${OUTPUT_DIR}/coverage-report.json" <<'PY'
import json
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
coverage = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
sections = {item["name"]: item for item in plan["sections"]}
required = {
    "readiness": "galileo-platform-setup",
    "object-lifecycle": "galileo-platform-setup",
    "observe-export": "galileo-platform-setup",
    "observe-runtime": "galileo-platform-setup",
    "protect-runtime": "galileo-platform-setup",
    "evaluate-assets": "galileo-platform-setup",
    "splunk-hec": "splunk-hec-service-setup",
    "splunk-otlp": "splunk-connect-for-otlp-setup",
    "otel-collector": "splunk-observability-otel-collector-setup",
    "dashboards": "splunk-observability-dashboard-builder",
    "detectors": "splunk-observability-native-ops",
}
missing = set(required) - set(sections)
if missing:
    raise SystemExit(f"missing apply sections: {sorted(missing)}")
for section, target in required.items():
    if sections[section]["delegates_to"] != target:
        raise SystemExit(f"{section} delegates to {sections[section]['delegates_to']}, expected {target}")
if plan.get("secret_files") is None:
    raise SystemExit("apply plan missing secret_files")
if coverage.get("secret_values_rendered") is not False:
    raise SystemExit("coverage report must assert secret_values_rendered=false")
lifecycle = coverage.get("coverage", {}).get("galileo_object_lifecycle", {})
if lifecycle.get("status") != "automated_create_or_get":
    raise SystemExit("coverage report must include automated Galileo object lifecycle coverage")
full_matrix = coverage.get("coverage", {}).get("galileo_full_feature_coverage_matrix", {})
if full_matrix.get("status") != "rendered" or full_matrix.get("domain_count", 0) < 45:
    raise SystemExit("coverage report must include the full Galileo feature coverage matrix")
matrix = json.loads(Path(sys.argv[1]).with_name("lifecycle").joinpath("product-coverage-matrix.json").read_text(encoding="utf-8"))
surfaces = {item.get("surface") for item in matrix}
for surface in (
    "Projects",
    "API keys, auth, users, groups, and RBAC",
    "REST API base URL, custom deployments, and healthcheck",
    "SSO, OIDC, SAML, and enterprise identity",
    "Log streams",
    "Datasets",
    "Dataset versions, sharing, prompt datasets, and synthetic extension",
    "Prompts",
    "Experiments",
    "Experiment groups, tags, comparison, search, and metric settings",
    "Evaluate workflow runs",
    "Python and TypeScript SDK parity",
    "Evaluate metrics and scorers",
    "Metric taxonomy, autotune, and use-case categories",
    "Custom scorers and scorer validation",
    "Luna and model/provider integrations",
    "Luna-2 fine-tuning and metric evaluation workflows",
    "Provider integrations, model aliases, costs, and pricing",
    "Observe traces, sessions, spans",
    "Tags, metadata, run labels, and filter hygiene",
    "Enterprise data retention, TTL, redaction, and privacy controls",
    "Trace query, columns, recompute, update, and delete maintenance",
    "Agent Graph, Logs UI, Messages UI, and console debugging views",
    "Distributed tracing and multi-service propagation",
    "Multimodal observability",
    "OpenTelemetry and OpenInference",
    "Third-party framework integrations and wrappers",
    "MCP tool-call logging and tool spans",
    "Galileo alerts and notifications",
    "Protect stages and invocation",
    "Protect rules, rulesets, actions, notifications, and LangChain/LangGraph runtime",
    "Agent Control targets",
    "Annotation templates, ratings, and queues",
    "Feedback templates and ratings",
    "Trends dashboards, widgets, sections, Signals, and insights",
    "Run insights, health scores, and token usage",
    "Jobs, async tasks, validation status, and progress polling",
    "Search, runs, traces SDK utilities, decorators, handlers, and wrappers",
    "Enterprise deployment, system users, and organization jobs",
    "Galileo MCP Server and IDE developer tooling",
    "Playgrounds, sample projects, unit tests, and CI experiments",
    "Cookbooks, use-case guides, and starter examples",
    "Error catalog, troubleshooting, and support diagnostics",
    "Release notes and version compatibility",
    "Splunk destinations",
):
    if surface not in surfaces:
        raise SystemExit(f"product coverage matrix missing {surface}")
request = json.loads(Path(sys.argv[1]).with_name("splunk-platform").joinpath("export-records-request.json").read_text(encoding="utf-8"))
if request.get("export_format") != "jsonl":
    raise SystemExit("export_records request must default to jsonl")
for key in ("root_type", "redact", "log_stream_id", "experiment_id", "metrics_testing_id"):
    if key not in request:
        raise SystemExit(f"export_records request missing {key}")
PY

if grep -RIl . "${OUTPUT_DIR}" | xargs grep -E -- 'Authorization:[[:space:]]*(Splunk|Bearer)[[:space:]]+[A-Za-z0-9._=-]{12,}' >/dev/null 2>&1; then
    log "ERROR: Rendered output appears to contain a concrete authorization secret."
    exit 1
fi

log "Galileo Platform Setup rendered assets passed static validation."

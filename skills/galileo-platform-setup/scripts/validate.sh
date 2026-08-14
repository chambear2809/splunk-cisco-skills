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
check_file "${OUTPUT_DIR}/readiness/galileo-2026-07-07-readiness.json"
check_exec "${OUTPUT_DIR}/readiness/healthcheck.sh"
check_file "${OUTPUT_DIR}/lifecycle/object-lifecycle-manifest.example.json"
check_file "${OUTPUT_DIR}/lifecycle/luna-scorer-map.example.json"
check_file "${OUTPUT_DIR}/lifecycle/product-coverage-matrix.json"
check_file "${OUTPUT_DIR}/lifecycle/product-coverage-matrix.md"
check_file "${OUTPUT_DIR}/runtime/python-opentelemetry-env.sh"
check_file "${OUTPUT_DIR}/runtime/python-galileo-protect.py"
check_file "${OUTPUT_DIR}/evaluate/evaluate-assets.yaml"
check_file "${OUTPUT_DIR}/evaluate/ai-assistant-handoff.md"
check_file "${OUTPUT_DIR}/evaluate/experiment-groups-and-scaling-handoff.md"
check_file "${OUTPUT_DIR}/evaluate/multimodal-metrics-handoff.yaml"
check_file "${OUTPUT_DIR}/alerts/generic-webhook-handoff.md"
check_file "${OUTPUT_DIR}/alerts/galileo-alert-webhook-payload.example.json"
check_file "${OUTPUT_DIR}/multimodal/multimodal-observability.md"
check_file "${OUTPUT_DIR}/multimodal/multimodal-intake.example.json"
check_file "${OUTPUT_DIR}/controls/agent-observability-controls.md"
check_file "${OUTPUT_DIR}/controls/control-intake.example.json"
check_file "${OUTPUT_DIR}/controls/splunk-search-examples.spl"
check_file "${OUTPUT_DIR}/splunk-platform/hec-event-sample.json"
check_file "${OUTPUT_DIR}/splunk-platform/export-records-request.json"
check_file "${OUTPUT_DIR}/splunk-platform/galileo-alert-hec-event.example.json"
check_file "${OUTPUT_DIR}/splunk-platform/galileo-alert-webhook-search-examples.spl"
check_file "${OUTPUT_DIR}/splunk-platform/multimodal-search-examples.spl"
check_file "${OUTPUT_DIR}/otel/collector-galileo-fanout.yaml"
check_file "${OUTPUT_DIR}/dashboards/galileo-global-dashboard-handoff.md"
check_exec "${OUTPUT_DIR}/scripts/galileo_alert_webhook_relay.py"
check_exec "${OUTPUT_DIR}/scripts/apply-readiness.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-object-lifecycle.sh"
check_exec "${OUTPUT_DIR}/scripts/cleanup-object-lifecycle.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-luna-scorers.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-observe-export.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-observe-runtime.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-protect-runtime.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-evaluate-assets.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-multimodal-assets.sh"
check_exec "${OUTPUT_DIR}/scripts/apply-observability-controls.sh"
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
    "luna-scorers": "galileo-platform-setup",
    "observe-export": "galileo-platform-setup",
    "observe-runtime": "galileo-platform-setup",
    "protect-runtime": "galileo-platform-setup",
    "evaluate-assets": "galileo-platform-setup",
    "multimodal-assets": "galileo-platform-setup",
    "observability-controls": "galileo-platform-setup",
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
luna = coverage.get("coverage", {}).get("galileo_luna_scorer_settings", {})
if luna.get("status") != "automated_inventory_and_metric_settings_patch":
    raise SystemExit("coverage report must include automated Galileo Luna scorer settings coverage")
controls = coverage.get("coverage", {}).get("galileo_agent_observability_controls", {})
if controls.get("status") != "rendered_handoff":
    raise SystemExit("coverage report must include Galileo Agent Observability Controls handoff coverage")
multimodal = coverage.get("coverage", {}).get("galileo_multimodal_observability", {})
if multimodal.get("status") != "rendered_handoff":
    raise SystemExit("coverage report must include Galileo multimodal observability handoff coverage")
full_matrix = coverage.get("coverage", {}).get("galileo_full_feature_coverage_matrix", {})
if full_matrix.get("status") != "rendered" or full_matrix.get("domain_count", 0) < 57:
    raise SystemExit("coverage report must include the full Galileo feature coverage matrix")
release = coverage.get("coverage", {}).get("galileo_release_2026_07_07", {})
expected_release_features = {
    "ai_assistant_beta_readiness",
    "global_dashboard_console_evidence",
    "generic_alert_webhook_v1_relay_to_splunk_hec",
    "experiment_group_create_and_run_assignment",
    "large_dataset_batched_processing_readiness_handoff",
}
if release.get("status") != "automated_where_documented_plus_guarded_console_handoffs":
    raise SystemExit("coverage report must include Galileo 2026-07-07 release coverage")
if set(release.get("covers") or []) != expected_release_features:
    raise SystemExit("Galileo 2026-07-07 release feature coverage is incomplete")
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
    "Dataset query, preview, content mutation, and bulk maintenance",
    "Prompts",
    "Prompt templates, rendering, and version utilities",
    "Experiments",
    "Experiment groups, tags, comparison, search, and metric settings",
    "Large-dataset Playground and experiment batched processing",
    "Experiment columns, metrics APIs, and paginated search",
    "Evaluate experiments and agentic workflow runs",
    "Python and TypeScript SDK parity",
    "Evaluate metrics and scorers",
    "Metric taxonomy, autotune, and use-case categories",
    "Custom scorers and scorer validation",
    "Scorer governance, health scores, and restore flows",
    "Luna and model/provider integrations",
    "Luna-2 fine-tuning and metric evaluation workflows",
    "Luna Studio UI and SDK training lifecycle",
    "Provider integrations, model aliases, costs, and pricing",
    "Provider integration selection, status, and Databricks helpers",
    "Observe traces, sessions, spans",
    "Tags, metadata, run labels, and filter hygiene",
    "Enterprise data retention, TTL, redaction, and privacy controls",
    "Trace query, columns, recompute, update, and delete maintenance",
    "Trace metrics, counts, partial queries, and live logging APIs",
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
    "Agent Observability Controls dashboard and control spans",
    "Annotation templates, ratings, and queues",
    "Feedback templates and ratings",
    "Trends dashboards, widgets, sections, Signals, and insights",
    "Global dashboards across projects and Log streams",
    "AI Assistant (beta) investigations",
    "Run insights, health scores, and token usage",
    "Jobs, async tasks, validation status, and progress polling",
    "Search, runs, traces SDK utilities, decorators, handlers, and wrappers",
    "Enterprise access control, system users, and organization jobs",
    "Galileo MCP Server and IDE developer tooling",
    "Playgrounds, sample projects, unit tests, and CI experiments",
    "Cookbooks, use-case guides, and starter examples",
    "Error catalog, troubleshooting, and support diagnostics",
    "Release notes and version compatibility",
    "Splunk destinations",
):
    if surface not in surfaces:
        raise SystemExit(f"product coverage matrix missing {surface}")
release_readiness = json.loads(
    Path(sys.argv[1]).with_name("readiness").joinpath("galileo-2026-07-07-readiness.json").read_text(encoding="utf-8")
)
if release_readiness.get("release_date") != "2026-07-07":
    raise SystemExit("latest Galileo release readiness date is stale")
if set((release_readiness.get("features") or {})) != {
    "ai_assistant_beta",
    "global_dashboards",
    "generic_alert_webhooks",
    "experiment_groups",
    "large_dataset_batched_processing",
}:
    raise SystemExit("latest Galileo release readiness features are incomplete")
manifest = json.loads(
    Path(sys.argv[1]).with_name("lifecycle").joinpath("object-lifecycle-manifest.example.json").read_text(encoding="utf-8")
)
experiment = (manifest.get("experiments") or [{}])[0]
if "experiment_group" not in experiment or "experiment_group_id" not in experiment:
    raise SystemExit("object lifecycle manifest must support experiment groups")
ownership = manifest.get("ownership_cleanup") or {}
if ownership.get("exact_id_only") is not True:
    raise SystemExit("object lifecycle manifest must require exact-ID cleanup")
if ownership.get("dataset_delete_requires_project_association") is not True:
    raise SystemExit("object lifecycle dataset cleanup must validate project association")
if ownership.get("metric_enablement") != "newly_created_owned_log_stream_only":
    raise SystemExit("object lifecycle must not replace metrics on pre-existing Log streams")
webhook = json.loads(
    Path(sys.argv[1]).with_name("alerts").joinpath("galileo-alert-webhook-payload.example.json").read_text(encoding="utf-8")
)
for key in ("version", "event", "event_id", "timestamp", "alert", "scope", "conditions", "dedup_key", "deep_link", "metadata"):
    if key not in webhook:
        raise SystemExit(f"Galileo webhook payload example missing {key}")
if webhook.get("version") != "1.0":
    raise SystemExit("Galileo webhook payload example must use version 1.0")
request = json.loads(Path(sys.argv[1]).with_name("splunk-platform").joinpath("export-records-request.json").read_text(encoding="utf-8"))
if request.get("export_format") not in {"csv", "jsonl", "jsonl_flat"}:
    raise SystemExit("export_records request has an unsupported export_format")
if request.get("export_computed_metrics_only") and request.get("export_format") == "jsonl_flat":
    raise SystemExit("export_records computed-metrics-only is incompatible with jsonl_flat")
for key in (
    "root_type",
    "redact",
    "export_computed_metrics_only",
    "include_code_metric_metadata",
    "log_stream_id",
    "experiment_id",
    "metrics_testing_id",
):
    if key not in request:
        raise SystemExit(f"export_records request missing {key}")
PY

python3 -m py_compile "${OUTPUT_DIR}/scripts/galileo_alert_webhook_relay.py"
bash -n "${OUTPUT_DIR}/scripts/cleanup-object-lifecycle.sh"

if grep -RIl . "${OUTPUT_DIR}" | xargs grep -E -- 'Authorization:[[:space:]]*(Splunk|Bearer)[[:space:]]+[A-Za-z0-9._=-]{12,}' >/dev/null 2>&1; then
    log "ERROR: Rendered output appears to contain a concrete authorization secret."
    exit 1
fi

log "Galileo Platform Setup rendered assets passed static validation."

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
check_file "${OUTPUT_DIR}/readiness/galileo-2026-08-07-readiness.json"
check_file "${OUTPUT_DIR}/readiness/galileo-2026-08-07-handoff.md"
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
from datetime import date
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
coverage = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
readiness_report = json.loads(
    Path(sys.argv[1])
    .with_name("readiness")
    .joinpath("readiness-report.json")
    .read_text(encoding="utf-8")
)
plan_gate = plan.get("apply_gate") or {}
readiness_gate = readiness_report.get("apply_gate") or {}
gate_fields = {
    "tenant_onboarding_date",
    "documentation_epoch",
    "boundary",
    "apply_supported",
    "reason",
}
if not gate_fields.issubset(plan_gate):
    raise SystemExit("apply plan is missing documentation epoch gate fields")
if not gate_fields.issubset(readiness_gate):
    raise SystemExit("readiness report is missing documentation epoch gate fields")
for field in gate_fields:
    if plan_gate[field] != readiness_gate[field]:
        raise SystemExit(
            f"documentation epoch gate mismatch for {field}: "
            f"plan={plan_gate[field]!r}, readiness={readiness_gate[field]!r}"
        )
boundary = date(2026, 8, 7)
if plan_gate["boundary"] != boundary.isoformat():
    raise SystemExit("documentation epoch boundary is stale")
onboarding_raw = plan_gate["tenant_onboarding_date"]
if onboarding_raw:
    try:
        onboarding_date = date.fromisoformat(onboarding_raw)
    except (TypeError, ValueError) as exc:
        raise SystemExit("tenant onboarding date in apply gate is invalid") from exc
    if onboarding_date.isoformat() != onboarding_raw:
        raise SystemExit("tenant onboarding date in apply gate is not canonical YYYY-MM-DD")
    if onboarding_date < boundary:
        expected_epoch = "legacy_galileo_pre_2026_08_07"
        expected_supported = True
    elif onboarding_date == boundary:
        expected_epoch = "boundary_2026_08_07_unverified"
        expected_supported = False
    else:
        expected_epoch = "splunk_agent_observability_post_2026_08_07"
        expected_supported = False
else:
    expected_epoch = "unconfirmed"
    expected_supported = False
if plan_gate["documentation_epoch"] != expected_epoch:
    raise SystemExit("documentation epoch does not match tenant onboarding date")
if plan_gate["apply_supported"] is not expected_supported:
    raise SystemExit("apply support does not match documentation epoch")
expected_blocked = [] if expected_supported else list(plan.get("selected_sections") or [])
if plan_gate.get("blocked_sections") != expected_blocked:
    raise SystemExit("apply plan blocked sections do not match documentation epoch gate")
expected_lifecycle_status = (
    "rendered_apply_ready"
    if expected_supported
    else "rendered_only_documentation_epoch_blocked"
)
if readiness_report.get("object_lifecycle_readiness", {}).get("status") != expected_lifecycle_status:
    raise SystemExit("readiness object lifecycle status does not match apply gate")
scripts_root = Path(sys.argv[1]).with_name("scripts")
guard_marker = "ERROR: Operational apply is blocked for documentation epoch"
expected_guard = f"{guard_marker} {expected_epoch}: {plan_gate['reason']}"
apply_wrappers = sorted(scripts_root.glob("apply-*.sh"))
if not apply_wrappers:
    raise SystemExit("rendered packet has no apply wrappers")


def active_guard_position(prefix: str, exact_message: str | None = None) -> int | None:
    lines = prefix.splitlines()
    for index, line in enumerate(lines[:-1]):
        if (
            index < 12
            and line.startswith("echo ")
            and guard_marker in line
            and (exact_message is None or exact_message in line)
            and line.endswith(" >&2")
            and lines[index + 1] == "exit 2"
        ):
            return index
    return None


for wrapper in apply_wrappers:
    prefix = wrapper.read_text(encoding="utf-8")[:2048]
    guard_position = active_guard_position(prefix)
    expected_guard_position = active_guard_position(prefix, expected_guard)
    if expected_supported:
        if guard_position is not None:
            raise SystemExit(f"legacy apply wrapper has an unexpected epoch guard: {wrapper.name}")
    elif expected_guard_position is None:
        raise SystemExit(
            f"blocked documentation epoch apply wrapper is missing its guard: {wrapper.name}"
        )
cleanup_wrapper = scripts_root / "cleanup-object-lifecycle.sh"
if active_guard_position(cleanup_wrapper.read_text(encoding="utf-8")[:2048]) is not None:
    raise SystemExit("exact-ID cleanup wrapper must remain available for recovery")
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
current_release = coverage.get("coverage", {}).get("galileo_release_2026_08_07", {})
expected_current_release_features = {
    "splunk_agent_observability_naming_and_docs_epoch",
    "annotation_queues_ga",
    "ai_assistant_expansion",
    "ai_assisted_custom_code_metrics",
    "cost_and_billing_surfaces",
    "trace_count_alerts",
    "multimodal_out_of_the_box_metrics",
    "hosted_models_and_console_theme",
}
if current_release.get("status") != "guarded_console_api_and_validation_handoffs":
    raise SystemExit("coverage report must include Galileo 2026-08-07 release coverage")
if set(current_release.get("covers") or []) != expected_current_release_features:
    raise SystemExit("Galileo 2026-08-07 release feature coverage is incomplete")
if plan.get("paths", {}).get("latest_release") != "readiness/galileo-2026-08-07-readiness.json":
    raise SystemExit("apply plan latest Galileo release pointer is stale")
matrix = json.loads(Path(sys.argv[1]).with_name("lifecycle").joinpath("product-coverage-matrix.json").read_text(encoding="utf-8"))
output_root = Path(sys.argv[1]).parent
for item in matrix:
    for asset in item.get("rendered_assets") or []:
        asset_path = Path(asset)
        if asset_path.is_absolute() or ".." in asset_path.parts:
            raise SystemExit(f"product coverage matrix has unsafe rendered asset path: {asset}")
        if not (output_root / asset_path).exists():
            raise SystemExit(
                f"product coverage matrix references missing rendered asset: {asset}"
            )
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
historical_release_readiness = json.loads(
    Path(sys.argv[1]).with_name("readiness").joinpath("galileo-2026-07-07-readiness.json").read_text(encoding="utf-8")
)
if historical_release_readiness.get("release_date") != "2026-07-07":
    raise SystemExit("historical Galileo release readiness date is invalid")
if set((historical_release_readiness.get("features") or {})) != {
    "ai_assistant_beta",
    "global_dashboards",
    "generic_alert_webhooks",
    "experiment_groups",
    "large_dataset_batched_processing",
}:
    raise SystemExit("historical Galileo release readiness features are incomplete")
release_readiness = json.loads(
    Path(sys.argv[1]).with_name("readiness").joinpath("galileo-2026-08-07-readiness.json").read_text(encoding="utf-8")
)
if release_readiness.get("release_date") != "2026-08-07":
    raise SystemExit("latest Galileo release readiness date is stale")
if release_readiness.get("reviewed_at") != "2026-08-20":
    raise SystemExit("latest Galileo release readiness review date is stale")
if set((release_readiness.get("features") or {})) != expected_current_release_features:
    raise SystemExit("latest Galileo release readiness features are incomplete")
naming = release_readiness["features"]["splunk_agent_observability_naming_and_docs_epoch"]
if naming.get("boundary", {}).get("on_boundary_date") != "verify_tenant_linked_documentation":
    raise SystemExit("Galileo documentation epoch boundary must fail closed")
for field in (
    "tenant_onboarding_date",
    "documentation_epoch",
    "apply_supported",
    "reason",
):
    if naming.get(field) != plan_gate[field]:
        raise SystemExit(
            f"latest Galileo release documentation epoch mismatch for {field}"
        )
multimodal_release = release_readiness["features"]["multimodal_out_of_the_box_metrics"]
expected_multimodal_metrics = {
    "Action Completion",
    "Context Adherence",
    "Correctness",
    "Ground Truth Adherence",
    "Reasoning Coherence",
    "Input Toxicity",
    "Output Toxicity",
    "User Intent Change",
}
if set(multimodal_release.get("metrics") or []) != expected_multimodal_metrics:
    raise SystemExit("latest Galileo release must track all eight multimodal metric variants")
if multimodal_release.get("modalities") != ["text", "image_or_pdf", "audio"]:
    raise SystemExit("latest Galileo multimodal metric variants have stale modalities")
if release_readiness["features"]["trace_count_alerts"].get("system_metric") != "Trace Count":
    raise SystemExit("latest Galileo release must track Trace Count alert coverage")
models = release_readiness["features"]["hosted_models_and_console_theme"]
if models.get("hosted_models") != ["GPT 5.6 Sol", "GPT 5.6 Terra", "GPT 5.6 Luna"]:
    raise SystemExit("latest Galileo hosted-model readiness is stale")
if models.get("console_themes") != ["light", "dark", "system"]:
    raise SystemExit("latest Galileo console-theme readiness is stale")
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

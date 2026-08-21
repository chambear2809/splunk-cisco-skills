"""Audit Galileo MCP product-boundary coverage against Galileo's docs index."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_DOCS_INDEX_URL = "https://docs.galileo.ai/llms-full.txt"
DEFAULT_NEW_ERA_DOCS_INDEX_URL = (
    "https://agent-observability-docs.splunk.com/llms-full.txt"
)
LATEST_REVIEWED_RELEASE = "2026-08-07"
RELEASE_LABEL_RE = re.compile(r'<Update\s+label=["\'](\d{4}-\d{2}-\d{2})["\']')

PRODUCT_RULES: list[dict[str, Any]] = [
    {
        "id": "mcp_client_setup",
        "docs_markers": ["Galileo MCP Server"],
        "matrix_markers": ["MCP client setup", "Tool inventory and drift"],
    },
    {
        "id": "datasets",
        "docs_markers": ["api-reference/datasets", "Datasets"],
        "matrix_markers": ["Dataset creation/status"],
    },
    {
        "id": "dataset_versioning_collaboration",
        "docs_markers": [
            "Update Dataset Content",
            "Query Dataset Versions",
            "List Group Dataset Collaborators",
            "Download Dataset",
        ],
        "matrix_markers": [
            "Dataset versioning, content update, download, sharing, and collaborators"
        ],
    },
    {
        "id": "prompts_and_experiments",
        "docs_markers": ["api-reference/experiment", "Prompts"],
        "matrix_markers": ["Prompt template creation", "Experiment setup"],
    },
    {
        "id": "ai_assistant_beta",
        "docs_markers": ["AI Assistant (Beta)", "concepts/ai-assistant"],
        "matrix_markers": [
            "AI Assistant beta, evidence-linked investigation, criticality, and organization-wide debugging"
        ],
    },
    {
        "id": "splunk_agent_observability_docs_epoch",
        "docs_markers": [
            "Galileo is now Splunk Agent Observability",
            "agent-observability-docs.splunk.com",
        ],
        "matrix_markers": [
            "Splunk Agent Observability naming and pre-/post-August 7 documentation epoch"
        ],
    },
    {
        "id": "annotation_queues_ga",
        "docs_markers": [
            "Annotation Queues now generally available",
            "Query Annotation Queues",
        ],
        "matrix_markers": [
            "Annotation Queues GA, templates, users, records, and human-feedback operations"
        ],
    },
    {
        "id": "ai_metric_authoring_and_billing",
        "docs_markers": [
            "Generate custom code-based metrics with AI",
            "View billing usage for your organization",
        ],
        "matrix_markers": [
            "AI-assisted custom-code metrics, organization billing usage, model pricing, and integration costs"
        ],
    },
    {
        "id": "trace_count_and_multimodal_metrics",
        "docs_markers": [
            "Log stream alerts on trace count",
            "Multimodal out-of-the-box evaluation metrics",
        ],
        "matrix_markers": [
            "Trace Count alerts and multimodal out-of-the-box evaluation metrics"
        ],
    },
    {
        "id": "hosted_models_and_console_theme",
        "docs_markers": [
            "GPT 5.6 Sol, Terra, and Luna",
            "Dark mode now generally available",
        ],
        "matrix_markers": [
            "Hosted-model availability and light, dark, or system console themes"
        ],
    },
    {
        "id": "global_dashboards",
        "docs_markers": ["Global dashboards", "Chart across projects"],
        "matrix_markers": ["Global dashboards across projects and log streams"],
    },
    {
        "id": "generic_alert_webhooks",
        "docs_markers": [
            "Generic webhook notifications",
            "alert.triggered",
            "dedup_key",
        ],
        "matrix_markers": [
            "Generic alert webhooks, payload v1.0, authentication, testing, and deduplication"
        ],
    },
    {
        "id": "experiment_groups_playgrounds_ci",
        "docs_markers": [
            "Experiment Groups",
            "Compare Experiments",
            "Run Experiments in Playgrounds",
            "Run Experiments in Unit Tests",
        ],
        "matrix_markers": [
            "Experiment groups (Python SDK >=2.2.0), comparison, ranking, playground runs, and unit-test gates"
        ],
    },
    {
        "id": "large_dataset_batched_experiments",
        "docs_markers": [
            "Scaling improvements in Playground and experiments",
            "thousands of rows",
        ],
        "matrix_markers": [
            "Large-dataset batched Playground and experiment metric processing"
        ],
    },
    {
        "id": "projects_auth_rbac_sso",
        "docs_markers": [
            "api-reference/projects",
            "api-reference/groups",
            "api-reference/users",
            "api-reference/api_keys",
            "Access Control",
            "SSO Integration",
        ],
        "matrix_markers": ["Projects, project sharing, users, groups, RBAC, SSO, and API keys"],
    },
    {
        "id": "log_streams",
        "docs_markers": ["api-reference/log_stream", "logstream-insights"],
        "matrix_markers": ["Log stream signals/insights"],
    },
    {
        "id": "observe_traces_sessions_spans",
        "docs_markers": [
            "api-reference/trace",
            "Sessions Overview",
            "OpenTelemetry",
            "OpenInference",
        ],
        "matrix_markers": ["Observe traces, sessions, spans, exports, metrics"],
    },
    {
        "id": "evaluate_scorers_luna_annotations_feedback",
        "docs_markers": [
            "api-reference/data/create-luna-scorer",
            "api-reference/annotation",
            "api-reference/feedback",
            "Luna-2",
            "scorer",
        ],
        "matrix_markers": [
            "Evaluate metrics, custom scorers, Luna-2, annotations, and feedback"
        ],
    },
    {
        "id": "luna_studio_workflows",
        "docs_markers": [
            "luna-studio",
            "Luna Studio SDK",
            "full session-level Luna metrics",
            "LLM spans with tools",
        ],
        "matrix_markers": [
            "Luna Studio tutorials, metric training datasets, and scorer development workflows"
        ],
    },
    {
        "id": "sql_preset_recompute_metrics",
        "docs_markers": [
            "Text-to-SQL Metrics",
            "SQL metrics",
            "Preset Metrics Examples",
            "Metric recomputation",
        ],
        "matrix_markers": [
            "Text-to-SQL metrics, preset metric benchmarks/examples, and metric recomputation"
        ],
    },
    {
        "id": "agentic_metrics_autotune",
        "docs_markers": ["concepts/metrics/agentic", "Autotune", "health score"],
        "matrix_markers": [
            "Agentic metrics, metric settings, scorer health scores, and Autotune"
        ],
    },
    {
        "id": "provider_integrations_costs_models",
        "docs_markers": [
            "api-reference/integrations",
            "Integration Costs",
            "Model Pricing",
            "Model Costs",
            "Model Integrations",
        ],
        "matrix_markers": ["Provider integrations, model aliases, model pricing, and costs"],
    },
    {
        "id": "trends_org_jobs",
        "docs_markers": ["trends_dashboard", "organization-jobs", "run_insights_settings"],
        "matrix_markers": ["Trends dashboards, health scores, and organization jobs"],
    },
    {
        "id": "agent_graph_console_analytics",
        "docs_markers": [
            "Agent Graph",
            "traffic analytics",
            "Aggregate Agent Graph View",
            "Search Nodes in Agent Graph",
        ],
        "matrix_markers": [
            "Agent Graph traffic analytics, aggregate graph, search, and metric overlays"
        ],
    },
    {
        "id": "saved_views_filters",
        "docs_markers": [
            "Saved Views",
            "views can be shared",
            "shared with the project",
            "private views",
        ],
        "matrix_markers": [
            "Log stream and experiment saved views, table columns, and shared/private filters"
        ],
        "optional_docs": True,
    },
    {
        "id": "protect",
        "docs_markers": ["api-reference/protect", "Protect"],
        "matrix_markers": ["Protect stages, rulesets, notifications, and invoke runtime"],
    },
    {
        "id": "framework_integrations",
        "docs_markers": [
            "A2A",
            "CrewAI",
            "Google ADK",
            "Microsoft Agent Framework",
            "Pydantic AI",
            "Strands Agents",
            "Vercel AI SDK",
        ],
        "matrix_markers": ["Other framework integrations"],
    },
    {
        "id": "python_typescript_sdk_reference",
        "docs_markers": [
            "sdk-api/python",
            "sdk-api/typescript",
            "Python SDK",
            "TypeScript",
        ],
        "matrix_markers": [
            "Python/TypeScript SDK reference, wrappers, decorators, async logging, and release compatibility"
        ],
    },
    {
        "id": "multimodal_distributed_tracing_tags_sdk",
        "docs_markers": [
            "Multimodal Observability",
            "Distributed Tracing",
            "Tags and Metadata",
        ],
        "matrix_markers": [
            "Multimodal logging, distributed tracing, tags, and metadata"
        ],
    },
    {
        "id": "samples_playgrounds_ci",
        "docs_markers": [
            "Sample Projects",
            "Playgrounds",
            "Run Experiments in Unit Tests",
            "Cookbooks",
        ],
        "matrix_markers": [
            "Cookbooks, sample projects, playgrounds, unit tests, and CI experiment gates"
        ],
    },
    {
        "id": "mcp_tool_call_logging",
        "docs_markers": ["Log MCP Server Tool Calls", "add_tool_span"],
        "matrix_markers": ["MCP tool-call logging"],
        "optional_docs": True,
    },
    {
        "id": "agent_control",
        "docs_markers": ["Agent Control"],
        "matrix_markers": ["Agent Control / Cursor hooks"],
    },
    {
        "id": "enterprise_custom_release",
        "docs_markers": [
            "enterprise",
            "retention",
            "custom deployment",
            "Release Notes",
            "Troubleshooting",
        ],
        "matrix_markers": [
            "Enterprise retention, TTL, privacy, custom deployments, and release checks"
        ],
        "optional_docs": True,
    },
]


FALLBACK_DOCS_INDEX = "\n".join(
    [
        *(
            marker
            for rule in PRODUCT_RULES
            for marker in rule["docs_markers"]
            if not rule.get("optional_docs")
        ),
        f'<Update label="{LATEST_REVIEWED_RELEASE}">',
    ]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix",
        default="skills/galileo-mcp-server-setup/references/product-gap-matrix.md",
        help="Product gap matrix markdown file.",
    )
    parser.add_argument(
        "--docs-index-url",
        "--legacy-docs-index-url",
        dest="docs_index_url",
        default=DEFAULT_DOCS_INDEX_URL,
        help="Pre-August 7 Galileo llms-full.txt URL.",
    )
    parser.add_argument(
        "--docs-index-file",
        "--legacy-docs-index-file",
        dest="docs_index_file",
        default="",
        help=(
            "Local pre-August 7 docs index. For backward-compatible fixtures, "
            "this file is also used for the new-era index unless "
            "--new-era-docs-index-file is set."
        ),
    )
    parser.add_argument(
        "--new-era-docs-index-url",
        default=DEFAULT_NEW_ERA_DOCS_INDEX_URL,
        help="Post-August 7 Splunk Agent Observability llms-full.txt URL.",
    )
    parser.add_argument(
        "--new-era-docs-index-file",
        default="",
        help="Local post-August 7 docs index.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use embedded docs markers instead of fetching either docs index.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def read_docs_index(args: argparse.Namespace) -> tuple[str, str]:
    """Read the legacy index retained for callers of the original helper."""

    if args.docs_index_file:
        path = Path(args.docs_index_file).expanduser()
        return path.read_text(encoding="utf-8"), str(path)
    if args.offline:
        return FALLBACK_DOCS_INDEX, "embedded-offline-markers"
    request = urllib.request.Request(
        args.docs_index_url,
        headers={"User-Agent": "galileo-mcp-server-setup-product-audit/1"},
    )
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        return response.read().decode("utf-8", "replace"), args.docs_index_url


def _read_index(*, path_value: str, url: str, offline: bool, timeout: float) -> tuple[str, str]:
    if path_value:
        path = Path(path_value).expanduser()
        return path.read_text(encoding="utf-8"), str(path)
    if offline:
        return FALLBACK_DOCS_INDEX, "embedded-offline-markers"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "galileo-mcp-server-setup-product-audit/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace"), url


def read_docs_indices(args: argparse.Namespace) -> dict[str, tuple[str, str]]:
    """Read the legacy and post-rename docs indices as distinct evidence sources."""

    legacy_file = getattr(args, "docs_index_file", "")
    new_era_file = getattr(args, "new_era_docs_index_file", "")
    if legacy_file and not new_era_file:
        # Preserve deterministic behavior for existing single-fixture callers.
        new_era_file = legacy_file

    return {
        "legacy": _read_index(
            path_value=legacy_file,
            url=getattr(args, "docs_index_url", DEFAULT_DOCS_INDEX_URL),
            offline=args.offline,
            timeout=args.timeout,
        ),
        "new_era": _read_index(
            path_value=new_era_file,
            url=getattr(
                args,
                "new_era_docs_index_url",
                DEFAULT_NEW_ERA_DOCS_INDEX_URL,
            ),
            offline=args.offline,
            timeout=args.timeout,
        ),
    }


def missing_coverage(
    docs_index: str,
    matrix: str,
    *,
    check_release: bool = True,
) -> list[dict[str, Any]]:
    docs_lower = docs_index.lower()
    matrix_lower = matrix.lower()
    missing: list[dict[str, Any]] = []
    release_dates = RELEASE_LABEL_RE.findall(docs_index)
    latest_release = max(release_dates, default="")
    if check_release and not release_dates:
        missing.append(
            {
                "id": "release_label_not_found",
                "reason": "release_note_date_markup_not_found",
                "latest_reviewed_release": LATEST_REVIEWED_RELEASE,
            }
        )
    elif check_release and latest_release > LATEST_REVIEWED_RELEASE:
        missing.append(
            {
                "id": "unreviewed_release",
                "reason": "newer_release_note_detected",
                "latest_documented_release": latest_release,
                "latest_reviewed_release": LATEST_REVIEWED_RELEASE,
            }
        )
    for rule in PRODUCT_RULES:
        docs_hits = [
            marker for marker in rule["docs_markers"] if marker.lower() in docs_lower
        ]
        if not docs_hits and not rule.get("optional_docs"):
            missing.append(
                {
                    "id": rule["id"],
                    "reason": "docs_markers_not_found",
                    "expected_docs_markers": rule["docs_markers"],
                }
            )
            continue
        if not docs_hits and rule.get("optional_docs"):
            continue
        absent_matrix = [
            marker for marker in rule["matrix_markers"] if marker.lower() not in matrix_lower
        ]
        if absent_matrix:
            missing.append(
                {
                    "id": rule["id"],
                    "reason": "matrix_markers_not_found",
                    "docs_hits": docs_hits,
                    "missing_matrix_markers": absent_matrix,
                }
            )
    return missing


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    docs_indices = read_docs_indices(args)
    docs_index = "\n".join(index for index, _source in docs_indices.values())
    matrix_path = Path(args.matrix)
    matrix = matrix_path.read_text(encoding="utf-8")
    release_dates = RELEASE_LABEL_RE.findall(docs_index)
    source_evidence = {
        epoch: {
            "source": source,
            "latest_documented_release": max(
                RELEASE_LABEL_RE.findall(index),
                default=None,
            ),
        }
        for epoch, (index, source) in docs_indices.items()
    }
    failures = missing_coverage(docs_index, matrix, check_release=False)
    for epoch, evidence in source_evidence.items():
        if evidence["latest_documented_release"] is None:
            failures.append(
                {
                    "id": "release_label_not_found",
                    "reason": "release_note_date_markup_not_found",
                    "docs_epoch": epoch,
                    "docs_source": evidence["source"],
                    "latest_reviewed_release": LATEST_REVIEWED_RELEASE,
                }
            )
    latest_release = max(release_dates, default="")
    if latest_release > LATEST_REVIEWED_RELEASE:
        failures.append(
            {
                "id": "unreviewed_release",
                "reason": "newer_release_note_detected",
                "latest_documented_release": latest_release,
                "latest_reviewed_release": LATEST_REVIEWED_RELEASE,
            }
        )
    return {
        # Retain the original field for JSON consumers while exposing both epochs.
        "docs_source": source_evidence["legacy"]["source"],
        "docs_sources": source_evidence,
        "matrix": str(matrix_path),
        "rules_checked": len(PRODUCT_RULES),
        "latest_documented_release": max(release_dates, default=None),
        "latest_reviewed_release": LATEST_REVIEWED_RELEASE,
        "missing_coverage": failures,
        "ok": not failures,
    }


def main() -> int:
    args = parse_args()
    try:
        report = build_report(args)
    except Exception as exc:  # noqa: BLE001 - CLI should produce concise diagnostics.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["ok"]:
        print(
            "Galileo product coverage audit passed "
            f"({report['rules_checked']} rules, source={report['docs_source']})."
        )
    else:
        print("ERROR: Galileo product coverage gaps detected:", file=sys.stderr)
        for item in report["missing_coverage"]:
            print(f"  - {item['id']}: {item['reason']}", file=sys.stderr)
            for marker in item.get("missing_matrix_markers", []):
                print(f"    missing matrix marker: {marker}", file=sys.stderr)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

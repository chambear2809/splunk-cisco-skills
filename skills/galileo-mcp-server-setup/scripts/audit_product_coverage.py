"""Audit Galileo MCP product-boundary coverage against Galileo's docs index."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_DOCS_INDEX_URL = "https://docs.galileo.ai/llms-full.txt"

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
        "id": "experiment_groups_playgrounds_ci",
        "docs_markers": [
            "Experiment Groups",
            "Compare Experiments",
            "Run Experiments in Playgrounds",
            "Run Experiments in Unit Tests",
        ],
        "matrix_markers": [
            "Experiment groups, comparison, ranking, playground runs, and unit-test gates"
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
    marker
    for rule in PRODUCT_RULES
    for marker in rule["docs_markers"]
    if not rule.get("optional_docs")
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix",
        default="skills/galileo-mcp-server-setup/references/product-gap-matrix.md",
        help="Product gap matrix markdown file.",
    )
    parser.add_argument("--docs-index-url", default=DEFAULT_DOCS_INDEX_URL)
    parser.add_argument("--docs-index-file", default="")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use embedded docs markers instead of fetching Galileo llms.txt.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def read_docs_index(args: argparse.Namespace) -> tuple[str, str]:
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


def missing_coverage(docs_index: str, matrix: str) -> list[dict[str, Any]]:
    docs_lower = docs_index.lower()
    matrix_lower = matrix.lower()
    missing: list[dict[str, Any]] = []
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
    docs_index, source = read_docs_index(args)
    matrix_path = Path(args.matrix)
    matrix = matrix_path.read_text(encoding="utf-8")
    failures = missing_coverage(docs_index, matrix)
    return {
        "docs_source": source,
        "matrix": str(matrix_path),
        "rules_checked": len(PRODUCT_RULES),
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
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

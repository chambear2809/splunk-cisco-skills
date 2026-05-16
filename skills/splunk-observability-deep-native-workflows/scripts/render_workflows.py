#!/usr/bin/env python3
"""Render deep native Splunk Observability Cloud workflow packets."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode


API_VERSION = "splunk-observability-deep-native-workflows/v1"
MODE = "deep-native-workflows"
ALLOWED_COVERAGE = {
    "api_apply",
    "api_validate",
    "delegated_apply",
    "deeplink",
    "handoff",
    "not_applicable",
}
SURFACES = {
    "modern_dashboard",
    "apm_service_map",
    "apm_service_view",
    "apm_business_transaction",
    "apm_trace_waterfall",
    "apm_tag_spotlight",
    "apm_profiling_flamegraph",
    "rum_session_replay",
    "rum_error_analysis",
    "rum_url_grouping",
    "rum_mobile",
    "db_query_explain_plan",
    "synthetic_waterfall",
    "slo_creation",
    "infrastructure_navigator",
    "kubernetes_navigator",
    "network_explorer",
    "related_content",
    "ai_assistant_investigation",
    "observability_mobile_app",
    "log_observer_chart",
}
DIRECT_SECRET_KEYS = {
    "token",
    "access_token",
    "api_token",
    "sf_token",
    "x_sf_token",
    "o11y_token",
    "rum_token",
    "password",
    "client_secret",
    "secret",
    "session_token",
    "database_password",
}
DOC_SOURCES = {
    "modern_dashboard": "https://help.splunk.com/en/splunk-observability-cloud/create-dashboards-and-charts/create-dashboards/use-modern-dashboards/use-new-dashboard-experience-beta",
    "dashboard_api": "https://dev.splunk.com/observability/reference/api/dashboards/latest",
    "charts_api": "https://dev.splunk.com/observability/reference/api/charts/latest",
    "apm_service_map": "https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/manage-services-spans-and-traces-in-splunk-apm/view-dependencies-among-your-services-in-the-service-map",
    "apm_service_view": "https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/manage-services-spans-and-traces-in-splunk-apm/use-the-service-view",
    "apm_dashboards": "https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/visualize-and-alert-on-your-application-in-splunk-apm/track-service-performance-using-dashboards-in-splunk-apm",
    "apm_business_transaction": "https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/correlate-traces-to-track-business-transactions/configure-business-transaction-rules",
    "apm_metricsets": "https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/analyze-services-with-span-tags-and-metricsets/learn-about-troubleshooting-metricsets/index-span-tags-to-create-troubleshooting-metricsets",
    "apm_profiling": "https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/alwayson-profiling",
    "apm_topology_api": "https://dev.splunk.com/observability/reference/api/apm_service_topology/latest",
    "trace_analyzer": "https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/manage-services-spans-and-traces-in-splunk-apm/search-traces-using-trace-analyzer",
    "trace_waterfall": "https://help.splunk.com/splunk-observability-cloud/monitor-application-performance/manage-services-spans-and-traces-in-splunk-apm/view-and-filter-for-spans-within-a-trace",
    "trace_api": "https://dev.splunk.com/observability/reference/api/trace_id/latest",
    "tag_spotlight": "https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/set-up-splunk-apm/learn-what-you-can-do-with-splunk-apm",
    "rum": "https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring",
    "rum_replay": "https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/replay-user-sessions",
    "rum_session_search": "https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/search-for-user-sessions",
    "rum_errors": "https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/monitor-errors-and-crashes-in-tag-spotlight/monitor-browser-errors",
    "rum_url_grouping": "https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/write-rules-for-url-grouping",
    "rum_mobile_crashes": "https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/monitor-errors-and-crashes-in-tag-spotlight/monitor-mobile-crashes",
    "metric_api": "https://dev.splunk.com/observability/docs/datamodel/metrics_metadata",
    "dbmon": "https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/introduction-to-splunk-database-monitoring",
    "db_queries": "https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/monitor-database-platform-instances/queries",
    "synthetics": "https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/synthetic-monitoring",
    "synthetic_waterfall": "https://help.splunk.com/splunk-observability-cloud/monitor-end-user-experience/synthetic-monitoring/browser-tests-for-webpages/interpret-browser-test-results",
    "synthetics_api": "https://dev.splunk.com/observability/reference/api/synthetics_tests/latest",
    "synthetics_artifacts_api": "https://dev.splunk.com/observability/reference/api/synthetics_artifacts/latest",
    "slo": "https://help.splunk.com/en/splunk-observability-cloud/create-alerts-detectors-and-service-level-objectives/create-service-level-objectives-slos",
    "slo_api": "https://dev.splunk.com/observability/reference/api/slo/latest",
    "infrastructure": "https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/monitor-services-and-hosts",
    "kubernetes": "https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/monitor-services-and-hosts/monitor-kubernetes/monitor-kubernetes-entities",
    "network_explorer": "https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/network-explorer",
    "navigator_dashboards": "https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/use-navigators/customize-dashboards-in-splunk-infrastructure-monitoring-navigators",
    "related_content": "https://help.splunk.com/en/splunk-observability-cloud/data-tools/related-content",
    "ai_assistant": "https://help.splunk.com/en/splunk-observability-cloud/splunk-ai-assistant/ai-assistant-in-observability-cloud",
    "mobile_app": "https://help.splunk.com/en/splunk-observability-cloud/use-splunk-observability-cloud-mobile/view-dashboards-and-alerts",
    "logs_chart": "https://help.splunk.com/en/splunk-observability-cloud/create-dashboards-and-charts/create-dashboards/use-modern-dashboards/use-new-dashboard-experience-beta",
}


class SpecError(ValueError):
    """Raised for invalid workflow specs."""


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise SpecError("YAML specs require PyYAML. Use JSON or install repo dependencies.") from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise SpecError("Spec root must be a mapping/object.")
    return data


def write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path.name


def write_text(path: Path, value: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path.name


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-").lower()
    return slug or "workflow"


def as_list(value: Any, label: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SpecError(f"{label} must be a list.")
    return value


def as_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SpecError(f"{label} must be a mapping/object.")
    return value


def get_any(mapping: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


def reject_inline_secrets(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            normalized = key_text.lower().replace("-", "_")
            allow_file_reference = normalized.endswith("_file") or normalized.endswith("_path")
            direct_secret = normalized in DIRECT_SECRET_KEYS
            direct_secret = direct_secret or (
                normalized.endswith("_token") and not normalized.endswith("_token_file")
            )
            direct_secret = direct_secret or (
                normalized.endswith("_password") and not normalized.endswith("_password_file")
            )
            direct_secret = direct_secret or (
                normalized.endswith("_secret") and not normalized.endswith("_secret_file")
            )
            if direct_secret and not allow_file_reference:
                dotted = ".".join((*path, key_text))
                raise SpecError(f"Inline secret field {dotted!r} is not allowed. Use a file reference.")
            reject_inline_secrets(child, (*path, key_text))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_inline_secrets(child, (*path, str(index)))


def app_base(realm: str) -> str:
    return f"https://app.{realm}.observability.splunkcloud.com"


def api_base(realm: str) -> str:
    return f"https://api.{realm}.observability.splunkcloud.com/v2"


def deeplink(base: str, path: str, params: dict[str, Any] | None = None) -> str:
    cleaned = path if path.startswith("/") else f"/{path}"
    if not params:
        return f"{base}{cleaned}"
    flat = {key: value for key, value in params.items() if value not in (None, "", [])}
    return f"{base}{cleaned}?{urlencode(flat, doseq=True)}"


def concrete_id(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and "{" not in text and "}" not in text and text.lower() != "latest"


def validate_spec(spec: dict[str, Any]) -> None:
    reject_inline_secrets(spec)
    if spec.get("api_version") != API_VERSION:
        raise SpecError(f"api_version must be {API_VERSION!r}.")
    workflows = as_list(spec.get("workflows", []), "workflows")
    if not workflows:
        raise SpecError("workflows must contain at least one item.")
    for index, raw in enumerate(workflows):
        workflow = as_mapping(raw, f"workflows[{index}]")
        name = str(workflow.get("name", "")).strip()
        surface = str(workflow.get("surface", "")).strip()
        if not name:
            raise SpecError(f"workflows[{index}] requires name.")
        if surface not in SURFACES:
            raise SpecError(f"workflow {name!r} uses unsupported surface {surface!r}.")
        if surface == "slo_creation":
            payload = workflow.get("payload")
            if payload is not None and not isinstance(payload, dict):
                raise SpecError(f"SLO workflow {name!r} payload must be an object.")


class RenderContext:
    def __init__(self, output_dir: Path, realm: str) -> None:
        self.output_dir = output_dir
        self.realm = realm
        self.app_base = app_base(realm)
        self.api_base = api_base(realm)
        self.coverage: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.links: list[dict[str, Any]] = []
        self.handoffs: list[dict[str, Any]] = []
        self.rendered_files: set[str] = set()

    def rel(self, *parts: str) -> Path:
        return Path(*parts)

    def write_payload(self, rel_path: Path, payload: Any) -> str:
        write_json(self.output_dir / rel_path, payload)
        rel = rel_path.as_posix()
        self.rendered_files.add(rel)
        return rel

    def add_coverage(
        self,
        surface: str,
        name: str,
        coverage: str,
        reason: str,
        outputs: list[str] | None = None,
        source: str | None = None,
    ) -> None:
        if coverage not in ALLOWED_COVERAGE:
            raise SpecError(f"Invalid coverage {coverage!r}.")
        self.coverage.append(
            {
                "coverage": coverage,
                "name": name,
                "outputs": sorted(outputs or []),
                "reason": reason,
                "source": source,
                "surface": surface,
            }
        )

    def add_link(self, surface: str, name: str, url: str, description: str) -> None:
        self.links.append({"description": description, "name": name, "surface": surface, "url": url})
        self.add_coverage(surface, name, "deeplink", description, ["deeplinks.json"], None)

    def add_action(
        self,
        action: str,
        surface: str,
        name: str,
        coverage: str,
        method: str,
        path: str,
        payload_file: str | None = None,
        service: str = "o11y",
        writes: bool = False,
    ) -> None:
        if coverage not in {"api_apply", "api_validate"}:
            raise SpecError(f"API action {action!r} cannot use coverage {coverage!r}.")
        base = f"{self.api_base}/synthetics" if service == "synthetics" else self.api_base
        item: dict[str, Any] = {
            "action": action,
            "coverage": coverage,
            "method": method,
            "name": name,
            "path": path,
            "service": service,
            "surface": surface,
            "url": f"{base}{path}",
            "writes": writes,
        }
        if payload_file:
            item["payload_file"] = payload_file
        self.actions.append(item)

    def add_handoff(
        self,
        surface: str,
        name: str,
        title: str,
        steps: list[str],
        source: str | None = None,
        coverage: str = "handoff",
    ) -> None:
        self.handoffs.append(
            {
                "coverage": coverage,
                "name": name,
                "source": source,
                "steps": steps,
                "surface": surface,
                "title": title,
            }
        )
        self.add_coverage(surface, name, coverage, title, ["workflow-handoff.md"], source)


def prepare_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        marker = output_dir / "metadata.json"
        if not marker.exists():
            raise SpecError(f"Refusing to overwrite non-rendered directory: {output_dir}")
        try:
            metadata = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SpecError(f"Refusing to overwrite directory with invalid metadata.json: {output_dir}") from exc
        if metadata.get("mode") != MODE:
            raise SpecError(f"Refusing to overwrite directory not marked as {MODE}: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def render_modern_dashboard(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    intent = {
        "audience": workflow.get("audience"),
        "dashboard": workflow.get("dashboard", name),
        "logs": workflow.get("logs"),
        "metrics": workflow.get("metrics", []),
        "sections": workflow.get("sections", []),
        "service_map": workflow.get("service_map"),
        "templates": workflow.get("templates", []),
    }
    rel = ctx.write_payload(Path("payloads") / "modern-dashboard" / f"{slugify(name)}.intent.json", intent)
    url = deeplink(ctx.app_base, "/dashboards", {"query": workflow.get("dashboard", name)})
    ctx.add_link("modern_dashboard", name, url, "Open modern dashboards and templates in Observability Cloud.")
    ctx.add_handoff(
        "modern_dashboard",
        name,
        "Build or review the modern dashboard in the new dashboard experience.",
        [
            f"Use rendered layout intent: {rel}",
            "Create sections or subsections for each operational question; do not nest sections.",
            "Add metrics charts from the Builder, logs charts with SPL1/SPL2/JSON query intent, and service-map visualizations where useful.",
            "Delegate classic API-renderable charts to splunk-observability-dashboard-builder when an API-managed dashboard is required.",
        ],
        DOC_SOURCES["modern_dashboard"],
    )
    ctx.add_coverage(
        "modern_dashboard",
        name,
        "delegated_apply",
        "Classic dashboard/chart apply is delegated; modern dashboard layout remains UI-guided.",
        [rel],
        DOC_SOURCES["dashboard_api"],
    )


def render_apm_service_map(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    service = get_any(workflow, "service", "service_name")
    environment = workflow.get("environment")
    time_range = get_any(workflow, "time_range", "timeRange", default="-1h")
    payload = {
        "timeRange": time_range,
        "tagFilters": workflow.get("tag_filters", workflow.get("filters", [])),
    }
    if environment:
        payload["tagFilters"] = [
            *as_list(payload.get("tagFilters", []), f"{name} tag filters"),
            {"name": "sf_environment", "operator": "equals", "scope": "GLOBAL", "value": environment},
        ]
    rel = ctx.write_payload(Path("payloads") / "apm" / f"{slugify(name)}.topology.json", payload)
    path = f"/apm/topology/{quote(str(service), safe='')}" if service else "/apm/topology"
    ctx.add_action("validate-apm-topology", "apm_service_map", name, "api_validate", "POST", path, rel)
    ctx.add_coverage(
        "apm_service_map",
        name,
        "api_validate",
        "APM topology APIs can validate the dependency data behind service-map triage.",
        [rel, "apply-plan.json"],
        DOC_SOURCES["apm_topology_api"],
    )
    url = deeplink(ctx.app_base, "/apm/service-map", {"service": service, "environment": environment})
    ctx.add_link("apm_service_map", name, url, "Open the generated APM service map with preserved context.")
    ctx.add_handoff(
        "apm_service_map",
        name,
        "Use the service map for dependency, bottleneck, and error propagation triage.",
        [
            "Apply service, environment, business transaction, and tag filters.",
            "Use service map search and breakdowns by endpoint, workflow, or indexed tag.",
            "Open the service sidebar and jump to the service dashboard when RED metrics need chart context.",
        ],
        DOC_SOURCES["apm_service_map"],
    )


def render_apm_service_view(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "apm" / f"{slugify(name)}.service-view.intent.json", workflow)
    url = deeplink(
        ctx.app_base,
        "/apm/service",
        {"service": workflow.get("service"), "environment": workflow.get("environment")},
    )
    ctx.add_link("apm_service_view", name, url, "Open the APM service view with service and environment context.")
    ctx.add_handoff(
        "apm_service_view",
        name,
        "Review the native APM service view before pivoting to traces or dashboards.",
        [
            f"Use rendered service-view intent: {rel}",
            "Confirm the selected environment and time range match the incident window.",
            "Review SLI, service map, requests, latency, errors, dependency latency, runtime, infrastructure, endpoints, Tag Spotlight, and embedded logs.",
            "Select request, latency, or error charts to open example traces; use endpoint rows to pivot to endpoint details, traces, code profiling, or the endpoint dashboard.",
            "When service dashboards need durable custom charts, hand off chart payloads to splunk-observability-dashboard-builder.",
        ],
        DOC_SOURCES["apm_service_view"],
    )


def render_apm_business_transaction(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "apm" / f"{slugify(name)}.business-transaction.intent.json", workflow)
    url = deeplink(ctx.app_base, "/settings/apm/business-transactions", {"query": workflow.get("rule", name)})
    ctx.add_link("apm_business_transaction", name, url, "Open APM business transaction rules.")
    ctx.add_handoff(
        "apm_business_transaction",
        name,
        "Plan or review business transaction rules in the native Data Management UI.",
        [
            f"Use rendered business transaction intent: {rel}",
            "Confirm Enterprise Edition availability and admin role before changing rules.",
            "If a rule uses global span tags, first index the tag as a Troubleshooting MetricSet and wait for cardinality analysis.",
            "Review rule behavior and limits, create or update the rule, enable it, then verify the workflow appears in service map and APM dashboards.",
            "If tag indexing or cardinality analysis is missing, hand off the MetricSet prerequisite to the APM owner before applying a rule.",
        ],
        DOC_SOURCES["apm_business_transaction"],
    )
    ctx.add_coverage(
        "apm_business_transaction",
        name,
        "handoff",
        "Business transaction rules are UI/admin workflows with MetricSet prerequisites.",
        [rel],
        DOC_SOURCES["apm_metricsets"],
    )


def render_apm_trace_waterfall(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    trace_id = str(get_any(workflow, "trace_id", "traceId", default="")).strip()
    if concrete_id(trace_id):
        segment = get_any(workflow, "segment_timestamp", "segmentTimestamp")
        path = f"/apm/trace/{trace_id}/{segment}" if segment else f"/apm/trace/{trace_id}/latest"
        ctx.add_action("download-trace", "apm_trace_waterfall", name, "api_validate", "GET", path)
        if workflow.get("include_segments"):
            ctx.add_action("list-trace-segments", "apm_trace_waterfall", name, "api_validate", "GET", f"/apm/trace/{trace_id}/segments")
        ctx.add_coverage(
            "apm_trace_waterfall",
            name,
            "api_validate",
            "Trace APIs can download trace JSON and list segment timestamps.",
            ["apply-plan.json"],
            DOC_SOURCES["trace_api"],
        )
    else:
        ctx.add_handoff(
            "apm_trace_waterfall",
            name,
            "Trace download requires a concrete trace ID.",
            ["Use Trace Analyzer filters to identify a trace, then rerender with trace_id."],
            DOC_SOURCES["trace_analyzer"],
        )
    url = deeplink(ctx.app_base, "/apm/traces", {"traceId": trace_id or None, "service": workflow.get("service")})
    ctx.add_link("apm_trace_waterfall", name, url, "Open Trace Analyzer and trace waterfall.")
    ctx.add_handoff(
        "apm_trace_waterfall",
        name,
        "Review the trace waterfall and correlated context in the native UI.",
        [
            "Use span filters for service, operation, tag values, and error status.",
            "Expand collapsed repeated spans and inspect duration contribution.",
            "Check the Trace Properties panel for RUM session details and related logs.",
            "Download trace segments through the action plan when offline review is required.",
        ],
        DOC_SOURCES["trace_waterfall"],
    )


def render_apm_tag_spotlight(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    url = deeplink(ctx.app_base, "/apm/tag-spotlight", {"service": workflow.get("service"), "environment": workflow.get("environment")})
    rel = ctx.write_payload(Path("payloads") / "apm" / f"{slugify(name)}.tag-spotlight.intent.json", workflow)
    ctx.add_link("apm_tag_spotlight", name, url, "Open APM Tag Spotlight.")
    ctx.add_handoff(
        "apm_tag_spotlight",
        name,
        "Analyze RED metrics by indexed span tags and drill into representative traces.",
        [
            f"Use rendered tag intent: {rel}",
            "Confirm required tags are indexed as Troubleshooting MetricSets.",
            "Compare request, error, root-cause error, p50, p90, and p99 latency by tag value.",
            "Select outlier tag values to pivot into relevant traces.",
        ],
        DOC_SOURCES["tag_spotlight"],
    )


def render_apm_profiling_flamegraph(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "apm" / f"{slugify(name)}.profiling.intent.json", workflow)
    url = deeplink(
        ctx.app_base,
        "/apm/profiling",
        {"service": workflow.get("service"), "environment": workflow.get("environment")},
    )
    ctx.add_link("apm_profiling_flamegraph", name, url, "Open AlwaysOn Profiling for the selected service.")
    ctx.add_handoff(
        "apm_profiling_flamegraph",
        name,
        "Use AlwaysOn Profiling flame graphs for code and memory bottleneck triage.",
        [
            f"Use rendered profiling intent: {rel}",
            "Confirm profiling data is present and tied to the same service, environment, and trace context as the incident.",
            "Review CPU flame graph, memory allocation or garbage collection views where supported, thread locks, memory leaks, file-system bottlenecks, and slow external calls.",
            "Pivot from spans or service view into code profiling and compare with trace duration contribution.",
            "If profiles are absent, hand off instrumentation to splunk-observability-k8s-auto-instrumentation-setup or splunk-observability-otel-collector-setup.",
        ],
        DOC_SOURCES["apm_profiling"],
    )


def render_rum_session_replay(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    url = deeplink(
        ctx.app_base,
        "/rum/sessions",
        {
            "query": workflow.get("query"),
            "application": workflow.get("application"),
            "sessionId": get_any(workflow, "session_id", "sessionId"),
        },
    )
    rel = ctx.write_payload(Path("payloads") / "rum" / f"{slugify(name)}.replay-checks.json", workflow)
    ctx.add_link("rum_session_replay", name, url, "Open RUM session search and replay player.")
    metrics = as_list(workflow.get("metrics", []), f"{name} metrics")
    for metric in metrics:
        ctx.add_action("validate-rum-metric", "rum_session_replay", name, "api_validate", "GET", f"/metric/{quote(str(metric), safe='')}")
    if metrics:
        ctx.add_coverage(
            "rum_session_replay",
            name,
            "api_validate",
            "RUM metric availability can be checked through the metric metadata API before UI replay review.",
            ["apply-plan.json"],
            DOC_SOURCES["metric_api"],
        )
    ctx.add_handoff(
        "rum_session_replay",
        name,
        "Review RUM session replay with privacy and RUM/APM context.",
        [
            f"Use rendered replay checklist: {rel}",
            "Confirm user notice/consent, enterprise subscription or feature availability, and replay recording status.",
            "Verify masking, sensitivity rules, recording masks, and excluded UI elements before enabling replay broadly.",
            "Open replay segments, JS errors or mobile crashes on the timeline, and RUM/APM links where present.",
            "If Server-Timing trace links are missing, hand off backend instrumentation to splunk-observability-k8s-auto-instrumentation-setup.",
        ],
        DOC_SOURCES["rum_replay"],
    )


def render_rum_error_analysis(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "rum" / f"{slugify(name)}.error-analysis.intent.json", workflow)
    url = deeplink(
        ctx.app_base,
        "/rum/errors",
        {"application": workflow.get("application"), "errorId": get_any(workflow, "error_id", "errorId")},
    )
    ctx.add_link("rum_error_analysis", name, url, "Open RUM browser error analysis.")
    ctx.add_handoff(
        "rum_error_analysis",
        name,
        "Investigate browser errors, backend errors, and source-map readiness in RUM.",
        [
            f"Use rendered RUM error intent: {rel}",
            "Start from Application Summary or Overview, then drill into JavaScript errors by error ID in Tag Spotlight.",
            "Review error type, message, stack trace, frequency trend, affected page or route, related sessions, and XHR/fetch backend errors.",
            "If raw stack traces are unreadable, upload or verify source maps through the source-map handoff in splunk-observability-k8s-frontend-rum-setup.",
            "Pivot from representative errors to user sessions and session replay when replay is available and privacy checks are complete.",
        ],
        DOC_SOURCES["rum_errors"],
    )


def render_rum_url_grouping(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "rum" / f"{slugify(name)}.url-grouping.intent.json", workflow)
    url = deeplink(ctx.app_base, "/rum/url-grouping", {"application": workflow.get("application")})
    ctx.add_link("rum_url_grouping", name, url, "Open RUM URL grouping.")
    ctx.add_handoff(
        "rum_url_grouping",
        name,
        "Plan URL grouping rules before changing RUM page-level metrics.",
        [
            f"Use rendered URL grouping intent: {rel}",
            "Decide whether v1 or v2 grouping applies; v2 supports request-parameter matching and more flexible wildcard behavior.",
            "Review path, domain, parameter, hash-fragment, wildcard, UUID, timestamp, and high-cardinality patterns.",
            "Before migration, review impacted dashboards and detectors where URL groups are used, then confirm manual updates.",
            "Rerender downstream dashboard and detector handoffs if URL group names change.",
        ],
        DOC_SOURCES["rum_url_grouping"],
    )


def render_rum_mobile(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "rum" / f"{slugify(name)}.mobile.intent.json", workflow)
    url = deeplink(ctx.app_base, "/rum", {"application": workflow.get("application"), "platform": workflow.get("platform")})
    ctx.add_link("rum_mobile", name, url, "Open Splunk RUM for Mobile.")
    ctx.add_handoff(
        "rum_mobile",
        name,
        "Investigate mobile app health, crashes, errors, and user-session timelines.",
        [
            f"Use rendered mobile workflow intent: {rel}",
            "Open Mobile App Health and review crashes, app errors, app launch, and network performance.",
            "Select crash or app-error groups, then inspect affected user sessions and session timeline.",
            "Confirm Android mapping files or iOS dSYM files are uploaded when stack traces are not readable.",
            "Use session replay only after consent and sensitivity controls are confirmed.",
        ],
        DOC_SOURCES["rum_mobile_crashes"],
    )


def render_db_query_explain_plan(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "dbmon" / f"{slugify(name)}.query-intent.json", workflow)
    url = deeplink(ctx.app_base, "/databases", {"database": workflow.get("database"), "query": workflow.get("query_hash")})
    ctx.add_link("db_query_explain_plan", name, url, "Open Database Monitoring query investigation.")
    ctx.add_handoff(
        "db_query_explain_plan",
        name,
        "Use DBMon query details and explain plans to isolate database-caused latency.",
        [
            f"Use rendered query intent: {rel}",
            "Open the database instance and review Queries, Query samples, Query metrics, Dependencies, Metadata, and AI Assistant.",
            "Select the normalized query and inspect Query statement, Explain plans, Metrics, Query samples, and Traces.",
            "If Traces is empty, confirm DB/APM trace correlation and query sample collection are configured.",
            "If collection is missing, hand off to splunk-observability-database-monitoring-setup.",
        ],
        DOC_SOURCES["db_queries"],
    )


def render_infrastructure_navigator(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "infrastructure" / f"{slugify(name)}.navigator.intent.json", workflow)
    url = deeplink(
        ctx.app_base,
        "/infrastructure",
        {"navigator": workflow.get("navigator"), "entity": workflow.get("entity")},
    )
    ctx.add_link("infrastructure_navigator", name, url, "Open Infrastructure Monitoring navigators.")
    ctx.add_handoff(
        "infrastructure_navigator",
        name,
        "Use Infrastructure Monitoring navigators for host, cloud, and integration triage.",
        [
            f"Use rendered navigator intent: {rel}",
            "Confirm data is still active; non-streaming infrastructure stops being counted after the documented inactivity window.",
            "Open the relevant aggregate or instance navigator, apply entity filters, inspect built-in dashboards, active alerts, and related services or logs.",
            "If navigator dashboards need customization, review aggregate versus instance navigator settings and add only dashboards the target users can read.",
            "Hand off missing telemetry to the relevant cloud integration or splunk-observability-otel-collector-setup skill.",
        ],
        DOC_SOURCES["infrastructure"],
    )
    ctx.add_coverage(
        "infrastructure_navigator",
        name,
        "handoff",
        "Navigator dashboard customization and entity triage are native UI workflows.",
        [rel],
        DOC_SOURCES["navigator_dashboards"],
    )


def render_kubernetes_navigator(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "infrastructure" / f"{slugify(name)}.kubernetes.intent.json", workflow)
    url = deeplink(
        ctx.app_base,
        "/infrastructure/kubernetes",
        {
            "cluster": workflow.get("cluster"),
            "namespace": workflow.get("namespace"),
            "workload": workflow.get("workload"),
            "pod": workflow.get("pod"),
        },
    )
    ctx.add_link("kubernetes_navigator", name, url, "Open Kubernetes entities.")
    ctx.add_handoff(
        "kubernetes_navigator",
        name,
        "Use the new Kubernetes entities experience for cluster, node, pod, container, and workload triage.",
        [
            f"Use rendered Kubernetes navigator intent: {rel}",
            "Confirm Kubernetes data collection is configured, required permissions are present, and the Splunk OTel Collector for Kubernetes is at a feature-compatible version.",
            "Review cluster health, nodes, workloads, pods, containers, K8s analyzer, events, dependencies, embedded logs, and related APM services.",
            "Use entity filters for cluster, namespace, workload, pod, container, and service context; preserve the incident time range.",
            "If telemetry is absent or stale, hand off collection repair to splunk-observability-otel-collector-setup.",
        ],
        DOC_SOURCES["kubernetes"],
    )


def render_network_explorer(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "infrastructure" / f"{slugify(name)}.network-explorer.intent.json", workflow)
    url = deeplink(
        ctx.app_base,
        "/infrastructure/network",
        {"cluster": workflow.get("cluster"), "namespace": workflow.get("namespace"), "service": workflow.get("service")},
    )
    ctx.add_link("network_explorer", name, url, "Open Network Explorer.")
    ctx.add_handoff(
        "network_explorer",
        name,
        "Use Network Explorer for service dependency and network telemetry triage.",
        [
            f"Use rendered Network Explorer intent: {rel}",
            "Confirm the upstream OpenTelemetry eBPF Helm chart is deployed and sends data through a Splunk OTel Collector gateway.",
            "Review the network map, service dependencies, TCP metrics, DNS metrics, drops, errors, retransmits, and namespace/service filters.",
            "Correlate network dependency changes with APM service map, Kubernetes entities, and logs through Related Content where metadata is aligned.",
            "Treat eBPF chart operation as a customer-managed runtime handoff; Splunk supports the navigator but not the upstream chart lifecycle.",
        ],
        DOC_SOURCES["network_explorer"],
    )


def render_related_content(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "related-content" / f"{slugify(name)}.intent.json", workflow)
    url = deeplink(ctx.app_base, "/settings/related-content", {"service": workflow.get("service")})
    ctx.add_link("related_content", name, url, "Open Related Content configuration and checks.")
    ctx.add_handoff(
        "related_content",
        name,
        "Validate cross-product Related Content pivots before declaring native workflow coverage complete.",
        [
            f"Use rendered Related Content intent: {rel}",
            "Check APM service, database service, database instance, host, cloud compute, Kubernetes, log line, and trace-ID starting points against expected destinations.",
            "Verify metadata names match the documented keys, including service.name, deployment.environment, trace_id, host.name, k8s.cluster.name, k8s.node.name, k8s.pod.name, container.id, and cloud provider IDs.",
            "For Log Observer Connect, verify entity-index mappings for logs and remap fields when log metadata names differ.",
            "If collector metadata is missing, hand off to splunk-observability-cloud-integration-setup or splunk-observability-otel-collector-setup.",
        ],
        DOC_SOURCES["related_content"],
    )


def render_ai_assistant_investigation(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "ai-assistant" / f"{slugify(name)}.prompt-pack.json", workflow)
    url = deeplink(ctx.app_base, "/", {"assistant": "open"})
    ctx.add_link("ai_assistant_investigation", name, url, "Open AI Assistant in Observability Cloud.")
    ctx.add_handoff(
        "ai_assistant_investigation",
        name,
        "Use AI Assistant as a native investigation aid with explicit data and policy guardrails.",
        [
            f"Use rendered prompt pack: {rel}",
            "Confirm realm availability, English-language support, organization policy, and AI Assistant Management settings.",
            "Use scoped prompts for service health, traces, logs, active incidents, Kubernetes resources, SignalFlow generation, dashboards, and alerts.",
            "Remember that log-grounded prompts can affect SVC quota and that only the most recent chat interaction is accessible within the documented window.",
            "Record ChatId when feedback or escalation is needed; do not paste secrets, tokens, credentials, or regulated data into prompts.",
        ],
        DOC_SOURCES["ai_assistant"],
    )


def render_synthetic_waterfall(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    test_id = str(get_any(workflow, "test_id", "id", default="")).strip()
    rel = ctx.write_payload(Path("payloads") / "synthetics" / f"{slugify(name)}.waterfall-intent.json", workflow)
    if concrete_id(test_id):
        ctx.add_action("list-synthetic-runs", "synthetic_waterfall", name, "api_validate", "GET", f"/tests/{quote(test_id, safe='')}/runs", service="synthetics")
        for artifact in as_list(workflow.get("artifacts", []), f"{name} artifacts"):
            ctx.add_action(
                "plan-synthetic-artifact-lookup",
                "synthetic_waterfall",
                name,
                "api_validate",
                "GET",
                f"/tests/{quote(test_id, safe='')}/artifacts",
                service="synthetics",
            )
            break
        ctx.add_coverage(
            "synthetic_waterfall",
            name,
            "api_validate",
            "Synthetics APIs can list run history and plan artifact retrieval for waterfall review.",
            [rel, "apply-plan.json"],
            DOC_SOURCES["synthetics_api"],
        )
    url = deeplink(ctx.app_base, "/synthetics/runs", {"testId": test_id if concrete_id(test_id) else None, "runId": workflow.get("run_id")})
    ctx.add_link("synthetic_waterfall", name, url, "Open Synthetic run results and waterfall.")
    ctx.add_handoff(
        "synthetic_waterfall",
        name,
        "Review Synthetic waterfall details, artifacts, and cross-product links.",
        [
            f"Use rendered waterfall intent: {rel}",
            "Open the test history or specific run result, then inspect waterfall resources, timings, headers, resource-type tabs, and search filters.",
            "Download HAR and available Enterprise video/filmstrip artifacts when needed.",
            "Check web vitals, run metrics, Try Now versus Run Now semantics, and links to backend APM spans.",
        ],
        DOC_SOURCES["synthetic_waterfall"],
    )


def slo_payload_is_applyable(payload: dict[str, Any]) -> bool:
    return all(payload.get(key) for key in ("name", "type", "inputs", "targets"))


def render_slo_creation(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    payload = workflow.get("payload")
    url = deeplink(ctx.app_base, "/slo", {"query": workflow.get("query", name)})
    ctx.add_link("slo_creation", name, url, "Open SLO management.")
    if isinstance(payload, dict):
        rel = ctx.write_payload(Path("payloads") / "slo" / f"{slugify(name)}.json", payload)
        if slo_payload_is_applyable(payload):
            slo_id = str(workflow.get("id", "")).strip()
            method = "PUT" if slo_id else "POST"
            path = f"/slo/{quote(slo_id, safe='')}" if slo_id else "/slo"
            ctx.add_action("validate-slo", "slo_creation", name, "api_validate", "POST", "/slo/validate", rel)
            ctx.add_action("upsert-slo", "slo_creation", name, "api_apply", method, path, rel, writes=True)
            ctx.add_coverage(
                "slo_creation",
                name,
                "api_apply",
                "SLO API supports validation and create/update when payload includes name, type, inputs, and targets.",
                [rel],
                DOC_SOURCES["slo_api"],
            )
        else:
            ctx.add_handoff(
                "slo_creation",
                name,
                "Complete required SLO API fields before apply.",
                [f"Rendered incomplete SLO intent: {rel}", "Add name, type, inputs, and targets before using /slo/validate or /slo."],
                DOC_SOURCES["slo_api"],
            )
    if workflow.get("search"):
        rel_search = ctx.write_payload(Path("payloads") / "slo" / f"{slugify(name)}.search.json", workflow["search"])
        ctx.add_action("search-slos", "slo_creation", name, "api_validate", "POST", "/slo/search", rel_search)
    ctx.add_handoff(
        "slo_creation",
        name,
        "Review SLO semantics before applying API payloads.",
        [
            "Confirm SLI source: service/endpoint spans, custom metrics, or Synthetics metrics.",
            "Confirm target, compliance period, rolling versus calendar semantics, and ownership.",
            "Review breach, error-budget-left, and burn-rate alert rules plus notification routes.",
            "Use a token-file based API workflow for live apply; never put tokens in chat or argv.",
        ],
        DOC_SOURCES["slo"],
    )


def render_observability_mobile_app(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    rel = ctx.write_payload(Path("payloads") / "mobile-app" / f"{slugify(name)}.intent.json", workflow)
    ctx.add_handoff(
        "observability_mobile_app",
        name,
        "Use Splunk Observability Cloud for Mobile for dashboard and alert triage.",
        [
            f"Use rendered mobile app intent: {rel}",
            "Open Dashboards, search or choose category, apply filters, and share dashboards when needed.",
            "Open Alerts, filter by severity, inspect alert details and trigger-time visualizations, then share the alert if needed.",
            "For push notifications and paging preferences, hand off to splunk-oncall-setup.",
        ],
        DOC_SOURCES["mobile_app"],
    )


def render_log_observer_chart(ctx: RenderContext, workflow: dict[str, Any]) -> None:
    name = workflow["name"]
    intent = {
        "dashboard": workflow.get("dashboard"),
        "fields": workflow.get("fields", []),
        "indexes": workflow.get("indexes", []),
        "query": workflow.get("query"),
        "query_language": workflow.get("query_language", "SPL2"),
        "visualization": workflow.get("visualization", "table"),
    }
    rel = ctx.write_payload(Path("payloads") / "logs" / f"{slugify(name)}.chart-intent.json", intent)
    url = deeplink(ctx.app_base, "/logs", {"query": workflow.get("query")})
    ctx.add_link("log_observer_chart", name, url, "Open Log Observer with the chart query.")
    ctx.add_handoff(
        "log_observer_chart",
        name,
        "Author the logs chart in the new dashboard experience.",
        [
            f"Use rendered logs chart intent: {rel}",
            "Confirm Log Observer Connect connection and index access.",
            "Choose SPL1, SPL2, or JSON editor, run the search, select fields, choose visualization, then save to the target dashboard.",
        ],
        DOC_SOURCES["logs_chart"],
    )


RENDERERS = {
    "modern_dashboard": render_modern_dashboard,
    "apm_service_map": render_apm_service_map,
    "apm_service_view": render_apm_service_view,
    "apm_business_transaction": render_apm_business_transaction,
    "apm_trace_waterfall": render_apm_trace_waterfall,
    "apm_tag_spotlight": render_apm_tag_spotlight,
    "apm_profiling_flamegraph": render_apm_profiling_flamegraph,
    "rum_session_replay": render_rum_session_replay,
    "rum_error_analysis": render_rum_error_analysis,
    "rum_url_grouping": render_rum_url_grouping,
    "rum_mobile": render_rum_mobile,
    "db_query_explain_plan": render_db_query_explain_plan,
    "synthetic_waterfall": render_synthetic_waterfall,
    "slo_creation": render_slo_creation,
    "infrastructure_navigator": render_infrastructure_navigator,
    "kubernetes_navigator": render_kubernetes_navigator,
    "network_explorer": render_network_explorer,
    "related_content": render_related_content,
    "ai_assistant_investigation": render_ai_assistant_investigation,
    "observability_mobile_app": render_observability_mobile_app,
    "log_observer_chart": render_log_observer_chart,
}


def render_handoff(ctx: RenderContext) -> str:
    lines = [
        "# Splunk Observability Deep Native Workflow Handoff",
        "",
        f"Realm: `{ctx.realm}`",
        "",
    ]
    for item in ctx.handoffs:
        lines.extend(
            [
                f"## {item['title']}",
                "",
                f"- Surface: `{item['surface']}`",
                f"- Workflow: `{item['name']}`",
                f"- Coverage: `{item['coverage']}`",
            ]
        )
        if item.get("source"):
            lines.append(f"- Source: {item['source']}")
        for step in item["steps"]:
            lines.append(f"- {step}")
        lines.append("")
    rel = "workflow-handoff.md"
    write_text(ctx.output_dir / rel, "\n".join(lines))
    ctx.rendered_files.add(rel)
    return rel


def render_spec(spec: dict[str, Any], output_dir: Path, realm_override: str | None = None) -> dict[str, Any]:
    validate_spec(spec)
    realm = realm_override or str(spec.get("realm", "us0") or "us0")
    prepare_output_dir(output_dir)
    ctx = RenderContext(output_dir, realm)

    for raw in as_list(spec.get("workflows", []), "workflows"):
        workflow = as_mapping(raw, "workflows[]")
        surface = str(workflow["surface"])
        RENDERERS[surface](ctx, workflow)

    deeplinks_rel = ctx.write_payload(Path("deeplinks.json"), {"links": ctx.links, "realm": realm})
    handoff_rel = render_handoff(ctx)
    summary = Counter(item["coverage"] for item in ctx.coverage)
    coverage_report = {
        "api_version": API_VERSION,
        "objects": ctx.coverage,
        "realm": realm,
        "summary": {coverage: summary.get(coverage, 0) for coverage in sorted(ALLOWED_COVERAGE)},
    }
    coverage_rel = ctx.write_payload(Path("coverage-report.json"), coverage_report)
    apply_plan = {
        "actions": ctx.actions,
        "api_base_url": ctx.api_base,
        "api_version": API_VERSION,
        "coverage_report": coverage_rel,
        "deeplinks": deeplinks_rel,
        "handoff": handoff_rel,
        "mode": MODE,
        "realm": realm,
    }
    apply_rel = ctx.write_payload(Path("apply-plan.json"), apply_plan)
    metadata = {
        "api_version": API_VERSION,
        "mode": MODE,
        "realm": realm,
        "rendered_files": sorted(ctx.rendered_files | {coverage_rel, apply_rel}),
        "workflow_count": len(spec.get("workflows", [])),
    }
    metadata_rel = ctx.write_payload(Path("metadata.json"), metadata)
    return {
        "api_version": API_VERSION,
        "coverage_report": coverage_report,
        "files": sorted(ctx.rendered_files | {metadata_rel}),
        "ok": True,
        "output_dir": str(output_dir),
        "realm": realm,
    }


REQUIRED_RENDERED = (
    "metadata.json",
    "coverage-report.json",
    "apply-plan.json",
    "deeplinks.json",
    "workflow-handoff.md",
)


def load_json_obj(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SpecError(f"{path} must contain a JSON object.")
    return data


def validate_output(output_dir: Path) -> dict[str, Any]:
    missing = [name for name in REQUIRED_RENDERED if not (output_dir / name).exists()]
    if missing:
        raise SpecError(f"Rendered output missing required files: {', '.join(missing)}")
    metadata = load_json_obj(output_dir / "metadata.json")
    if metadata.get("mode") != MODE:
        raise SpecError(f"metadata.json mode must be {MODE}.")
    if metadata.get("api_version") != API_VERSION:
        raise SpecError(f"metadata.json api_version must be {API_VERSION!r}.")
    coverage = load_json_obj(output_dir / "coverage-report.json")
    objects = coverage.get("objects", [])
    if not isinstance(objects, list):
        raise SpecError("coverage-report.json objects must be a list.")
    for index, item in enumerate(objects):
        if not isinstance(item, dict):
            raise SpecError(f"coverage-report.json objects[{index}] must be an object.")
        if item.get("coverage") not in ALLOWED_COVERAGE:
            raise SpecError(f"coverage-report.json objects[{index}] has invalid coverage.")
        if item.get("surface") == "modern_dashboard" and item.get("coverage") == "api_apply":
            raise SpecError("modern_dashboard must not be marked api_apply.")
        if item.get("surface") in {"rum_session_replay", "db_query_explain_plan", "observability_mobile_app"} and item.get("coverage") == "api_apply":
            raise SpecError(f"{item.get('surface')} must not be marked api_apply.")
    apply_plan = load_json_obj(output_dir / "apply-plan.json")
    if apply_plan.get("mode") != MODE:
        raise SpecError(f"apply-plan.json mode must be {MODE}.")
    actions = apply_plan.get("actions", [])
    if not isinstance(actions, list):
        raise SpecError("apply-plan.json actions must be a list.")
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise SpecError(f"apply-plan.json actions[{index}] must be an object.")
        if action.get("coverage") not in {"api_apply", "api_validate"}:
            raise SpecError(f"apply-plan.json actions[{index}] has invalid API coverage.")
        path = str(action.get("path", ""))
        if not path.startswith("/"):
            raise SpecError(f"apply-plan.json actions[{index}] path must start with '/'.")
        payload_file = action.get("payload_file")
        if payload_file and not (output_dir / str(payload_file)).exists():
            raise SpecError(f"apply-plan.json actions[{index}] references missing payload_file {payload_file!r}.")
    return {"actions": len(actions), "coverage_objects": len(objects), "ok": True, "output_dir": str(output_dir)}


def validate_only(spec_path: Path | None, output_dir: Path | None) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True}
    if spec_path:
        spec = load_structured(spec_path)
        validate_spec(spec)
        result["spec"] = {"ok": True, "path": str(spec_path), "workflow_count": len(spec.get("workflows", []))}
    if output_dir and output_dir.exists():
        result["rendered"] = validate_output(output_dir)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--realm", default="")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.validate:
            if not args.spec and not args.output_dir:
                parser.error("--validate requires --spec or --output-dir")
            result = validate_only(args.spec, args.output_dir)
        else:
            if not args.spec or not args.output_dir:
                parser.error("--spec and --output-dir are required for rendering")
            spec = load_structured(args.spec)
            result = render_spec(spec, args.output_dir, args.realm or None)
    except (OSError, SpecError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if args.validate:
            print("Validated Splunk Observability deep native workflow spec/output.")
        else:
            print(f"Rendered Splunk Observability deep native workflows to {result['output_dir']}")
            print(f"Coverage objects: {len(result['coverage_report']['objects'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

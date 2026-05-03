# Product Coverage Matrix

## Renderable Through Classic API

| Area | Coverage | Notes |
|------|----------|-------|
| Dashboard groups | Full create/read/update/delete surface | Create custom groups or attach to an existing group ID. |
| Custom dashboards | Full create/read/update/delete surface | Built-in dashboards are read-only/template-like; clone or recreate into custom groups. |
| Metric charts | Full for supported chart schemas | TimeSeriesChart, SingleValue, List, TableChart, Heatmap. |
| Text notes | Full | Use Text charts with Markdown. |
| Filters and variables | Renderable | Validate property names and defaults against live dimensions when possible. |
| Event overlays | Renderable | Use detector or custom event overlays when event type and filters are known. |
| Detector links | Renderable when represented by chart properties | Verify detector IDs before apply when possible. |

## Documented But Not Yet API-Rendered

| Product/UI chart type | Current treatment | Reason |
|-----------------------|-------------------|--------|
| Pie and donut charts | Advisory only | Product docs list them as chart types, but the renderer needs a verified classic `/v2/chart` payload schema before apply. |
| Event feed charts | Advisory only | Product docs list them as chart types, but the renderer needs a verified classic `/v2/chart` payload schema before apply. Dashboard-level event overlays remain renderable. |

## Metric-Derived Product Coverage

These products can be covered when the relevant metrics and dimensions exist in the organization:

| Product area | Dashboard approach |
|--------------|--------------------|
| Infrastructure Monitoring | CPU, memory, disk, network, host/container/Kubernetes/cloud resource health, saturation, top-N entities. |
| Kubernetes | Cluster, namespace, workload, pod, node, and container metrics; use `k8s.cluster.name`, `k8s.namespace.name`, and workload dimensions. |
| Cloud infrastructure | AWS, Azure, and GCP metrics by account, region, zone, service, or resource ID. |
| Database Monitoring | Database health and performance metrics; deep query details and explain plans are not recreated by classic dashboard charts. |
| APM | Service RED metrics, latency percentiles, request/error rates, dependency metrics when metricized; trace samples and waterfalls are link/advisory. |
| RUM | Web vitals, route/page metrics, error and latency metrics when metricized; sessions and replay are link/advisory. |
| RUM for Mobile | Mobile crash, error, latency, and custom workflow metrics when metricized; mobile sessions and replay are link/advisory. |
| Synthetic Monitoring | Test availability, duration, error, and step metrics; waterfall detail is link/advisory. |
| Log Observer Connect | Logs-derived metrics only in classic API; modern logs charts are UI/advisory unless API support is verified. |
| Custom business metrics | Fully renderable when metric names and dimensions are known. |
| AI Infrastructure Monitoring | Renderable for exposed metrics such as model-serving, GPU, vector database, LLM, and agent telemetry. |
| AI Agent Monitoring | Renderable through APM and custom metrics when exposed; agent traces, session-style drilldowns, and native troubleshooting workflows are link/advisory. |
| Alerts and detectors | Detector links, event overlays, and alert-count metrics are renderable; detector creation and alert routing are out of scope for this dashboard skill. |
| Observability Cloud for Mobile app | Mobile-friendly dashboard content can be planned, but native mobile app workflows are not rendered by API. |

## Advisory Or Link-Only Coverage

Do not promise API-rendered dashboards for these surfaces in the classic path:

- Modern dashboard sections, subsections, and section tabs.
- Modern Splunk logs charts using SPL1, SPL2, or JSON query editors.
- Pie/donut charts and event feed charts until a public classic chart payload schema is verified.
- Service map visualizations.
- APM trace waterfall views, trace samples, span detail, and Tag Spotlight-style native workflows.
- RUM sessions, session replay, browser route detail, and mobile session workflows.
- Synthetic waterfall and step-level diagnostic workflows beyond metric summaries.
- Database query explain plans and deep query analytics views.
- On-Call schedules, escalation policies, paging workflows, and incident response UI.
- Alert detector creation, muting, notification policy, and routing workflows.
- Observability Cloud for Mobile app-specific navigation and alert workflows.
- Product-native navigators.

When the user asks for one of these, create metric summary charts plus Text charts with links or manual follow-up steps, or use browser/UI automation only with explicit user approval.

## Dashboard Studio Secondary Mode

Dashboard Studio Observability metrics are not the same as native Observability dashboards. Before proposing Dashboard Studio output, verify:

- Splunk Cloud Platform version 9.3.2408+ or Splunk Enterprise 10.0+.
- Realm support for Observability metrics.
- Not a Splunk Cloud Platform trial.
- Required capabilities such as `read_o11y_content` and `write_o11y_content`.
- Pairing mode and export behavior. Scheduled publish/export rendering differs for API token pairing and Unified Identity.
- Import limitations: charts from the new Observability dashboard experience are not supported for import into Dashboard Studio.

## Source Review Notes

Reviewed on 2026-05-02 against current Splunk documentation for Observability Cloud service coverage, chart types, the new dashboard experience, AI Infrastructure Monitoring, and the Observability domain transition. Re-check before adding API rendering for any chart type or modern dashboard capability that is not listed in the classic API reference.

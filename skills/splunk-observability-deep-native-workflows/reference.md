# Splunk Observability Deep Native Workflow Reference

This skill was researched against current Splunk Observability Cloud help and
developer documentation in May 2026. Use it to distinguish native product
workflows from collector setup, classic dashboard API rendering, and basic
detector creation.

## Product Coverage Matrix

| Surface | Coverage | What the skill renders | Owning follow-up |
|---|---|---|---|
| Modern dashboards | `handoff`, `delegated_apply` for classic chart fallbacks | Sections, subsections, templates, metrics chart intent, logs chart intent, service-map intent, operator steps | `splunk-observability-dashboard-builder` for classic API dashboard/chart payloads |
| APM service map | `api_validate`, `deeplink` | `/apm/topology` validation plan, service/environment filters, breakdown checklist, service-dashboard jump | Native UI for map investigation |
| APM service view and built-in dashboards | `deeplink`, `handoff` | Service SLI, RED metrics, dependency latency, runtime/infrastructure metrics, endpoints, embedded logs, dashboard pivots | `splunk-observability-dashboard-builder` for durable custom dashboard payloads |
| APM business transactions | `deeplink`, `handoff` | Enterprise/admin checks, global span-tag and MetricSet prerequisites, rule review and enablement checklist | Native Data Management UI |
| APM trace waterfall | `api_validate`, `deeplink`, `handoff` | Trace download actions, segment download plan, Trace Analyzer link, span/RUM/log checklist | Native UI for waterfall analysis |
| APM Tag Spotlight | `deeplink`, `handoff` | Indexed-span-tag prerequisites, RED breakdown checklist, trace drilldown steps | APM MetricSet and tag configuration skills if indexing is missing |
| AlwaysOn Profiling flame graphs | `deeplink`, `handoff` | CPU flame graph, memory profiling, span/service correlation, instrumentation handoff | `splunk-observability-k8s-auto-instrumentation-setup` or OTel collector setup if absent |
| RUM session replay | `deeplink`, `handoff`, optional `api_validate` for metric metadata | Session search link, replay privacy checklist, browser/mobile replay checks, RUM/APM linking checks | `splunk-observability-k8s-frontend-rum-setup` for browser injection |
| RUM browser error analysis | `deeplink`, `handoff` | JavaScript error IDs, source-map readiness, backend XHR/fetch errors, Tag Spotlight, session and replay pivots | RUM source-map handoff in `splunk-observability-k8s-frontend-rum-setup` |
| RUM URL grouping | `deeplink`, `handoff` | v1/v2 rule intent, path/domain/parameter/hash matching, migration impact checklist | Native Data Management UI; rerender dashboards/detectors when groups change |
| RUM for Mobile | `handoff`, `deeplink` | App summary, crashes/errors, session timeline, dSYM/mapping-file checks, launch/network workflow | Mobile app instrumentation work outside this repo unless a future skill owns it |
| Database Query Performance and DBMon explain plans | `handoff`, `deeplink` | Query-details plan: statement, explain plans, metrics, samples, traces, dependencies, metadata, AI Assistant | `splunk-observability-database-monitoring-setup` for collection |
| Synthetic waterfall detail | `api_validate`, `deeplink`, `handoff` | Run/artifact lookup plan, waterfall/HAR/video/filmstrip checks, resource filters, APM/RUM link checks | `splunk-observability-native-ops` for Synthetic test CRUD |
| SLO creation | `api_apply`, `api_validate`, `deeplink` | `/slo/validate`, `/slo`, `/slo/{id}`, `/slo/search` action plan and payloads | Apply through an approved Observability API client or updated native-ops path |
| Infrastructure navigators | `deeplink`, `handoff` | Host/cloud/integration navigator intent, aggregate/instance dashboard checks, alert and Related Content pivots | Cloud integration or OTel collector skills for missing data |
| Kubernetes entities | `deeplink`, `handoff` | New K8s entities workflow, permissions, collector version check, analyzer/events/dependencies/logs/APM pivots | `splunk-observability-otel-collector-setup` |
| Network Explorer | `deeplink`, `handoff` | Network map, service dependency, eBPF support caveat, TCP/DNS/drop/error/retransmit checklist | Customer-managed eBPF plus OTel gateway handoff |
| Related Content | `deeplink`, `handoff` | Cross-product pivot matrix, metadata key checks, LOC entity-index mapping checks | `splunk-observability-cloud-integration-setup` and OTel collector setup |
| AI Assistant investigation | `deeplink`, `handoff` | Prompt pack, realm/policy checks, service/trace/log/incident/K8s/SignalFlow workflows, quota and ChatId notes | Native AI Assistant UI |
| Observability Cloud for Mobile app | `handoff` | Dashboards, filters, alert details, sharing, push notification/on-call checks | `splunk-oncall-setup` for paging policies and incident lifecycle |
| Modern logs charts | `handoff`, `deeplink` | SPL1/SPL2/JSON query intent, index selection, fields, visualization, dashboard placement | `splunk-observability-cloud-integration-setup` for Log Observer Connect prerequisites |

## Research Notes

### Modern Dashboards

Splunk's new dashboard experience supports dashboard sections/subsections,
metrics charts, logs charts, service maps, templates, and demos. Current docs
also state some legacy dashboard-builder features might not yet be available in
the new experience. Treat modern layout as UI-authored unless a public API is
verified for the exact modern object. Use classic dashboard APIs only for
classic chart/dashboard/group payloads.

Source anchors:

- https://help.splunk.com/en/splunk-observability-cloud/create-dashboards-and-charts/create-dashboards/use-modern-dashboards/use-new-dashboard-experience-beta
- https://help.splunk.com/en/splunk-observability-cloud/create-dashboards-and-charts/create-dashboards
- https://dev.splunk.com/observability/reference/api/dashboards/latest
- https://dev.splunk.com/observability/reference/api/charts/latest
- https://dev.splunk.com/observability/reference/api/dashboard_groups/latest

### APM Service Maps, Trace Analyzer, And Waterfalls

The service map is dynamically generated from telemetry and supports service,
environment, business transaction, and tag filters, plus service breakdowns. Do
not create service maps as objects. Validate topology using the APM topology API
and render the UI path for investigation.

The service view is a separate native workflow from the service map. It combines
the selected service's SLI, RED metrics, dependency latency, runtime and
infrastructure metrics, Tag Spotlight, endpoints, embedded logs, and pivots to
dashboards, traces, code profiling, and memory profiling. It is also where
database services expose Database Query Performance and where service dashboards
can be customized or converted into durable dashboard-builder handoffs.

Trace Analyzer is the native search UI for full-fidelity traces. The trace
waterfall supports span filtering, collapsed repeated spans, RUM session links,
related logs, and trace download. The public trace APIs download latest or
timestamped trace segments and list segment timestamps; they do not replace the
interactive Trace Analyzer UI.

Business transaction rules are Data Management workflows. They require Enterprise
Edition and an admin role. Rules based on global span tags require the tag to be
indexed first, and MetricSet cardinality analysis must complete before the tag is
activated. Do not mark business transaction rules as API-applied unless a public
write API is verified.

AlwaysOn Profiling is a native APM investigation surface. It links code
performance context to trace data and visualizes CPU and memory behavior with
flame graphs. Missing profile data is an instrumentation/setup handoff, not a
native UI failure.

Source anchors:

- https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/manage-services-spans-and-traces-in-splunk-apm/view-dependencies-among-your-services-in-the-service-map
- https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/manage-services-spans-and-traces-in-splunk-apm/use-the-service-view
- https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/visualize-and-alert-on-your-application-in-splunk-apm/track-service-performance-using-dashboards-in-splunk-apm
- https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/correlate-traces-to-track-business-transactions/configure-business-transaction-rules
- https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/analyze-services-with-span-tags-and-metricsets/learn-about-troubleshooting-metricsets/index-span-tags-to-create-troubleshooting-metricsets
- https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/alwayson-profiling
- https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/manage-services-spans-and-traces-in-splunk-apm/search-traces-using-trace-analyzer
- https://help.splunk.com/splunk-observability-cloud/monitor-application-performance/manage-services-spans-and-traces-in-splunk-apm/view-and-filter-for-spans-within-a-trace
- https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/manage-services-spans-and-traces-in-splunk-apm/download-traces
- https://dev.splunk.com/observability/reference/api/apm_service_topology/latest
- https://dev.splunk.com/observability/reference/api/trace_id/latest

### RUM Session Replay And Mobile RUM

Splunk RUM covers Browser and Mobile. Browser RUM collects web vitals, errors,
resource timing, route/page views, custom events, and RUM/APM links through the
Server-Timing header. Session replay is privacy-sensitive and must include
consent, masking, sensitivity rules, and enterprise-edition/subscription checks.
Mobile session replay uses platform-specific SDK modules and is played in the
RUM UI. Mobile RUM workflows also include app summary, crashes, app errors,
session timelines, readable stack traces when dSYM or Android mapping files are
available, app launch, and network performance.

RUM browser error analysis is its own workflow. JavaScript errors are grouped by
error ID, and readable stack traces depend on source maps. Backend XHR/fetch
errors, resource errors, related sessions, and replay pivots must be reviewed
with the application and route/page context preserved.

RUM URL grouping lives under Data Tools. The current docs describe both v1 and
v2 behavior, including request-parameter matching, flexible wildcards, hash
fragment handling, and migration review for affected dashboards and detectors.

Source anchors:

- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/search-for-user-sessions
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/replay-user-sessions
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/replay-user-sessions/replay-a-user-session
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/replay-user-sessions/record-android-sessions
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/replay-user-sessions/record-react-native-sessions
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/understand-user-sessions
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/monitor-errors-and-crashes-in-tag-spotlight/monitor-browser-errors
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/write-rules-for-url-grouping
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/monitor-errors-and-crashes-in-tag-spotlight/monitor-mobile-crashes
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/splunk-rum-dashboards/splunk-rum-built-in-dashboards

### Database Monitoring And Explain Plans

Splunk Database Monitoring provides query statistics, execution plans, health
and performance metrics, query analytics, application correlation, infrastructure
correlation, and a unified monitoring interface. The DBMon query details view
includes normalized query statement, explain plans, metrics, query samples, and
traces. Correlation from database queries to APM traces requires extra
instrumentation and only sampled queries have propagated trace information.

Source anchors:

- https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/introduction-to-splunk-database-monitoring
- https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/monitor-database-platform-instances/queries
- https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/monitor-database-platform-instances/query-samples
- https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/monitor-database-platform-instances/query-metrics
- https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/correlate-database-queries-with-splunk-apm-traces
- https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/monitor-database-query-performance

### Synthetic Waterfalls

Browser tests monitor single pages, multi-step flows, conversion paths, and
JavaScript-heavy journeys. Each browser test captures a HAR and many metrics.
Run results include a waterfall chart, performance/user/resource/error metrics,
and Enterprise-only video/filmstrip artifacts. Waterfall rows can expose request
and response headers, timing details, resource-type tabs, search, downloadable
artifacts, and APM span links when the same app is instrumented.

Source anchors:

- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/synthetic-monitoring
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/synthetic-monitoring/browser-tests-for-webpages/set-up-a-browser-test
- https://help.splunk.com/splunk-observability-cloud/monitor-end-user-experience/synthetic-monitoring/browser-tests-for-webpages/interpret-browser-test-results
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/synthetic-monitoring/browser-tests-for-webpages/browser-test-metrics
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/synthetic-monitoring/advanced-test-configurations/validate-your-test-configuration-with-try-now
- https://dev.splunk.com/observability/reference/api/synthetics_tests/latest
- https://dev.splunk.com/observability/reference/api/synthetics_artifacts/latest

### SLO Creation

SLO management tracks SLIs against reliability goals using targets, compliance
windows, error budgets, and burn rate. Current public API coverage includes
SLO creation/update/delete/search/validate surfaces. Render SLO payloads as
`api_apply` only when the payload contains `name`, `type`, `inputs`, and
`targets`. Include alert rule types for breach, error-budget-left, and burn
rate where requested.

Source anchors:

- https://help.splunk.com/en/splunk-observability-cloud/create-alerts-detectors-and-service-level-objectives/create-service-level-objectives-slos
- https://help.splunk.com/en?resourceId=alerts-detectors-notifications_slo_create-slo
- https://help.splunk.com/splunk-observability-cloud/create-alerts-detectors-and-service-level-objectives/create-service-level-objectives-slos/view-and-manage-slos
- https://help.splunk.com/en/splunk-observability-cloud/create-alerts-detectors-and-service-level-objectives/create-service-level-objectives-slos/configure-a-service-level-objective-slo-based-on-a-synthetics-check
- https://dev.splunk.com/observability/reference/api/slo/latest

### Infrastructure, Kubernetes, Network Explorer, And Related Content

Infrastructure Monitoring native workflows are still deep product workflows
even when data collection belongs to OTel or cloud integration skills. Navigator
triage includes aggregate and instance views, active alerts, built-in dashboards,
custom navigator dashboard settings, and Related Content pivots. Data freshness
matters: stale infrastructure streams stop being counted after documented
inactivity windows.

The new Kubernetes entities experience supersedes the classic navigator path.
It requires Kubernetes data collection, navigator/dashboard/SignalFlow
permissions, and a feature-compatible Splunk OTel Collector for Kubernetes.
Coverage must include cluster, node, workload, pod, container, K8s analyzer,
events, dependencies, logs, and APM pivots.

Network Explorer is supported as an Observability navigator, but its upstream
eBPF Helm chart lifecycle is customer-managed. Treat eBPF deployment, privileges,
and gateway wiring as external runtime handoffs.

Related Content is a cross-product coverage requirement. APM, Infrastructure,
Log Observer Connect, Kubernetes, database, host, trace, and log pivots depend
on exact metadata names and, for logs, entity-index mapping. Missing pivots are
usually metadata or collector configuration issues.

Source anchors:

- https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/monitor-services-and-hosts
- https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/use-navigators/customize-dashboards-in-splunk-infrastructure-monitoring-navigators
- https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/monitor-services-and-hosts/monitor-kubernetes/monitor-kubernetes-entities
- https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/network-explorer
- https://help.splunk.com/en/splunk-observability-cloud/data-tools/related-content
- https://help.splunk.com/splunk-observability-cloud/data-tools/configure-the-collector-to-enable-related-content-for-infra-and-apm

### AI Assistant In Observability Cloud

AI Assistant is a native investigation surface for metrics, traces, logs,
incidents, alerts, dashboards, services, Kubernetes resources, and SignalFlow
generation. It is realm-limited, English-only, and governed by organization
policy. Log-grounded prompts can affect SVC quota. The skill should render prompt
packs and guardrails, not pretend to automate the AI Assistant UI.

Source anchors:

- https://help.splunk.com/en/splunk-observability-cloud/splunk-ai-assistant/ai-assistant-in-observability-cloud

### Splunk Observability Cloud For Mobile

Splunk Observability Cloud for Mobile is the iOS/Android companion app for
viewing dashboards and alerts. It supports dashboard search/categories, filters,
dashboard sharing, alert severity filtering, alert details, and visualizations
from trigger time. Push notification behavior depends on on-call notification
preference and belongs with the On-Call lifecycle where paging policy changes
are needed.

Source anchors:

- https://help.splunk.com/en/splunk-observability-cloud/use-splunk-mobile
- https://help.splunk.com/en/splunk-observability-cloud/use-splunk-observability-cloud-mobile/view-dashboards-and-alerts
- https://help.splunk.com/en/splunk-observability-cloud/create-alerts-detectors-and-service-level-objectives/create-alerts-and-detectors/view-alerts
- https://help.splunk.com/en/splunk-observability-cloud/splunk-on-call/mobile-app

## Handoff Rules

- Prefer `deeplink` plus `handoff` for native product surfaces when the public
  API covers only read or validation.
- Use `delegated_apply` instead of duplicating setup ownership.
- If a user asks to automate SLOs, render the SLO API action plan and require a
  token-file based apply path outside chat.
- If a user asks to "build a modern dashboard", render the new-dashboard layout
  intent, then also emit a classic dashboard-builder handoff for any chart that
  can be safely represented by the classic API.
- If a workflow depends on data that might not exist, add a validation step:
  metric metadata lookup, APM topology read, trace download, Synthetic run
  lookup, or DBMon collection handoff.
- Treat native investigation surfaces as first-class coverage even when no
  public write API exists. The correct output is a reproducible UI packet with
  source-backed handoffs, not a false API claim.

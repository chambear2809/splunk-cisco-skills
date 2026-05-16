---
name: splunk-observability-deep-native-workflows
description: Render and validate deep native Splunk Observability Cloud operator workflows for modern dashboards, APM service maps, service views, business transactions, Trace Analyzer and trace waterfalls, AlwaysOn Profiling flame graphs, RUM session replay for browser and mobile, RUM error analysis, RUM URL grouping, Database Monitoring query and explain-plan triage, Synthetic waterfall details and artifacts, SLO creation and burn-rate alerting, Infrastructure/Kubernetes/Network Explorer navigators, Related Content, AI Assistant investigations, and Splunk Observability Cloud for Mobile app workflows. Use when the user asks for full native UI/product workflow coverage beyond collection, classic dashboards, or basic detector setup.
---

# Splunk Observability Deep Native Workflows

Use this skill for native Observability Cloud product workflows where the
operator experience matters as much as the underlying API object. It complements:

- `splunk-observability-otel-collector-setup` for telemetry collection.
- `splunk-observability-dashboard-builder` for classic dashboard API payloads.
- `splunk-observability-native-ops` for detectors, teams, muting rules,
  Synthetics API payloads, APM topology/trace checks, and simple RUM/log handoffs.
- `splunk-observability-database-monitoring-setup` for DBMon collector wiring.
- `splunk-observability-k8s-frontend-rum-setup` for Browser RUM and Session
  Replay instrumentation injection.
- `splunk-observability-cloud-integration-setup` for Log Observer Connect,
  Related Content, Dashboard Studio O11y metrics, and SIM add-on streams.

The default workflow is render-first and non-mutating. This skill produces a
reviewable workflow packet: coverage report, deeplinks, UI handoff steps, and
API action plans for surfaces with documented public APIs.

## Coverage Model

Every rendered item gets a coverage status:

- `api_apply`: a documented public Observability API can create or update the
  object. This skill renders the action plan; run live apply only through the
  specific owning skill or an approved apply client.
- `api_validate`: a documented public API can read, validate, or download data
  for the workflow.
- `delegated_apply`: another repo skill owns the apply path.
- `deeplink`: the skill renders deterministic Observability UI links and
  preserves filter context.
- `handoff`: the product surface is UI-guided or app-side; the skill renders
  exact operator steps.
- `not_applicable`: the requested workflow does not apply to the selected
  product, edition, realm, or instrumentation state.

Do not claim `api_apply` for modern dashboard layout, RUM session replay
playback, DBMon explain-plan UI, Synthetic waterfall detail, Trace Analyzer
search UI, or the Observability Cloud mobile app unless a public API is verified
for that exact action.

## Safety Rules

- Never ask for Splunk Observability API tokens, RUM tokens, mobile app
  credentials, database passwords, session replay consent secrets, or Splunk
  Platform credentials in conversation.
- Never pass tokens or passwords on the command line or as environment-variable
  prefixes.
- This skill does not need token files for rendering. If a downstream owning
  skill applies an API plan, use that skill's `--token-file` or file-backed
  credential flags.
- Reject inline secret fields such as `token`, `api_token`, `access_token`,
  `password`, `client_secret`, `secret`, and direct `*_token` values. Use
  file-reference fields in downstream specs instead.
- Treat session replay as privacy-sensitive. Always include consent, retention,
  masking/sensitivity, replay enablement, and enterprise-subscription checks in
  handoffs.

## Primary Workflow

1. Identify product surface and target workflow:
   - Modern dashboard composition, sections, tabs, logs charts, metrics charts,
     service-map panels, dashboard templates, or demos.
   - APM service map, service view, endpoint dashboards, Trace Analyzer, trace
     waterfall, RUM/log/span links, Tag Spotlight, business transactions,
     AlwaysOn Profiling, MetricSet prerequisites, or Database Query Performance
     in APM.
   - RUM session search, replay playback, browser or mobile replay
     instrumentation checks, crashes/errors, source maps, URL grouping, mobile
     app health dashboards, or RUM/APM linking.
   - Splunk Database Monitoring query details, explain plans, query samples,
     query metrics, trace correlation, infrastructure correlation, or AI
     Assistant handoff.
   - Synthetic browser/API/uptime workflows, Try Now/Run Now, waterfall,
     HAR/video/filmstrip artifacts, or RUM/APM correlation.
   - SLO creation, validation, targets, compliance windows, breach/error-budget/
     burn-rate alert rules, or SLO dashboards.
   - Infrastructure Monitoring, Kubernetes entities, Network Explorer, Related
     Content pivots, or AI Assistant investigations.
   - Splunk Observability Cloud for Mobile dashboards, alerts, push
     notifications, sharing, and on-call handoff.

2. Copy `template.example` and fill in non-secret values only.

3. Render and validate:

   ```bash
   bash skills/splunk-observability-deep-native-workflows/scripts/setup.sh \
     --render --validate \
     --spec skills/splunk-observability-deep-native-workflows/template.example \
     --output-dir splunk-observability-deep-native-rendered
   ```

4. Review:
   - `coverage-report.json` for per-surface API-vs-UI status.
   - `deeplinks.json` for direct Observability UI entry points.
   - `apply-plan.json` for public API validation or apply actions.
   - `workflow-handoff.md` for operator steps and downstream skill handoffs.
   - `payloads/` for SLO API payloads, modern dashboard intents, DB query
     investigation intents, Synthetic artifact intents, and RUM replay checks.

5. Apply only through the owning skill or approved apply client:
   - Classic dashboards -> `splunk-observability-dashboard-builder`.
   - Detectors, teams, muting rules, Synthetics tests -> `splunk-observability-native-ops`.
   - Browser RUM instrumentation -> `splunk-observability-k8s-frontend-rum-setup`.
   - DBMon collection -> `splunk-observability-database-monitoring-setup`.
   - LOC, Dashboard Studio O11y metrics, SIM inputs -> `splunk-observability-cloud-integration-setup`.
   - On-Call mobile paging and incident response -> `splunk-oncall-setup`.

## Supported Surfaces

Specs use `api_version: splunk-observability-deep-native-workflows/v1` and a
top-level `workflows` list. Each workflow has `surface`, `name`, and optional
surface-specific fields.

- `modern_dashboard`: new dashboard experience, sections/subsections, templates,
  demos, metrics charts, logs charts, service maps, and UI-only layout intent.
  Delegate classic API charts to `splunk-observability-dashboard-builder`.
- `apm_service_map`: service map navigation, service groups, endpoint/workflow
  breakdowns, inferred services, and topology API validation.
- `apm_service_view`: service SLI, RED metrics, dependency latency, runtime and
  infrastructure metrics, endpoints, Tag Spotlight, embedded logs, and built-in
  service dashboard pivots.
- `apm_business_transaction`: business transaction rule planning, Enterprise
  and admin-role checks, global span-tag prerequisites, and MetricSet/cardinality
  handoffs.
- `apm_trace_waterfall`: Trace Analyzer trace lookup, waterfall filtering,
  span details, repeated spans, RUM session links, related logs, and trace JSON
  download actions when `trace_id` is present.
- `apm_tag_spotlight`: indexed span-tag RED analysis, top contributors, trace
  drilldowns, and MetricSet prerequisites.
- `apm_profiling_flamegraph`: AlwaysOn Profiling CPU flame graphs, memory
  profiling, trace correlation, and instrumentation handoff.
- `rum_session_replay`: session search, replay player, privacy/masking,
  browser and mobile replay enablement, RUM/APM trace links, and replay
  troubleshooting.
- `rum_error_analysis`: browser JavaScript errors, backend XHR/fetch errors,
  source-map readiness, Tag Spotlight, related sessions, and replay pivots.
- `rum_url_grouping`: URL grouping v1/v2 rule planning, path/domain/parameter
  and hash-fragment patterns, migration impact, and dashboard/detector updates.
- `rum_mobile`: RUM for Mobile workflows: app summary, crashes, app errors,
  session timeline, stack-trace symbolication/mapping files, launch and network
  performance, and mobile app health dashboards.
- `db_query_explain_plan`: DBMon query details, explain plans, query samples,
  query metrics, traces, dependencies, metadata, AI Assistant, and APM/IM
  correlation.
- `synthetic_waterfall`: browser/API/uptime test history, Try Now/Run Now,
  waterfall, HAR download, video/filmstrip Enterprise checks, resource filters,
  web vitals, and APM/RUM links.
- `slo_creation`: SLO API payload intent, `/slo/validate`, `/slo`, `/slo/{id}`,
  `/slo/search`, request-based or custom-metric SLIs, rolling/calendar windows,
  and breach/error-budget/burn-rate alert rules.
- `infrastructure_navigator`: host, cloud, and integration navigator triage,
  aggregate/instance dashboard review, active alerts, and telemetry freshness.
- `kubernetes_navigator`: new Kubernetes entities experience, cluster/node/pod/
  container/workload triage, K8s analyzer, events, dependencies, logs, and APM
  pivots.
- `network_explorer`: network map, service dependencies, eBPF telemetry caveats,
  TCP/DNS/drop/error/retransmit review, and gateway handoff.
- `related_content`: APM, Infrastructure, Log Observer Connect, Kubernetes,
  database, host, trace, and log pivots plus metadata/entity-index checks.
- `ai_assistant_investigation`: scoped AI Assistant prompt packs for service
  health, traces, logs, incidents, Kubernetes, SignalFlow, dashboards, alerts,
  realm availability, SVC quota, and policy guardrails.
- `observability_mobile_app`: Splunk Observability Cloud for Mobile dashboards,
  filters, alert visualizations, sharing, and push notification/on-call handoff.
- `log_observer_chart`: modern logs chart workflow using SPL1, SPL2, or JSON
  query intent inside the new dashboard experience.

For official-source details and the full feature matrix, read
[reference.md](reference.md).

## Output Contract

Rendered packets must contain:

- `metadata.json`
- `coverage-report.json`
- `apply-plan.json`
- `deeplinks.json`
- `workflow-handoff.md`

If a workflow includes `payload`, `intent`, `logs`, `privacy`, `slo`, or
artifact fields, the renderer writes the normalized form under `payloads/`.

## Useful Commands

Validate a spec without writing a new packet:

```bash
bash skills/splunk-observability-deep-native-workflows/scripts/setup.sh \
  --validate \
  --spec skills/splunk-observability-deep-native-workflows/template.example
```

Render with an explicit realm:

```bash
bash skills/splunk-observability-deep-native-workflows/scripts/setup.sh \
  --render --validate \
  --realm us1 \
  --spec my-deep-native-workflows.yaml \
  --output-dir splunk-observability-deep-native-rendered
```

Use `--json` in CI to emit machine-readable validation or render summaries.

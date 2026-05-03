# Native Observability Coverage Reference

This skill complements:

- `splunk-observability-otel-collector-setup`, which deploys telemetry collection.
- `splunk-observability-dashboard-builder`, which renders classic dashboard API
  groups, charts, and dashboards.

## Public API Surfaces

Use `api_apply` only for documented public APIs:

- Detectors: `/v2/detector`, `/v2/detector/{id}`, `/v2/detector/validate`,
  `/v2/detector/{id}/events`, and `/v2/detector/{id}/incidents`.
- Alert operations: `/v2/alertmuting`, `/v2/incident`.
- Integrations: `/v2/integration`, `/v2/integration/{id}`, and
  `/v2/integration/validate/{id}`.
- Teams: `/v2/team`, `/v2/team/{tid}`, team membership and notification policy
  payloads.
- APM topology and traces: `/v2/apm/topology`, `/v2/apm/topology/{serviceName}`,
  `/v2/apm/trace/{traceId}/latest`, `/v2/apm/trace/{traceId}/segments`, and
  `/v2/apm/trace/{traceId}/{segmentTimestamp}`.
- Synthetics: `/v2/synthetics/tests`, `/v2/synthetics/tests/{id}/runs`,
  `/v2/synthetics/tests/{id}/run_now`, `/v2/synthetics/tests/{id}/artifacts`,
  and test-type endpoints for browser, API, HTTP, SSL, and port tests.

## Handoff Or Deeplink Surfaces

Use `deeplink` or `handoff` for surfaces where product documentation describes
UI workflows rather than stable write APIs:

- APM service maps are generated from telemetry and can be queried through the
  topology API; do not create service maps.
- RUM session search and session replay are operator workflows. Validate related
  metrics through `/v2/metric/{name}` where possible, then render
  session-search and replay links.
- Synthetic waterfall detail is viewed in the UI, while run/artifact retrieval
  is API-backed.
- Modern logs charts are created in the new dashboard experience from Log
  Observer or Dashboard UI using SPL1, SPL2, or JSON query specs; render a
  chart intent handoff instead of claiming classic chart API support.
- SLO links render deeplinks and deterministic intent handoffs. Do not mark SLO
  payloads `api_apply` unless the renderer is explicitly updated for a
  documented public SLO write API and covered by live validation tests.
- Splunk On-Call has its own public API and credential model. Use file-based
  On-Call API keys only for explicit API requests; otherwise render rotations,
  escalation policies, routing keys, and calendar handoffs.

## Source Anchors

- https://dev.splunk.com/observability/docs/apibasics/api_list
- https://dev.splunk.com/observability/reference/api/detectors/latest
- https://dev.splunk.com/observability/reference/api/teams/latest
- https://dev.splunk.com/observability/reference/api/incidents/latest
- https://dev.splunk.com/observability/reference/api/integrations/latest
- https://dev.splunk.com/observability/docs/datamodel/metrics_metadata
- https://dev.splunk.com/observability/reference/api/apm_service_topology/latest
- https://dev.splunk.com/observability/reference/api/trace_id/latest
- https://dev.splunk.com/observability/reference/api/synthetics_tests/latest
- https://dev.splunk.com/observability/reference/api/synthetics_artifacts/latest
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/real-user-monitoring/search-for-user-sessions
- https://help.splunk.com/splunk-observability-cloud/monitor-end-user-experience/synthetic-monitoring/browser-tests-for-webpages/interpret-browser-test-results
- https://help.splunk.com/en/splunk-observability-cloud/create-dashboards-and-charts/create-dashboards/use-new-dashboard-experience/add-a-logs-chart
- https://help.splunk.com/en/splunk-observability-cloud/splunk-on-call/introduction-to-splunk-on-call/splunk-on-call-api

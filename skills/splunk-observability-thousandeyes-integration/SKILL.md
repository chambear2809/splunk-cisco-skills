---
name: splunk-observability-thousandeyes-integration
description: >-
  Render and (optionally) apply the full ThousandEyes -> Splunk Observability
  Cloud integration end-to-end: Integration 1.0 OpenTelemetry metric stream
  (POST /v7/streams to ingest.<realm>.signalfx.com/v2/datapoint/otlp),
  Integrations 2.0 Splunk Observability APM connector (generic connector +
  splunk-observability-apm operation), and the full TE asset lifecycle
  (tests, alert rules, labels, tags, TE-side dashboards, TE Templates with
  Handlebars-only credential placeholders) across the canonical TE
  OpenTelemetry Data Model v2 taxonomy. Generates SignalFlow dashboard specs
  and starter detectors for hand-off to splunk-observability-dashboard-builder
  and splunk-observability-native-ops. Use when the user asks to wire
  ThousandEyes telemetry into Splunk Observability Cloud, configure
  Integrations 2.0 APM trace linking, manage TE tests/alert rules/templates
  for an O11y integration, or produce the per-test-type O11y dashboards.
---

# Splunk Observability ThousandEyes Integration

This is a **generalized TE -> Splunk Observability Cloud skill**, NOT tied to any one demo. A private RTSP/UDP/RTP demo repo was used during initial development to validate the TE Streams API + Integrations 2.0 mechanics; that demo's test taxonomy is demo-specific and is NOT carried into this skill. Source of truth: the public **ThousandEyes for OpenTelemetry Data Model v2** (`docs.thousandeyes.com/.../opentelemetry/data-model/data-model-v2/metrics`) and the **TE API v7** schemas (`developer.cisco.com/docs/thousandeyes/`).

## Three TE-side surfaces

1. **Integration 1.0 OpenTelemetry stream** — `POST /v7/streams` with `type=opentelemetry`, `signal=metric|trace|log` (default `metric`), `endpointType=http|grpc`, `streamEndpointUrl=https://ingest.<realm>.signalfx.com/v2/datapoint/otlp`, `customHeaders.X-SF-Token`, `dataModelVersion=v2`, `testMatch[]`, optional `filters.testTypes[]`.
2. **Integrations 2.0 Splunk Observability APM connector** — generic connector targeting `https://api.<realm>.signalfx.com` with `X-SF-Token`; assigned to the `splunk-observability-apm` operation for trace linking.
3. **Full TE asset lifecycle** — render and apply across the canonical taxonomy:
   - **Tests**: `POST /v7/tests/{type}` for `http-server`, `page-load`, `web-transactions`, `api`, `agent-to-server`, `agent-to-agent`, `bgp`, `dns-server`, `dns-trace`, `dnssec`, `sip-server`, `voice`, `ftp-server`.
   - **Alert Rules**: `POST /v7/alerts/rules` aligned with the SignalFlow detector specs we ship for O11y.
   - **Labels** and **Tags** for grouping tests and propagating metadata into the OTel stream attributes.
   - **TE-side Dashboards**: `POST /v7/dashboards`.
   - **TE Templates**: `POST /v7/templates` and `POST /v7/templates/{id}/deploy` (Handlebars-only credential placeholders).

## Out of scope (handed off)

- Splunk Platform `ta_cisco_thousandeyes` add-on -> [cisco-thousandeyes-setup](../cisco-thousandeyes-setup/SKILL.md).
- ThousandEyes MCP Server registration with Cursor / Claude / Codex / VS Code / Kiro -> [cisco-thousandeyes-mcp-setup](../cisco-thousandeyes-mcp-setup/SKILL.md).
- TE Enterprise Agent K8s/VM deployment.
- O11y dashboard apply -> [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md).
- O11y detector apply -> [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md).
- `signal=log` and `signal=trace` deep targets — render the payload shape and document that O11y's `/v2/datapoint/otlp` endpoint is metrics-only.

## Safety Rules

- Never ask for the ThousandEyes API token, the Splunk Observability ingest token, or the Splunk Observability API token in conversation.
- Never pass any token on the command line or as an environment-variable prefix.
- Use file-based secret flags only:
  - `--te-token-file` for the TE bearer token (used for Streams, Tests, Alert Rules, Templates, Dashboards).
  - `--o11y-ingest-token-file` for the Splunk Observability **Org access token** with ingest authorization (used as `X-SF-Token` in the OTLP metric stream `customHeaders`).
  - `--o11y-api-token-file` for the Splunk Observability **User API access token** (used as `X-SF-Token` in the Integrations 2.0 APM connector and SignalFlow validate calls).
- Reject every direct token flag (`--te-token`, `--access-token`, `--token`, `--bearer-token`, `--api-token`, `--o11y-token`, `--sf-token`).
- Token files must be `chmod 600`. `--apply` runs a permission preflight and aborts with a `chmod 600 <path>` hint when looser. `--allow-loose-token-perms` overrides with a `WARN`.
- TE Templates render with **Handlebars placeholders only** — TE API rejects plain-text credentials with HTTP 400.
- Apply scripts read token files at runtime (`$(cat $TOKEN_FILE)`) inside the rendered shell; the renderer never reads token files.

## Primary Workflow

1. Collect non-secret values: realm (us0/us1/eu0/...), account group ID, list of TE test IDs or test types to include, optional alert rules / labels / tags / dashboards / templates.

2. Create or update a YAML/JSON spec from `template.example`. Spec supports test selection via:
   - explicit `test_match[]` (list of `{id, domain: cea|endpoint}`),
   - `filters.test_types[]` (any of the canonical TE OTel v2 types),
   - or `mode: all` (stream every enabled test).

3. Render and validate:

   ```bash
   bash skills/splunk-observability-thousandeyes-integration/scripts/setup.sh \
     --render \
     --validate \
     --spec skills/splunk-observability-thousandeyes-integration/template.example \
     --output-dir splunk-observability-thousandeyes-rendered
   ```

4. Review `splunk-observability-thousandeyes-rendered/`:
   - `te-payloads/` — request bodies for `POST/PUT /v7/streams`, connector + APM operation, per-test JSON, alert rules, labels, tags, TE dashboards, templates.
   - `dashboards/` — one SignalFlow spec per selected test type (consumable by `splunk-observability-dashboard-builder`).
   - `detectors/` — starter detector specs (consumable by `splunk-observability-native-ops`).
   - `scripts/` — per-step apply scripts, list helpers, SignalFlow validation, hand-off drivers.
   - `metadata.json` — non-secret plan summary.

5. Apply only when explicitly requested:

   ```bash
   bash skills/splunk-observability-thousandeyes-integration/scripts/setup.sh \
     --apply stream,apm,tests,alert_rules,labels,tags,te_dashboards,templates \
     --spec my-integration.yaml \
     --te-token-file /tmp/te_token \
     --o11y-ingest-token-file /tmp/sfx_ingest \
     --o11y-api-token-file /tmp/sfx_api
   ```

   To apply only a subset:

   ```bash
   bash skills/splunk-observability-thousandeyes-integration/scripts/setup.sh \
     --apply stream,apm \
     --spec my-integration.yaml \
     --te-token-file /tmp/te_token \
     --o11y-ingest-token-file /tmp/sfx_ingest \
     --o11y-api-token-file /tmp/sfx_api
   ```

   Mutating apply (tests, alert_rules, labels, tags, te_dashboards, templates) requires `--i-accept-te-mutations`.

## Per-test-type metric coverage (TE OpenTelemetry Data Model v2)

| TE test type | Canonical metrics |
|--------------|-------------------|
| `agent-to-server` / `agent-to-agent` | `network.latency`, `network.loss`, `network.jitter` |
| `http-server` | `http.server.request.availability`, `http.server.throughput`, `http.client.request.duration` |
| `page-load` | `web.page_load.duration`, `web.page_load.completion` |
| `web-transactions` | `web.transaction.duration`, `web.transaction.errors.count`, `web.transaction.completion` |
| `api` / `api-step` | `api.duration`, `api.completion`, `api.step.duration`, `api.step.completion` |
| `bgp` | `bgp.path_changes.count`, `bgp.reachability`, `bgp.updates.count` |
| `dns-server` / `dns-trace` | `dns.lookup.availability`, `dns.lookup.duration` |
| `dnssec` | `dns.lookup.validity` |
| `voice` (RTP-stream) | `rtp.client.request.{mos,loss,discards,duration,pdv}` |
| `sip-server` | `sip.server.request.availability`, `sip.client.request.duration`, `sip.client.request.total_time` |
| `ftp-server` | `ftp.server.request.availability`, `ftp.client.request.duration`, `ftp.server.throughput` |

All charts are filtered by `thousandeyes.account.id` and `thousandeyes.test.id`.

## Hand-offs

- Dashboards: `scripts/handoff-dashboards.sh` emits the exact `splunk-observability-dashboard-builder` invocation.
- Detectors: `scripts/handoff-detectors.sh` emits the exact `splunk-observability-native-ops` invocation.
- TE MCP registration: `scripts/handoff-mcp.sh` emits the `cisco-thousandeyes-mcp-setup` invocation.
- Splunk Platform TA: `scripts/handoff-ta.sh` emits the `cisco-thousandeyes-setup` invocation.

See `reference.md` for option details and the `references/` annexes for the per-test-type catalog, TE Templates, alert rules, Integrations 2.0 APM, dashboards catalog, and SignalFlow validation.

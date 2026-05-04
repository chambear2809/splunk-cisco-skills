# Splunk Observability ThousandEyes Integration Reference

## Source guidance

- TE OpenTelemetry Data Model v2 metrics catalog: `docs.thousandeyes.com/product-documentation/integration-guides/opentelemetry/data-model/data-model-v2/metrics`
- TE Streams API v7 schema: `developer.cisco.com/docs/thousandeyes/stream/`
- TE TestMatch + FiltersTestTypes: `developer.cisco.com/docs/thousandeyes/testmatch`, `.../filterstesttypes`
- TE Tests API v7 (per-type endpoints): `developer.cisco.com/docs/thousandeyes/tests-api-model-tests`
- TE Templates API v7: `developer.cisco.com/docs/thousandeyes/create-template`
- TE Dashboards API v7: `developer.cisco.com/docs/thousandeyes/dashboards-api-overview`
- TE Alert Rule template (used by Templates): `developer.cisco.com/docs/thousandeyes/alertruleconfigurationtemplate`
- Private reference implementation (RTSP demo) was used during initial development; its scripts were canonicalized into this skill's renderer and the per-test-type SignalFlow templates. No machine-local path dependency.

## Rendered layout

By default, assets are written under `splunk-observability-thousandeyes-rendered/`:

- `te-payloads/stream.json` — `POST /v7/streams` body.
- `te-payloads/connector.json` — Integrations 2.0 generic connector.
- `te-payloads/apm-operation.json` — `splunk-observability-apm` operation assignment.
- `te-payloads/tests/<slug>.json` — per-test creation bodies.
- `te-payloads/tests/_index.json` — index that maps slug → test type so apply-tests.sh can route.
- `te-payloads/alert-rules/<slug>.json` — `POST /v7/alerts/rules` bodies.
- `te-payloads/labels/<slug>.json` — `POST /v7/labels` bodies.
- `te-payloads/tags/<slug>.json` — `POST /v7/tags` bodies.
- `te-payloads/te-dashboards/<slug>.json` — `POST /v7/dashboards` bodies.
- `te-payloads/templates/<slug>.json` — `POST /v7/templates` bodies (Handlebars placeholders only).
- `dashboards/<test_type>.signalflow.yaml` — SignalFlow specs (consumable by `splunk-observability-dashboard-builder`).
- `detectors/<test_type>.yaml` — starter detector specs (consumable by `splunk-observability-native-ops`).
- `scripts/apply-stream.sh`, `apply-apm-connector.sh`, `apply-tests.sh`, `apply-alert-rules.sh`, `apply-labels-tags.sh`, `apply-te-dashboards.sh`, `apply-template.sh`.
- `scripts/list-account-groups.sh`, `list-agents.sh`, `list-tests.sh`, `list-templates.sh`, `validate-signalflow.sh`.
- `scripts/handoff-dashboards.sh`, `handoff-detectors.sh`, `handoff-mcp.sh`, `handoff-ta.sh`.
- `metadata.json`.

## Setup modes

`setup.sh` supports these mode flags:

- `--render` — render artifacts (default).
- `--apply [SECTIONS]` — render then apply selected sections. Sections: `stream, apm, tests, alert_rules, labels, tags, te_dashboards, templates`. With no list, applies all.
- `--validate` — run static validation against an already-rendered output directory.
- `--dry-run` — show the plan without writing files.
- `--json` — emit JSON dry-run output.
- `--explain` — print plan in plain English (no API calls or writes).

## Required values

`--spec PATH` is always required.

`--realm` is read from `spec.realm` if not passed on the command line; one or the other is required.

For `--apply stream` you also need `--te-token-file` and `--o11y-ingest-token-file`. For `--apply apm` you need `--te-token-file` and `--o11y-api-token-file`. For all other apply sections you need `--te-token-file` and `--i-accept-te-mutations`.

## Secret handling

Three file-backed token flags:

- `--te-token-file` — TE bearer token (Streams + Tests + Alert Rules + Labels + Tags + Dashboards + Templates).
- `--o11y-ingest-token-file` — Splunk Observability **Org access token** with ingest authorization (used as `X-SF-Token` in the OTLP metric stream `customHeaders`).
- `--o11y-api-token-file` — Splunk Observability **User API access token** (used as `X-SF-Token` in the Integrations 2.0 APM connector and SignalFlow validate calls).

Rejected direct-secret flags: `--te-token`, `--access-token`, `--token`, `--bearer-token`, `--api-token`, `--o11y-token`, `--sf-token`. Each error message points at the matching `--*-token-file` flag.

The renderer never reads token files. Apply scripts read tokens from chmod-600 files at runtime through curl config or payload-substitution helpers, so secrets never enter argv or rendered files.

TE Templates render with **Handlebars placeholders only** (`{{te_credentials.api_key}}` style). The TE API rejects plain-text credentials with HTTP 400; the renderer catches this at render time so the operator gets a clear error before the network call.

## Test selection (stream)

Three modes (use exactly one):

- `stream.test_match: [{id, domain: cea|endpoint}, ...]` — explicit IDs. `domain=cea` for Cloud + Enterprise Agent tests, `domain=endpoint` for Endpoint Experience tests.
- `stream.filters.test_types: [http-server, agent-to-server, ...]` — any combination of canonical TE OTel v2 types.
- `stream.mode: all` — omit testMatch entirely; stream every enabled test in the account group.

## Apply sequence (when `--apply` is used without an explicit section list)

1. `stream` — POST `/v7/streams` (or PUT if `TE_STREAM_ID` env var set).
2. `apm` — POST `/v7/connectors/generic`, then PUT `/v7/operations/splunk-observability-apm/<connector_id>` to enable the operation.
3. `tests` — POST `/v7/tests/<type>` for each test entry (gated by `--i-accept-te-mutations`).
4. `alert_rules` — POST `/v7/alerts/rules` (gated by `--i-accept-te-mutations`).
5. `labels` and `tags` — POST `/v7/labels` and POST `/v7/tags` (gated by `--i-accept-te-mutations`).
6. `te_dashboards` — POST `/v7/dashboards` (gated by `--i-accept-te-mutations`).
7. `templates` — POST `/v7/templates` and (when `--deploy-templates`) POST `/v7/templates/<id>/deploy` (gated by `--i-accept-te-mutations`).

## SignalFlow handoff

The rendered `dashboards/<test_type>.signalflow.yaml` files use `${ACCOUNT_GROUP_ID}` and `${TEST_ID}` placeholders so the dashboard-builder skill can substitute per dashboard. See `references/dashboards-catalog.md` for the per-test-type chart catalog.

## Detector handoff

The rendered `detectors/<test_type>.yaml` files include the starter detector definitions for hand-off to `splunk-observability-native-ops`. The thresholds come from `spec.detectors.thresholds.<test_type>`; if a threshold is missing, the corresponding detector is skipped.

Deep-dive annexes:

- `references/test-types-catalog.md` — canonical TE OTel v2 metric set per test type
- `references/te-templates.md` — Templates authoring (Handlebars-only credentials)
- `references/te-alert-rules.md` — Alert Rule authoring + per-test-type starter rules
- `references/integrations-2-apm.md` — APM connector flow (User API token scope)
- `references/dashboards-catalog.md` — SignalFlow chart specs per test type
- `references/signalflow-validation.md` — WebSocket-based dry-run validation pattern
- `references/troubleshooting.md` — common failure modes (auth, stream lifecycle, MTS budget)

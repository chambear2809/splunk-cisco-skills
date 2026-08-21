# Galileo Platform Setup Reference

This reference covers an already-running Galileo application platform. Use
`galileo-on-prem-kubernetes-setup` for Kubernetes installation, upgrades,
rollback, uninstall, CRDs, storage, routing, registry, Wizard GPU
infrastructure, packaged Agent Control, or Luna Studio deployment.

## Official References

- Galileo overview: `https://docs.galileo.ai/what-is-galileo`
- Galileo REST API overview: `https://docs.galileo.ai/api/getting-started`
- Galileo Python SDK projects: `https://docs.galileo.ai/sdk-api/python/reference/projects`
- Galileo Python SDK log streams: `https://docs.galileo.ai/sdk-api/python/reference/log_streams`
- Galileo datasets: `https://docs.galileo.ai/sdk-api/experiments/datasets`
- Galileo prompts: `https://docs.galileo.ai/sdk-api/experiments/prompts`
- Galileo experiments: `https://docs.galileo.ai/sdk-api/python/reference/experiments`
- Galileo experiment groups:
  `https://docs.galileo.ai/sdk-api/experiments/experiment-groups`
- Galileo AI Assistant beta: `https://docs.galileo.ai/concepts/ai-assistant`
- Galileo generic alert webhooks:
  `https://docs.galileo.ai/how-to-guides/basics/set-up-alerts-on-logs#generic-webhook-notifications`
- Galileo release notes through August 7, 2026:
  `https://docs.galileo.ai/release-notes`
- Splunk Agent Observability documentation for customers onboarded after
  August 7, 2026: `https://agent-observability-docs.splunk.com`
- Galileo OpenTelemetry/OpenInference: `https://docs.galileo.ai/sdk-api/third-party-integrations/opentelemetry-and-openinference`
- Galileo multimodal observability:
  `https://docs.galileo.ai/concepts/logging/multimodal-observability`
- Galileo multimodal quality metrics:
  `https://docs.galileo.ai/concepts/metrics/multimodal-quality/multimodal-quality-overview`
- Galileo Agent Control target resolution: `https://docs.galileo.ai/sdk-api/python/reference/agent_control`
- Galileo Agent Observability Controls: `https://docs.galileo.ai/how-to-guides/agent-control/create-a-control`
- Galileo control monitoring: `https://docs.galileo.ai/how-to-guides/agent-control/monitor-a-control`
- Galileo export records API: `https://docs.galileo.ai/api-reference/trace/export-records`
- Galileo agentic metrics: `https://docs.galileo.ai/concepts/metrics/agentic/agentic-overview`
- Galileo Protect invoke API: `https://docs.galileo.ai/api-reference/protect/invoke`
- Splunk HEC REST endpoints:
  `https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-enterprise/http-event-collector-rest-api-endpoints`
- Splunk HEC event format:
  `https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-enterprise/format-events-for-http-event-collector`

Re-check these docs before changing endpoint paths, header names, exporter
schema, HEC envelope shape, or collector handoff flags.

## Apply Sections

Operational apply is supported only when `--tenant-onboarding-date` (or
`galileo.onboarding_date`) is a valid date before `2026-08-07`. A missing date,
the exact boundary date, or a later date produces a complete render/validation
packet but blocks all apply sections. The post-boundary product uses Splunk
Agent Observability names and contracts that are not implemented by these
legacy Galileo helpers. The generated wrappers enforce the same gate even when
run directly. `cleanup-object-lifecycle.sh` is the sole exception so an
existing exact-ID ownership ledger remains recoverable.

The copied Python lifecycle, export, and Luna helpers are internal
implementation details behind the guarded wrappers; do not treat them as
independent public apply entry points. The alert relay is a standalone helper:
its handoff emits a runnable launch command only for a verified pre-boundary
tenant and is explicitly render-only for every blocked epoch.

| Section | Owner | Purpose |
| --- | --- | --- |
| `readiness` | `galileo-platform-setup` | Render endpoint derivation, `/v2/healthcheck`, auth/RBAC/Luna/Protect/Evaluate coverage checks. |
| `object-lifecycle` | `galileo-platform-setup` | Create or validate Galileo projects, log streams, datasets, prompts, experiments, metrics, Protect stages, and Agent Control target resolution. |
| `luna-scorers` | `galileo-platform-setup` | Inventory Luna/SLM scorers, PATCH log-stream metric settings for mapped scorers, preserve unavailable targets, and optionally recompute metrics. |
| `observe-export` | `galileo-platform-setup` | Pull Galileo records through `export_records` and send HEC JSON events. |
| `observe-runtime` | `galileo-platform-setup` | Provide Python and Kubernetes OTel/OpenInference bootstrap snippets. |
| `protect-runtime` | `galileo-platform-setup` | Provide a legacy Python `/v2/protect/invoke` helper for existing Protect users. |
| `evaluate-assets` | `galileo-platform-setup` | Render Evaluate, experiment, dataset, metric, annotation, feedback, Signals, and Trends handoffs. |
| `multimodal-assets` | `galileo-platform-setup` | Render multimodal logging, quality metric, Splunk metadata-only export, and validation-search handoffs. |
| `observability-controls` | `galileo-platform-setup` | Render Galileo Agent Observability Controls console inventory, Log stream attachment, control-span export, and Splunk search handoffs. |
| `splunk-hec` | `splunk-hec-service-setup` | Prepare Splunk HEC service/token configuration. |
| `splunk-otlp` | `splunk-connect-for-otlp-setup` | Configure the Splunk Platform OTLP receiver and sender handoff assets. |
| `otel-collector` | `splunk-observability-otel-collector-setup` | Render Splunk OTel Collector Kubernetes/Linux assets. |
| `dashboards` | `splunk-observability-dashboard-builder` | Render/apply Observability dashboard specs. |
| `detectors` | `splunk-observability-native-ops` | Render/apply Observability detector specs. |

## Splunk Observability Cloud-only Mode

Use `--o11y-only` when Galileo telemetry should go to Splunk Observability
Cloud without pairing the workflow to Splunk Platform HEC. In this mode, a
default render/apply selects only:

- `readiness`
- `object-lifecycle`
- `luna-scorers`
- `otel-collector`
- `dashboards`
- `detectors`

The runtime snippets and console-only Evaluate, multimodal, and observability
control assets remain in the rendered packet. They are excluded from the
default apply set because they need workload-specific inputs or an explicit
operator handoff.

Explicit Splunk Platform sections (`observe-export`, `splunk-hec`,
`splunk-otlp`) are rejected when `--o11y-only` is set.

## Galileo Object Lifecycle

Use `object-lifecycle` before Observe exports or runtime handoff when a new
tenant/project needs isolated Galileo assets. The apply wrapper reads only
`--galileo-api-key-file`, sets `GALILEO_CONSOLE_URL` and API-base environment
variables for custom deployments, and runs `scripts/galileo_object_lifecycle.py`.

Lifecycle inputs:

- `--lifecycle-manifest`: primary YAML/JSON manifest for all Galileo objects.
- `--dataset-dir`: directory of `.json`, `.jsonl`, or `.csv` datasets to create.
- `--prompt-manifest`: list or mapping of prompt templates to create.
- `--experiment-manifest`: experiment definitions; `mode: create_only` is the
  safe default, while `mode: run` opts into executing an SDK experiment.
- `--protect-stage-manifest`: Protect stage definitions; stages are created
  only where `create: true`.
- `--metrics`: comma-separated built-in metric names to enable on the log
  stream or attach to experiment definitions.
- `--ownership-ledger`: path for the mode-`0600` exact-ID ledger written after
  each created object; defaults beside the lifecycle result.
- `--cleanup-created`: delete only objects proven by that ledger. Datasets are
  deleted by exact ID with project-association validation, prompts by exact ID,
  and then an owned project by exact ID and verified absent. Creation fails
  closed for Log streams, experiments, and Protect stages in a pre-existing
  project because those SDK surfaces expose no documented exact delete.

Dataset lookup and creation use `project_id` (or `project_name` when no ID is
available). `update_existing: true` appends rows as a new Galileo dataset
version and is explicitly non-reversible; cleanup never claims to roll it back.
An explicit Log stream ID must be paired with its name because Galileo SDK
2.4.0 exposes project-scoped name lookup; the returned object must match the
requested ID exactly. Project or Log stream setup failure stops metrics and all
child-object calls. Configured metrics fail closed on a pre-existing Log stream;
they are enabled only when that stream was created by the same ownership ledger,
so existing scorer settings are never replaced without captured restore state.

Rendered lifecycle assets:

- `lifecycle/object-lifecycle-manifest.example.json`
- `lifecycle/luna-scorer-map.example.json`
- `lifecycle/product-coverage-matrix.json`
- `lifecycle/product-coverage-matrix.md`
- `scripts/apply-object-lifecycle.sh`
- `scripts/cleanup-object-lifecycle.sh`
- `scripts/apply-luna-scorers.sh`
- `scripts/galileo_object_lifecycle.py`
- `scripts/galileo_luna_scorers.py`

Experiment entries accept `experiment_group` and `experiment_group_id` with
Galileo Python SDK 2.2.0 or later. A name can create its group on demand; an ID
must already resolve in the project. When both are supplied, the SDK gives the
ID precedence. Group listing/filtering, moving existing experiments, and
weighted rankings are covered by the rendered operator handoff.

## Luna Scorer Settings

Use `luna-scorers` after `object-lifecycle` has created or validated the
project and log stream. The default `lifecycle/luna-scorer-map.example.json`
maps common LLM-backed preset metric names to matching Luna/SLM preset names
where the tenant exposes them. Missing targets are preserved by default so a
partial tenant rollout does not remove existing columns.

Operator controls:

- `--luna-list-only true`: inventory current log-stream scorers and available
  SLM scorers without PATCHing metric settings.
- `--luna-scorer-map PATH`: provide a JSON map with `replacements` entries of
  `{ "from": "metric_name", "to": "metric_name_luna" }`.
- `remove: true`: optional replacement flag to drop a known-bad scorer from
  metric settings when no replacement should be enabled.
- `custom_luna_scorer_ids`: optional entries in the map with `from`, `to_id`,
  `scorer_type`, and `model_type` for custom registered Luna scorer IDs.
- `--luna-strict true`: fail instead of preserving a scorer when a requested
  Luna target is unavailable.
- `--luna-recompute true`: call Galileo recompute-metrics for attached scorer
  IDs after a successful settings update.

Product coverage surfaces tracked in the matrix:

- API keys, auth modes, users, groups, project/dataset/integration
  collaborators, and RBAC
- REST API base URL derivation, custom deployment routing, and healthcheck
  validation
- SSO/OIDC/SAML and enterprise identity readiness
- Projects and RBAC/project-sharing handoff
- Log streams and metric enablement
- Datasets, dataset versions, sharing, prompt-evaluation datasets, and
  synthetic extension
- Dataset query, preview, content mutation/upsert, bulk delete guardrails, and
  synthetic extension status polling
- Prompts, prompt-version review, prompt-template rendering, and TypeScript
  prompt utility handoffs
- Experiments, experiment groups, tags, comparison, search, metric settings,
  available columns, metrics APIs, paginated search, and optional experiment
  runs
- AI Assistant beta enterprise/LLM-integration readiness, organization-wide
  debugging, signal criticality ordering, evidence-link verification,
  read-only limitations, and reviewed remediation handoff
- Organization-wide global dashboards across projects and Log streams, with a
  console evidence workflow and explicit public global-CRUD API gap
- Generic alert webhooks with auth-mode review, payload v1.0 schema,
  at-least-once relay delivery, downstream Splunk `event_id` deduplication,
  `dedup_key` lifecycle correlation, metadata routing, test-event validation,
  and a Bearer-to-Splunk-HEC relay
- Playground and experiment processing for datasets with thousands of rows,
  using Galileo-managed batching, async progress evidence, and paginated reads
  without an invented client batch-size control or maximum
- Evaluate experiments and agentic workflow runs
- Python and TypeScript SDK parity, Observe/Evaluate workflow classes, package
  versioning, and runtime package handoffs
- Metric taxonomy across agentic, RAG, response-quality, safety/compliance,
  expression/readability, model-confidence, multimodal-quality, text-to-SQL,
  and Autotune/metric-improvement handoffs
- Evaluate metrics, built-in scorers, custom scorers, scorer validation, and
  scorer settings
- Scorer governance including Autogen LLM scorers, multipart validation, scorer
  RBAC/scope, version restore, and scorer health-score read/write handoffs
- Luna Enterprise, model/provider integrations, model aliases, Model Pricing,
  Integration Costs, organization Billing Usage, and pricing readiness
- Luna-2 fine-tuning, Luna metric evaluation, experiment use, and feature
  availability readiness
- Luna Studio UI and SDK training lifecycle across datasets, test/training sets,
  config files, run lifecycle, output artifacts, registration, and full
  session/trace/RAG/tool/retriever tutorials
- Provider integration selection/status, named custom providers, Vegas Gateway,
  Databricks catalog/database helpers, and integration collaborator handoffs
- Observe traces, sessions, spans, OpenTelemetry, and OpenInference
- Tags, metadata, run labels, and filter hygiene for sessions, traces, spans,
  prompt runs, and Splunk fields
- Enterprise data retention, TTL, redacted inputs/outputs, PII/privacy
  controls, and compliance handoffs
- Trace query, columns, recompute, update, delete, and organization-job
  maintenance handoffs
- Trace metrics APIs, custom metrics, count endpoints, partial queries,
  aggregated trace view, create-session, and live log-spans/log-traces API
  handoffs
- Agent Graph, Logs UI, Messages UI, large-log filtering, and console
  debugging views
- Distributed tracing and multi-service trace propagation
- Multimodal observability for images, audio, and documents
- Multimodal quality metrics for Visual Quality, Visual Fidelity, and
  Interruption Detection, plus the eight out-of-the-box text, image/PDF, and
  audio metric variants released July 21, 2026
- Third-party framework integrations and wrappers including A2A, CrewAI,
  Google ADK, LangChain/LangGraph, Microsoft Agent Framework, OpenAI,
  OpenAI Agents SDK, Mastra, Pydantic AI, Strands Agents, Vercel AI SDK,
  custom spans, OpenInference, AWS Bedrock inference profiles, Gemini
  Enterprise credentials, LangGraph Command/Send, LangChain middleware, and
  LangChain/LangGraph runtime protection
- MCP tool-call logging and tool spans
- Galileo alerts, email notifications, Slack webhooks, Trace Count system
  metric alerts, and Splunk detector mapping, plus generic webhook delivery
  through the rendered HEC relay
- Protect stages, rules, rulesets, actions, notifications, and invocation
  runtime
- Agent Control log stream target resolution
- Agent Observability Controls dashboard, Log stream control attachment, control
  span evidence, and Splunk field mapping. Public Galileo v2 OpenAPI does not
  currently expose documented control CRUD endpoints, so control creation and
  attachment remain console/operator actions in this skill.
- Annotation templates, ratings, generally available Annotation Queues,
  feedback templates, feedback ratings, Signals, and Trends
  dashboards/widgets/sections
- Run insights, health scores, token usage, search, runs, traces SDK utilities,
  decorators, handlers, and wrappers
- Jobs, async tasks, validation status, and progress polling
- Enterprise deployment, system users/social users, organization jobs, and
  delete-by-metadata guardrails
- Galileo MCP Server and IDE developer tooling
- Playgrounds, sample projects, unit-test experiments, and CI experiment gates
- Official cookbooks, use-case guides, starter examples, and applied agent/RAG
  playbooks
- Error catalog, troubleshooting, and project-key diagnostics
- Release notes and version compatibility
- Splunk HEC, OTLP, OTel Collector, dashboards, and detectors

## Galileo REST Export

The bridge script uses:

- `POST /v2/projects/{project_id}/export_records`
- `root_type`: `session`, `trace`, or `span`
- `export_format`: `jsonl` by default; current API options are `jsonl`,
  `jsonl_flat`, and `csv`
- `redact`: `true` by default
- optional `export_computed_metrics_only`; Galileo rejects this with
  `jsonl_flat`, so use `jsonl` or `csv`
- optional `include_code_metric_metadata` for reviewed code-scorer metadata
- optional `log_stream_id`, `experiment_id`, and `metrics_testing_id`

The Splunk event defaults are:

- `source=galileo`
- `sourcetype=galileo:observe:json`
- `index=galileo`

Preferred record fields:

- `galileo_record_key`
- `galileo_project_id`
- `galileo_log_stream_id`
- `galileo_record_id`
- `galileo_record_type`
- `galileo_trace_id`
- `galileo_session_id`
- `galileo_parent_id`
- `metrics`
- `metric_info`
- `feedback_rating_info`
- `annotations`
- `control_info`
- `galileo_control_name`
- `galileo_control_step_type`
- `galileo_control_action`
- `galileo_control_stage`
- `galileo_control_source`
- `redacted_input`
- `redacted_output`

Raw prompt/response fields are excluded unless the operator explicitly passes
`--include-raw` to the bridge script and confirms Splunk is an approved
destination. Unknown CSV columns are also excluded without that approval;
computed `metrics/…` columns remain eligible for the metadata-only path. The
terminal sample is always metadata-only, even when raw fields are approved for
delivery to Splunk.

## Current Release Assets Through August 7, 2026

The latest readiness contract is
`readiness/galileo-2026-08-07-readiness.json`, with the operator summary in
`readiness/galileo-2026-08-07-handoff.md`. It covers the July 21, August 4, and
August 7 releases:

- Select `docs.galileo.ai` for customers onboarded before August 7, 2026.
  Exact-boundary, later, and unknown tenants are render-only: use
  `agent-observability-docs.splunk.com` to assess the implementation gap, but
  do not run this skill's legacy operational apply path.
- Treat Annotation Queues as generally available and validate queue,
  template, reviewer, record, and export access through
  `evaluate/annotation-feedback-handoff.md`.
- Keep AI Assistant beta read-only across its expanded debugging surfaces and
  verify signal criticality and evidence against the underlying records.
- Review, test, and version every AI-generated custom code scorer before
  publishing it.
- Reconcile Model Pricing, Integration Costs, and organization Billing Usage
  for traces, spans, and Luna tokens.
- Configure Trace Count alerts per Log stream and validate trigger and clear
  delivery through the rendered notification path.
- Validate all eight out-of-the-box metric variants across text, image/PDF,
  and audio using `evaluate/multimodal-metrics-handoff.yaml`.
- Treat GPT 5.6 Sol, Terra, and Luna availability as tenant state and the
  light/dark/system theme as an operator preference.

## Historical July 7, 2026 Release Assets

The release-specific readiness contract is
`readiness/galileo-2026-07-07-readiness.json`. Companion assets are:

- `evaluate/ai-assistant-handoff.md`
- `evaluate/experiment-groups-and-scaling-handoff.md`
- `dashboards/galileo-global-dashboard-handoff.md`
- `alerts/generic-webhook-handoff.md`
- `alerts/galileo-alert-webhook-payload.example.json`
- `scripts/galileo_alert_webhook_relay.py`
- `splunk-platform/galileo-alert-hec-event.example.json`
- `splunk-platform/galileo-alert-webhook-search-examples.spl`

AI Assistant and global dashboards are console/evidence workflows because no
public automation API is documented for either surface. The alert relay is
needed because Galileo's generic token mode sends `Authorization: Bearer`,
while Splunk HEC requires `Authorization: Splunk`. Both relay credentials must
come from mode-0600 files. Expose the loopback listener only through an
operator-owned HTTPS reverse proxy and validate a Galileo test event end to end.
The export bridge and alert relay both require HTTPS for non-loopback HEC URLs,
reject credentials and ambiguous URL components, and refuse HTTP redirects.
Plaintext non-loopback HEC requires the explicit
`--allow-insecure-hec-http` review override. The export bridge verifies HTTPS
certificates and hostnames by default; the separate
`--accept-insecure-hec-tls` flag is the explicit, reviewed escape hatch for a
lab HTTPS endpoint with an untrusted certificate.

## Codex Notify Runtime Logging

Use this pattern when the agent being instrumented is Codex itself and the
operator expects completed interactive turns to appear in a Galileo Observe log
stream.

Galileo MCP and Galileo logging are separate:

- Galileo MCP lets Codex call Galileo tools.
- It does not automatically mirror Codex turns into Galileo Observe.
- A Codex `notify` bridge is needed for post-turn logging.

The bridge should run after `turn-ended`, parse the completed turn from the
local Codex session JSONL, and write one trace to Galileo direct ingest:

```text
POST /v2/projects/{project_id}/traces
```

Recommended payload fields:

- `log_stream_id`: target coding-agent log stream
- `logging_method`: `api_direct`
- `reliable`: `true`
- `include_trace_ids`: `true`
- `session_external_id`: Codex session ID
- trace `name`: `codex.turn`
- trace `tags`: `codex`, `codex-cli`, `turn-ended`
- child spans: one `llm` span for the turn and `tool` / `retriever` spans for
  tool calls or web-search events when present

Use `redacted_input` and `redacted_output` when sending captured content.
Prompt, response, tool argument, and tool output capture requires explicit
operator acceptance; otherwise prefer metadata-only placeholders.

`user_metadata` values must be strings. Convert counts, booleans, numeric IDs,
and similar values before sending. Non-string metadata values can produce HTTP
`422` validation errors.

Keep the notifier fail-soft:

- read the Galileo key from `GALILEO_API_KEY_FILE`
- never pass API keys on argv
- redact obvious secrets, bearer tokens, JWTs, and high-entropy strings
- maintain a local duplicate-suppression state file such as
  `CODEX_HOME/log/codex-galileo-emitted-turns.json`
- write local non-secret failure evidence to
  `CODEX_HOME/log/codex-galileo-notify.log`
- exit `0` if Galileo is unavailable so telemetry cannot block Codex

Verify that a turn is stored, not merely accepted, by filtering on the returned
trace ID:

```text
POST /v2/projects/{project_id}/traces/count
POST /v2/projects/{project_id}/export_records
```

Expected proof:

- ingest returns `records_count`, `traces_count`, `spans_count`, and
  `trace_ids`
- count returns `total_count >= 1`
- export returns one JSONL trace whose `id` matches the returned trace ID

## Multimodal Observability

Rendered assets:

- `multimodal/multimodal-observability.md`
- `multimodal/multimodal-intake.example.json`
- `evaluate/multimodal-metrics-handoff.yaml`
- `splunk-platform/multimodal-search-examples.spl`

Use GalileoLogger for external media URLs or local file uploads, and use the
LangChain/LangGraph handler when multimodal content already flows through
LangChain messages. OpenTelemetry/OpenInference snippets remain useful for
trace context and span telemetry, but they do not carry multimodal attachments
by themselves.

The Splunk bridge keeps `redact=true` by default and emits safe metadata:
modality names, input/output modality sets, asset counts, MIME types, dimensions
or duration/page counts where present, and multimodal metric names/results.
Raw base64 payloads, bytes, media URLs, and document text stay out of Splunk by
default. Treat `--include-raw` as a separate data-governance approval, not as a
normal multimodal setup step.

If a user says "multimodel" and means comparing more than one model, use the
Evaluate and experiment assets instead: run the same dataset and metric set
across model variants, preserve model/provider/prompt-version tags, and compare
the resulting experiment groups.

## Agent Observability Controls

Use `observability-controls` for the Galileo console Controls surface shown in
Agent Observability. The skill renders:

- `controls/agent-observability-controls.md`
- `controls/control-intake.example.json`
- `controls/splunk-search-examples.spl`

The handoff tracks control name, step, stage, execution, source, action,
selector path, evaluator, threshold, owner, and enabled state. Because the
public OpenAPI currently lacks documented control CRUD endpoints, this skill
does not create or mutate controls. Export `span` records through
`observe-export` to capture control-span evidence where Galileo includes it.

## HEC Event Shape

Use `/services/collector/event` for JSON objects. The `event` field is a JSON
object, while `fields` is optional and flat:

```json
{
  "time": 1770000000.0,
  "source": "galileo",
  "sourcetype": "galileo:observe:json",
  "index": "galileo",
  "event": {
    "galileo_record_key": "project:log-stream:trace:record",
    "galileo_record_type": "trace",
    "redacted_input": "<redacted>",
    "redacted_output": "<redacted>"
  }
}
```

## Troubleshooting

- Galileo 401/403: verify the API key file, project permissions, API base, and
  project sharing.
- Galileo empty results: verify project ID, log stream ID, root type, export
  filters, and `log_stream_id`/`experiment_id`/`metrics_testing_id`.
- Splunk 401/403: verify the HEC token file, token enablement, allowed indexes,
  and HEC URL.
- Splunk 400: verify the HEC URL ends in `/services/collector/event`, the
  payload has an `event` key, and indexed fields are flat.
- Duplicate events: search by `galileo_record_key`; use a cursor file for
  scheduled jobs.
- Missing prompt/response text: expected unless raw fields were explicitly
  approved and `--include-raw` was used.

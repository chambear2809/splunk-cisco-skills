# Claude Code Instrumentation Reference

## Source Basis

- Claude Code monitoring, environment variables, metrics, log events, and
  traces (beta): `https://code.claude.com/docs/en/monitoring-usage`
- Claude Code `settings.json`, `env` block, and `otelHeadersHelper`:
  `https://code.claude.com/docs/en/settings`
- Splunk Observability Cloud ingest endpoints:
  `https://dev.splunk.com/observability/reference/api/ingest_data/latest`
- Splunk Observability histogram guidance:
  `https://help.splunk.com/en/splunk-observability-cloud/manage-data/metrics-metadata-and-events/metrics-events-and-metadata/get-histogram-data-in`
- Splunk AI Agent Monitoring setup:
  `https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/code-based-instrumentation`
- Galileo Observe OpenTelemetry ingest:
  `https://docs.galileo.ai/integrations/otel`
- Galileo Observe API reference (project, log stream, direct REST fallback):
  `https://docs.galileo.ai/reference`

## Claude Code OTel Environment Variables

Every value below is set through the `env` block of `.claude/settings.json`
(user or project scope) or exported before invoking `claude`. The rendered
`env` file mirrors the same key set.

### Enable Telemetry

| Variable | Values | Notes |
|---|---|---|
| `CLAUDE_CODE_ENABLE_TELEMETRY` | `1` | Required to turn any OTel export on. |
| `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA` | `1` | Required for trace export. |
| `ENABLE_BETA_TRACING_DETAILED` | `1` | Enables detailed beta tracing, including `claude_code.hook` and experimental content-bearing attributes. Base beta tracing emits `llm_request` and `tool` spans on current releases. Interactive detailed tracing can require organization allowlisting. |
| `BETA_TRACING_ENDPOINT` | URL | **Separate** endpoint (distinct from `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`) that detailed beta tracing requires. The skill sets it to the same trace target: the local collector for `local-collector`, the Splunk trace ingest URL for `splunk-direct`. |

### Signal Exporters

| Variable | Values | Notes |
|---|---|---|
| `OTEL_METRICS_EXPORTER` | `otlp`, `none` | Metrics signal. |
| `OTEL_LOGS_EXPORTER` | `otlp`, `none` | Log-event signal. |
| `OTEL_TRACES_EXPORTER` | `otlp`, `none` | Traces signal. Beta. Requires `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`. |

### OTLP Transport

| Variable | Values | Notes |
|---|---|---|
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf`, `http/json`, `grpc` | Applies to every signal unless overridden per signal. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | URL | Base endpoint for every signal. |
| `OTEL_EXPORTER_OTLP_HEADERS` | comma-separated `key=value` | Single global header string. Claude Code offers no per-signal header override. This constraint is what forces dual-destination fan-out through a collector. |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | URL | Per-signal endpoint override. |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | URL | Per-signal endpoint override. |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | URL | Per-signal endpoint override. |
| `OTEL_METRIC_EXPORT_INTERVAL` | milliseconds | Default `60000`. |
| `OTEL_LOGS_EXPORT_INTERVAL` | milliseconds | Default `5000`. |

### Content Capture (opt-in only)

| Variable | Default | Notes |
|---|---|---|
| `OTEL_LOG_USER_PROMPTS` | off | Emit user prompt text in OTLP logs and expose `user_prompt` on detailed trace spans for the Galileo content transform. |
| `OTEL_LOG_ASSISTANT_RESPONSES` | off | Emit assistant response text as an OTLP log event. Requires Claude Code **v2.1.193+**. This flag alone does not populate a trace output field; detailed tracing exposes `response.model_output`, which the Galileo-only transform maps to `output.value`. On supported releases an unset value inherits `OTEL_LOG_USER_PROMPTS`, so the renderer emits `0` explicitly for prompt-only capture. |
| `OTEL_LOG_TOOL_DETAILS` | off | Emit tool argument and result metadata (Bash commands, MCP/skill names, tool input). |
| `OTEL_LOG_TOOL_CONTENT` | off | Emit tool input and output content bodies in span events (requires tracing; truncated at 60 KB). |
| `OTEL_LOG_RAW_API_BODIES` | off | Emit full Messages API request/response JSON as log events with `1`, or write untruncated bodies locally with `file:/absolute/directory`. This implies broad conversation-content consent. |

Enabling any of these requires `--accept-content-capture`. Captured content
flows through the OTLP logs exporter and, under detailed beta tracing, is also
attached to span attributes (`tool_input`, `response.model_output`, etc.), so
it inherits every configured back end (Splunk O11y and Galileo).
Enabling detailed tracing also requires this acceptance because current Claude
Code can add experimental content-bearing span attributes even when individual
log capture flags are off.

Empty `input`/`output` on Galileo traces can mean capture is off, the CLI is
older than v2.1.193, detailed tracing is unavailable, or the Galileo-only
content transform is missing from the trace branch. Trace *structure* depends
on base trace beta; detailed tracing exposes the native content attributes;
the collector then maps those attributes to Galileo/OpenInference fields.

### Metric Cardinality Controls

| Variable | Default | Notes |
|---|---|---|
| `OTEL_METRICS_INCLUDE_SESSION_ID` | `true` | Include `session.id` attribute on metrics. |
| `OTEL_METRICS_INCLUDE_VERSION` | `false` | Include `app.version` attribute on metrics. |
| `OTEL_METRICS_INCLUDE_ACCOUNT_UUID` | `true` | Include `user.account_uuid`. |
| `OTEL_METRICS_INCLUDE_ENTRYPOINT` | `false` | Include entry-point attribute. |
| `OTEL_METRICS_INCLUDE_RESOURCE_ATTRIBUTES` | `true` | Include keys from `OTEL_RESOURCE_ATTRIBUTES` (e.g. the skill's `department`/`team.id`) as per-datapoint metric attributes; set the spec field `metrics_include_resource_attributes: false` to keep them in the OTLP resource block only and cut cardinality. |

### Resource Attributes

| Variable | Notes |
|---|---|
| `OTEL_RESOURCE_ATTRIBUTES` | Comma-separated `key=value` list appended to every signal's resource. Merged with defaults (`service.name`, `service.version`, `os.type`, `os.version`, `host.arch`). The renderer validates keys and percent-encodes values that are invalid in the OTel environment grammar. |

### Settings-Only Keys

| Key | Location | Notes |
|---|---|---|
| `otelHeadersHelper` | top level of `settings.json` (not inside `env`) | Absolute path to an executable that prints OTLP headers as JSON on stdout. Direct mode reads `SPLUNK_O11Y_TOKEN_FILE`; external OTLP/HTTP mode resolves `${NAME}` header values from runtime environment variables. Keeps literal credentials out of settings. Runs at startup and periodically, not per export. |
| `CLAUDE_CODE_OTEL_HEADERS_HELPER_DEBOUNCE_MS` | `env` block | Tuning knob for the `otelHeadersHelper` refresh interval (default ~1740000 ms / ~29 min). Lower it to pick up a rotated token file sooner. |

## Destination Behavior

### Local Collector (default)

Rendered assets:

- `settings/claude-settings.<scope>.local-collector.json` with the `env` block
  pointing at `local_collector_endpoint`.
- `env/claude-code-o11y.local-collector.env` mirroring the same env.
- `collector/claude-code-o11y-local-collector.yaml`.

Endpoint contract:

- Base: `local_collector_endpoint`, default `http://127.0.0.1:14318`.
  Override with `--local-collector-endpoint`.
- Receiver bind: defaults to the client endpoint's host and port for a native
  collector. Set `--collector-receiver-endpoint 0.0.0.0:4318` inside Docker
  while publishing host port `127.0.0.1:14318` to container port `4318`.
- Must be `http://` with an explicit port, no credentials, and no `/v1/...`
  path.
- The renderer sets only the base `OTEL_EXPORTER_OTLP_ENDPOINT` plus
  `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`; the OpenTelemetry SDK appends
  `/v1/<signal>` per signal at export time.
- When detailed beta tracing is explicitly enabled with content-capture
  acceptance, `BETA_TRACING_ENDPOINT` is set to the same base endpoint.
- `OTEL_EXPORTER_OTLP_HEADERS` is left empty. The collector adds Splunk and
  Galileo auth on the egress side.

### Splunk Direct

Rendered assets:

- `settings/claude-settings.<scope>.json` with the `env` block plus the
  top-level `otelHeadersHelper` key pointing at
  `bin/claude-code-otel-headers.sh`.
- `env/claude-code-o11y.splunk-direct.env` mirroring the same env (helper
  path is emitted as a comment; env-mode operators must invoke the helper
  themselves).
- `bin/claude-code-otel-headers.sh`.

Endpoint contract:

- metrics: `https://ingest.<realm>.observability.splunkcloud.com/v2/datapoint/otlp`
- logs: `https://ingest.<realm>.observability.splunkcloud.com/v2/log/otlp`
- traces: `https://ingest.<realm>.observability.splunkcloud.com/v2/trace/otlp`
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`. gRPC is refused.
- Auth: `X-SF-TOKEN` header from `otelHeadersHelper`. The helper reads the
  token from the file at `SPLUNK_O11Y_TOKEN_FILE`.
- Galileo trace ingest is refused. Claude Code cannot attach a second auth
  header, and re-using `X-SF-TOKEN` for Galileo is unsafe.

### External Collector

Rendered assets:

- `settings/claude-settings.<scope>.json` with the `env` block pointing at
  the operator-supplied endpoint(s).
- `env/claude-code-o11y.external-collector.env` mirroring the same env.

Endpoint contract:

- Required: `--external-collector-endpoint` or per-signal
  `--external-metric-endpoint`, `--external-log-endpoint`,
  `--external-trace-endpoint`.
- `--external-collector-protocol http/protobuf|http/json|grpc`.
  Compatibility aliases `otlp-http` and `otlp-grpc` are accepted and rendered
  as `http/protobuf` and `grpc`.
- `--external-header KEY=VALUE` appends safe literals or environment
  placeholders. Secret literals are refused. OTLP/HTTP placeholders are
  resolved by `otelHeadersHelper`; gRPC placeholders are rejected because
  Claude's dynamic headers do not apply to gRPC.
- For OTLP/HTTP mTLS, CA/client paths render as `NODE_EXTRA_CA_CERTS`,
  `CLAUDE_CODE_CLIENT_CERT`, and `CLAUDE_CODE_CLIENT_KEY`. For gRPC they render
  as `OTEL_EXPORTER_OTLP_CERTIFICATE`,
  `OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE`, and
  `OTEL_EXPORTER_OTLP_CLIENT_KEY`.
- If an HTTP client key is encrypted, export
  `CLAUDE_CODE_CLIENT_KEY_PASSPHRASE` in the launch environment. The skill does
  not persist passphrases in a spec, settings file, or generated helper.
- No collector overlay is rendered. The operator owns the collector.

### All

Both `local-collector` and `splunk-direct` are rendered side by side under
distinct filenames (`claude-settings.<scope>.local-collector.json` and
`claude-settings.<scope>.splunk-direct.json`). The operator picks which one
to apply. `apply` refuses to write both settings profiles into the same
scope in a single run.

## Metrics Catalog

Claude Code emits eight metrics. Attribute keys listed here are documented on
`https://code.claude.com/docs/en/monitoring-usage`.

| Metric | Type | Key attributes |
|---|---|---|
| `claude_code.session.count` | counter | session-scoped resource attrs only |
| `claude_code.lines_of_code.count` | counter | `type` (`added`/`removed`), `model` |
| `claude_code.pull_request.count` | counter | resource attrs |
| `claude_code.commit.count` | counter | resource attrs |
| `claude_code.cost.usage` | counter (USD) | `model`, `query_source`, `speed`, `effort`, `agent.name`, `skill.name` |
| `claude_code.token.usage` | counter | `type` (`input`/`output`/`cacheRead`/`cacheCreation`), `model`, `query_source` |
| `claude_code.code_edit_tool.decision` | counter | `tool_name`, `decision`, `language` |
| `claude_code.active_time.total` | counter (seconds) | `type` (`user`/`cli`) |

Every metric carries the standard resource attributes below and the enabled
cardinality attributes.

### Where to view the data in Splunk Observability Cloud

Claude Code emits its own native `claude_code.*` **metric** namespace, which is
a different schema from the OpenTelemetry GenAI semantic conventions
(`gen_ai.*`). Two consequences:

- **Metrics** (tokens, cost, sessions, active time) land as `claude_code.*`
  MTS. Find them under **Metrics → Metric Finder** (search `claude_code`),
  filtered by `deployment.environment` (the `--environment` value) and `model`.
  Build fleet dashboards on `claude_code.token.usage`, `claude_code.cost.usage`,
  `claude_code.session.count`, and `claude_code.active_time.total` (hand off to
  `splunk-observability-dashboard-builder`).
- **The prebuilt "AI overview" / AI Agent Monitoring dashboard** reads
  GenAI-convention APM spans (`gen_ai.operation.name = chat`,
  `gen_ai.usage.*`, span kind Client) and identifies agents from span-level
  `gen_ai.agent.name`. Claude Code's native spans do **not** satisfy that shape
  out of the box, so the rendered collector overlay includes a
  `transform/claude_code_genai` processor that maps `llm_request` spans to chat
  spans and marks root `claude_code.interaction` spans as
  `gen_ai.operation.name=invoke_workflow` with `gen_ai.workflow.name` — see
  [Collector Fan-out](#collector-fan-out). It also derives
  `gen_ai.client.operation.duration` from transformed chat spans and
  normalizes cumulative `claude_code.token.usage` input into deltas when needed
  `gen_ai.client.token.usage` histogram. The AI overview Tokens/Cost tiles ignore
  both the native metric name and a counter incorrectly renamed to the GenAI
  name; the metric must be a histogram. The collector and rendered settings stamp `sf_environment`
  explicitly because the AI overview Environment picker uses Splunk's
  environment dimension, not only OTel `deployment.environment`, and the derived
  GenAI metrics are exported through Splunk OTLP metric ingest so those
  dimensions are preserved. With the collector fan-out in place, the AI overview
  populates from Claude Code trace spans plus converted GenAI metrics. In
  `splunk-direct` mode there is no collector to run the
  transform, so the AI overview stays empty; use `local-collector` (or `all`)
  for AI Agent Monitoring.

If `traces.count` contains `chat <model>` operations and Metric Finder shows a
HISTOGRAM `gen_ai.client.operation.duration` plus a HISTOGRAM
`gen_ai.client.token.usage` for the expected `sf_environment`, the Claude and
collector paths are complete. If the AI overview's `count(agents)` stream is
still zero at that point, check **Settings -> AI agent monitoring** and confirm
the organization's conversation data source is **Splunk Observability Cloud**.
The AI overview is unavailable with the Splunk logs data source, so further
collector rewrites do not address that state.

## Events (Log) Catalog

Claude Code emits the log-event names listed here through the OTLP logs
exporter. Content-bearing bodies are gated by the `OTEL_LOG_*` flags in
[Content Capture](#claude-code-otel-environment-variables).

- `claude_code.user_prompt`
- `claude_code.assistant_response`
- `claude_code.tool_result`
- `claude_code.tool_decision`
- `claude_code.api_request`
- `claude_code.api_error`
- `claude_code.api_refusal`
- `claude_code.api_request_body`
- `claude_code.api_response_body`
- `claude_code.api_retries_exhausted`
- `claude_code.permission_mode_changed`
- `claude_code.auth`
- `claude_code.mcp_server_connection`
- `claude_code.internal_error`
- `claude_code.plugin_installed`
- `claude_code.plugin_loaded`
- `claude_code.skill_activated`
- `claude_code.at_mention`
- `claude_code.hook_registered`
- `claude_code.hook_execution_start`
- `claude_code.hook_execution_complete`
- `claude_code.hook_plugin_metrics`
- `claude_code.compaction`
- `claude_code.feedback_survey`

## Traces (Beta) Catalog

Basic traces require `OTEL_TRACES_EXPORTER=otlp` and
`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`. Current Claude Code releases emit the
interaction, LLM request, tool, and nested tool spans under base beta tracing.
Detailed beta tracing (`ENABLE_BETA_TRACING_DETAILED=1` +
`BETA_TRACING_ENDPOINT`) adds hook spans and experimental attributes. Span
hierarchy:

- Root: `claude_code.interaction`
  - Attributes: `user_prompt` (content-gated), `user_prompt_length`,
    `interaction.sequence`, `interaction.duration_ms`.
- Child: `claude_code.llm_request`
  - Attributes: `model`, `gen_ai.system` (`anthropic`),
    `gen_ai.request.model`, `gen_ai.response.id`,
    `gen_ai.response.finish_reasons`, `duration_ms`, `ttft_ms`,
    `input_tokens`, `output_tokens`, `cache_read_tokens`,
    `cache_creation_tokens`, `request_id`. These `gen_ai.*` attributes are
    exactly what Galileo's GenAI-attribute ingest filter looks for.
- Child: `claude_code.tool`
  - Attributes: `tool_name`, `duration_ms`, `tool_use_id`,
    `gen_ai.tool.call.id`.
- Child: `claude_code.hook` *(detailed tracing only)* — hook lifecycle span.
- Nested: `claude_code.tool.blocked_on_user`, `claude_code.tool.execution`.

Content-bearing span attributes (`new_context`, `system_prompt_preview`,
`user_system_prompt`, `tool_input`, `response.model_output`) appear only under
detailed tracing AND with the matching content-capture flag set.

### Galileo Luna span requirements

Galileo Luna span scorers score child spans:

| Scorer | Scores | Needs |
|---|---|---|
| `action_advancement_luna` | the trace as a whole | root span only |
| `completeness_luna` | llm/chat spans | `claude_code.llm_request` |
| `tool_selection_quality_luna` | llm/chat spans | `claude_code.llm_request` |
| `tool_error_rate_luna` | tool spans | `claude_code.tool` |
| `action_completion_luna` | sessions | session grouping |

Detailed tracing is off by default because its experimental attributes can
contain content. Enable it with `--enable-detailed-traces` only alongside
`--accept-content-capture`. On current releases, missing `llm_request` or
`tool` children is not proof that detailed tracing is off. Validate base trace
beta, endpoint routing, Claude Code version, and any interactive allowlisting
before attributing a Luna failure to this flag.

## Standard Attributes

Applied to every signal:

- `session.id`
- `user.id`
- `user.email`
- `user.account_uuid`
- `user.account_id`
- `organization.id`
- `terminal.type`
- `app.version`
- `app.entrypoint` when enabled
- Any keys supplied through `OTEL_RESOURCE_ATTRIBUTES`.

Resource attributes:

- `service.name` (default `claude-code`)
- `service.version` (Claude Code build version)
- `os.type`
- `os.version`
- `host.arch`

`--service-name` overrides `service.name` on the rendered profile.

## Collector Fan-out

The overlay requires a collector distribution that contains the alpha
`signal_to_metrics` connector. It is validated on
`otel/opentelemetry-collector-contrib:0.154.0`. The stock Splunk Distribution
v0.154.2 does not include that connector and therefore cannot produce the token
histogram, although it supports the other components in this overlay. Use the
matching contrib image or a custom build with `signal_to_metrics`; a sum
connector is not an equivalent fallback.

The rendered local collector overlay
(`collector/claude-code-o11y-local-collector.yaml`) contains:

- `receivers.otlp/claude_code`: HTTP receiver bound to
  `collector_receiver_endpoint` when supplied, otherwise to the host and port
  parsed from `local_collector_endpoint`.
- `processors`: `resource/claude_code` (upserts `service.name` /
  `sf_service` from `--service-name` and `deployment.environment` /
  `deployment.environment.name` / `sf_environment` from `--environment`),
  `transform/claude_code_genai`, `filter/claude_code_token_metrics`,
  `transform/claude_code_token_metric_genai`,
  `cumulativetodelta/claude_code_tokens`, and `batch/claude_code`. There is no
  `resourcedetection` processor.
- `processors.transform/claude_code_genai` (traces route only): maps Claude
  Code's native beta span attributes onto the OpenTelemetry GenAI semantic
  conventions that Splunk AI Agent Monitoring and Galileo read. Scoped to
  `span.type == "llm_request"`, it sets `gen_ai.operation.name = chat`, sets
  `gen_ai.system = anthropic` when absent, promotes the span kind to
  `SPAN_KIND_CLIENT`, ensures `gen_ai.request.model`,
  `gen_ai.response.model`, and `gen_ai.provider.name` are present, and copies
  native input/output/cache token values onto the corresponding `gen_ai.usage.*`
  keys, with cached tokens included in the input total. Without this,
  the AI overview's chat-span-count, token, and cost tiles read zero because
  Claude Code omits `gen_ai.operation.name`, emits Internal-kind spans, and uses
  non-`gen_ai` token keys. `error_mode: ignore` keeps a malformed span from
  failing the batch.
- Provider inference recognizes Bedrock ARNs/model IDs and otherwise defaults
  to Anthropic. `--provider-name` overrides ambiguous routes. Repeatable
  `--model-alias SOURCE_MODEL=DISPLAY_MODEL` values normalize opaque provider
  IDs in both spans and token metrics; the generic skill contains no
  tenant-specific inference-profile IDs.
- `connectors.span_metrics/claude_code_genai`: derives the
  `gen_ai.client.operation.duration` histogram from transformed Claude chat
  spans with `unit: s` and the OpenTelemetry seconds-based bucket boundaries.
  Splunk AI Agent Monitoring setup requires histogram metrics for AI pages,
  and this mirrors the Splunk GenAI utility's duration histogram.
- `processors.filter/claude_code_token_metrics` and
  `processors.transform/claude_code_token_metric_genai`: filter native
  `claude_code.token.usage` datapoints, rename them to
  `gen_ai.client.token.usage`, and map Claude's `model` / `type` attributes to
  `gen_ai.request.model` / `gen_ai.token.type`. This path is load-bearing for
  Claude Code versions or model routes where `llm_request` spans omit
  `input_tokens` / `output_tokens`. The original native metric remains
  available in Metric Finder but does not directly populate the prebuilt AI
  overview Tokens/Cost tiles.
- `processors.cumulativetodelta/claude_code_tokens`: converts cumulative token
  sums to increments before histogram observation; Claude's default delta input
  passes through unchanged. Start the collector before a new Claude process so the
  processor's default `initial_value: auto` behavior retains that process's
  first counter value.
- `connectors.signal_to_metrics/claude_code_token_histogram`: observes each
  normalized token increment as a delta `gen_ai.client.token.usage` histogram
  with unit `{token}`, the OpenTelemetry GenAI token bucket boundaries, and the
  model/provider/operation/token-type dimensions used by Splunk AI Agent
  Monitoring. This is intentionally not a sum connector: a sum produces a
  counter that the prebuilt Tokens/Cost views do not read.
- `processors.filter/claude_code_galileo_genai`: used only on the Galileo
  fan-out pipeline after `transform/claude_code_galileo`. It drops spans without
  GenAI semantic-convention attributes and removes `tool.execution`,
  `tool.blocked_on_user`, and hook timing children, so Galileo receives one
  logical Tool span rather than duplicate generic Agent records.
- `processors.transform/claude_code_galileo`: maps root `user_prompt`, LLM
  `new_context`, and `response.model_output` to OpenInference `input.value`,
  `output.value`, and flattened `llm.input_messages` / `llm.output_messages`.
  It dynamically rewrites Claude's compact `tools` name/hash array into one
  minimal `llm.tools.<index>.tool.json_schema` attribute per advertised tool
  plus `gen_ai.tool.definitions`; there is no fixed inventory ceiling. It does
  not fabricate descriptions or argument schemas, because Claude emits those
  in separate log records rather than on the LLM span. The transform promotes
  only the parent `claude_code.tool` span to `execute_tool`, and copies
  `tool_input` plus the `tool.output` span-event result to
  `gen_ai.tool.call.arguments/result`.
  A temporary resource attribute carries the final child response to the root
  interaction within the final OTLP batch and is deleted before export. This
  processor is deliberately not present on the Splunk trace pipeline.
- `exporters.otlp_http/claude_code_traces`: OTLP APM ingest for traces,
  `traces_endpoint: https://ingest.<realm>.observability.splunkcloud.com/v2/trace/otlp`,
  auth `X-SF-TOKEN: ${env:SPLUNK_ACCESS_TOKEN}`.
- `exporters.otlp_http/claude_code_metrics`: OTLP metric ingest for converted
  GenAI token metrics,
  `metrics_endpoint: https://ingest.<realm>.observability.splunkcloud.com/v2/datapoint/otlp`,
  auth `X-SF-TOKEN: ${env:SPLUNK_ACCESS_TOKEN}`.
- `exporters.otlp_http/claude_code_logs`: sends Claude Code logs to
  `https://ingest.<realm>.observability.splunkcloud.com/v2/log/otlp`
  (best-effort; Splunk O11y ingests logs via Log Observer / HEC rather than the
  OTLP logs endpoint).
- `exporters.signalfx/claude_code`: realm-based,
  `access_token: ${env:SPLUNK_ACCESS_TOKEN}`, `send_otlp_histograms: true`.
- `exporters.otlp_http/galileo` (only when Galileo is enabled): the endpoint
  derived from the required user-confirmed `--galileo-console-url`, or supplied
  explicitly via `--galileo-otel-endpoint`. Only the
  `Galileo-API-Key` header uses `${env:GALILEO_API_KEY}`; the `project` and
  `logstream` headers are baked as literal values from `--galileo-project` and
  `--galileo-log-stream`.
- `service.pipelines.metrics/claude_code`:
  `otlp/claude_code -> [resource/claude_code, batch/claude_code] -> signalfx/claude_code`.
- `service.pipelines.logs/claude_code`:
  `otlp/claude_code -> [resource/claude_code, batch/claude_code] -> otlp_http/claude_code_logs`.
- `service.pipelines.traces/claude_code`:
  `otlp/claude_code -> [resource/claude_code, transform/claude_code_genai, batch/claude_code] -> [otlp_http/claude_code_traces, span_metrics/claude_code_genai]`.
- `service.pipelines.traces/claude_code_galileo` (only when Galileo is enabled):
  `otlp/claude_code -> [resource/claude_code, transform/claude_code_genai, filter/claude_code_galileo_genai, batch/claude_code] -> [otlp_http/galileo]`.
- `service.pipelines.metrics/claude_code_genai_duration`: receives
  `span_metrics/claude_code_genai` output and exports
  `gen_ai.client.operation.duration` histograms through
  `otlp_http/claude_code_metrics`.
- `service.pipelines.metrics/claude_code_token_genai`:
  `otlp/claude_code -> [resource/claude_code, filter/claude_code_token_metrics, transform/claude_code_token_metric_genai, cumulativetodelta/claude_code_tokens, batch/claude_code] -> signal_to_metrics/claude_code_token_histogram`.
- `service.pipelines.metrics/claude_code_token_histogram`: receives the
  `signal_to_metrics/claude_code_token_histogram` output and exports the
  histogram through `otlp_http/claude_code_metrics`.

### Shared collectors

If Claude Code shares a single OTLP receiver with Codex or another agent, route
by the signal record, not only the resource envelope:

- Traces: use routing connector entries with `context: span` matching
  `attributes["data.source"] == "claude-code"`,
  `attributes["service.name"] == "claude-code"`, or
  `IsMatch(name, "^claude_code\\.")`. Export the transformed Claude trace
  pipeline to `span_metrics/claude_code_genai` so
  `gen_ai.client.operation.duration` histograms remain reachable.
- Metrics: route `name == "claude_code.token.usage"` to both
  `metrics/claude_code` and `metrics/claude_code_token_genai`, use
  `context: metric` for `IsMatch(name, "^claude_code\\.")`, and use
  `context: datapoint` for datapoint-level `data.source` / `service.name`. The
  token pipeline must export to `signal_to_metrics/claude_code_token_histogram`,
  and `metrics/claude_code_token_histogram` must receive that connector and
  export to `otlp_http/claude_code_metrics`; merely defining the transform or
  connector leaves it unreachable.
- Logs: use `context: log` for log-record attributes.

Resource-only routes are insufficient because current Claude Code beta tracing
can emit `service.name=claude-code` and `data.source=claude-code` on the span or
datapoint while the resource still belongs to the host agent process. The
renderer emits `runtime/shared-collector-routing.md` with a mergeable pattern,
and validation fails known resource-only Claude routes that target
`traces/claude_code`, `metrics/claude_code`, or `logs/claude_code`.
Pass the deployed merged YAML through
`validate.sh --collector-config /path/to/collector.yaml`; validation checks
component references, record-level routes, transform ordering/reachability,
both connector output pipelines, histogram shape, and Splunk OTLP metric
export reachability.

In Docker deployments, keep these network roles separate:

- Claude client endpoint on the host: `http://127.0.0.1:14318`.
- Docker port publication: `127.0.0.1:14318:4318`.
- OTLP receiver bind inside the container: `0.0.0.0:4318`.

Use `--collector-receiver-endpoint 0.0.0.0:4318` when the rendered receiver is
the container receiver.

Do not bind the container receiver to `127.0.0.1:14318`; Docker's published
port cannot reach a service listening only on the container loopback interface.

Secrets in the overlay:

- Splunk access token: `${env:SPLUNK_ACCESS_TOKEN}`.
- Galileo API key: `${env:GALILEO_API_KEY}`.
- Both are populated by the operator's collector wrapper sourcing the
  respective file paths (`SPLUNK_O11Y_TOKEN_FILE`, `GALILEO_API_KEY_FILE`)
  into env vars at process start.

## Dynamic Headers and `otelHeadersHelper`

Claude Code exposes exactly one global `OTEL_EXPORTER_OTLP_HEADERS`. Storing a
literal Splunk access token in that env would put the secret into
`settings.json`, shell history, and process listings.

`otelHeadersHelper` avoids that. It is a top-level `settings.json` key
pointing at an executable. Claude Code runs it at startup and then periodically
to refresh the headers (default debounce ~29 minutes / 1740000 ms; tune with
the `CLAUDE_CODE_OTEL_HEADERS_HELPER_DEBOUNCE_MS` env var), merging the JSON
stdout into the outgoing OTLP headers. Because it is a periodic refresh rather
than a per-export call, after rotating the token file expect up to one debounce
interval before the new token is used. Dynamic headers apply only to the
`http/protobuf` and `http/json` protocols; the gRPC exporter uses only the
static `OTEL_EXPORTER_OTLP_HEADERS`, which is why direct mode pins
`http/protobuf` and refuses gRPC.

The rendered shim `bin/claude-code-otel-headers.sh`:

- Reads the token from the file at `SPLUNK_O11Y_TOKEN_FILE` on each refresh.
  Only the file path is passed to the embedded interpreter; the token value is
  read inside the script and never appears on argv.
- Emits `{"X-SF-TOKEN": "<token>"}` on stdout, exit `0`.
- Emits `{}` and exit `0` when the file is missing or unreadable so a
  temporary secret outage does not break the CLI.
- Redacts any accidental logging of the token.

Applied path: `~/.claude/bin/claude-code-otel-headers.sh` when
`--settings-scope user`, or `<repo>/.claude/bin/claude-code-otel-headers.sh`
when `--settings-scope project`.

For `external-collector` with OTLP/HTTP, a header value in `${NAME}` form is
resolved by the same helper from the Claude process environment. When any
header is dynamic, the helper returns the complete dynamic-plus-literal header
set so the configuration does not depend on undocumented merge behavior.
All-literal sets remain static. The renderer rejects dynamic gRPC header
placeholders because Claude documents dynamic headers as HTTP-only.

## Galileo Integration

Galileo Observe accepts OTLP traces at the ingest endpoint:

- Public Galileo Cloud: after the user confirms
  `https://app.galileo.ai/`, pass it as `--galileo-console-url`; the derived
  endpoint is `https://api.galileo.ai/otel/traces`.
- Non-public Galileo Cloud, Splunk-hosted Agent Observability, or self-hosted:
  pass the exact console URL. The skill supports the documented
  `console.` -> `api.` and `console-` -> `api-` conventions and appends
  `/otel/traces`. Supply `--galileo-otel-endpoint` for other layouts.

Galileo-enabled rendering fails without one of those explicit URLs. This is
intentional because keys are tenant-bound and a public-endpoint fallback can
produce a valid-looking configuration that only returns HTTP 401.

**Tenant match matters:** an API key created in one Galileo tenant is rejected
(HTTP 401 "Invalid credentials") by every other tenant, including the public
`api.galileo.ai`. If a freshly created key returns 401, confirm the endpoint
host matches the console the key was created in.

**GenAI-attribute ingest requirement:** Galileo's `/otel/traces` only ingests
spans carrying OTel GenAI semantic-convention attributes (`gen_ai.*`). A span
without them is rejected with `partialSuccess` and the message "No GenAI
patterns detected in spans." Claude Code's
`claude_code.llm_request` spans carry `gen_ai.system`, `gen_ai.request.model`,
and related keys, so they are accepted. The bare `claude_code.interaction`
workflow span lacks a model call and is rejected by that ingest filter.

Required headers on every OTLP request:

- `Galileo-API-Key: <API key>`
- `project: <project name>`
- `logstream: <log stream name>`

Project and log stream must exist before the collector forwards traces. The
skill delegates provisioning to `galileo-platform-setup` and emits a
`runtime/galileo-handoff.md` companion with the exact provisioning steps.

Direct REST fallback (used only when `galileo-platform-setup` is not
available). These paths are informational; confirm them against current Galileo
API docs before relying on them, as none are exercised against a live API by
this skill:

- Provision project: `POST /v2/projects` with a body naming the project.
- Provision log stream: `POST /v2/projects/{project_id}/log_streams`.
- Ingest a turn (the step the rendered `runtime/galileo-handoff.md` shows):
  `POST /v2/projects/{project_id}/traces` with
  `{"logging_method": "api_direct", "reliable": true, "records": [ ... ]}`.
- Verify ingest: `POST /v2/projects/{project_id}/traces/count` after the first
  Claude Code interaction.

Galileo requires string values in `user_metadata`. Numeric or boolean values
must be stringified. This is enforced upstream by the collector's Galileo
exporter, not by this skill.

## Secret Handling

- Splunk access token: file path in `SPLUNK_O11Y_TOKEN_FILE`. The
  `otelHeadersHelper` shim reads the file on each periodic header refresh. The
  collector wrapper sources the same file into `SPLUNK_ACCESS_TOKEN` at process
  start. Never rendered inline.
- Galileo API key: file path in `GALILEO_API_KEY_FILE`. The collector
  wrapper sources the file into `GALILEO_API_KEY` at process start.
- Create either file with `bash skills/shared/scripts/write_secret_file.sh
  /path/to/file` (chmod-600, no shell history).
- The renderer refuses to accept a literal token or API key on argv. Direct
  secret flags (`--token`, `--access-token`, `--sf-token`, `--o11y-token`,
  `--api-key`, `--galileo-api-key`, `--password`) are rejected in both
  space and equals form.

## Cardinality and Privacy

- `OTEL_METRICS_INCLUDE_SESSION_ID` on adds a per-session unique attribute
  to every metric. In fleets with many short-lived interactions, this
  explodes MTS count. Disable when running at scale unless per-session
  metrics are load-bearing.
- Content capture is off by default. Content flows through Claude Code's OTLP
  logs exporter and inherits whichever log back end is wired (Splunk OTLP logs
  or an external collector). Galileo receives traces only in this skill.
  Redact and gate content capture through `--accept-content-capture`.
- Standard `user.email` and `user.id` attributes are always attached and
  cannot be stripped through Claude Code env alone. If they must not leave
  the environment, run through the local collector and apply a
  `transform/attributes` processor that redacts those keys before export.

## Settings.json Apply and Merge

`--apply settings` merges the rendered `env` block into the existing
`settings.json`. Merge semantics:

- Every managed key in the rendered `env` block overwrites the same key in
  the existing `settings.json.env`. Managed keys include
  `CLAUDE_CODE_ENABLE_TELEMETRY`, `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA`,
  every `OTEL_*` key, Claude's detailed-tracing keys, HTTP mTLS keys, and the
  content-capture keys.
- Keys inside `env` that are not managed by this skill are preserved
  unchanged.
- Keys outside `env` (`permissions`, `hooks`, `mcpServers`, and so on) are
  preserved unchanged.
- The top-level `otelHeadersHelper` is set for direct mode or dynamic external
  OTLP/HTTP headers. When switching modes, a skill-generated helper path is
  removed while an unrelated operator-set helper is left alone.
- A pre-apply backup is written to `settings.json.bak.<timestamp>` in the
  same directory, and the merged JSON replaces the target atomically.

## Strict Config

Claude Code does not currently expose a `--strict-config` equivalent. The
skill's `--validate` renders and re-parses the settings JSON, verifies OTLP
endpoint shapes, checks that content-capture flags require
`--accept-content-capture`, and checks that Galileo is not paired with
`splunk-direct`. With `--collector-config`, it also parses the deployed merged
collector YAML and checks route/transform/connector reachability. It does not
verify Splunk realm reachability, token validity, or Galileo project existence.
Spec loading rejects unknown top-level and `claude_code` fields, invalid API
versions, malformed booleans, nonpositive export intervals, and unsupported
temporality values so misspelled options do not silently fall back to defaults.

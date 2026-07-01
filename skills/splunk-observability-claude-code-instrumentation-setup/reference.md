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
| `ENABLE_BETA_TRACING_DETAILED` | `1` | Enables **detailed** beta tracing: the child spans `claude_code.llm_request` and `claude_code.tool`. Required for Galileo Luna span scorers. On by default in this skill. |
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
| `OTEL_LOG_USER_PROMPTS` | off | Emit user prompt text (populates trace `input`). |
| `OTEL_LOG_ASSISTANT_RESPONSES` | off | Emit assistant response text (populates trace `output`). Requires Claude Code **v2.1.193+**; on older CLIs it falls back to the `OTEL_LOG_USER_PROMPTS` value (responses stay redacted). |
| `OTEL_LOG_TOOL_DETAILS` | off | Emit tool argument and result metadata (Bash commands, MCP/skill names, tool input). |
| `OTEL_LOG_TOOL_CONTENT` | off | Emit tool input and output content bodies in span events (requires tracing; truncated at 60 KB). |

Enabling any of these requires `--accept-content-capture`. Captured content
flows through the OTLP logs exporter and, under detailed beta tracing, is also
attached to span attributes (`tool_input`, `response.model_output`, etc.), so
it inherits every configured back end (Splunk O11y and Galileo).

Empty `input`/`output` on Galileo traces almost always means content capture is
off (default) or the CLI predates `OTEL_LOG_ASSISTANT_RESPONSES` — not a
pipeline failure. Trace *structure* (child spans) depends on
`ENABLE_BETA_TRACING_DETAILED`; trace *content* depends on these flags. They are
independent opt-ins.

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
| `OTEL_RESOURCE_ATTRIBUTES` | Comma-separated `key=value` list appended to every signal's resource. Merged with defaults (`service.name`, `service.version`, `os.type`, `os.version`, `host.arch`). |

### Settings-Only Keys

| Key | Location | Notes |
|---|---|---|
| `otelHeadersHelper` | top level of `settings.json` (not inside `env`) | Absolute path to an executable that prints OTLP headers as JSON on stdout. The rendered direct-mode helper reads `SPLUNK_O11Y_TOKEN_FILE` and emits `{"X-SF-TOKEN": "<token>"}`. Keeps the literal token out of settings. Runs at startup and on a periodic refresh, not per export. |
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
- Must be `http://` with an explicit port, no credentials, and no `/v1/...`
  path.
- The renderer sets only the base `OTEL_EXPORTER_OTLP_ENDPOINT` plus
  `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`; the OpenTelemetry SDK appends
  `/v1/<signal>` per signal at export time.
- When detailed beta tracing is on (default), `BETA_TRACING_ENDPOINT` is also
  set to the same base endpoint.
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
  placeholders. Secret literals are refused.
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
`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`, which alone emit **only** the root
`claude_code.interaction` span. The **child** spans below are emitted only when
detailed beta tracing is active (`ENABLE_BETA_TRACING_DETAILED=1` +
`BETA_TRACING_ENDPOINT`). Span hierarchy:

- Root: `claude_code.interaction`
  - Attributes: `user_prompt` (content-gated), `user_prompt_length`,
    `interaction.sequence`, `interaction.duration_ms`.
- Child: `claude_code.llm_request` *(detailed tracing)*
  - Attributes: `model`, `gen_ai.system` (`anthropic`),
    `gen_ai.request.model`, `gen_ai.response.id`,
    `gen_ai.response.finish_reasons`, `duration_ms`, `ttft_ms`,
    `input_tokens`, `output_tokens`, `cache_read_tokens`,
    `cache_creation_tokens`, `request_id`. These `gen_ai.*` attributes are
    exactly what Galileo's GenAI-attribute ingest filter looks for.
- Child: `claude_code.tool` *(detailed tracing)*
  - Attributes: `tool_name`, `duration_ms`, `tool_use_id`,
    `gen_ai.tool.call.id`.
- Child: `claude_code.hook` *(detailed tracing only)* — hook lifecycle span.
- Nested: `claude_code.tool.blocked_on_user`, `claude_code.tool.execution`.

Content-bearing span attributes (`new_context`, `system_prompt_preview`,
`user_system_prompt`, `tool_input`, `response.model_output`) appear only under
detailed tracing AND with the matching content-capture flag set.

### Why detailed tracing matters for Galileo Luna

Galileo Luna span scorers score child spans:

| Scorer | Scores | Needs |
|---|---|---|
| `action_advancement_luna` | the trace as a whole | root span only |
| `completeness_luna` | llm/chat spans | `claude_code.llm_request` |
| `tool_selection_quality_luna` | llm/chat spans | `claude_code.llm_request` |
| `tool_error_rate_luna` | tool spans | `claude_code.tool` |
| `action_completion_luna` | sessions | session grouping |

Without detailed tracing, only `action_advancement_luna` succeeds; the others
fail with "no child spans with this metric were found". This is why the skill
enables detailed tracing by default.

## Standard Attributes

Applied to every signal:

- `session.id`
- `user.id`
- `user.email`
- `user.account_uuid`
- `organization.id`
- `terminal.type`
- `app.version`
- Any keys supplied through `OTEL_RESOURCE_ATTRIBUTES`.

Resource attributes:

- `service.name` (default `claude-code`)
- `service.version` (Claude Code build version)
- `os.type`
- `os.version`
- `host.arch`

`--service-name` overrides `service.name` on the rendered profile.

## Collector Fan-out

The rendered local collector overlay
(`collector/claude-code-o11y-local-collector.yaml`) contains:

- `receivers.otlp/claude_code`: HTTP receiver bound to the host and port parsed
  from `local_collector_endpoint`.
- `processors`: `batch/claude_code` and `resource/claude_code`, the latter
  upserting `service.name` (from `--service-name`) and `deployment.environment`
  (from `--environment`). There is no `resourcedetection` processor.
- `exporters.otlphttp/claude_code_traces`: OTLP APM ingest for traces,
  `traces_endpoint: https://ingest.<realm>.observability.splunkcloud.com/v2/trace/otlp`,
  auth `X-SF-TOKEN: ${env:SPLUNK_ACCESS_TOKEN}`.
- `exporters.otlphttp/claude_code_logs`: sends Claude Code logs to
  `https://ingest.<realm>.observability.splunkcloud.com/v2/log/otlp`
  (best-effort; Splunk O11y ingests logs via Log Observer / HEC rather than the
  OTLP logs endpoint).
- `exporters.signalfx/claude_code`: realm-based,
  `access_token: ${env:SPLUNK_ACCESS_TOKEN}`, `send_otlp_histograms: true`.
- `exporters.otlphttp/galileo` (only when Galileo is enabled): endpoint
  `https://api.galileo.ai/otel/traces` (or the tenant endpoint derived from
  `--galileo-console-url` / supplied via `--galileo-otel-endpoint`). Only the
  `Galileo-API-Key` header uses `${env:GALILEO_API_KEY}`; the `project` and
  `logstream` headers are baked as literal values from `--galileo-project` and
  `--galileo-log-stream`.
- `service.pipelines.metrics/claude_code`:
  `otlp/claude_code -> [resource/claude_code, batch/claude_code] -> signalfx/claude_code`.
- `service.pipelines.logs/claude_code`:
  `otlp/claude_code -> [resource/claude_code, batch/claude_code] -> otlphttp/claude_code_logs`.
- `service.pipelines.traces/claude_code`:
  `otlp/claude_code -> [resource/claude_code, batch/claude_code] -> [otlphttp/claude_code_traces, otlphttp/galileo]`
  (Galileo appended only when enabled).

Secrets in the overlay:

- Splunk access token: `${env:SPLUNK_ACCESS_TOKEN}`.
- Galileo API key: `${env:GALILEO_API_KEY}`.
- Both are populated by the operator's collector wrapper sourcing the
  respective file paths (`SPLUNK_O11Y_TOKEN_FILE`, `GALILEO_API_KEY_FILE`)
  into env vars at process start.

## Direct Mode and `otelHeadersHelper`

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

## Galileo Integration

Galileo Observe accepts OTLP traces at the ingest endpoint:

- SaaS default: `https://api.galileo.ai/otel/traces`.
- Non-public tenant (Galileo Cloud, Splunk-hosted Agent Observability, or
  self-hosted): pass `--galileo-console-url https://console.<tenant>/`. The
  skill rewrites the `console.` host to `api.` and appends `/otel/traces`,
  yielding e.g. `https://api.demo-v2.galileocloud.io/otel/traces`. Override
  directly with `--galileo-otel-endpoint` if the host does not follow the
  `console.`/`api.` convention.

**Tenant match matters:** an API key created in one Galileo tenant is rejected
(HTTP 401 "Invalid credentials") by every other tenant, including the public
`api.galileo.ai`. If a freshly created key returns 401, confirm the endpoint
host matches the console the key was created in.

**GenAI-attribute ingest requirement:** Galileo's `/otel/traces` only ingests
spans carrying OTel GenAI semantic-convention attributes (`gen_ai.*`). A span
without them is rejected with `partialSuccess` and the message "No GenAI
patterns detected in spans." Claude Code's detailed-tracing
`claude_code.llm_request` spans carry `gen_ai.system`, `gen_ai.request.model`,
and related keys, so they are accepted — but only when detailed tracing is on.
The bare `claude_code.interaction` workflow span (basic tracing) is rejected.

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
  every `OTEL_*` key, and the four `OTEL_LOG_*` content-capture keys.
- Keys inside `env` that are not managed by this skill are preserved
  unchanged.
- Keys outside `env` (`permissions`, `hooks`, `mcpServers`, and so on) are
  preserved unchanged.
- The top-level `otelHeadersHelper` is set to the applied helper path only
  when direct-mode was rendered. In every other mode this skill removes any
  managed helper path it previously set and leaves an operator-set helper
  alone (managed origin is tracked in `metadata.json`).
- A pre-apply backup is written to `settings.json.bak.<timestamp>` in the
  same directory.

## Strict Config

Claude Code does not currently expose a `--strict-config` equivalent. The
skill's `--validate` renders and re-parses the settings JSON, verifies OTLP
endpoint shapes, checks that content-capture flags require
`--accept-content-capture`, and checks that Galileo is not paired with
`splunk-direct`. It does not verify Splunk realm reachability, token
validity, or Galileo project existence.

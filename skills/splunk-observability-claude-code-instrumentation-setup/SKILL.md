---
name: splunk-observability-claude-code-instrumentation-setup
description: >-
  Render, validate, and safely apply Claude Code CLI OpenTelemetry
  instrumentation to Splunk Observability Cloud and Galileo. Use when
  instrumenting Claude Code to emit metrics, log events, and distributed
  traces (beta) to Splunk Observability Cloud via a local OTel Collector
  fan-out, with optional Galileo OTLP trace ingestion for AI observability;
  covers all three destination modes (local-collector, splunk-direct,
  external-collector), env-block and settings.json rendering, collector
  overlay with dual fan-out, otelHeadersHelper for secret-safe direct-mode
  auth, Galileo project/log-stream handoffs, detailed beta tracing for Galileo
  Luna span scorers, non-public Galileo tenant support, and content-capture
  gating.
---

# Splunk Observability Claude Code Instrumentation Setup

## Overview

Claude Code has native OpenTelemetry support. Metrics, log events, and traces
(beta) are configured entirely through environment variables and the
`.claude/settings.json` `env` block. This skill renders those configuration
assets, an optional local OTel Collector overlay, and a `otelHeadersHelper`
shim for secret-safe direct-mode authentication.

## Required Intake

Before enabling Galileo, ask the user for the exact Galileo instance console
URL and use the value they provide, for example
`https://console.demo-v2.galileocloud.io/`. Do not assume the public Galileo
Cloud tenant. Pass the answer as `--galileo-console-url`; an explicitly supplied
`--galileo-otel-endpoint` is also accepted when the deployment does not follow
Galileo's documented console-to-API hostname convention. The renderer fails
closed when Galileo is enabled without either URL.

Claude Code exposes exactly one global `OTEL_EXPORTER_OTLP_HEADERS` value. That
means the CLI itself cannot fan out to two destinations that require different
auth headers. To send telemetry to both Splunk Observability Cloud and Galileo
Observe at the same time, Claude Code must ship to a local OTel Collector, and
the collector must fan out. The skill defaults to that mode.

The skill renders three destination modes:

- `local-collector` (default): Claude Code emits OTLP to
  `http://127.0.0.1:14318`. A rendered collector overlay exports metrics via the
  SignalFx exporter (`send_otlp_histograms: true`), traces via OTLP APM ingest,
  and fans traces out to Galileo Observe when Galileo is enabled.
- `splunk-direct`: Claude Code emits OTLP/HTTP directly to
  `https://ingest.<realm>.observability.splunkcloud.com/v2/{trace,datapoint,log}/otlp`,
  authenticated by a `otelHeadersHelper` script that reads the token from
  `SPLUNK_O11Y_TOKEN_FILE`. No collector is required. Galileo is not
  reachable in this mode.
- `external-collector`: Operator-specified OTLP endpoints; the collector
  overlay is not rendered. Header values must be safe literals or
  environment placeholders.

**Galileo is optional for collector-capable destinations**
(`local-collector`, `external-collector`, `all`). Passing `--galileo-project`
enables it automatically; pass `--galileo-enabled` when using a spec-driven
render that already contains the project/log-stream values. Use
`--disable-galileo` for a Splunk-only render. `--galileo-project` is required
whenever Galileo is enabled, and the user-confirmed instance URL is required
regardless of project or log-stream values.

Note on logs: the Splunk Observability logs OTLP path is included in the overlay,
but Splunk Observability Cloud ingests logs through Log Observer / HEC rather
than the O11y OTLP logs endpoint. Treat the O11y logs pipeline as best-effort;
route Claude Code log events to Splunk Platform via HEC when you need them
searchable.

Note on where data appears: Claude Code metrics land as the native
`claude_code.*` namespace — find them under Metrics → Metric Finder (search
`claude_code`). The prebuilt Splunk "AI overview" (AI Agent Monitoring)
dashboard instead reads GenAI-convention APM spans, so the `local-collector`
overlay includes a `transform/claude_code_genai` processor that maps Claude
Code's `llm_request` spans to `gen_ai.operation.name=chat` + `gen_ai.usage.*` +
Client span kind, stamps `gen_ai.agent.name` onto Claude spans, and marks root
`claude_code.interaction` spans as `gen_ai.operation.name=invoke_workflow`. The
overlay derives `gen_ai.client.operation.duration` in seconds with a spanmetrics
connector. Claude Code's reliable native `claude_code.token.usage` sum is first
normalized, converted from cumulative to delta when necessary, and observed by
`signal_to_metrics/claude_code_token_histogram` as the required
`gen_ai.client.token.usage` histogram. The old sum-connector path is invalid for
the prebuilt Tokens/Cost tiles because it creates a counter with the right name
but the wrong metric type. The rendered settings and collector also stamp `sf_environment`
because the AI overview Environment picker filters on Splunk's
`sf_environment`, not only OTel `deployment.environment`. The derived GenAI
metrics are exported through Splunk OTLP metric ingest so those Splunk
dimensions are preserved. These transforms run only in collector modes;
`splunk-direct` cannot feed the AI overview.

When Galileo fan-out is enabled, a second, Galileo-only
`transform/claude_code_galileo` maps Claude's detailed `user_prompt`,
`new_context`, and `response.model_output` attributes to OpenInference
input/output fields. It also promotes the parent `claude_code.tool` span to an
`execute_tool` operation, copies tool arguments/results, advertises Claude's
`tools` inventory on LLM spans, and filters duplicate permission/execution
children. This transform must run after `transform/claude_code_genai` and before
the Galileo filter. It is intentionally absent from the Splunk trace branch.

The token histogram requires a collector build containing the alpha
`signal_to_metrics` connector. `otel/opentelemetry-collector-contrib:0.154.0`
is validated with this overlay. The stock Splunk Distribution v0.154.2 does not
include that connector, even though the rest of the overlay starts there. Use a
matching contrib build or a custom collector that includes the connector; do
not silently fall back to a sum connector. Start the collector before the new
Claude process so cumulative-to-delta can retain the first counter value using
its normal gateway heuristic.

Diagnostic boundary: if Splunk contains `traces.count` for `chat <model>`, a
HISTOGRAM `gen_ai.client.operation.duration`, and a HISTOGRAM
`gen_ai.client.token.usage` under the intended `sf_environment`, but the AI
overview's internal `count(agents)` stream remains zero, the collector path is
healthy. Check **Settings -> AI agent monitoring** and confirm the organization
stores AI conversation data in **Splunk Observability Cloud**. The AI overview
is not supported when that data source is set to Splunk logs; this is an
organization-level product setting, not a Claude Code exporter failure.

Galileo fan-out uses a separate filtered trace pipeline. Splunk receives full
Claude traces; Galileo receives only spans with GenAI semantic-convention
attributes so root workflow spans do not create `partialSuccess` warnings.

Shared-collector warning: when Claude Code shares one OTLP receiver with Codex
or other agents, do not route Claude signals only by resource-level
`service.name` or `data.source`. Claude Code can place those identifiers on
spans and metric datapoints instead of the resource envelope. Use the rendered
`runtime/shared-collector-routing.md` pattern: `context: span` for traces,
`context: metric` / `context: datapoint` for metrics, and `context: log` for
logs.

For a Docker collector, `http://127.0.0.1:14318` is Claude's host-side client
endpoint, not the receiver bind address inside the container. Publish
`127.0.0.1:14318:4318`, pass
`--collector-receiver-endpoint 0.0.0.0:4318` for a standalone rendered
overlay, or merge the processors, connectors, exporters, and routes into an
existing receiver bound to `0.0.0.0:4318`.

Traces are a Claude Code beta. They require `OTEL_TRACES_EXPORTER=otlp` plus
`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`. Base and **detailed** beta tracing are
separate controls. Base traces are on by default; detailed tracing
is off because it can emit experimental content-bearing attributes. Enable it
only with `--enable-detailed-traces --accept-content-capture`. Current Claude
Code emits `claude_code.llm_request` and `claude_code.tool` under base beta tracing;
detailed tracing adds `claude_code.hook` and experimental content-bearing span
attributes. Interactive detailed tracing can require Anthropic allowlisting.

### Detailed beta tracing

When explicitly enabled, the skill renders both detailed-tracing variables for
hook spans and the richest available trace shape:

- `ENABLE_BETA_TRACING_DETAILED=1`
- `BETA_TRACING_ENDPOINT=<trace destination>` — a **separate** endpoint from
  `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`. The skill points it at the same target
  the traces go to (the local collector for `local-collector`, the Splunk trace
  ingest URL for `splunk-direct`).

Do not diagnose missing `llm_request` or `tool` spans solely by the absence of
detailed tracing on current Claude Code releases. First verify base trace beta,
the trace endpoint, the collector route, and the installed Claude Code version.

### Galileo GenAI-attribute ingest requirement

Galileo's `/otel/traces` endpoint only ingests spans carrying OpenTelemetry
**GenAI semantic-convention attributes** (`gen_ai.*`). Spans without them are
rejected with `partialSuccess` and the message
"No GenAI patterns detected in spans." Claude Code's
`claude_code.llm_request` spans carry `gen_ai.system`, `gen_ai.request.model`,
and related attributes, so they satisfy this filter. Detailed tracing enriches
the path but is not the source of base LLM/tool child spans on current releases.

## Safety Rules

- Never pass a Splunk access token, Galileo API key, or any secret on argv.
  Reject direct secret flags including equals form: `--token`, `--access-token`,
  `--sf-token`, `--o11y-token`, `--api-key`, `--galileo-api-key`, and
  `--password`.
- Direct-mode auth is delivered through `otelHeadersHelper`, a top-level
  `settings.json` key pointing to a script that reads the token from
  `SPLUNK_O11Y_TOKEN_FILE` and prints the OTLP headers as JSON. The literal
  token value never lands in `settings.json`, in `env` blocks, or in argv.
- In `external-collector` OTLP/HTTP mode, placeholder-backed headers such as
  `Authorization=${OTLP_AUTH}` are also resolved by `otelHeadersHelper` from
  the Claude process environment. Dynamic headers are unsupported by Claude's
  gRPC exporter, so the renderer rejects unresolved gRPC placeholders.
- Galileo API keys live in `GALILEO_API_KEY_FILE`. The collector overlay reads
  the value at collector process start through `${env:GALILEO_API_KEY}`, which
  is populated by an operator-owned wrapper that sources the file.
- Content capture is off by default. Enabling any of
  `OTEL_LOG_USER_PROMPTS=1`, `OTEL_LOG_ASSISTANT_RESPONSES=1`,
  `OTEL_LOG_TOOL_DETAILS=1`, `OTEL_LOG_TOOL_CONTENT=1`, or
  `OTEL_LOG_RAW_API_BODIES` requires `--accept-content-capture`. Raw API bodies
  contain the conversation history; use `file:/absolute/directory` only after
  reviewing local retention and permissions.
- Detailed beta tracing also requires `--accept-content-capture` because its
  experimental span attributes can include prompt, tool, or model content.
- The skill refuses to render Galileo assets for `splunk-direct` (Claude Code
  cannot send two independent auth headers).
- `--apply` consumes the reviewed `apply-plan.json` already present in
  `--output-dir`. If no apply plan exists, the skill renders from the current
  options first.

## Destinations

| Destination | Splunk O11y | Galileo | Notes |
|---|---|---|---|
| `local-collector` (default) | metrics + logs + traces | traces | Claude Code emits OTLP to a local collector; the rendered collector overlay fans out to Splunk (SignalFx + OTLP + logs) and optionally to Galileo Observe. |
| `splunk-direct` | metrics + logs + traces | not supported | Direct OTLP/HTTP to Splunk ingest with a single `X-SF-TOKEN` header from `otelHeadersHelper`. |
| `external-collector` | via operator collector | via operator collector | Operator-specified OTLP endpoint(s); no overlay rendered. |
| `all` | ✓ | ✓ | Renders `local-collector` and `splunk-direct` side by side so the operator can choose which settings profile to apply. |

## Primary Workflow

After collecting the required instance URL, render local collector assets with
Splunk + Galileo fan-out. Passing `--galileo-project` enables Galileo
automatically. The skill derives the OTLP endpoint from documented
`app.galileo.ai`, `console.<tenant>`, and `console-<tenant>` URL forms:

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/setup.sh \
  --render \
  --destination local-collector \
  --local-collector-endpoint http://127.0.0.1:14318 \
  --collector-receiver-endpoint 0.0.0.0:4318 \
  --realm us1 \
  --galileo-console-url https://console.demo-v2.galileocloud.io/ \
  --galileo-project coding-agents \
  --galileo-log-stream claude-code \
  --output-dir splunk-observability-claude-code-instrumentation-rendered
```

For public Galileo Cloud, pass the user-confirmed
`--galileo-console-url https://app.galileo.ai/`; it derives
`https://api.galileo.ai/otel/traces`. Base traces are on by default, so no
`--enable-traces-beta` flag is required. Detailed tracing remains off unless
explicitly enabled with content-capture acceptance.

Render direct Splunk Observability metrics, logs, and traces:

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/setup.sh \
  --render \
  --destination splunk-direct \
  --realm us1 \
  --enable-traces-beta
```

Render both destinations side by side:

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/setup.sh \
  --render \
  --destination all \
  --realm us1
```

Render an external OTLP collector profile. Provide either a single
`--external-collector-endpoint` (used as the base for all signals) or explicit
per-signal endpoints (`--external-trace-endpoint`, `--external-metric-endpoint`,
`--external-log-endpoint`). When traces beta is on, a trace endpoint is required
(either the shared base or the explicit trace endpoint):

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/setup.sh \
  --render \
  --destination external-collector \
  --external-collector-endpoint https://otel-gateway.example.com:4318 \
  --external-collector-protocol http/protobuf
```

No collector overlay is rendered in this mode — the operator owns the collector.

Validate rendered output:

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/validate.sh \
  --output-dir splunk-observability-claude-code-instrumentation-rendered
```

For a shared deployment, validate the actual merged collector configuration as
well as the rendered assets:

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/validate.sh \
  --output-dir splunk-observability-claude-code-instrumentation-rendered \
  --collector-config ~/.config/otelcol/config.yaml
```

Apply only after review:

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/setup.sh \
  --apply settings \
  --settings-scope user
```

Preview apply operations without writing:

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/setup.sh \
  --apply all \
  --dry-run \
  --json
```

## Rendered Artifacts

- `settings/claude-settings.<scope>.<destination>.json`: the rendered
  `settings.json` fragment containing an `env` block with
  `CLAUDE_CODE_ENABLE_TELEMETRY`, `OTEL_*` exporter selections, per-signal
  endpoints, cardinality flags, and (for direct or dynamic external HTTP auth)
  the top-level `otelHeadersHelper` key.
- `env/claude-code-o11y.<destination>.env`: a shell-source-friendly copy of
  the same env block for operators who prefer to export the variables from a
  wrapper script or shell startup file.
- `collector/claude-code-o11y-local-collector.yaml`: the local collector
  overlay for `local-collector` mode. Configures an OTLP HTTP receiver bound
  to `collector_receiver_endpoint` when supplied, otherwise to the parsed host
  and port of `local_collector_endpoint`; a SignalFx
  metrics exporter (`send_otlp_histograms: true`), an OTLP APM traces
  exporter, an OTLP/HTTP logs exporter, an optional Galileo OTLP
  traces exporter with `Galileo-API-Key`, `project`, and `logstream` headers,
  and pipelines that fan out traces to both back ends.
- `bin/claude-code-otel-headers.sh`: the `otelHeadersHelper` shim used in
  `splunk-direct` mode and for placeholder-backed external OTLP/HTTP headers.
  It reads the direct token file or named runtime environment variables and
  writes JSON on stdout. Literal credentials never appear in `settings.json`.
- `runtime/galileo-handoff.md`: companion handoff for provisioning the
  Galileo project and log stream through `galileo-platform-setup`, including
  the direct REST API fallback for operators who cannot invoke that skill.
- `runtime/shared-collector-routing.md`: routing pattern for gateways that
  multiplex Codex, Claude Code, and other agents through one OTLP receiver.
- `apply-plan.json`, `coverage-report.json`, `coverage-report.md`,
  `doctor-report.md`, `handoff.md`, and `metadata.json`.

## Galileo Integration

Galileo Observe requires a project and at least one log stream to receive
traces. This skill does not create Galileo resources directly. It hands off
to `galileo-platform-setup` for project and log-stream provisioning, then
renders the collector overlay with the operator-supplied names.

The renderer does not assume a Galileo endpoint. It derives one from the
user-confirmed console URL: public `app.galileo.ai` maps to `api.galileo.ai`,
`console.` maps to `api.`, and `console-` maps to `api-`, then
`/otel/traces` is appended. Use `--galileo-otel-endpoint` for custom layouts.

Galileo authentication is a single header, `Galileo-API-Key`, plus routing
headers `project` and `logstream`. The API key is read from
`GALILEO_API_KEY_FILE` at collector process start; the rendered overlay
references `${env:GALILEO_API_KEY}`. A wrapper script sources the file into
the environment immediately before invoking the collector.

Galileo trace ingest is disabled when `destination` is `splunk-direct`. There
is no way to attach a second auth header to Claude Code's global
`OTEL_EXPORTER_OTLP_HEADERS`, and re-using the same header for two back ends
is unsafe.

## Provider And Model Normalization

The collector infers `aws.bedrock` from Bedrock ARNs and Bedrock model IDs and
otherwise defaults `gen_ai.provider.name` to `anthropic`. Use
`--provider-name` when Claude runs through Vertex AI, Foundry, or a gateway
whose provider cannot be inferred from the model string.

Bedrock application inference-profile ARNs do not contain the underlying model
name. Supply repeatable `--model-alias SOURCE_MODEL=DISPLAY_MODEL` values (or
the `model_aliases` spec object) when normalized model grouping and Splunk cost
estimation are required. Aliases are applied consistently to transformed spans
and derived token metrics; no tenant-specific profile IDs are built in.

## Content Capture Gating

Content capture is opt-in. The following env flags are all off by default and
require `--accept-content-capture` to render:

- `OTEL_LOG_USER_PROMPTS=1`: emit user prompt text in the
  `claude_code.user_prompt` log event.
- `OTEL_LOG_ASSISTANT_RESPONSES=1`: emit assistant reply text in
  `claude_code.assistant_response`.
- `OTEL_LOG_TOOL_DETAILS=1`: emit tool argument and result metadata for
  `claude_code.tool_*` events.
- `OTEL_LOG_TOOL_CONTENT=1`: emit tool argument and result content bodies.
- `OTEL_LOG_RAW_API_BODIES=1`: emit full Messages API request/response bodies
  through log events, or use `file:/absolute/directory` for local body files.

Content capture routes through Claude Code's OTLP logs exporter and, for
detailed beta tracing, is also attached to span attributes (`tool_input`,
`response.model_output`, etc.). Whatever back end receives the log events and
traces also receives the captured content. Redact before enabling.

Version note: `OTEL_LOG_ASSISTANT_RESPONSES` requires Claude Code **v2.1.193 or
later**. On those releases, an unset response flag inherits
`OTEL_LOG_USER_PROMPTS`; the renderer therefore emits an explicit `0` for a
prompt-only capture profile. Older CLIs do not provide the current assistant
response log event. Applying a response-capture profile fails closed when the
installed CLI is older than v2.1.193. The response flag alone does not populate
Galileo: it emits an OTLP log event, while Galileo ingests traces. Detailed beta
tracing plus the Galileo-only content transform are what copy the corresponding
trace attributes into Galileo's Input/Output schema.

The same Galileo-only transform converts Claude's compact advertised-tool array
(`name` plus definition `hash`) into one dynamic OpenInference
`llm.tools.<index>.tool.json_schema` attribute per tool and an OTel
`gen_ai.tool.definitions` inventory. The mapping has no fixed tool-count limit
and makes Tool Selection Quality eligible for built-in and MCP tools. It emits
only the observed tool name: Claude sends descriptions and parameter schemas as
separate correlated log records, so the collector must not invent requirements
that were not present on the LLM span.

## Cardinality Flags

Claude Code cardinality flags map directly to metric attributes:

- `OTEL_METRICS_INCLUDE_SESSION_ID` (default `true`): include the session ID
  on every metric. High cardinality; disable in large fleets.
- `OTEL_METRICS_INCLUDE_VERSION` (default `false`): include Claude Code
  version on every metric.
- `OTEL_METRICS_INCLUDE_ACCOUNT_UUID` (default `true`): include account UUID.
- `OTEL_METRICS_INCLUDE_ENTRYPOINT` (default `false`): include entry-point
  attribute (interactive, exec, etc.).
- `OTEL_METRICS_INCLUDE_RESOURCE_ATTRIBUTES` (default `true`): stamp the keys
  from `OTEL_RESOURCE_ATTRIBUTES` (including the skill's custom
  `resource_attributes`) onto every datapoint. Set the spec field
  `metrics_include_resource_attributes: false` to keep them in the OTLP resource
  block only and cut per-datapoint cardinality.

## Apply Sections

- `settings`: write the rendered `env` block into `~/.claude/settings.json`
  (user scope) or `<repo>/.claude/settings.json` (project scope). The
  managed `env` keys are merged into an existing settings file; other keys
  are preserved. A timestamped sibling backup is created before an existing
  settings file is atomically replaced. A skill-generated `otelHeadersHelper`
  is reconciled across modes; an unrelated operator helper is preserved.
- `env-helper`: install rendered shell env helper files and, for direct or
  dynamic external OTLP/HTTP auth,
  copy `bin/claude-code-otel-headers.sh` into the stable
  `otelHeadersHelper` path and mark it executable.
- `collector-overlay`: copy the local collector overlay to an operator-owned
  path (defaults to reporting the render path; the operator applies it
  through their collector deployment workflow).
- `galileo-handoff`: emit a doctor entry pointing at `galileo-platform-setup`
  for project and log-stream provisioning.
- `all`: run every section.

`--apply` consumes the reviewed `apply-plan.json` already present in
`--output-dir`. If no apply plan exists, the skill first regenerates the entire
output directory from the current options. That render validates before it
clears anything, so a render that fails validation leaves any previously good
`settings/`, `env/`, `collector/`, `bin/`, and `runtime/` artifacts intact —
re-run `--render` with valid options to regenerate.

## Settings Scope

`--settings-scope user` (default) writes `~/.claude/settings.json`.
`--settings-scope project` writes `<current-repo>/.claude/settings.json`.
`--settings-scope managed` renders to
`<output-dir>/settings/managed-settings.json` for enterprise-managed
deployment; install it to the platform managed-settings path yourself
(macOS `/Library/Application Support/ClaudeCode/managed-settings.json`,
Linux/WSL `/etc/claude-code/managed-settings.json`, Windows
`C:\ProgramData\ClaudeCode\managed-settings.json`), which requires
elevated privileges. All scopes share the same `env` merge semantics.

Read [reference.md](reference.md) for the full option contract, source
basis, metric and event catalogs, and collector overlay shape.

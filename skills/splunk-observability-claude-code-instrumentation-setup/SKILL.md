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
whenever Galileo is enabled, regardless of any endpoint override.

Note on logs: the Splunk Observability logs OTLP path is included in the overlay,
but Splunk Observability Cloud ingests logs through Log Observer / HEC rather
than the O11y OTLP logs endpoint. Treat the O11y logs pipeline as best-effort;
route Claude Code log events to Splunk Platform via HEC when you need them
searchable.

Traces are a Claude Code beta. They require `OTEL_TRACES_EXPORTER=otlp` plus
`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`. Both traces beta and **detailed** beta
tracing are on by default in this skill; use `--disable-traces-beta` or
`--disable-detailed-traces` to turn them off.

### Detailed beta tracing (required for Galileo Luna)

By default Claude Code emits only the top-level `claude_code.interaction`
workflow span. Galileo Luna span scorers (`completeness_luna`,
`tool_selection_quality_luna`, `tool_error_rate_luna`, etc.) score the **child**
spans — `claude_code.llm_request` and `claude_code.tool` — which are emitted
only when *detailed* beta tracing is active. This skill therefore renders both
required variables by default:

- `ENABLE_BETA_TRACING_DETAILED=1`
- `BETA_TRACING_ENDPOINT=<trace destination>` — a **separate** endpoint from
  `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`. The skill points it at the same target
  the traces go to (the local collector for `local-collector`, the Splunk trace
  ingest URL for `splunk-direct`).

Without detailed tracing, only `action_advancement_luna` (which scores the
trace as a whole) succeeds; the span-scoped Luna scorers fail with
"no child spans with this metric were found".

### Galileo GenAI-attribute ingest requirement

Galileo's `/otel/traces` endpoint only ingests spans carrying OpenTelemetry
**GenAI semantic-convention attributes** (`gen_ai.*`). Spans without them are
rejected with `partialSuccess` and the message
"No GenAI patterns detected in spans." Claude Code's detailed beta
`claude_code.llm_request` spans carry `gen_ai.system`, `gen_ai.request.model`,
and related attributes, so they satisfy this filter — which is another reason
detailed tracing must stay on for the Galileo path.

## Safety Rules

- Never pass a Splunk access token, Galileo API key, or any secret on argv.
  Reject direct secret flags including equals form: `--token`, `--access-token`,
  `--sf-token`, `--o11y-token`, `--api-key`, `--galileo-api-key`, and
  `--password`.
- Direct-mode auth is delivered through `otelHeadersHelper`, a top-level
  `settings.json` key pointing to a script that reads the token from
  `SPLUNK_O11Y_TOKEN_FILE` and prints the OTLP headers as JSON. The literal
  token value never lands in `settings.json`, in `env` blocks, or in argv.
- Galileo API keys live in `GALILEO_API_KEY_FILE`. The collector overlay reads
  the value at collector process start through `${env:GALILEO_API_KEY}`, which
  is populated by an operator-owned wrapper that sources the file.
- Content capture is off by default. Enabling any of
  `OTEL_LOG_USER_PROMPTS=1`, `OTEL_LOG_ASSISTANT_RESPONSES=1`,
  `OTEL_LOG_TOOL_DETAILS=1`, or `OTEL_LOG_TOOL_CONTENT=1` requires
  `--accept-content-capture`. Prompt, response, and tool content is written
  through Claude Code's log-event exporter and inherits whatever backend is
  wired.
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

Render local collector assets with Splunk + Galileo fan-out. Passing
`--galileo-project` enables Galileo automatically. For a non-public Galileo
tenant (Galileo Cloud, or Splunk-hosted Agent Observability), pass
`--galileo-console-url` — the skill rewrites the `console.` host to `api.` and
derives `https://api.<tenant>/otel/traces`:

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/setup.sh \
  --render \
  --destination local-collector \
  --local-collector-endpoint http://127.0.0.1:14318 \
  --realm us1 \
  --galileo-console-url https://console.demo-v2.galileocloud.io/ \
  --galileo-project coding-agents \
  --galileo-log-stream claude-code \
  --output-dir splunk-observability-claude-code-instrumentation-rendered
```

For public Galileo SaaS, omit `--galileo-console-url` (the default endpoint is
`https://api.galileo.ai/otel/traces`). Traces beta and detailed tracing are on
by default, so no `--enable-traces-beta` flag is required.

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
  endpoints, cardinality flags, and (when direct-mode is selected) the
  top-level `otelHeadersHelper` key.
- `env/claude-code-o11y.<destination>.env`: a shell-source-friendly copy of
  the same env block for operators who prefer to export the variables from a
  wrapper script or shell startup file.
- `collector/claude-code-o11y-local-collector.yaml`: the local collector
  overlay for `local-collector` mode. Configures an OTLP HTTP receiver bound
  to the parsed host and port of `local_collector_endpoint`, a SignalFx
  metrics exporter (`send_otlp_histograms: true`), an OTLP APM traces
  exporter, an OTLP/HTTP logs exporter, an optional Galileo OTLP
  traces exporter with `Galileo-API-Key`, `project`, and `logstream` headers,
  and pipelines that fan out traces to both back ends.
- `bin/claude-code-otel-headers.sh`: the `otelHeadersHelper` shim used in
  `splunk-direct` mode. Reads the token from `SPLUNK_O11Y_TOKEN_FILE` and
  writes the OTLP headers as JSON on stdout. The literal token never appears
  in `settings.json`.
- `runtime/galileo-handoff.md`: companion handoff for provisioning the
  Galileo project and log stream through `galileo-platform-setup`, including
  the direct REST API fallback for operators who cannot invoke that skill.
- `apply-plan.json`, `coverage-report.json`, `coverage-report.md`,
  `doctor-report.md`, `handoff.md`, and `metadata.json`.

## Galileo Integration

Galileo Observe requires a project and at least one log stream to receive
traces. This skill does not create Galileo resources directly. It hands off
to `galileo-platform-setup` for project and log-stream provisioning, then
renders the collector overlay with the operator-supplied names.

The rendered collector overlay ships traces to
`https://api.galileo.ai/otel/traces` by default. For self-hosted Galileo,
swap the console URL host prefix from `console.` to `api.` and append
`/otel/traces`. Override with `--galileo-otel-endpoint`.

Galileo authentication is a single header, `Galileo-API-Key`, plus routing
headers `project` and `logstream`. The API key is read from
`GALILEO_API_KEY_FILE` at collector process start; the rendered overlay
references `${env:GALILEO_API_KEY}`. A wrapper script sources the file into
the environment immediately before invoking the collector.

Galileo trace ingest is disabled when `destination` is `splunk-direct`. There
is no way to attach a second auth header to Claude Code's global
`OTEL_EXPORTER_OTLP_HEADERS`, and re-using the same header for two back ends
is unsafe.

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

Content capture routes through Claude Code's OTLP logs exporter and, for
detailed beta tracing, is also attached to span attributes (`tool_input`,
`response.model_output`, etc.). Whatever back end receives the log events and
traces also receives the captured content. Redact before enabling.

Version note: `OTEL_LOG_ASSISTANT_RESPONSES` requires Claude Code **v2.1.193 or
later**. On older CLIs the flag is accepted but assistant response text stays
redacted (it falls back to the `OTEL_LOG_USER_PROMPTS` value). User prompts and
tool content populate on current releases regardless. Empty `input`/`output`
on Galileo traces almost always means content capture is off (or the CLI
predates the responses flag), not a pipeline failure.

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
  are preserved. If direct-mode is selected, the top-level
  `otelHeadersHelper` key is set to the rendered helper path.
- `env-helper`: install rendered shell env helper files and, for direct mode,
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

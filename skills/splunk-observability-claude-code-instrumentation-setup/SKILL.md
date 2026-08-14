---
name: splunk-observability-claude-code-instrumentation-setup
description: "Use when instrumenting Claude Code to emit metrics, log events, and distributed traces (beta) to Splunk
  Observability Cloud via a local OTel Collector fan-out, with optional Galileo OTLP trace ingestion for
  AI observability; covers all three destination modes (local-collector, splunk-direct, external-
  collector), env-block and settings.json rendering, collector overlay with dual fan-out,
  otelHeadersHelper for secret-safe direct-mode auth, Galileo project/log-stream handoffs, detailed beta
  tracing for Galileo Luna span scorers, non-public Galileo tenant support, and content-capture gating.
  Render, validate, and safely apply Claude Code CLI OpenTelemetry instrumentation to Splunk Observability
  Cloud and Galileo."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk Observability Claude Code Instrumentation Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Instrumenting Claude Code to emit metrics, log events, and distributed traces (beta) to Splunk Observability Cloud
  via a local OTel Collector fan-out, with optional Galileo OTLP trace ingestion for AI observability; covers all
  three.
- Preview and review the splunk observability claude code instrumentation setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

## Overview

Claude Code has native OpenTelemetry support. Metrics, log events, and traces
(beta) are configured entirely through environment variables and the
`.claude/settings.json` `env` block. This skill renders those configuration
assets, an optional local OTel Collector overlay, and a `otelHeadersHelper`
shim for secret-safe direct-mode authentication.

## Required Intake

Collect the destination mode, Splunk realm, environment, and service identity.
For Galileo, also collect the exact user-confirmed console URL and project; do
not assume a tenant. Never collect secret values directly—collect only the
paths to the operator-owned token or API-key files.

Choose one destination model:

- `local-collector` (default) sends Claude Code to loopback and lets the
  collector export to Splunk and optionally Galileo.
- `splunk-direct` sends OTLP/HTTP to Splunk with `otelHeadersHelper`; it cannot
  fan out to Galileo or feed the transformed AI Agent Monitoring view.
- `external-collector` uses operator-specified OTLP endpoints and does not
  render the collector overlay.

Claude Code has one global OTLP header value, so destinations with different
credentials require collector fan-out. Logs needed for search should be routed
to Splunk Platform through HEC; the Observability Cloud OTLP logs path is only
best-effort. In collector mode, the rendered transform maps Claude signals to
the GenAI conventions and histogram types expected by AI Agent Monitoring. It
requires a collector build containing `signal_to_metrics`; use the validated
contrib build or a custom build, never a sum-connector substitute.

For shared collectors, route using span, metric/datapoint, and log context—not
resource attributes alone. For Docker, distinguish the host-side loopback port
from the receiver's container bind address. Detailed beta tracing and any
content-bearing attributes require both the relevant trace controls and
`--accept-content-capture`.

Use [reference.md](reference.md) for the authoritative destination behavior,
signal catalogs, GenAI transforms, shared-collector routing, header helper,
Galileo contract, secrets, privacy, and cardinality controls. In particular,
follow the exact beta trace and Galileo ingest requirements in
[reference.md](reference.md#traces-beta-catalog) and
[reference.md](reference.md#galileo-integration).

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
| `all` | yes | yes | Renders both profiles so the operator can choose which one to apply. |

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

These exported traces can ground Galileo AI Assistant beta investigations, but
this skill does not enable or query the Assistant. Use
`galileo-platform-setup` for the enterprise enablement, LLM-integration
readiness, evidence-link verification, and reviewed-remediation handoff added
for the July 7, 2026 Galileo release.

## Provider And Model Normalization

The collector infers common Anthropic and Bedrock identities. Use explicit
provider and model aliases for gateways or opaque inference-profile ARNs; see
[collector fan-out](reference.md#collector-fan-out) for normalization behavior.

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

Session and account attributes are enabled by default and can be high-cardinality
in large fleets. Review every default and the resource-attribute opt-out in
[reference.md](reference.md#metric-cardinality-controls).

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

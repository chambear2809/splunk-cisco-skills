# Codex Instrumentation Reference

## Source Basis

- Codex profiles, user/project config boundaries, hooks, `--strict-config`, and
  `codex exec --json`: `https://developers.openai.com/codex/codex-manual.md`
- Splunk Observability ingest endpoints:
  `https://dev.splunk.com/observability/reference/api/ingest_data/latest`
- Splunk histogram guidance:
  `https://help.splunk.com/en/splunk-observability-cloud/manage-data/metrics-metadata-and-events/metrics-events-and-metadata/get-histogram-data-in`
- Splunk AI Agent Monitoring setup:
  `https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/code-based-instrumentation`

## Destination Behavior

### Local Collector

Rendered file:
`profiles/codex-o11y-local.config.toml`

- Base endpoint: `local_collector_endpoint`, default
  `http://127.0.0.1:14318`. Override with
  `--local-collector-endpoint http://localhost:14318` or the spec key
  `codex.local_collector_endpoint`.
- The endpoint must be an `http://` base URL with an explicit port, no
  credentials, and no `/v1/...` path. The rendered collector receiver is plain
  OTLP HTTP, so `https://` is rejected unless future TLS receiver rendering is
  added. The renderer appends `/v1/traces`, `/v1/metrics`, and `/v1/logs` as
  needed.
- Collector receiver bind: `local_collector_receiver_endpoint`, default
  `0.0.0.0:4318`. Override it with
  `--local-collector-receiver-endpoint 127.0.0.1:24318` or the spec key
  `codex.local_collector_receiver_endpoint`. This is a `HOST:PORT` bind address,
  not a client URL. It is intentionally independent from
  `local_collector_endpoint`, so a Docker deployment can publish host port
  `14318` to container port `4318` while the collector listens on all container
  interfaces.
- `trace_exporter` is an `otlp-http` inline exporter table
- `metrics_exporter` is an `otlp-http` inline exporter table
- default trace endpoint: `http://127.0.0.1:14318/v1/traces`
- default metric endpoint: `http://127.0.0.1:14318/v1/metrics`
- default native log endpoint, when enabled:
  `http://127.0.0.1:14318/v1/logs`
- native log exporter remains `none` unless `--enable-native-logs` is set
- collector overlay exports traces through OTLP/HTTP APM ingest, metrics through
  SignalFx with `send_otlp_histograms: true`, adds an OTLP/HTTP event pipeline
  targeting `https://ingest.<realm>.observability.splunkcloud.com/v3/event`
  when native logs are enabled, binds its OTLP HTTP receiver to
  `local_collector_receiver_endpoint`, and reads the token with
  `${env:SPLUNK_ACCESS_TOKEN}` in the collector process
- the rendered runner uses the Splunk Distribution `0.154.2` multi-platform
  digest; it does not use the upstream contrib image
- native GenAI histograms do not require a `splunk_otlp_histograms` application
  resource marker
- `gen_ai.client.operation.duration` uses unit `s` and explicit delta
  temporality; `gen_ai.client.token.usage` uses unit `{token}`, explicit delta
  temporality, and `gen_ai.token.type=input|output`
- the collector resource processor upserts `service.name`,
  `deployment.environment`, `sf_service`, and `sf_environment` so native Codex
  service names do not fragment Splunk service/environment dimensions

### External Collector

Rendered file:
`profiles/codex-o11y-external.config.toml`

Required options:

- `--external-trace-endpoint`
- `--external-metric-endpoint`

Optional:

- `--external-log-endpoint` with `--enable-native-logs`
- `--external-collector-protocol otlp-http|otlp-grpc`
- `--external-header KEY=VALUE`
- external TLS file paths

Header and TLS values must be safe literals. `${NAME}` placeholders are
refused because Codex sends OTel exporter header values literally rather than
expanding the process environment. Credential-bearing headers are therefore
unsupported; use `local-collector` for Splunk or another authenticated backend.

### Direct Splunk Observability

No profile is rendered. `--destination direct` fails closed because Splunk
requires `X-SF-TOKEN`, Codex sends `${SPLUNK_ACCESS_TOKEN}` literally in OTel
headers, and the renderer refuses both token values in generated files and
tokens passed on argv. Use `local-collector`; its collector configuration can
safely expand `${env:SPLUNK_ACCESS_TOKEN}` at runtime.

## Advanced Span Helpers

`bin/codex-o11y-exec` wraps the profile selected at render time:

```bash
codex exec --profile codex-o11y-local --json "$@"
```

The wrapper tees JSONL to a local file and converts events into metadata-only
span and metric JSON. Prompt/response/tool-output content remains off unless
`--accept-content-capture` is supplied.

The wrapper runs the parser even when `codex exec` exits nonzero, then exits
with Codex's original status. This preserves failure telemetry without hiding
the underlying command result.

The optional interactive Stop hook parses a session JSONL path supplied through
`CODEX_O11Y_SESSION_JSONL`. It logs local failures and exits `0` so hook
failures do not block Codex.

`--apply hooks` installs the hook script and merges the managed Stop hook entry
into `CODEX_HOME/hooks.json`. Existing unrelated hooks are preserved; an older
managed Codex O11y Stop hook is replaced.

`--apply` consumes the reviewed `apply-plan.json` already present in
`--output-dir`. This prevents an apply-only command from re-rendering the output
with default options and installing a different profile than the operator
reviewed.

## Interactive Notify Bridge

Codex has two different telemetry surfaces that are easy to conflate:

- Native `[otel]` profile export sends Codex-managed traces, metrics, and
  optionally native logs to the configured OTel destination. If
  `[otel].exporter = "none"`, native log export is disabled.
- `notify = [...]` runs an operator command when a Codex turn ends. It can be
  used as a fail-soft post-turn bridge even when native `[otel]` log export is
  disabled.

For Splunk turn telemetry, install the maintained runtime with
`scripts/install_notify_runtime.sh`. The installer resolves its pinned,
hash-locked dependencies once and records the installed lock checksum. The
notify path itself performs no dependency resolution, emits metadata only,
selects the exact completed thread and turn from the notify payload, and keeps
failed trace/metric exports in a private persistent outbox for a later retry.
Run `$CODEX_HOME/bin/codex-splunk-o11y-health.zsh` for offline checks or add
`--live` for a synthetic export. Keep an existing notifier in the chain; the
installer deliberately does not replace `notify` in `config.toml`. A collector
supervisor can run `codex-splunk-o11y-notify-span.py --drain` after a successful
health probe so the final failed turn is retried even when no later turn runs.

Use `notify` for Galileo Observe turn mirroring. A configured Galileo MCP
server only exposes Galileo tools to Codex; it does not automatically populate
Galileo log streams with Codex turns.

The proven bridge shape is:

1. Keep the existing notifier chain intact when one exists.
2. Run a background Python logger from the notifier on `turn-ended`.
3. Parse the local Codex session JSONL under
   `CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`, preferring a session path
   from the notify payload when Codex supplies one.
4. Build one Galileo trace named `codex.turn` for the completed turn.
5. Add one LLM child span for the turn and child spans for tool calls and web
   retrievals when present.
6. Read the Galileo API key from `GALILEO_API_KEY_FILE`; never pass it on argv.
7. Suppress duplicates with a local state file such as
   `CODEX_HOME/log/codex-galileo-emitted-turns.json`.
8. Log non-secret failures to `CODEX_HOME/log/codex-galileo-notify.log` and
   exit `0` so telemetry does not block Codex.

For Galileo direct ingest, call:

```text
POST /v2/projects/{project_id}/traces
```

Use `reliable=true` and `include_trace_ids=true`. The response should include
`records_count`, `traces_count`, `spans_count`, and `trace_ids`.

Verify persistence, not just API acceptance, with:

```text
POST /v2/projects/{project_id}/traces/count
POST /v2/projects/{project_id}/export_records
```

Filter both calls by the returned trace ID. A successful export returns a
`codex.turn` trace with `tags=["codex","codex-cli","turn-ended"]`.

Galileo `user_metadata` values must be strings. Convert values such as
`tool_count`, `retrieval_count`, booleans, and numeric IDs before sending the
payload. A non-string metadata value returns HTTP `422`.

Prompt, response, tool argument, and tool output capture is content capture. Use
metadata-only placeholders by default, or require explicit operator acceptance
before sending content to Galileo. Always redact obvious secrets, bearer
tokens, JWTs, and high-entropy strings before exporting any captured text.

## Strict Config

Every rendered profile has an `apply-plan.json` command like:

```bash
codex --strict-config --profile codex-o11y-local
```

This checks whether the active Codex version accepts the rendered config keys.
It does not verify Splunk realm, token, collector reachability, or endpoint
semantics.

The generated execution wrapper also supplies `--profile` on every
`codex exec` invocation. Installing a profile does not activate it globally;
commands that omit `--profile` continue to use the base Codex configuration.

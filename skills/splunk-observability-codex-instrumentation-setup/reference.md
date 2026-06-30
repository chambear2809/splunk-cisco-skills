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
- The endpoint must be an `http://` or `https://` base URL with an explicit
  port, no credentials, and no `/v1/...` path. The renderer appends
  `/v1/traces`, `/v1/metrics`, and `/v1/logs` as needed.
- `trace_exporter` is an `otlp-http` inline exporter table
- `metrics_exporter` is an `otlp-http` inline exporter table
- default trace endpoint: `http://127.0.0.1:14318/v1/traces`
- default metric endpoint: `http://127.0.0.1:14318/v1/metrics`
- default native log endpoint, when enabled:
  `http://127.0.0.1:14318/v1/logs`
- native log exporter remains `none` unless `--enable-native-logs` is set
- collector overlay exports traces through OTLP/HTTP APM ingest, metrics through
  SignalFx with `send_otlp_histograms: true`, adds a logs pipeline when native
  logs are enabled, binds its OTLP HTTP receiver to the host and port parsed
  from `local_collector_endpoint`, and reads the token with
  `${env:SPLUNK_ACCESS_TOKEN}`

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

Header and TLS values must be safe literals or environment placeholders.

### Direct Splunk Observability

Rendered file:
`profiles/codex-o11y-direct.config.toml`

- traces:
  `https://ingest.<realm>.observability.splunkcloud.com/v2/trace/otlp`
- metrics:
  `https://ingest.<realm>.observability.splunkcloud.com/v2/datapoint/otlp`
- header placeholder: `"X-SF-TOKEN" = "${SPLUNK_ACCESS_TOKEN}"`
- native logs disabled
- gRPC refused

## Advanced Span Helpers

`bin/codex-o11y-exec` wraps:

```bash
codex exec --json "$@"
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

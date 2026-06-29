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

- `trace_exporter` is an `otlp-http` inline exporter table
- `metrics_exporter` is an `otlp-http` inline exporter table
- trace endpoint: `http://127.0.0.1:14318/v1/traces`
- metric endpoint: `http://127.0.0.1:14318/v1/metrics`
- native log endpoint, when enabled: `http://127.0.0.1:14318/v1/logs`
- native log exporter remains `none` unless `--enable-native-logs` is set
- collector overlay exports traces through OTLP/HTTP APM ingest, metrics through
  SignalFx with `send_otlp_histograms: true`, adds a logs pipeline when native
  logs are enabled, and reads the token with `${env:SPLUNK_ACCESS_TOKEN}`

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

## Strict Config

Every rendered profile has an `apply-plan.json` command like:

```bash
codex --strict-config --profile codex-o11y-local
```

This checks whether the active Codex version accepts the rendered config keys.
It does not verify Splunk realm, token, collector reachability, or endpoint
semantics.

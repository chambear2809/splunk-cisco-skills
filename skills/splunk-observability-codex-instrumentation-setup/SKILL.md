---
name: splunk-observability-codex-instrumentation-setup
description: Render, validate, diagnose, and safely apply Splunk Observability instrumentation for Codex CLI profiles, OTel destinations, JSONL runtime helpers, and optional hooks. Use when instrumenting Codex itself for Splunk Observability or AI Agent Monitoring.
---

# Splunk Observability Codex Instrumentation Setup

## Overview

Use this skill to render Codex OTel profiles and optional runtime helpers for
Splunk Observability. Codex telemetry belongs in user-level `CODEX_HOME`
profile files such as `~/.codex/codex-o11y-local.config.toml`; do not put OTel
settings in project `.codex/config.toml`.

The skill recognizes three destination modes; two render profiles and one is a
fail-closed compatibility diagnostic:

- `local-collector`: traces and metrics to
  `http://127.0.0.1:14318` by default. Override the base endpoint with
  `--local-collector-endpoint http://localhost:14318`. Native logs are enabled
  with `--enable-native-logs`. The collector receiver bind is independent and
  defaults to Docker-safe `0.0.0.0:4318`; override it with
  `--local-collector-receiver-endpoint HOST:PORT`.
- `external-collector`: traces, metrics, and optional native logs to explicit
  unauthenticated external OTLP collector endpoints. Safe literal routing
  headers and literal TLS paths are supported; credential placeholders are
  refused because Codex sends them literally.
- `direct`: recognized only to fail closed with a migration message. Direct
  Splunk ingest requires `X-SF-TOKEN`, but Codex does not expand environment
  placeholders in OTel exporter headers and this skill never renders raw
  tokens.

Use `local-collector` for Splunk Observability. The collector expands
`${env:SPLUNK_ACCESS_TOKEN}` in its own process and keeps the credential out of
Codex configuration and process arguments.

For Galileo Observe, do not assume a configured Galileo MCP server means Codex
turns are being logged. MCP enables tool access only. Interactive Codex turn
logging needs a separate `notify`-based bridge that runs after `turn-ended`,
parses the local Codex session JSONL, and writes a Galileo `codex.turn` trace
through the Galileo trace ingest API.

## Safety Rules

- Never pass Splunk tokens on argv.
- Reject direct secret flags, including equals form: `--token`,
  `--access-token`, `--sf-token`, `--o11y-token`, `--api-key`, and
  `--password`.
- Do not render `${NAME}` placeholders in Codex OTel profile headers. Codex
  sends those values literally; credentialed exporters must terminate at a
  collector that owns secret expansion.
- `codex --strict-config --profile <profile>` validates Codex config shape only;
  it does not validate Splunk endpoint semantics.
- Direct mode is refused for every protocol because Splunk authentication
  cannot be rendered safely into a Codex OTel profile.
- Prompt, response, or tool-output content capture requires
  `--accept-content-capture`.
- AI Defense content inspection requires `--enable-ai-defense` plus
  `--accept-ai-defense-content-inspection`.
- Galileo turn mirroring must be fail-soft and secret-file based. The notifier
  should read the Galileo key from a file, redact obvious secrets/high-entropy
  values, write local non-secret failure evidence, and exit `0` if Galileo is
  unavailable.

## Primary Workflow

Render local collector assets:

```bash
bash skills/splunk-observability-codex-instrumentation-setup/scripts/setup.sh \
  --render \
  --destination local-collector \
  --local-collector-endpoint http://localhost:14318 \
  --local-collector-receiver-endpoint 0.0.0.0:4318 \
  --enable-native-logs \
  --realm us0 \
  --output-dir splunk-observability-codex-instrumentation-rendered
```

Direct Splunk Observability export fails closed and directs the operator to the
local collector path:

```bash
bash skills/splunk-observability-codex-instrumentation-setup/scripts/setup.sh \
  --render \
  --destination direct \
  --realm us0
```

Render an external OTLP collector profile:

```bash
bash skills/splunk-observability-codex-instrumentation-setup/scripts/setup.sh \
  --render \
  --destination external-collector \
  --external-collector-protocol otlp-http \
  --external-trace-endpoint https://otel-gateway.example.com/v1/traces \
  --external-metric-endpoint https://otel-gateway.example.com/v1/metrics
```

Validate rendered output:

```bash
bash skills/splunk-observability-codex-instrumentation-setup/scripts/validate.sh \
  --output-dir splunk-observability-codex-instrumentation-rendered
```

Apply only after review:

```bash
bash skills/splunk-observability-codex-instrumentation-setup/scripts/setup.sh \
  --apply profiles \
  --codex-home "$HOME/.codex"
```

Install the durable interactive turn notifier once, outside the per-turn path:

```bash
bash skills/splunk-observability-codex-instrumentation-setup/scripts/install_notify_runtime.sh \
  --codex-home "$HOME/.codex" \
  --service-name codex-cli \
  --environment prod \
  --realm us0 \
  --trace-endpoint http://127.0.0.1:14318/v1/traces \
  --metrics-endpoint http://127.0.0.1:14318/v1/metrics
```

The installer builds a hash-locked virtual environment once, installs static
notify and health scripts transactionally, and writes a non-secret runtime
manifest. A failed install restores the complete prior managed runtime. Preserve
any existing notifier chain when adding
`$CODEX_HOME/bin/codex-splunk-o11y-notify.zsh` to user-level Codex `notify`.
Per-turn execution never invokes `uv`, `pip`, or another package manager.

Preview apply operations without writing to `CODEX_HOME`:

```bash
bash skills/splunk-observability-codex-instrumentation-setup/scripts/setup.sh \
  --apply all \
  --dry-run \
  --json
```

## Rendered Artifacts

- `profiles/*.config.toml`: user-level Codex profile files.
- `collector/codex-o11y-local-collector.yaml`: local collector overlay with
  OTLP trace export, SignalFx metric export, `/v3/event` log export, optional logs pipeline,
  normalized `service.name`/`deployment.environment` and
  `sf_service`/`sf_environment`, and `send_otlp_histograms: true`.
- `collector/run-codex-o11y-local-collector.sh`: runner pinned by multi-platform
  digest to Splunk Distribution `0.154.2`; upstream contrib is rejected for
  this native-histogram path.
- `bin/codex-o11y-exec`: wrapper around
  `codex exec --profile <rendered-profile> --json`.
- `bin/codex-o11y-jsonl-to-spans.py`: metadata-only JSONL parser used by the
  wrapper.
- `hooks/hooks.json` and `hooks/codex-o11y-stop-hook.py`: optional fail-soft
  interactive Stop hook.
- `runtime/codex-notify-galileo-handoff.md`: companion handoff for sending
  completed Codex turns into Galileo Observe. It documents the `notify`
  strategy, trace shape, secret handling, duplicate suppression, and read-back
  validation using `traces/count` plus `export_records`.
- `runtime/codex-splunk-o11y-notify.zsh` and
  `runtime/codex-splunk-o11y-notify-span.py`: metadata-only, fail-soft
  interactive turn export with exact thread/turn routing and a persistent
  retry outbox. GenAI token and duration metrics use the OpenTelemetry bucket
  advisories, `{token}`/`s` units, and explicit delta temporality.
- `runtime/codex-splunk-o11y-health.zsh`: offline runtime/contract check and
  optional live OTLP export smoke test.
- `codex-splunk-o11y-notify-span.py --drain`: retry queued metadata-only turns
  without waiting for another Codex turn; invoke it from the collector
  supervisor after health recovery.
- `scripts/install_notify_runtime.sh`: explicit, hash-locked one-time runtime
  installer. It does not rewrite the user-level Codex notifier chain.
- `apply-plan.json`, `coverage-report.json`, `coverage-report.md`,
  `doctor-report.md`, and `handoff.md`.

## Apply Sections

- `profiles`: copy rendered profile files into `CODEX_HOME`.
- `runtime`: copy `codex-o11y-exec` and `codex-o11y-jsonl-to-spans.py` into
  `CODEX_HOME/bin`.
- `hooks`: copy the optional Stop hook and merge the managed Stop hook entry
  into `CODEX_HOME/hooks.json` without removing unrelated hooks.
- `env-helper`: source helper only; no file write is required.
- `all`: run every section.

`--apply` consumes the already-rendered and reviewed `apply-plan.json` when it
exists in `--output-dir`. If no apply plan exists, the skill renders from the
current options first.

Read [reference.md](reference.md) for the full option contract and source
basis.

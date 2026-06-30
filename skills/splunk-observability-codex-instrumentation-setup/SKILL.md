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

The skill renders three destination profiles:

- `local-collector`: traces and metrics to
  `http://127.0.0.1:14318` by default. Override the base endpoint with
  `--local-collector-endpoint http://localhost:14318`.
- `external-collector`: traces, metrics, and optional native logs to explicit
  external OTLP collector endpoints.
- `direct`: traces to
  `https://ingest.<realm>.observability.splunkcloud.com/v2/trace/otlp` and
  metrics to
  `https://ingest.<realm>.observability.splunkcloud.com/v2/datapoint/otlp`.

Direct native Codex logs are refused. Native logs are allowed only through local
or external collector destinations.

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
- Use environment placeholders such as `${SPLUNK_ACCESS_TOKEN}` in rendered
  profile headers.
- `codex --strict-config --profile <profile>` validates Codex config shape only;
  it does not validate Splunk endpoint semantics.
- Direct mode is OTLP/HTTP only and refuses gRPC.
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
  --realm us0 \
  --output-dir splunk-observability-codex-instrumentation-rendered
```

Render direct Splunk Observability traces and metrics:

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
  OTLP trace export, SignalFx metric export, optional logs pipeline, and
  `send_otlp_histograms: true`.
- `bin/codex-o11y-exec`: wrapper around `codex exec --json`.
- `bin/codex-o11y-jsonl-to-spans.py`: metadata-only JSONL parser used by the
  wrapper.
- `hooks/hooks.json` and `hooks/codex-o11y-stop-hook.py`: optional fail-soft
  interactive Stop hook.
- `runtime/codex-notify-galileo-handoff.md`: companion handoff for sending
  completed Codex turns into Galileo Observe. It documents the `notify`
  strategy, trace shape, secret handling, duplicate suppression, and read-back
  validation using `traces/count` plus `export_records`.
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

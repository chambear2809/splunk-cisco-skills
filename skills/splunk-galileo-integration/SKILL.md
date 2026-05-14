---
name: splunk-galileo-integration
description: >-
  Render, validate, and optionally apply Galileo Observe to Splunk workflows
  including Observability Cloud-only `--o11y-only` mode, REST export to Splunk
  HTTP Event Collector, Galileo OpenTelemetry and OpenInference runtime
  instrumentation, Splunk Platform OTLP input handoffs, Splunk OTel Collector
  handoffs, and Splunk Observability dashboard/detector handoffs. Use when the
  user asks to connect Galileo sessions, traces, spans, GenAI evaluations,
  OpenInference spans, or AI observability records to Splunk Platform or
  Splunk Observability Cloud without duplicating existing HEC, OTLP, OTel
  Collector, dashboard, or detector setup skills.
---

# Splunk Galileo Integration

This skill is the repo-owned automation home for Galileo to Splunk workflows.
It composes existing Splunk skills rather than reimplementing their logic.

## Supported Paths

1. **Galileo REST export to Splunk HEC**: render and run
   `scripts/galileo_to_splunk_hec.py` to pull Galileo sessions, traces, or
   spans and send normalized JSON events to Splunk HEC.
2. **Galileo OpenTelemetry/OpenInference runtime**: render Python and
   Kubernetes snippets that configure Galileo OTel tracing and show how to
   send OpenInference spans.
3. **Splunk handoffs**:
   - HEC token/service: `splunk-hec-service-setup`
   - Splunk Platform OTLP input: `splunk-connect-for-otlp-setup`
   - Splunk OTel Collector: `splunk-observability-otel-collector-setup`
   - Dashboards: `splunk-observability-dashboard-builder`
   - Detectors/native ops: `splunk-observability-native-ops`
4. **Splunk Observability Cloud-only mode**: pass `--o11y-only` when the user
   wants Galileo runtime telemetry, dashboards, and detectors in Observability
   Cloud without any Splunk Platform HEC or OTLP dependency.

## Safe First Command

```bash
bash skills/splunk-galileo-integration/scripts/setup.sh --help
```

## Primary Workflow

Render default artifacts first:

```bash
bash skills/splunk-galileo-integration/scripts/setup.sh \
  --render \
  --output-dir splunk-galileo-rendered
```

Render from the intake template:

```bash
bash skills/splunk-galileo-integration/scripts/setup.sh \
  --render \
  --validate \
  --spec skills/splunk-galileo-integration/template.example \
  --output-dir splunk-galileo-rendered
```

Apply only explicit sections:

```bash
bash skills/splunk-galileo-integration/scripts/setup.sh \
  --apply hec-service,hec-export \
  --project-id "$GALILEO_PROJECT_ID" \
  --log-stream-id "$GALILEO_LOG_STREAM_ID" \
  --splunk-hec-url "$SPLUNK_HEC_URL" \
  --galileo-api-key-file /tmp/galileo_api_key \
  --splunk-hec-token-file /tmp/splunk_hec_token
```

Render and apply only Splunk Observability Cloud sections:

```bash
bash skills/splunk-galileo-integration/scripts/setup.sh \
  --apply \
  --o11y-only \
  --realm "$SPLUNK_O11Y_REALM" \
  --o11y-token-file /tmp/splunk_o11y_token
```

## CLI Contract

`setup.sh` supports:

- `--render`
- `--validate`
- `--doctor`
- `--apply SECTIONS`
- `--o11y-only`

Apply sections:

- `hec-service`
- `hec-export`
- `otlp-input`
- `otel-collector`
- `python-runtime`
- `kubernetes-runtime`
- `dashboards`
- `detectors`

With `--o11y-only`, the default selected sections are `otel-collector`,
`python-runtime`, `kubernetes-runtime`, `dashboards`, and `detectors`.
Explicit Splunk Platform sections (`hec-service`, `hec-export`, `otlp-input`)
are rejected in that mode, and the OTel Collector handoff omits Platform HEC
helper flags.

## Secret Handling

Use file-based flags only:

- `--galileo-api-key-file`
- `--splunk-hec-token-file`
- `--o11y-token-file`

Never pass token values on the command line or in chat. Direct token/password
flags such as `--galileo-api-key`, `--splunk-hec-token`, `--o11y-token`,
`--token`, `--api-key`, `--password`, and `--authorization` are rejected.

Rendered output must not contain token values. Apply wrappers read token files
at runtime and keep secret material out of argv.

## Rendered Output

The default render creates:

- `apply-plan.json`
- `coverage-report.json`
- `handoff.md`
- `runtime/`
- `splunk-platform/`
- `otel/`
- `dashboards/`
- `detectors/`
- `scripts/apply-*.sh`

## Validation

```bash
bash skills/splunk-galileo-integration/scripts/validate.sh \
  --output-dir splunk-galileo-rendered
```

For code validation:

```bash
python3 -m py_compile \
  skills/splunk-galileo-integration/scripts/render_assets.py \
  skills/splunk-galileo-integration/scripts/galileo_to_splunk_hec.py
```

## Boundaries

- This skill owns the Galileo bridge script and cross-skill orchestration.
- It does not duplicate Splunk HEC, OTLP input, OTel Collector, dashboard, or
  detector internals.
- Runtime instrumentation is rendered as deterministic assets unless the user
  supplies an explicit `--runtime-target-dir` or Kubernetes workload target.
  App code is not patched implicitly.

See `reference.md` for endpoint notes, field mapping, apply sections, and
troubleshooting.

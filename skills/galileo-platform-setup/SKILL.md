---
name: galileo-platform-setup
description: >-
  Render, validate, and optionally apply Galileo platform readiness and Splunk
  wiring for Galileo SaaS or Enterprise deployments. Covers Observe exports
  through export_records, OpenTelemetry/OpenInference runtime snippets, Protect
  invoke snippets, Evaluate/experiments/datasets/metrics/annotation handoffs,
  Luna Enterprise readiness, RBAC/project-sharing checks, Splunk HEC/OTLP/OTel
  Collector handoffs, and Splunk Observability dashboards/detectors. Use when
  the user asks to connect Galileo Observe, Evaluate, Protect, Luna, metrics,
  experiments, datasets, annotations, feedback, or GenAI observability records
  to Splunk Platform or Splunk Observability Cloud.
---

# Galileo Platform Setup

This skill is the repo-owned automation home for Galileo platform to Splunk
workflows. It composes existing Splunk skills rather than reimplementing their
logic.

## Supported Paths

1. **Platform readiness**: render endpoint derivation, `/v2/healthcheck`,
   auth mode inventory, RBAC/group/project-sharing checklist, Luna Enterprise
   readiness, metric sampling/filtering coverage, Protect invoke readiness, and
   Signals/Trends/annotation coverage.
2. **Observe export to Splunk HEC**: render and run
   `scripts/galileo_to_splunk_hec.py` against
   `/v2/projects/{project_id}/export_records` using JSONL by default.
3. **Observe runtime**: render Python and Kubernetes Galileo
   OpenTelemetry/OpenInference snippets.
4. **Protect runtime**: render a file-secret-backed Python helper for
   `/v2/protect/invoke`.
5. **Evaluate assets**: render handoffs for experiments, datasets, metrics
   testing, annotations, feedback, Signals, and Trends.
6. **Splunk handoffs**:
   - HEC token/service: `splunk-hec-service-setup`
   - Splunk Platform OTLP input: `splunk-connect-for-otlp-setup`
   - Splunk OTel Collector: `splunk-observability-otel-collector-setup`
   - Dashboards: `splunk-observability-dashboard-builder`
   - Detectors/native ops: `splunk-observability-native-ops`

## Safe First Command

```bash
bash skills/galileo-platform-setup/scripts/setup.sh --help
```

## Primary Workflow

Render default artifacts first:

```bash
bash skills/galileo-platform-setup/scripts/setup.sh \
  --render \
  --output-dir galileo-platform-rendered
```

Render from the intake template:

```bash
bash skills/galileo-platform-setup/scripts/setup.sh \
  --render \
  --validate \
  --spec skills/galileo-platform-setup/template.example \
  --output-dir galileo-platform-rendered
```

Apply only explicit sections:

```bash
bash skills/galileo-platform-setup/scripts/setup.sh \
  --apply splunk-hec,observe-export \
  --project-id "$GALILEO_PROJECT_ID" \
  --log-stream-id "$GALILEO_LOG_STREAM_ID" \
  --splunk-hec-url "$SPLUNK_HEC_URL" \
  --galileo-api-key-file /tmp/galileo_api_key \
  --splunk-hec-token-file /tmp/splunk_hec_token
```

Render and apply only Splunk Observability Cloud sections:

```bash
bash skills/galileo-platform-setup/scripts/setup.sh \
  --apply \
  --o11y-only \
  --realm "$SPLUNK_O11Y_REALM" \
  --o11y-token-file /tmp/splunk_o11y_token
```

## CLI Contract

`setup.sh` supports `--render`, `--validate`, `--doctor`, `--apply SECTIONS`,
`--dry-run`, `--json`, and `--o11y-only`.

Apply sections:

- `readiness`
- `observe-export`
- `observe-runtime`
- `protect-runtime`
- `evaluate-assets`
- `splunk-hec`
- `splunk-otlp`
- `otel-collector`
- `dashboards`
- `detectors`

With `--o11y-only`, the default selected sections are `readiness`,
`observe-runtime`, `protect-runtime`, `evaluate-assets`, `otel-collector`,
`dashboards`, and `detectors`. Explicit Splunk Platform sections
(`observe-export`, `splunk-hec`, `splunk-otlp`) are rejected in that mode.

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

## Validation

```bash
bash skills/galileo-platform-setup/scripts/validate.sh \
  --output-dir galileo-platform-rendered
```

For code validation:

```bash
python3 -m py_compile \
  skills/galileo-platform-setup/scripts/render_assets.py \
  skills/galileo-platform-setup/scripts/galileo_to_splunk_hec.py
```

See `reference.md` for endpoint notes, field mapping, apply sections, and
troubleshooting.

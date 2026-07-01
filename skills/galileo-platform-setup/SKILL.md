---
name: galileo-platform-setup
description: >-
  Render, validate, and optionally apply Galileo platform readiness, object
  lifecycle, Observe export/runtime, Evaluate, Luna, Controls, multimodal, and
  Splunk wiring for Galileo SaaS or Enterprise deployments. Covers projects,
  log streams, datasets, prompts, experiments, metrics, annotations, feedback,
  RBAC, provider handoffs, trace maintenance/metrics APIs, Luna Studio training,
  metadata-only media export, HEC/OTLP/OTel handoffs, dashboards, and detectors.
  Use when configuring Galileo-to-Splunk Platform or Splunk Observability Cloud setup,
  including multimodal traces and multi-model experiment comparison evidence.
---

# Galileo Platform Setup

This skill is the repo-owned automation home for Galileo platform to Splunk
workflows. It composes existing Splunk skills rather than reimplementing their
logic.

## Required Intake

Before rendering, validating, doctoring, probing, or applying this skill, ask
the user for the Galileo instance console URL and record the exact value they
provide, for example `https://console.demo-v2.galileocloud.io/`. Do not assume
`https://app.galileo.ai` or `https://api.galileo.ai` unless the user explicitly
confirms the default Galileo Cloud instance.

Pass the URL as `--galileo-console-url "$GALILEO_CONSOLE_URL"` or set
`galileo.console_url` in the spec. Derive API and OTLP endpoints from that
console URL unless the user provides explicit endpoint overrides.

## Supported Paths

1. **Platform readiness**: render endpoint derivation, `/v2/healthcheck`,
   auth mode inventory, RBAC/group/project-sharing checklist, Luna Enterprise
   readiness, metric sampling/filtering coverage, Protect invoke readiness, and
   Signals/Trends/annotation coverage.
2. **Galileo object lifecycle**: create or validate projects, log streams,
   datasets, prompts, experiments, log stream metrics, Protect stages, and
   Agent Control targets using `scripts/galileo_object_lifecycle.py`. The
   rendered coverage matrix also tracks auth/RBAC, integrations, costs,
   dataset query/preview/content maintenance, prompt rendering, custom scorers,
   scorer governance, Evaluate workflow runs and experiment metrics APIs, trace
   maintenance and trace metrics APIs, annotation and feedback templates,
   Trends dashboards, run insights, multimodal logging,
   distributed tracing, tags/metadata, enterprise retention/TTL/privacy,
   Agent Graph and console debugging views, alerts, framework wrappers, Python
   and TypeScript SDK parity, REST API/custom deployment healthchecks,
   SSO/OIDC/SAML, Luna-2 fine-tuning/evaluation handoffs, Luna Studio training
   lifecycle, Galileo MCP tooling,
   MCP tool-call logging, Agent Observability Controls inventory and control-span
   export validation, async job progress, playground/sample/CI workflows,
   official cookbook/use-case starter examples, troubleshooting, release/version
   checks, search/SDK utilities, and enterprise admin handoffs.
   If the request says "multimodel", distinguish Galileo multimodal
   observability from multi-model experiment comparison: this skill supports
   both, with first-class multimodal assets under `multimodal/` and
   multi-model comparison guidance under `evaluate/experiment-handoff.md`.
3. **Luna scorer settings**: inventory available Luna/SLM preset scorers,
   replace mapped OpenAI/LLM-backed log-stream metric settings with Luna/SLM
   preset or custom scorer IDs using `scripts/galileo_luna_scorers.py`, preserve
   unmapped scorers, and optionally request metric recomputation.
4. **Observe export to Splunk HEC**: render and run
   `scripts/galileo_to_splunk_hec.py` against
   `/v2/projects/{project_id}/export_records` using JSONL by default.
5. **Observe runtime**: render Python and Kubernetes Galileo
   OpenTelemetry/OpenInference snippets.
   For Codex itself, use the rendered `runtime/codex-notify-galileo-handoff.md`
   guidance: Galileo MCP connectivity does not automatically populate Observe
   log streams, so interactive Codex turn logging requires a separate
   `notify`-based bridge that writes `codex.turn` traces through Galileo direct
   trace ingest.
6. **Protect runtime**: render a file-secret-backed legacy Python helper for
   `/v2/protect/invoke` where an existing deployment still uses Protect.
7. **Evaluate assets**: render handoffs for experiments, datasets, metrics
   testing, annotations, feedback, Signals, and Trends.
8. **Multimodal observability**: render GalileoLogger, file/upload,
   LangChain/LangGraph, multimodal quality metric, Splunk metadata-only export,
   and validation-search handoffs for image, audio, and PDF/document traces.
9. **Agent Observability Controls**: render console inventory, Log stream
   attachment, control-span export, and Splunk search evidence handoffs without
   claiming undocumented control CRUD API support.
10. **Splunk handoffs**:
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
  --galileo-console-url "$GALILEO_CONSOLE_URL" \
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
  --apply object-lifecycle \
  --project-name "$GALILEO_PROJECT" \
  --log-stream "$GALILEO_LOG_STREAM" \
  --galileo-console-url "$GALILEO_CONSOLE_URL" \
  --lifecycle-manifest ./galileo-lifecycle.json \
  --galileo-api-key-file /tmp/galileo_api_key
```

Export records after object provisioning:

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
- `object-lifecycle`
- `luna-scorers`
- `observe-export`
- `observe-runtime`
- `protect-runtime`
- `evaluate-assets`
- `multimodal-assets`
- `observability-controls`
- `splunk-hec`
- `splunk-otlp`
- `otel-collector`
- `dashboards`
- `detectors`

With `--o11y-only`, the default selected sections are `readiness`,
`object-lifecycle`, `luna-scorers`, `observe-runtime`, `protect-runtime`,
`evaluate-assets`, `multimodal-assets`, `observability-controls`,
`otel-collector`, `dashboards`, and `detectors`.
Explicit Splunk Platform sections (`observe-export`, `splunk-hec`,
`splunk-otlp`) are rejected in that mode.

Use `--lifecycle-manifest`, `--dataset-dir`, `--prompt-manifest`,
`--experiment-manifest`, `--protect-stage-manifest`, and `--metrics` when the
tenant needs Galileo objects provisioned before export or runtime handoff.
Use `--luna-list-only true` to inventory current and available scorers without
patching metric settings. Use `--luna-scorer-map`, `--luna-recompute true`, and
`--luna-strict true` when replacing preset LLM judge scorers with Luna/SLM
preset or custom scorer IDs.

## Codex Turn Logging Note

When instrumenting Codex as a coding agent, expect three separate surfaces:

- Galileo MCP server: tool access only.
- Codex native `[otel]` profile: Codex-managed OTel export.
- Codex `notify` bridge: post-turn session JSONL parsing and direct Galileo
  trace ingest.

Use the `notify` bridge when the requirement is "every completed Codex turn
appears in a Galileo log stream." The bridge should read the Galileo API key
from `--galileo-api-key-file`, send `POST /v2/projects/{project_id}/traces`
with `reliable=true` and `include_trace_ids=true`, and verify storage through
`traces/count` plus `export_records`.

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

For Codex notify turn logging, the same rule applies: the notifier reads
`GALILEO_API_KEY_FILE` at runtime, logs only non-secret local failure evidence,
and exits `0` if Galileo is temporarily unavailable.

## Validation

```bash
bash skills/galileo-platform-setup/scripts/validate.sh \
  --output-dir galileo-platform-rendered
```

For code validation:

```bash
python3 -m py_compile \
  skills/galileo-platform-setup/scripts/render_assets.py \
  skills/galileo-platform-setup/scripts/galileo_to_splunk_hec.py \
  skills/galileo-platform-setup/scripts/galileo_object_lifecycle.py
```

See `reference.md` for endpoint notes, field mapping, apply sections, and
troubleshooting.

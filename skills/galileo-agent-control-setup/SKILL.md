---
name: galileo-agent-control-setup
description: >-
  Render, validate, and optionally apply Agent Control setup assets covering
  Docker or external server readiness, file-backed auth templates, policy
  controls, Python @control() snippets, TypeScript runtime snippets,
  OpenTelemetry and custom Splunk HEC event sinks, Splunk HEC and OTel
  Collector handoffs, and Splunk Observability dashboards/detectors. Use when
  the user asks to govern runtime agent behavior with Agent Control and wire
  control events to Splunk Platform or Splunk Observability Cloud.
---

# Galileo Agent Control Setup

This skill renders Agent Control setup assets without exposing secret values.
It owns the Agent Control runtime and sink examples, and delegates Splunk-side
HEC, OTel Collector, dashboard, and detector work to the existing Splunk skills.

## Required Intake

Before rendering, validating, doctoring, probing, or applying this skill, ask
the user for the Galileo instance console URL and record the exact value they
provide, for example `https://console.demo-v2.galileocloud.io/`. Do not assume
the default Galileo Cloud URL unless the user explicitly confirms it.

Pass the URL as `--galileo-console-url "$GALILEO_CONSOLE_URL"` or set
`galileo.console_url` in the spec. This URL is separate from
`--server-url`, which points to the standalone Agent Control server.

Use `galileo-platform-setup` instead when the user is asking about the Galileo
Agent Observability `Controls` console tab, Log stream control attachment, or
exported control-span evidence. This skill is for external/open-source Agent
Control runtime and server assets.

## Supported Paths

1. **Server readiness**: render Docker/external server readiness notes, health
   endpoint checks, and auth expectations.
2. **Auth templates**: render file-backed Agent Control API and admin key env
   templates.
3. **Controls**: render starter policy templates for observe-first and deny
   controls.
4. **Runtime snippets**: render Python `@control()` and TypeScript skeleton
   snippets for protected agents.
5. **Event sinks**: render the built-in OTel sink env and a custom Splunk HEC
   event sink.
6. **Splunk handoffs**:
   - HEC token/service: `splunk-hec-service-setup`
   - Splunk OTel Collector: `splunk-observability-otel-collector-setup`
   - Dashboards: `splunk-observability-dashboard-builder`
   - Detectors/native ops: `splunk-observability-native-ops`

## Safe First Command

```bash
bash skills/galileo-agent-control-setup/scripts/setup.sh --help
```

## Primary Workflow

Render default artifacts first:

```bash
bash skills/galileo-agent-control-setup/scripts/setup.sh \
  --render \
  --output-dir galileo-agent-control-rendered
```

Render from the intake template:

```bash
bash skills/galileo-agent-control-setup/scripts/setup.sh \
  --render \
  --validate \
  --galileo-console-url "$GALILEO_CONSOLE_URL" \
  --spec skills/galileo-agent-control-setup/template.example \
  --output-dir galileo-agent-control-rendered
```

Apply only explicit sections:

```bash
bash skills/galileo-agent-control-setup/scripts/setup.sh \
  --apply splunk-hec,otel-collector,dashboards,detectors \
  --realm "$SPLUNK_O11Y_REALM" \
  --splunk-hec-url "$SPLUNK_HEC_URL" \
  --splunk-hec-token-file /tmp/splunk_hec_token \
  --o11y-token-file /tmp/splunk_o11y_token
```

## CLI Contract

`setup.sh` supports `--render`, `--validate`, `--doctor`, `--apply SECTIONS`,
`--dry-run`, and `--json`.

Apply sections:

- `server`
- `auth`
- `controls`
- `python-runtime`
- `typescript-runtime`
- `otel-sink`
- `splunk-sink`
- `splunk-hec`
- `otel-collector`
- `dashboards`
- `detectors`

## Secret Handling

Use file-based flags only:

- `--agent-control-api-key-file`
- `--agent-control-admin-key-file`
- `--splunk-hec-token-file`
- `--o11y-token-file`

Never pass token values on the command line or in chat. Direct token/password
flags such as `--agent-control-api-key`, `--agent-control-admin-key`,
`--splunk-hec-token`, `--o11y-token`, `--token`, `--api-key`, `--password`, and
`--authorization` are rejected.

## Validation

```bash
bash skills/galileo-agent-control-setup/scripts/validate.sh \
  --output-dir galileo-agent-control-rendered
```

For code validation:

```bash
python3 -m py_compile \
  skills/galileo-agent-control-setup/scripts/render_assets.py
```

See `reference.md` for server, control, sink, and Splunk handoff notes.

# Coding Agent Instrumentation Router Reference

Last researched: `2026-07-02`.

## Source Anchors

- Codex configuration and telemetry:
  https://developers.openai.com/codex/codex-manual.md
- Claude Code OpenTelemetry monitoring:
  https://code.claude.com/docs/en/monitoring-usage
- Splunk Observability ingest APIs:
  https://dev.splunk.com/observability/reference/api/ingest_data/latest
- Splunk AI Agent Monitoring code-based instrumentation:
  https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/code-based-instrumentation

## Contract

The parent skill is a routing and planning layer only. It never writes to
`CODEX_HOME`, never installs hooks, and never changes collector or Splunk
configuration.

## Agent Matrix

| Agent | Status | Child skill |
|---|---|---|
| `codex` | implemented | `splunk-observability-codex-instrumentation-setup` |
| `claude-code` | implemented | `splunk-observability-claude-code-instrumentation-setup` |
| `future` | placeholder | none |

## Destination Matrix

| Destination | Parent behavior |
|---|---|
| `local-collector` | Emit the selected child render command for loopback OTLP. |
| `external-collector` | Emit the selected child render command and warn that trace and metric endpoints are required. |
| `direct` | Emit the selected child render command; normalize to the child's direct-mode name and preserve agent-specific direct-ingest warnings. |
| `splunk-direct` | Emit the selected child render command; normalize to the child's direct-mode name and preserve agent-specific direct-ingest warnings. |
| `all` | Emit the selected child render command covering every destination, with agent-specific endpoint warnings. |

## Exact Dry-Run Shape

`--execute --dry-run --json --agent codex --destination direct` returns:

```json
{
  "agent": "codex",
  "child_skill": "splunk-observability-codex-instrumentation-setup",
  "destination": "direct",
  "router_only": true,
  "would_execute": [
    "bash",
    "skills/splunk-observability-codex-instrumentation-setup/scripts/setup.sh",
    "--render",
    "--destination",
    "direct"
  ]
}
```

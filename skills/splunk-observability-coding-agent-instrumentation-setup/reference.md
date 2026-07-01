# Coding Agent Instrumentation Router Reference

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
| `local-collector` | Emit a Codex child render command for loopback OTLP. |
| `external-collector` | Emit a Codex child render command and warn that trace and metric endpoints are required. |
| `direct` | Emit a Codex child render command and warn that direct native logs are refused. |
| `all` | Emit a Codex child render command covering every destination, with endpoint warnings. |

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


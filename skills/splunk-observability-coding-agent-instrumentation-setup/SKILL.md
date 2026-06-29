---
name: splunk-observability-coding-agent-instrumentation-setup
description: Route coding-agent telemetry requests to the right child skill and render a non-mutating orchestration plan. Use when planning Splunk Observability instrumentation for Codex or future coding agents without applying agent-specific config.
---

# Splunk Observability Coding Agent Instrumentation Setup

## Overview

This is a parent router for coding-agent telemetry. It resolves the target
agent, destination mode, and child skill command. It does not install profiles,
hooks, runtime helpers, or collector assets.

The first fully implemented child is
`splunk-observability-codex-instrumentation-setup`.

## Safety Rules

- The parent does not have `--apply`.
- Use `--execute --dry-run --json` to return the exact child command.
- Only child skills mutate their own agent setup.
- Reject direct secret flags such as `--token`, `--access-token`,
  `--sf-token`, `--o11y-token`, `--api-key`, and `--password`.

## Primary Workflow

Render a child orchestration plan:

```bash
bash skills/splunk-observability-coding-agent-instrumentation-setup/scripts/setup.sh \
  --render \
  --agent codex \
  --destination local-collector
```

Get the exact child command without executing it:

```bash
bash skills/splunk-observability-coding-agent-instrumentation-setup/scripts/setup.sh \
  --execute \
  --dry-run \
  --json \
  --agent codex \
  --destination direct
```

## Modes

- `--render`: write `coding-agent-orchestration-plan.json` and
  `doctor-report.md`.
- `--validate`: validate and render the parent orchestration output.
- `--doctor`: same router diagnostics as render.
- `--discover`: list implemented agents and destinations.
- `--execute`: execute the child command, or with `--dry-run`, only print it.
- `--json`: emit JSON.

## Options

- `--agent codex|future`
- `--destination local-collector|external-collector|direct|all`
- `--output-dir DIR`

## Child Handoff

When the agent is `codex`, hand off to:

```bash
bash skills/splunk-observability-codex-instrumentation-setup/scripts/setup.sh --help
```

Read [reference.md](reference.md) for the routing contract and child command
mapping.


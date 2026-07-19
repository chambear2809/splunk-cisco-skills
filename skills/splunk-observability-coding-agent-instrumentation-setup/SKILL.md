---
name: splunk-observability-coding-agent-instrumentation-setup
description: "Use when planning Splunk Observability instrumentation for Codex or future coding agents without
  applying agent-specific config. Route coding-agent telemetry requests to the right child skill and
  render a non-mutating orchestration plan."
compatibility: "Splunk Cloud Platform 10.5.2605: delegated. Compatibility is determined by the canonical replacement or selected child skill; this compatibility alias or router does not own a runtime or package."
metadata:
  splunk_cloud_10_5: "delegated"
  compatibility_verified: "2026-07-02"
---

# Splunk Observability Coding Agent Instrumentation Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Planning Splunk Observability instrumentation for Codex or future coding agents without applying agent-specific
  config.
- Preview and review the splunk observability coding agent instrumentation setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-observability-coding-agent-instrumentation-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-observability-coding-agent-instrumentation-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

## Overview

This is a parent router for coding-agent telemetry. It resolves the target
agent, destination mode, and child skill command. It does not install profiles,
hooks, runtime helpers, or collector assets.

The fully implemented children are
`splunk-observability-codex-instrumentation-setup` and
`splunk-observability-claude-code-instrumentation-setup`.

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
- `--discover`: list implemented agents (`codex`, `claude-code`) and
  supported destinations (`local-collector`, `external-collector`, `direct`,
  `all`).
- `--execute`: execute the child command, or with `--dry-run`, only print it.
- `--json`: emit JSON.

## Options

- `--agent codex|claude-code|future`
- `--destination local-collector|external-collector|direct|all`
- `--output-dir DIR`

## Child Handoff

When the agent is `codex`, hand off to:

```bash
bash skills/splunk-observability-codex-instrumentation-setup/scripts/setup.sh --help
```

When the agent is `claude-code`, hand off to:

```bash
bash skills/splunk-observability-claude-code-instrumentation-setup/scripts/setup.sh --help
```

Read [reference.md](reference.md) for the routing contract and child command
mapping.

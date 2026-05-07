---
name: splunk-platform-restart-orchestrator
description: >-
  Plan, validate, audit, and safely execute Splunk Platform restarts and reloads
  across Splunk Enterprise, Splunk Cloud, systemd-managed hosts, deployment
  servers, indexer clusters, and search head clusters. Use when the user asks to
  restart Splunk, avoid unnecessary restarts, recover from management API restart
  trouble, review repo-wide restart handling, choose between REST/CLI/systemd/ACS
  restart paths, or validate that a Splunk app/config change has been activated.
---

# Splunk Platform Restart Orchestrator

Use this skill whenever restart or reload handling is part of the task. It is a
guardrail skill: prefer reload or topology-aware restart paths, and refuse to
hide a risky restart behind a generic REST call.

## Guardrails

- Never ask for secrets in chat and never place secrets on argv or env prefixes.
- Default to `--plan-restart`; actual restart requires `--restart --accept-restart`.
- Do not kill Splunk processes automatically. Detect partial shutdown and render
  an operator handoff.
- Treat REST `/services/server/control/restart` as explicit fallback only.
- Use ACS for Splunk Cloud and restart only when `restartRequired=true`.
- Delegate indexer cluster peer restarts to `splunk-indexer-cluster-setup`.
- For SHC, use searchable rolling restart only when the change is eligible.

## Quick Start

Plan a restart:

```bash
bash skills/splunk-platform-restart-orchestrator/scripts/setup.sh \
  --plan-restart \
  --operation "app installation" \
  --target-role search-tier \
  --json
```

Execute an accepted Enterprise restart:

```bash
bash skills/splunk-platform-restart-orchestrator/scripts/setup.sh \
  --restart \
  --accept-restart \
  --operation "app installation"
```

Audit the repository:

```bash
bash skills/splunk-platform-restart-orchestrator/scripts/setup.sh --audit-repo
```

## Workflow

1. Read `reference.md` when the task touches Cloud, systemd, clusters, or repo
   adoption.
2. Run `--plan-restart` before any live restart unless another skill has already
   rendered a plan.
3. For reloadable paths, use `--reload ENDPOINT_OR_HINT` or the skill-specific
   reload helper.
4. For repo work, run `--audit-repo` and use the report to choose adoption
   targets.
5. Validate after restart with management API readiness and any expected data or
   listener probes.

## Shared Helper

Existing skills should call the shared helpers loaded by
`skills/shared/lib/credential_helpers.sh`:

- `platform_restart_or_exit <session_key> <uri> <operation> [skip_message]`
- `platform_restart_plan <operation> <target_role> <restart_mode>`
- `platform_reload_or_restart_guidance <change_description>`
- `platform_restart_handoff <operation> <reason>`

Keep existing skill flags such as `--no-restart` compatible.

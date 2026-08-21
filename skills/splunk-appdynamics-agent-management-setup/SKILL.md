---
name: splunk-appdynamics-agent-management-setup
description: "Use when the user asks for AppDynamics Smart Agent, Agent Management, remote agent installation,
  deployment groups, managed agent upgrade, rollback, auto-attach, auto-discovery, managed Apache, .NET,
  Database, Java, Machine, Node.js, PHP, or Python agents, package download automation, checksum
  validation, signature validation, or release compatibility. Render, validate, and gate Splunk
  AppDynamics Smart Agent and Agent Management workflows, including prerequisites, platform and permission
  checks, Smart Agent config, local and remote install, upgrade, uninstall, synchronization, deployment
  groups, auto-attach, auto-discovery, UI paths, smartagentctl lifecycle commands, deprecated Smart Agent
  CLI guidance, and supported managed agent types for Apache, .NET MSI, Database, Java, Machine, Node.js,
  PHP, and Python agents, plus software downloads, checksum validation, digital signatures, and release
  posture."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Splunk AppDynamics Agent Management Setup

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

- The user asks for AppDynamics Smart Agent, Agent Management, remote agent installation, deployment groups, managed
  agent upgrade, rollback, auto-attach, auto-discovery, managed Apache, .NET, Database, Java, Machine, Node.js, PHP,
  or Python.
- Preview and review the splunk appdynamics agent management setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-appdynamics-agent-management-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-appdynamics-agent-management-setup/scripts/validate.sh --help
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

Owns the Smart Agent and Agent Management lifecycle. The safe path is render
first: it creates reviewed plans, templates, and runbooks without touching
hosts. The wrapper does not execute local or remote Smart Agent commands;
`--apply` fails closed instead of claiming a deployment occurred.

```bash
bash skills/splunk-appdynamics-agent-management-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-agent-management-setup/scripts/validate.sh
```

## What This Skill Covers

- Smart Agent readiness: Controller version, licenses, permissions, supported
  platforms, memory, disk, service user/group, and service-vs-process decision.
- Smart Agent setup: `config.ini`, file-backed access-key handling, proxy/TLS
  settings, environment overrides, local install, remote install, validate,
  upgrade, uninstall, and primary-host to remote-host synchronization.
- Agent Management UI: inventory, Smart Agents tab, app-server and Machine
  Agent install/upgrade/rollback, Database Agent install/upgrade/rollback, CSV
  host import, custom package locations, local directory, and custom HTTP source
  review.
- `smartagentctl`: local and remote install, upgrade, uninstall, rollback,
  `remote.yaml`, Linux SSH, Windows WinRM, SSH password environment variables,
  HTTP/SOCKS5 SSH proxies, local-directory downloads, and source-specific flags.
- Large-scale operations: deployment groups, per-host assignment, Java and
  Node.js auto-attach, application process auto-discovery, and generated
  `ld_preload.json` planning.
- Standalone Smart Agent CLI: past End of Support since February 2, 2026, so it
  is retained only as a migration runbook off the CLI and onto `smartagentctl`.
  The 26.8.0 page still states the date in the future tense; that is unrevised
  vendor wording, not continuing support.
- Software supply chain: download portal/cURL plan, binary transfer warning,
  checksums, PGP or code-signing validation where published, release-note link,
  package inventory, and rollback package confirmation.

## Consume It

Start with `smart-agent-readiness.yaml` and `agent-management-decision-guide.md`.
They keep the intake small: deployment mode, host OS, target agents, local vs
remote, UI vs `smartagentctl`, package source, and whether deployment groups or
auto-attach are in scope.

Only after that should an operator review and explicitly execute the applicable
commands from `smart-agent-remote-command-plan.sh`,
`smartagentctl-lifecycle-plan.sh`, `remote.yaml.template`, and the UI runbooks.
The generated shell files print command plans; they do not execute them. No
generated file contains secret values.

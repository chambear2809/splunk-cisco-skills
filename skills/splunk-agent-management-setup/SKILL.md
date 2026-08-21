---
name: splunk-agent-management-setup
description: "Use when the user asks to manage universal forwarder or heavy forwarder fleets, create serverclass.conf,
  configure deploymentclient.conf, or prepare Splunk 10.x Agent Management / legacy Deployment Server
  workflows. Render, preflight, apply, and validate Splunk Enterprise agent management assets for
  deployment-server style server classes, deployment apps, and deployment clients."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Splunk Agent Management Setup

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

- Manage universal forwarder or heavy forwarder fleets, create serverclass.conf, configure deploymentclient.conf, or
  prepare Splunk 10.x Agent Management / legacy Deployment Server workflows.
- Preview and review the splunk agent management setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-agent-management-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-agent-management-setup/scripts/validate.sh --help
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

This skill manages the Splunk Enterprise Agent Management control plane,
formerly known as Deployment Server. It renders reviewable `serverclass.conf`,
deployment app, and `deploymentclient.conf` assets before any apply phase.

## Agent Behavior

Never ask for secrets in chat. This workflow does not need passwords unless the
operator chooses to run Splunk commands through their own shell session.

Use `template.example` for non-secret values:

- agent manager URI
- server class names
- deployment app names
- whitelist and blacklist filters
- client names
- Splunk home path

## Quick Start

Render a Linux forwarder server class and client app:

```bash
bash skills/splunk-agent-management-setup/scripts/setup.sh \
  --mode both \
  --agent-manager-uri https://am01.example.com:8089 \
  --serverclass-name all_linux_forwarders \
  --deployment-app-name ZZZ_cisco_skills_forwarder_base \
  --whitelist "*.example.com" \
  --machine-types-filter linux-x86_64
```

Apply after review on the relevant host:

```bash
bash skills/splunk-agent-management-setup/scripts/setup.sh \
  --mode agent-manager \
  --phase apply \
  --agent-manager-uri https://am01.example.com:8089
```

## Important Details

- Agent management can manage universal forwarders, heavy forwarders, indexers,
  search heads, and OTel collectors, but OTel support is currently fleet
  overview only.
- Do not use agent management to push configuration directly to indexer cluster
  peers or search head cluster members. Use cluster bundles or the SHC deployer
  for those clustered roles.
- The rendered `serverclass.conf` sets app-level `filterType` explicitly because
  Splunk Enterprise 9.4.3 and later changed the implicit app-level default.
- Deployment clients are configured with
  `serverRepositoryLocationPolicy = rejectAlways` by default so apps land under
  `$SPLUNK_HOME/etc/apps` unless the operator changes it.
- The rendered `apply-deployment-client.sh` runs `splunk restart` after writing
  `deploymentclient.conf` because the new configuration only takes effect after
  splunkd restarts. Pass `--client-restart-splunkd false` if another
  orchestrator (image bake, configuration management) is responsible for the
  restart; the rendered script will then install the file and exit without
  restarting.

## Validation

Static validation:

```bash
bash skills/splunk-agent-management-setup/scripts/validate.sh
```

Live validation runs the rendered `status.sh`:

```bash
bash skills/splunk-agent-management-setup/scripts/validate.sh --live
```

Read `reference.md` for researched behavior and official documentation links.

## Hand-off Contracts

- **DS runtime** (bootstrap, `phoneHome` tuning, REST fleet inspection, HA pair, client migration): handled by [`splunk-deployment-server-setup`](../splunk-deployment-server-setup/SKILL.md). This skill owns `serverclass.conf` authoring; `splunk-deployment-server-setup` owns DS runtime operations.
- **UF enrollment**: handled by [`splunk-universal-forwarder-setup`](../splunk-universal-forwarder-setup/SKILL.md) for the client side of DS enrollment.

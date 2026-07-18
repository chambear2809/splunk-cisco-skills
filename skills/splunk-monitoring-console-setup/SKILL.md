---
name: splunk-monitoring-console-setup
description: "Use when the user asks to configure distributed or standalone Monitoring Console mode,
  splunk_monitoring_console_assets.conf auto-config, distsearch.conf search peer groups, forwarder
  monitoring, platform alerts, search peer onboarding checks, or Monitoring Console status validation.
  Render, preflight, apply, and validate Splunk Enterprise Monitoring Console configuration."
compatibility: "Splunk Cloud Platform 10.5.2605: not applicable. This self-managed runtime workflow remains on the public Splunk Enterprise or Universal Forwarder 10.4 baseline."
metadata:
  splunk_cloud_10_5: "self-managed-10.4"
  compatibility_verified: "2026-07-02"
---

# Splunk Monitoring Console Setup

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

- Configure distributed or standalone Monitoring Console mode, splunk_monitoring_console_assets.conf auto-config,
  distsearch.conf search peer groups, forwarder monitoring, platform alerts, search peer onboarding checks, or
  Monitoring Console.
- Preview and review the splunk monitoring console setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-monitoring-console-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-monitoring-console-setup/scripts/validate.sh --help
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

This skill prepares Splunk Enterprise Monitoring Console local configuration
for standalone or distributed deployments. It renders reviewable assets before
any apply phase.

## Agent Behavior

Never ask for search-head or search-peer passwords in chat. This skill does not
automate `splunk add search-server` because the documented CLI requires
`-remotePassword`, which would expose a secret as a process argument. Render the
peer checklist, then have the operator add peers through Splunk Web or their own
secure session.

Use `template.example` for non-secret values:

- standalone or distributed mode
- search peer host:management-port values
- search peer URI scheme and optional distributed search groups
- peer username
- auto-config setting
- forwarder monitoring schedule
- platform alert names
- Splunk home path

## Quick Start

Render distributed Monitoring Console assets with auto-config:

```bash
bash skills/splunk-monitoring-console-setup/scripts/setup.sh \
  --mode distributed \
  --search-peers cm01.example.com:8089,sh01.example.com:8089 \
  --peer-username admin \
  --enable-auto-config true
```

Enable forwarder monitoring and selected platform alerts:

```bash
bash skills/splunk-monitoring-console-setup/scripts/setup.sh \
  --mode distributed \
  --enable-forwarder-monitoring true \
  --enable-platform-alerts true \
  --platform-alerts "Near Critical Disk Usage,Search Peer Not Responding"
```

Apply after search peers and server roles have been reviewed:

```bash
bash skills/splunk-monitoring-console-setup/scripts/setup.sh \
  --phase apply \
  --mode distributed \
  --enable-auto-config true
```

## What It Renders

- `splunk_monitoring_console_assets.conf` with `mc_auto_config`
- `distsearch.conf` review file for search peers and custom distributed search groups
- `savedsearches.conf` overrides for forwarder monitoring and platform alerts
- `app.conf` local app visibility/configuration metadata
- helper scripts for preflight, apply, peer checklist, and status

Read `reference.md` before enabling distributed mode, forwarder monitoring, or
platform alerts.

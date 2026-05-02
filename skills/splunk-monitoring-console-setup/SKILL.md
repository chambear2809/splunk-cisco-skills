---
name: splunk-monitoring-console-setup
description: >-
  Render, preflight, apply, and validate Splunk Enterprise Monitoring Console
  configuration. Use when the user asks to configure distributed or standalone
  Monitoring Console mode, splunk_monitoring_console_assets.conf auto-config,
  distsearch.conf search peer groups, forwarder monitoring, platform alerts,
  search peer onboarding checks, or Monitoring Console status validation.
---

# Splunk Monitoring Console Setup

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

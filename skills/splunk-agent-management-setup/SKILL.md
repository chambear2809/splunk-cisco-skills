---
name: splunk-agent-management-setup
description: >-
  Render, preflight, apply, and validate Splunk Enterprise agent management
  assets for deployment-server style server classes, deployment apps, and
  deployment clients. Use when the user asks to manage universal forwarder or
  heavy forwarder fleets, create serverclass.conf, configure deploymentclient.conf,
  or prepare Splunk 10.x Agent Management / legacy Deployment Server workflows.
---

# Splunk Agent Management Setup

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

---
name: splunk-federated-search-setup
description: >-
  Render, preflight, apply, and validate Splunk Federated Search provider and
  federated index configuration. Use when the user asks to configure standard
  or transparent mode Splunk-to-Splunk federated search, federated.conf,
  standard-mode federated indexes, service-account based remote search,
  federated: index syntax, or search head cluster replication for federated
  index definitions.
---

# Splunk Federated Search Setup

This skill prepares Federated Search for Splunk across remote Splunk platform
deployments. It renders reviewable Splunk-to-Splunk provider and
standard-mode federated-index assets before any apply phase.

## Agent Behavior

Never ask for the federated provider service-account password in chat. Use a
local-only password file:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/federated_provider_password
```

Collect non-secret values in `template.example`: provider name, remote
management endpoint, service-account username, provider mode, federated index
name, dataset type, dataset name, app context, and SHC replication choice.

## Quick Start

Render a standard-mode provider and federated index:

```bash
bash skills/splunk-federated-search-setup/scripts/setup.sh \
  --mode standard \
  --remote-host-port remote-sh.example.com:8089 \
  --service-account federated_svc \
  --provider-name remote_prod \
  --federated-index-name remote_main \
  --dataset-type index \
  --dataset-name main
```

Apply after review on a standalone search head:

```bash
bash skills/splunk-federated-search-setup/scripts/setup.sh \
  --phase apply \
  --remote-host-port remote-sh.example.com:8089 \
  --service-account federated_svc \
  --password-file /tmp/federated_provider_password
```

For search head clusters, render and push the SHC deployer app before creating
standard-mode federated indexes:

```bash
bash skills/splunk-federated-search-setup/scripts/setup.sh \
  --phase apply \
  --apply-target shc-deployer \
  --remote-host-port remote-sh.example.com:8089 \
  --service-account federated_svc \
  --password-file /tmp/federated_provider_password
```

## What It Renders

- `federated.conf.template` with provider settings and a password placeholder
- `indexes.conf` with `[federated:<name>]` for standard mode
- `server.conf` with `conf_replication_include.indexes = true` for SHC standard mode
- helper scripts for preflight, apply, and status

Read `reference.md` before choosing standard versus transparent mode.

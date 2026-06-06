---
name: splunk-kvstore-admin-setup
description: >-
  Render, validate, and apply Splunk App Key Value Store administration: backup
  and restore (point-in-time), clean/reset, storage-engine migration to
  WiredTiger, KV Store server-version upgrade (7.0/8.0), maintenance mode,
  collections.conf and KV Store lookup-definition governance, and standalone vs
  search head cluster paths. Use when the user asks to back up or restore the KV
  Store, migrate the KV Store storage engine, upgrade the KV Store server
  version, reset or clean the KV Store, define a KV Store collection or lookup,
  or recover KV Store on an SHC.
---

# Splunk KV Store Admin Setup

This skill renders and applies Splunk App Key Value Store (KV Store)
administration assets. It is render-first because backup, restore, clean,
migrate, and upgrade operations change durable state; review the rendered host
scripts before applying.

## Agent Behavior

Never ask for the Splunk admin password in chat. Lifecycle operations run as
the splunk user on the host after `splunk login`; collection governance uses the
project `credentials` file via the shared helper. Restore and clean are
destructive and refuse to run without their acceptance flag.

Read `reference.md` before any restore, migrate, or upgrade. Always take a
point-in-time backup first.

## Quick Start

Render the lifecycle assets:

```bash
bash skills/splunk-kvstore-admin-setup/scripts/setup.sh --topology shc
```

Take a point-in-time backup live:

```bash
bash skills/splunk-kvstore-admin-setup/scripts/setup.sh --phase apply --operation backup --point-in-time true
```

Restore (destructive, captain on SHC):

```bash
bash skills/splunk-kvstore-admin-setup/scripts/setup.sh --phase apply --operation restore \
  --backup-archive-name kvdump_2026.tar.gz --accept-kvstore-restore
```

Define a KV Store collection + lookup definition live via REST:

```bash
bash skills/splunk-kvstore-admin-setup/scripts/setup.sh --phase apply --operation collections \
  --collection-name asset_inventory --collection-fields ip:string,risk:number \
  --lookup-definition-name asset_inventory_lookup
```

## What It Renders

- `backup.sh` / `restore.sh` / `clean.sh` / `migrate.sh` / `upgrade.sh` / `status.sh` / `preflight.sh`
- `server.conf` with optional `[kvstore] kvstoreUpgradeOnStartupEnabled = false`
- `collections.conf` and `transforms.conf` KV Store lookup-definition templates

## Operations

- `backup` - `splunk backup kvstore [-pointInTime true]`
- `restore` - `splunk restore kvstore -archiveName <file>.tar.gz` (gated)
- `clean` - `splunk clean kvstore --local|--cluster` (gated)
- `migrate` - SHC `start-shcluster-migration kvstore -storageEngine wiredTiger`
- `upgrade` - SHC `start-shcluster-upgrade kvstore -version <v>`
- `collections` - write collection + lookup definition via REST

Hand SHC replication health, captain transfer, and KV Store reset coordination
to `splunk-search-head-cluster-setup`.

---
name: splunk-kvstore-admin
description: >-
  Render, preflight, and validate Splunk App Key Value Store (KV Store)
  administration assets for backup, restore, migration, resync, and health
  checks. Use when the user asks to back up or restore the KV Store, migrate the
  KV Store storage engine to WiredTiger, recover a stale or failed SHC KV Store
  member, resync KV Store replication, change kvstore server.conf settings, or
  check kvstore-status and replication on standalone search heads or search head
  clusters.
---

# Splunk KV Store Administration

This skill renders Splunk Enterprise App Key Value Store (KV Store) operations:
backup, restore, storage-engine migration, SHC member resync, and health
checks. It is render-first because KV Store restore and resync rewrite
collection data and can disrupt apps that depend on it (Enterprise Security,
ITSI, lookups, and saved-search state).

## Agent Behavior

Never ask for the Splunk admin password in chat. KV Store CLI verbs
(`splunk backup kvstore`, `splunk restore kvstore`) authenticate against
splunkd; let the operator run the rendered scripts and authenticate
interactively with `splunk login` and the CLI's local authenticated session.
Do not embed credentials in argv.

Use `template.example` for non-secret values: deployment type, `$SPLUNK_HOME`,
archive names, and target storage engine.

## Quick Start

Render standalone backup and health assets:

```bash
bash skills/splunk-kvstore-admin/scripts/setup.sh \
  --deployment standalone \
  --archive-name kvstore_$(date +%Y%m%d)
```

Render a search head cluster migration + resync plan:

```bash
bash skills/splunk-kvstore-admin/scripts/setup.sh \
  --deployment shc \
  --storage-engine wiredTiger \
  --archive-name kvstore_premigration
```

Run the read-only status check after rendering:

```bash
bash skills/splunk-kvstore-admin/scripts/validate.sh --live
```

## What It Renders

- `backup.sh` — `splunk backup kvstore` with an explicit archive name
- `restore.sh` — `splunk restore kvstore` with guardrails and a manifest list step
- `status.sh` — read-only `splunk show kvstore-status --verbose`
- `migrate.sh` — SHC storage-engine dry run and migration with
  `start-shcluster-migration`; standalone emits an upgrade handoff
- `resync.sh` — gated SHC stale-member clean, restart, explicit resync, and
  status check; standalone refuses the operation
- `server.conf` — optional `[kvstore]` storage-engine override and tuning comments
- `README.md` / `metadata.json` — review context

## Operating Notes

- Take a fresh backup before any restore, migrate, or resync.
- On a search head cluster, run restore on the captain with maintenance mode;
  resync is only for one stale non-captain member at a time.
- WiredTiger is the supported storage engine on current Splunk releases; the
  migration is one-way and requires a maintenance window.
- Live migration requires `--deployment shc --storage-engine wiredTiger`.
  Standalone migration occurs through the supported Splunk upgrade workflow.
- KV Store and the bundled MongoDB are version-coupled to the Splunk release;
  validate version compatibility before upgrades.

Read `reference.md` before restoring, migrating, or resyncing in production.

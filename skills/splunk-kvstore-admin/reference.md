# Splunk KV Store Administration Reference

This reference covers the App Key Value Store (KV Store) lifecycle operations
this skill renders: backup, restore, storage-engine migration, search head
cluster (SHC) member resync, and health checks. KV Store is backed by a Splunk
embedded MongoDB and stores collection data used by lookups, saved-search
state, Enterprise Security, ITSI, and many apps.

## When To Use This Skill

- Scheduled or pre-change KV Store backups.
- Restoring KV Store collections after corruption, accidental deletion, or a
  failed change.
- Migrating the KV Store storage engine to WiredTiger before or during a Splunk
  upgrade.
- Recovering a search head cluster member whose KV Store is stale, failed, or
  out of sync.
- Auditing `kvstore-status` and replication health.

## Backup

`splunk backup kvstore -archiveName <name>` creates an archive under
`$SPLUNK_HOME/var/lib/splunk/kvstorebackup/`. Notes:

- Run backups on the captain in an SHC; the captain holds the authoritative
  copy.
- Backups are point-in-time; schedule them around heavy write windows.
- The archive name should be unique and descriptive (for example, include the
  date). This skill validates the name characters.
- Authenticate against splunkd. Pass `-auth user:<password-from-file>` only from
  a file you control; never paste the password into chat or argv.

## Restore

`splunk restore kvstore -archiveName <name>` overwrites current collection
data with the archive contents. Guardrails the rendered `restore.sh` enforces:

- Lists available archives and requires typing `RESTORE` to proceed.
- Always take a fresh backup first.
- On an SHC, restore is performed on the captain and replicated outward; do not
  restore on multiple members concurrently.
- After restore, re-run `status.sh` and confirm collection counts and
  replication.

## Storage-Engine Migration

Current Splunk releases use the WiredTiger storage engine. Legacy deployments
on the older engine must migrate with `splunk migrate migrate-kvstore`:

- The migration is one-way and requires a maintenance window.
- Take a fresh backup first.
- On an SHC, follow the documented per-member sequence; do not migrate all
  members at once.
- KV Store and the bundled MongoDB are version-coupled to the Splunk release.
  Validate version compatibility before and after a Splunk upgrade.

### Splunk Enterprise 10.4

- Enterprise **10.4** removes MongoDB 4–6 binaries. A direct **9.x → 10.4**
  upgrade path is invalid; upgrade through **10.0** or **10.2** first.
- On **10.x → 10.4**, MongoDB **8** is applied automatically during upgrade.
- After upgrade, read `splunk show kvstore-status --verbose` and confirm
  `serverVersion` before restore, migrate, resync, or collection changes.
- There is no Splunk Enterprise **10.3** release train; Cloud **10.3.x** stacks
  are Cloud-only doc trains.

The optional rendered `server.conf` sets `[kvstore] storageEngine = wiredTiger`
for documentation/intent; the actual conversion is performed by the migrate
verb, not by the conf alone.

## SHC Member Resync

When one SHC member's KV Store is stale or failed (visible in
`splunk show kvstore-status --verbose` as a member not in `Ready`/replicating
state):

1. Confirm the captain and other members are healthy.
2. Take a backup on the captain.
3. On the affected member only: `splunk stop`, `splunk clean kvstore --local`,
   `splunk start`. The member rejoins and re-replicates from the captain.
4. If required, run `splunk resync kvstore` on the member.

Never run `clean kvstore --local` on the captain or on multiple members at once.

## Health Checks

`splunk show kvstore-status --verbose` reports:

- `serverVersion` and `storageEngine`.
- Per-member `replicationStatus`, `standalone` vs `replica set`, and roles.
- `disabled` state and last sync information.

Read this before and after any restore, migrate, or resync. The rendered
`status.sh` also runs `btool server list kvstore` to surface effective
`[kvstore]` settings.

## Common Failure Modes

- KV Store does not start after an upgrade: usually a storage-engine or version
  mismatch; check `mongod.log` and `splunkd.log`, validate version
  compatibility, and consider migration.
- SHC member stuck not-ready: resync the member from the captain.
- Restore appears to succeed but collections are empty: confirm the archive
  name, that the restore ran on the captain, and that replication completed.

## Out Of Scope

- KV Store TLS/certificate configuration (handled by `splunk-platform-pki-setup`,
  including the KV Store dual-EKU and hostname-validation requirements).
- Index lifecycle and SmartStore (handled by
  `splunk-index-lifecycle-smartstore-setup`).
- SHC bootstrap and captaincy operations (handled by
  `splunk-search-head-cluster-setup`).

# Splunk KV Store Admin Reference

## Research Basis

Current Splunk Enterprise KV Store documentation (verified 2026):

- For portable runtime selection, query authenticated `splunk show kvstore-status
  first. A ready cohosted store has `type: Pdl` under its nested
  Service Info and uses `splunk backup kvstore -backupParallelJobs true
  -archiveName NAME`; the archive is restored with `-restoreParallelJobs true`
  and `NAME.tar.gz`. A legacy store uses `-pointInTime true` for consistent
  backups. The rendered scripts poll `backupRestoreStatus` with a bounded
  timeout and requires `backupRestoreStatus : Ready` before claiming completion.
- Restore with `splunk restore kvstore -pointInTime true -archiveName <file>.tar.gz`
  for a legacy store, or the parallel restore flags above for cohosted stores.
  On a search head cluster, run a parallel restore from one cluster member; only
  one restore can run at a time. A point-in-time restore must run from the
  static captain with `splunk enable kvstore-maintenance-mode`, and maintenance
  is disabled after success. Parallel restore does not require maintenance mode.
  The rendered script leaves PIT maintenance enabled when restore fails so the
  operator can investigate safely.
- `splunk clean kvstore --local` (standalone) or `--cluster` (SHC) permanently
  deletes KV Store data; back up first.
- Storage-engine migration: single-instance deployments migrate to WiredTiger
  automatically during the upgrade to Splunk Enterprise 9.0+. Search head
  clusters migrate manually with
  `splunk start-shcluster-migration kvstore -storageEngine wiredTiger`, using
  `-isDryRun true` first to verify readiness.
- KV Store server-version upgrade: Splunk Enterprise 9.4+ no longer supports
  server version 4.2; it auto-upgrades to 7.0, and 10.2+ auto-upgrades to 8.0
  about 60 seconds after the first start once all SHC members run the same
  Splunk version. On legacy Enterprise releases before 10.3, operators may
  temporarily use `kvstoreUpgradeOnStartupEnabled = false` in `[kvstore]` to
  coordinate a manual upgrade. The setting is removed and has no effect in
  Enterprise 10.3 and newer; never render it for those versions. If a manual
  server-version upgrade fails, Splunk auto-restores from the backup it took
  just before the upgrade.
- Check state with authenticated `splunk show kvstore-status`.
- Enterprise 10.6 cohosted PostgreSQL migration deferral is a different
  control: when ITSI 5.0.x requires postponing migration, set
  `[kvstore] postgresMigrateOnStartup = false` on Enterprise 10.4 before the
  Enterprise upgrade. Use the renderer's `--defer-postgres-migration true`
  option to produce a reviewable `server.conf`; distribute it through normal
  configuration management and verify effective precedence with
  `splunk btool server list kvstore --debug`. After upgrade, verify the flag is
  still false, status reports `migrationStatus : NotStarted`, and KV data and
  service remain healthy. Re-enable only in a later approved migration window.

## Collections And Lookups

KV Store collections are defined in `collections.conf` (`[<collection>]` with
optional `replicate` and `field.<name> = <number|string|bool|time|cidr>`). KV
Store lookups are defined in `transforms.conf` with `external_type = kvstore`,
`collection = <collection>`, and `fields_list = _key, <fields>`. This skill
writes both via the REST `configs/conf-*` endpoints (SHC-deployer-bundle aware)
so no restart is required for the collection definition itself.

## Platform Boundary

The wrapper accepts `--platform auto|cloud|enterprise`. Before any live apply,
all phase, preflight, or status action, `auto` resolves the configured target
with the shared platform helpers.

- Splunk Enterprise/customer-managed runtimes can use host lifecycle scripts
  after the supported Enterprise-version gate succeeds.
- Managed Splunk Cloud owns backup, restore, clean/reset, maintenance mode,
  storage-engine migration, server-version upgrade, and host KV Store status.
  Those requests exit `2` before rendering or running host assets and route to
  Splunk Support.
- Collection definitions and KV Store lookup definitions are customer-managed
  knowledge objects on Cloud and can be applied through the standard Splunk
  REST configuration endpoints only in an existing writable app namespace.
  The workflow verifies that namespace before mutation and forces direct REST
  delivery so unrelated deployer credentials cannot select a local bundle
  path. This exception does not grant access to any host lifecycle command.

When assets are rendered explicitly with `--platform cloud`, every host script
contains an independent Cloud gate and exits `2` before invoking `splunk`.

## Topology Notes

- Standalone: storage-engine migration and server-version upgrade are automatic
  on the Splunk Enterprise upgrade. Live standalone migrate/upgrade operations
  therefore return a nonzero handoff instead of reporting a status-only script
  as a completed mutation.
- SHC: migrate and upgrade are explicit, coordinated cluster commands; run them
  from a member after all members are on the same Splunk version. Hand off
  replication-lag triage, oplog reset, and captain transfer to
  `splunk-search-head-cluster-setup`.

The migration apply path defaults to the supported dry run and clearly reports
that no conversion occurred. Actual SHC migration and server-version upgrade
are separately acceptance-gated by the setup wrapper and rendered scripts.

## Validation

Static validation confirms the rendered assets exist. Live validation runs the
rendered `status.sh` (`splunk show kvstore-status`).

The optional `server.conf` is not installed by collection REST apply. Distribute
it through the topology's normal app/bundle workflow before relying on either
`kvstoreUpgradeOnStartupEnabled` or `postgresMigrateOnStartup`; these settings
control separate upgrade behaviors.

`--backup-mode auto` is the default. `parallel`, `point-in-time`, and `legacy`
are explicit modes; an explicit point-in-time request is rejected for a
cohosted `Pdl` store so its consistency guarantee is never silently downgraded.

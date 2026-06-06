# Splunk KV Store Admin Reference

## Research Basis

Current Splunk Enterprise KV Store documentation (verified 2026):

- Back up with `splunk backup kvstore -pointInTime true` from any search head.
  Point-in-time backups are consistent and land in `$SPLUNK_DB/kvstorebackup`
  as a `.tar.gz` archive. Take a backup before every restore, migrate, or upgrade.
- Restore with `splunk restore kvstore -pointInTime true -archiveName <file>.tar.gz`.
  On a search head cluster, run restore from the captain; only one restore can
  run at a time across the cluster. Enable maintenance mode with
  `splunk enable kvstore-maintenance-mode` before a clustered restore.
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
  Splunk version. Disable the automatic upgrade with
  `kvstoreUpgradeOnStartupEnabled = false` in the `[kvstore]` stanza of
  `server.conf` and upgrade manually with
  `splunk start-shcluster-upgrade kvstore -version 7.0` (or `8.0`). If a manual
  server-version upgrade fails, Splunk auto-restores from the backup it took
  just before the upgrade.
- Check state with `splunk show kvstore-status`.

## Collections And Lookups

KV Store collections are defined in `collections.conf` (`[<collection>]` with
optional `replicate` and `field.<name> = <number|string|bool|time|cidr>`). KV
Store lookups are defined in `transforms.conf` with `external_type = kvstore`,
`collection = <collection>`, and `fields_list = _key, <fields>`. This skill
writes both via the REST `configs/conf-*` endpoints (SHC-deployer-bundle aware)
so no restart is required for the collection definition itself.

## Topology Notes

- Standalone: storage-engine migration and server-version upgrade are automatic
  on the Splunk Enterprise upgrade; this skill mostly reports status and renders
  backup/restore helpers.
- SHC: migrate and upgrade are explicit, coordinated cluster commands; run them
  from a member after all members are on the same Splunk version. Hand off
  replication-lag triage, oplog reset, and captain transfer to
  `splunk-search-head-cluster-setup`.

## Validation

Static validation confirms the rendered assets exist. Live validation runs the
rendered `status.sh` (`splunk show kvstore-status`).

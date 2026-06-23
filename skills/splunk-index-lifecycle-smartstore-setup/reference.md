# Splunk Index Lifecycle / SmartStore Reference

## Lifecycle Model

This skill covers decisions around Splunk index lifecycle:

- Inventory: index size, age, latest event, disabled state, retention settings,
  ingest throughput, HEC token targets, saved searches, dashboards, macros,
  roles, and ES/ITSI/ARI/CIM dependencies.
- Retention: Enterprise `maxTotalDataSizeMB` and `frozenTimePeriodInSecs`,
  SmartStore `maxGlobalDataSizeMB`, `maxGlobalRawDataSizeMB`, and Cloud ACS
  `searchableDays` / `maxDataSizeMB`.
- SmartStore: Enterprise remote volumes, per-index/global `remotePath`, cache
  manager, provider settings, and cluster-manager bundle assets.
- Archive/restore: Splunk Cloud DDAA handoff to `splunk-ddaa-archive`; Cloud
  restore is UI-only. Enterprise archive/thaw remains a reviewed runbook.
- Disable/delete/clean: full apply is available only behind explicit gates.

Research anchors:

- Splunk indexes age through hot, warm, cold, frozen, and thawed buckets.
- `frozenTimePeriodInSecs` is a minimum searchable-retention window; size limits
  can freeze data earlier.
- SmartStore freezing uses `maxGlobalDataSizeMB`,
  `maxGlobalRawDataSizeMB`, and `frozenTimePeriodInSecs`; old local-only size
  settings such as `maxTotalDataSizeMB` are not the SmartStore control surface.
- Splunk Cloud index lifecycle uses ACS fields such as `searchableDays`,
  `maxDataSizeMB`, and, for DDAA, `splunkArchivalRetentionDays`.
- Cloud DDAA disable/switch and restore are not generic ACS apply operations in
  this workflow; use Splunk Web/support handoffs.
- The SPL `delete` command hides events and does not reclaim disk, so it is not
  used for lifecycle cleanup.

## Operations

- `inventory`: render read-only collection searches and reports.
- `retention`: render Enterprise retention overlays or Cloud ACS payloads.
- `smartstore`: render existing SmartStore assets.
- `archive`: render DDAA or Enterprise archive handoff.
- `restore-handoff`: render Cloud restore or Enterprise thaw instructions.
- `disable-index`: gated Enterprise disable workflow; Cloud disable is a
  handoff, not a generic apply.
- `delete-index`: gated Enterprise or Cloud index deletion workflow.
- `clean-data`: gated standalone Enterprise data clean workflow; refused for
  indexer clusters.

## Destructive Gate Evidence

`delete-index` and `clean-data` fail before Splunk/ACS calls unless all required
inputs exist:

- `--accept-destructive-index-delete`
- `--owner-approval-file`
- `--backup-evidence-file`
- `--evidence-file`
- `--confirm-token DELETE_INDEX:<index>` for every target index

The evidence file is JSON. Supported deletion approval shapes:

```json
{
  "safe_to_delete_indexes": ["old_lab"],
  "non_production_test_indexes": ["main"],
  "sensitive_delete_approved_indexes": ["risk"],
  "destructive_actions": {
    "indexes": {
      "old_lab": {
        "safe_to_delete": true,
        "dependencies_clear": true,
        "ingest_stopped": true
      }
    }
  }
}
```

Hard blocks and protected defaults:

- Index names beginning with `_` are always refused for deletion.
- `main`, `summary`, `history`, `lastchanceindex`, and `splunklogger` require
  non-production test classification in evidence.
- ES/ITSI/ARI-sensitive indexes such as `notable`, `risk`,
  `threat_activity`, `itsi_summary*`, and `ari_*` require explicit sensitive
  delete approval.
- `--indexes all` is refused for disruptive operations.
- Clustered `clean-data` is refused.

## SmartStore Notes

- SmartStore settings live primarily in `indexes.conf`, with cache-manager
  settings in `server.conf` and low-level bucket localization settings in
  `limits.conf`.
- SmartStore can be enabled globally with `[default] remotePath = ...` or
  per-index with `remotePath` under individual index stanzas.
- Remote volumes use `[volume:<name>]`, `storageType = remote`, and a provider
  URI such as `s3://...`, `gs://...`, or `azure://...`.
- For indexer clusters, distribute peer-side `indexes.conf` and `server.conf`
  through the cluster-manager configuration bundle.
- SmartStore indexes in indexer clusters require `repFactor = auto`.
- SmartStore index stanzas still require `homePath`, `coldPath`, and
  `thawedPath`; `coldPath` and `thawedPath` are ignored for normal SmartStore
  operation but remain required settings.
- Remote volume paths must be unique to a single running standalone indexer or
  indexer cluster.
- Keep `enableTsidxReduction = false` and `maxDataSize = auto` at defaults for
  SmartStore unless Splunk Support directs otherwise.

## Cloud And Handoffs

- Cloud retention/delete apply uses ACS token files and a generated curl config
  file so token values are not placed directly in argv.
- Cloud DDAA enable/update is delegated to `splunk-ddaa-archive`.
- Cloud restore is a UI handoff from Settings > Indexes.
- Dependency proof routes to `splunk-data-source-readiness-doctor`.
- `collect-evidence.sh` can POST read-only searches to
  `/services/search/v2/jobs/export` when `--session-key-file` and
  `--splunk-uri` are supplied. The session key is read from a local file and
  placed in a temporary curl config file, not directly in process argv.
- General Cloud index/HEC/role management routes to `splunk-cloud-acs-admin-setup`
  or `splunk-hec-service-setup`.

## Validation

Run:

```bash
bash skills/splunk-index-lifecycle-smartstore-setup/scripts/validate.sh
```

Static validation checks lifecycle reports and operation-specific files. For
SmartStore renders it also verifies the remote volume stanza. `--live` runs the
rendered `status.sh` and redacts obvious remote credential fields.

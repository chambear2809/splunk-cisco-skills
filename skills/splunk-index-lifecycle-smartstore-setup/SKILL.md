---
name: splunk-index-lifecycle-smartstore-setup
description: >-
  Render, preflight, apply, and validate Splunk index lifecycle and SmartStore
  workflows. Use when the user asks to inventory index age/size/retention,
  decide whether indexes are unused, change searchable retention, configure
  SmartStore remote volumes, enable Cloud archive handoffs, restore/thaw
  archived data, disable indexes, delete indexes, clean standalone index data,
  configure S3/GCS/Azure object storage for indexes, set indexes.conf lifecycle
  settings, maxTotalDataSizeMB, maxGlobalDataSizeMB, maxGlobalRawDataSizeMB,
  frozenTimePeriodInSecs, cache manager settings, limits.conf remote-storage
  localization settings, cluster-manager bundle deployment, or standalone
  indexer lifecycle assets.
---

# Splunk Index Lifecycle / SmartStore Setup

This skill is the canonical index lifecycle workflow for Splunk Platform. It
renders evidence collection, dependency reports, retention plans, SmartStore
configuration, archive/restore handoffs, and gated apply scripts for selected
high-risk operations.

## Agent Behavior

Never ask for Splunk session keys, ACS tokens, object-store access keys, or
other secrets in chat. Use local files only:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/acs_token
bash skills/shared/scripts/write_secret_file.sh /tmp/smartstore_s3_access_key
bash skills/shared/scripts/write_secret_file.sh /tmp/smartstore_s3_secret_key
```

Start with render or inventory. Do not treat a frozen, stale, or low-volume
index as unused until dependency evidence has been collected and reviewed.

Destructive operations fail closed. `delete-index` and `clean-data` require:

- `--accept-destructive-index-delete`
- `--owner-approval-file`
- `--backup-evidence-file`
- `--evidence-file` marking each target index safe to delete
- `--confirm-token DELETE_INDEX:<index>` for each target index

The skill hard-blocks deletion of internal indexes beginning with `_`. It also
blocks protected default indexes and ES/ITSI/ARI-sensitive indexes unless the
evidence explicitly classifies the index as safe under the documented gates.
Clustered `clean-data` is refused.

## Quick Start

Inventory all indexes and render collection searches:

```bash
bash skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh \
  --phase inventory \
  --indexes all
```

Render and optionally run REST export collection with a local session-key file:

```bash
bash skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh \
  --phase inventory \
  --indexes all \
  --session-key-file /tmp/splunk_session_key \
  --splunk-uri https://localhost:8089
```

Render an Enterprise retention overlay:

```bash
bash skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh \
  --operation retention \
  --indexes cisco_asa,network \
  --max-total-data-size-mb 1048576 \
  --frozen-time-period-in-secs 7776000
```

Render per-index SmartStore for an indexer cluster:

```bash
bash skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh \
  --operation smartstore \
  --deployment cluster \
  --remote-provider s3 \
  --remote-path s3://splunk-prod-smartstore/cluster-a \
  --indexes main,summary \
  --max-global-data-size-mb 10485760 \
  --cache-size-mb 262144
```

Render a Splunk Cloud retention payload:

```bash
bash skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh \
  --platform cloud \
  --operation retention \
  --stack my-stack \
  --indexes cisco_asa \
  --searchable-days 90 \
  --max-data-size-mb 512000
```

## What It Renders

The default output directory is `splunk-smartstore-rendered/smartstore/`.

- `index-lifecycle-report.md/json`
- `index-dependency-report.md/json`
- `collection-searches.spl`
- `collect-evidence.sh`
- `retention-change-plan.md`
- `destructive-action-plan.md`
- SmartStore `indexes.conf.template`, `server.conf`, and `limits.conf`
- Enterprise retention/disable overlays and apply helpers
- Cloud ACS retention/delete payload helpers
- DDAA archive and restore/thaw handoffs

Use `splunk-data-source-readiness-doctor` when evidence must prove whether
dashboards, saved searches, ES, ITSI, ARI, CIM, HEC tokens, or macros still
depend on an index. Use `splunk-ddaa-archive` for Splunk Cloud DDAA archive
enable/update and restore auditing.

Read `reference.md` before changing lifecycle safety gates, destructive apply
behavior, or SmartStore retention defaults.

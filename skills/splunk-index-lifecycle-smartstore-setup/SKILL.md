---
name: splunk-index-lifecycle-smartstore-setup
description: >-
  Render, preflight, apply, and validate Splunk index lifecycle and SmartStore
  configuration. Use when the user asks to configure SmartStore remote volumes,
  S3/GCS/Azure object storage for indexes, indexes.conf lifecycle settings,
  maxGlobalDataSizeMB, maxGlobalRawDataSizeMB, frozenTimePeriodInSecs, cache
  manager settings, limits.conf remote-storage localization settings,
  cluster-manager bundle deployment, or standalone indexer SmartStore assets.
---

# Splunk Index Lifecycle / SmartStore Setup

This skill renders Splunk Enterprise SmartStore and retention configuration for
indexer clusters or standalone indexers. It is render-first because SmartStore
settings affect bucket placement and freezing behavior.

## Agent Behavior

Never ask for object-store access keys in chat. Prefer IAM roles, managed
identity, or existing credential files. If S3 access keys are unavoidable, use
local-only files:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/smartstore_s3_access_key
bash skills/shared/scripts/write_secret_file.sh /tmp/smartstore_s3_secret_key
```

Use `template.example` for non-secret values: deployment type, remote path,
provider, volume name, index list, retention limits, and cache sizing.

## Quick Start

Render per-index SmartStore for an indexer cluster:

```bash
bash skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh \
  --deployment cluster \
  --remote-provider s3 \
  --remote-path s3://splunk-prod-smartstore/cluster-a \
  --indexes main,summary \
  --max-global-data-size-mb 10485760 \
  --cache-size-mb 262144
```

Apply on a cluster manager after review:

```bash
bash skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh \
  --phase apply \
  --deployment cluster \
  --remote-provider s3 \
  --remote-path s3://splunk-prod-smartstore/cluster-a \
  --indexes main,summary
```

## What It Renders

- `indexes.conf.template` with SmartStore remote volume and index stanzas
- `server.conf` with optional cache manager and cleanup settings
- `limits.conf` with optional low-level remote-storage localization settings
- helper scripts for preflight, cluster-manager apply, standalone apply, and status

For indexer clusters, use the configuration bundle method. For standalone
indexers, apply locally and coordinate restart carefully.

Read `reference.md` before choosing global SmartStore scope or changing
retention values.

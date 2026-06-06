# Splunk Cloud DDAA Archive Lifecycle Reference

Dynamic Data Active Archive (DDAA) is a Splunk Cloud Platform retention tier that
moves expired index data into a **Splunk-managed** archive for long-term,
compliance-oriented retention, with an integrated restore workflow. This skill
manages DDAA archive retention per index through the ACS API and provides the
restore/audit handoffs.

## Retention Tiers

- **DDAS** — Dynamic Data Active Searchable. Hot/warm searchable storage. New
  data lands here. Controlled by `searchableDays`.
- **DDAA** — Dynamic Data Active Archive. Splunk-managed archive for data that
  has aged past `searchableDays`. Controlled by `splunkArchivalRetentionDays`.
- **DDSS** — Dynamic Data Self Storage. Customer-owned S3 archive
  (`selfStorageBucketPath`). DDSS is a separate option from DDAA; this skill does
  not manage DDSS (use `splunk-cloud-acs-admin-setup` / the UI).

`splunkArchivalRetentionDays` is the **total** retention (searchable + archive),
measured from the **index creation date** (not rolling). The archive period is
`splunkArchivalRetentionDays − searchableDays`.

## ACS API Rules

- Create: `POST /<stack>/adminconfig/v2/indexes` with `name`, `datatype`,
  `searchableDays`, `splunkArchivalRetentionDays`, optional `maxDataSizeMB`.
- Enable/update DDAA: `PATCH /<stack>/adminconfig/v2/indexes/<name>` with a
  non-zero `splunkArchivalRetentionDays`.
- `splunkArchivalRetentionDays` must be **greater than** `searchableDays`.
- `splunkArchivalRetentionDays` must be **≤ 3650 days** (10 years), and ≤ the
  deployment's `maxDataArchiveRetentionPeriod`.
- You **cannot disable DDAA** or switch between DDAA and DDSS via the API. Use
  the Splunk Web UI for those. This skill refuses to render an API "disable".

The rendered `enable-ddaa.sh` calls the ACS API with `curl`, reading the Bearer
token from a local file (never argv/chat), and is gated behind a typed `APPLY`
confirmation. `status.sh` reads the values back.

## Restore (UI-Only)

There is no public ACS restore endpoint. Restore from **Settings > Indexes** in
Splunk Web:

- Select the index and the archived time range to restore.
- You can restore up to ~10% of your DDAS entitlement at once.
- Restored data lands back in DDAS and is searchable for **30 days**, then
  auto-expires. You can clear it earlier via the Restore Archive window.
- Restoring never removes data from the archive; the restored copy is temporary.

After restore, inspect restored buckets with:

```
| dbinspect index=<index> | search state=* | stats count by state, bucketId
```

## Storage Consumption

Archived and restored storage consumption appears in **Settings > Indexes** and
the Cloud Monitoring Console storage views. There is no single ACS metric
endpoint for archive GB. The rendered `audit.sh` provides `dbinspect` searches
for current DDAS footprint and restored buckets.

## Entitlements And Cost

- DDAA archive size is governed by your subscription entitlement.
- Restores are bounded (~10% of DDAS entitlement at a time).
- Increasing `splunkArchivalRetentionDays` keeps data longer; decreasing it can
  make data eligible for deletion sooner. Changes compute from the index
  creation date, so confirm the effective dates before applying.

## Relationship To Other Skills

- General Cloud index management (create indexes, searchable retention, DDSS,
  HEC, roles): `splunk-cloud-acs-admin-setup`.
- On-prem index lifecycle / SmartStore / freezing: not DDAA — see
  `splunk-index-lifecycle-smartstore-setup`.
- Ingest-time routing to S3 (different from retention archiving):
  `splunk-ingest-actions`.

## Out Of Scope

- DDSS (self storage) configuration and restore.
- On-prem cold-to-frozen archiving and `coldToFrozenScript`.
- Data deletion / legal hold workflows.

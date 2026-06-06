---
name: splunk-ddaa-archive
description: >-
  Render, preflight, and validate Splunk Cloud Platform Dynamic Data Active
  Archive (DDAA) lifecycle assets: per-index archive retention via the ACS API
  (searchableDays plus splunkArchivalRetentionDays), enable/update payloads,
  archived/restored storage audits, and a guided UI restore handoff. Use when
  the user asks to archive expired Splunk Cloud data to the Splunk-managed
  archive, set or change DDAA archive retention, enable DDAA on an index,
  restore archived data for searching, audit archive/restore storage
  consumption, or understand DDAA versus DDSS retention tiers.
---

# Splunk Cloud DDAA Archive Lifecycle

This skill renders Splunk Cloud Platform **Dynamic Data Active Archive (DDAA)**
lifecycle assets: per-index archive retention configuration through the Admin
Config Service (ACS) API, enable/update payloads, archived/restored storage
audits, and a guided restore handoff. It is render-first because retention
changes affect how long data is kept and when it is permanently deleted.

## Retention Model (Read First)

- **DDAS** (Dynamic Data Active Searchable) — searchable storage. Controlled by
  `searchableDays`.
- **DDAA** (Dynamic Data Active Archive) — Splunk-managed archive for expired
  data. Controlled by `splunkArchivalRetentionDays`, which is the **total**
  retention (searchable + archived) measured from index creation date, not a
  rolling window.
- Archive retention period = `splunkArchivalRetentionDays` − `searchableDays`.
- `splunkArchivalRetentionDays` must be **greater than** `searchableDays` and
  **≤ 3650** days (10 years, deployment max may be lower).

Constraints enforced by ACS:

- You can enable DDAA and increase/decrease `splunkArchivalRetentionDays` via the
  API (POST to create, PATCH to update).
- You **cannot disable DDAA**, nor switch between DDAA and DDSS, via the API —
  those require the Splunk Web UI.
- **Restore is UI-only**: restore archived data from **Settings > Indexes**.
  Restored data lands in DDAS and auto-expires after 30 days (or clear it
  manually). You can restore up to ~10% of your DDAS entitlement at a time.

## Agent Behavior

Never paste the ACS token into chat or argv. Provide it as a local file:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/acs_token
```

The rendered apply script reads the token from that file. Use `template.example`
for non-secret values: stack, index, datatype, and retention days.

## Quick Start

Render a DDAA enable plan (1 year total, 90 days searchable):

```bash
bash skills/splunk-ddaa-archive/scripts/setup.sh \
  --stack my-stack --index cisco_asa \
  --searchable-days 90 --archival-retention-days 365 --operation enable
```

Audit and check current archive retention (read-only):

```bash
bash skills/splunk-ddaa-archive/scripts/validate.sh --live
```

## What It Renders

- `create-payload.json` / `patch-payload.json` — ACS index bodies for DDAA
- `enable-ddaa.sh` — apply create/PATCH via the ACS API using a token file (gated)
- `status.sh` — GET the index and show `searchableDays` / `splunkArchivalRetentionDays`
- `restore.sh` — guided UI restore handoff + a search to inspect restored buckets
- `audit.sh` — archived/restored storage consumption hints
- `README.md` / `metadata.json` — review context

## Operating Notes

- DDAA enablement and retention changes are not rolling; compute from the index
  creation date.
- To disable DDAA or switch DDAA/DDSS, use the Splunk Web UI; this skill refuses
  to render an API "disable".
- For general Cloud index management (create, searchable retention, DDSS), see
  `splunk-cloud-acs-admin-setup`.

Read `reference.md` before changing retention or restoring archived data.

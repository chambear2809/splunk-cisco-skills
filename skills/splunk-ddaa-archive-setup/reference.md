# Splunk Cloud DDAA Archive Reference

## Research Basis

Based on current Splunk Cloud Platform documentation (verified 2026):

- Dynamic Data Active Archive (DDAA) moves expired index data from Splunk Cloud
  to a Splunk-managed archive, configured per index by an archiving rule. It is
  separate from Dynamic Data Self Storage (DDSS), where you own the archive
  bucket.
- Enable or change DDAA through the ACS API/CLI (version 2.4.0+) by setting
  `splunkArchivalRetentionDays` on the index (create or PATCH/update). The ACS
  CLI exposes `--splunk-archival-retention-days` on `acs indexes create` and
  `acs indexes update`.
- `splunkArchivalRetentionDays` must be greater than `searchableDays` because
  the archival retention is the TOTAL retention including the searchable period.
  It must be <= the deployment maximum of 3650 days (10 years), and it is
  counted from the index creation date, not a rolling window.
- You cannot use the ACS API/CLI to disable DDAA, nor to switch between DDAA and
  DDSS. Those changes are Splunk Web only (Settings > Indexes, Dynamic Data
  Storage field).
- Restoring archived data is a Splunk Web operation (Settings > Indexes >
  Restore). Restored data lands in Dynamic Data Active Searchable (DDAS), is
  searchable for 30 days, then is removed automatically (the archive copy is
  retained). You can restore up to 10% of your DDAS entitlement at a time, and
  can Clear a restore early.

## Apply Transport

Apply uses the `acs` CLI through the shared ACS helpers (`acs_prepare_context`,
`cloud_check_index`, `acs_command`). If the index exists, the skill updates its
`splunkArchivalRetentionDays`; otherwise it creates the index with DDAA enabled.
Restore and disable are emitted as runbooks because they have no ACS API.

## Boundaries

Generic Splunk Cloud index lifecycle, DDSS self-storage locations, and other ACS
administration live in `splunk-cloud-acs-admin-setup`. This skill focuses on the
DDAA archive policy, retention math, and the UI-only restore/disable runbooks.

## Validation

Static validation confirms the rendered assets exist and that `acs-payload.json`
declares `splunkArchivalRetentionDays`. Live status runs `acs indexes describe`.

---
name: splunk-ddaa-archive-setup
description: >-
  Render, validate, and apply Splunk Cloud Platform Dynamic Data Active Archive
  (DDAA): per-index archival retention via the ACS index splunkArchivalRetentionDays
  setting, retention math validation, and restore and disable runbooks for the
  Splunk Web-only operations. Use when the user asks to archive expired Splunk
  Cloud index data to the Splunk-managed archive, set or change DDAA archival
  retention, restore archived data, or move an index onto Splunk Archive. Not
  for DDSS self-storage or generic index administration, which live in
  splunk-cloud-acs-admin-setup.
---

# Splunk Cloud DDAA Archive Setup

This skill renders and applies Dynamic Data Active Archive policy for Splunk
Cloud indexes. It is render-first because archival retention is a durable
storage policy counted from index creation.

## Agent Behavior

Never ask for secrets; ACS auth uses the project `credentials` file and the
configured stack. Applying archival retention refuses to run without
`--accept-archive-retention`. Restore and disable have no ACS API and are
emitted as Splunk Web runbooks.

## Quick Start

Render a DDAA policy (90 searchable days, 365 total):

```bash
bash skills/splunk-ddaa-archive-setup/scripts/setup.sh --index netfw --searchable-days 90 --archival-retention-days 365
```

Apply it via ACS (gated):

```bash
bash skills/splunk-ddaa-archive-setup/scripts/setup.sh --phase apply \
  --index netfw --searchable-days 90 --archival-retention-days 365 --accept-archive-retention
```

## What It Renders

- `acs-payload.json` - ACS index body with `splunkArchivalRetentionDays`
- `restore-runbook.md` - Splunk Web restore steps (30-day searchable copy, <=10% DDAS)
- `disable-runbook.md` - Splunk Web disable steps (no API)
- `status.sh` - `acs indexes describe <index>`

## Rules

- `splunkArchivalRetentionDays` is the TOTAL retention including the searchable
  period, counted from index creation, and must exceed searchable days and be
  <= 3650 days (10 years).
- DDAA must be enabled for the stack; if Splunk Archive is greyed out, contact
  your Splunk account team.
- Generic index CRUD and DDSS self-storage are handled by
  `splunk-cloud-acs-admin-setup`.

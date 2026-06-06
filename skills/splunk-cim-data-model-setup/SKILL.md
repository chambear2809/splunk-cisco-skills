---
name: splunk-cim-data-model-setup
description: >-
  Render, validate, and apply Splunk Common Information Model (CIM) data model
  governance: install handoff for the CIM add-on (Splunk_SA_CIM), data model
  acceleration settings, allowed-index constraint macros (cim_<model>_indexes),
  and CIM eventtype/tag mapping to make sourcetypes CIM-compliant, with tstats
  validation. Use when the user asks to accelerate a CIM data model, constrain
  CIM data model indexes, map data to CIM with tags and eventtypes, fix CIM
  compliance, or manage datamodels.conf for CIM or custom data models. Not for
  Enterprise Security-specific acceleration, which lives in
  splunk-enterprise-security-config.
---

# Splunk CIM Data Model Setup

This skill renders and applies Common Information Model data model governance.
It is render-first because acceleration consumes indexer and storage resources
and index constraints change what searches return.

## Agent Behavior

Never ask for the Splunk admin password; the apply path reads the project
`credentials` file via the shared helper. Acceleration refuses to apply without
`--accept-acceleration`. If `Splunk_SA_CIM` is missing, hand off to
`splunk-app-install` (Splunkbase 1621) before applying.

Read `reference.md` before enabling acceleration on a high-volume model.

## Quick Start

Render acceleration governance for a model:

```bash
bash skills/splunk-cim-data-model-setup/scripts/setup.sh --datamodel Network_Traffic --acceleration true --earliest-time -7d
```

Apply acceleration live (gated):

```bash
bash skills/splunk-cim-data-model-setup/scripts/setup.sh --phase apply \
  --datamodel Network_Traffic --acceleration true --accept-acceleration
```

Map a sourcetype into CIM (eventtype + tags) and constrain indexes:

```bash
bash skills/splunk-cim-data-model-setup/scripts/setup.sh --phase apply \
  --datamodel Authentication \
  --eventtype-name cisco_ise_auth --eventtype-search 'sourcetype=cisco:ise:syslog' \
  --tags authentication --constrain-indexes ise,identity
```

## What It Renders

- `datamodels.conf` - acceleration override (earliest_time, backfill, cron, max_concurrent, manual_rebuilds)
- `macros.conf` - `cim_<model>_indexes` allowed-index constraint
- `eventtypes.conf` + `tags.conf` - CIM compliance mapping
- `validate-tstats.sh` - `| tstats ... from datamodel=<model>` check

## Boundaries

This skill owns CIM-wide data model governance for any app. Enterprise
Security's own data model acceleration and detection wiring stay in
`splunk-enterprise-security-config`. Data readiness scoring stays in
`splunk-data-source-readiness-doctor`.

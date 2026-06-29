---
name: splunk-cim-data-model
description: >-
  Render, preflight, and validate Splunk Common Information Model (CIM)
  data-model management assets: per-model acceleration settings in
  datamodels.conf, acceleration enable/disable plans, rebuild and backfill
  helpers, and CIM population/compliance audits via tstats and the
  summarization REST endpoint. Use when the user asks to manage CIM data models,
  enable or tune data model acceleration, set earliest/backfill ranges, rebuild
  an accelerated data model, audit CIM field compliance or model population, or
  prepare Splunk_SA_CIM acceleration overrides for Enterprise Security and ITSI.
---

# Splunk CIM Data-Model Management

This skill renders Common Information Model (CIM) data-model administration:
acceleration configuration (`datamodels.conf`), acceleration enable/disable and
rebuild helpers, and CIM population/compliance audits. It is render-first
because data model acceleration consumes indexer storage and search resources
and is a prerequisite for Enterprise Security and many ITSI/correlation
workflows.

## Agent Behavior

This skill does not handle secrets. Acceleration applies to data models defined
by `Splunk_SA_CIM` (or custom models). Render overrides into a dedicated app so
you never edit the shipped `Splunk_SA_CIM/default` files.

Use `template.example` for non-secret values: model list, acceleration toggle,
summary range, backfill range, and app name.

## Quick Start

Render acceleration for the core ES models with a 7-day summary range:

```bash
bash skills/splunk-cim-data-model/scripts/setup.sh \
  --models Authentication,Network_Traffic,Web,Endpoint \
  --acceleration true \
  --earliest-time -7d@d
```

Render a CIM population/compliance audit only (no config changes):

```bash
bash skills/splunk-cim-data-model/scripts/setup.sh --phase render --acceleration false
bash skills/splunk-cim-data-model/scripts/validate.sh --live
```

## What It Renders

- `datamodels.conf` — per-model `acceleration`, `acceleration.earliest_time`,
  `acceleration.backfill_time`, and `acceleration.max_concurrent` overrides
- `apply.sh` — stages `datamodels.conf` into an app `local/` and reloads it
- `rebuild.sh` — documented rebuild/backfill options (automatic / UI / disable-enable)
- `status.sh` — acceleration status via the summarization REST endpoint
- `audit.sh` — per-model population checks via `tstats` and CIM compliance hints
- `README.md` / `metadata.json` — review context

## Operating Notes

- Acceleration only summarizes data already mapped to a model by its
  constraints, tags, and field aliases. If a model is empty, fix data onboarding
  and CIM mapping first (see `splunk-data-source-readiness-doctor`).
- Set `acceleration.earliest_time` to the smallest range your detections need;
  larger ranges cost more storage and longer backfills.
- On indexer clusters, accelerated summaries live on the indexers; coordinate
  capacity before enabling many models.
- Enterprise Security expects the standard CIM models accelerated; align ranges
  with ES retention.

Read `reference.md` before enabling acceleration broadly or changing ranges.

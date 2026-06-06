# Splunk CIM Data-Model Management Reference

The Common Information Model (CIM) is a set of normalized data models shipped by
the `Splunk_SA_CIM` add-on. Detections, dashboards, Enterprise Security, and
ITSI correlation searches run `tstats` against accelerated CIM data models, so
acceleration configuration is an operational prerequisite, not a nicety.

## What This Skill Manages

- Per-model acceleration settings in `datamodels.conf`.
- Acceleration enable/disable and rebuild/backfill.
- CIM population and compliance audits.

It does not change the model definitions (constraints, fields) shipped by
`Splunk_SA_CIM`; it manages acceleration of those models and verifies that data
is actually mapped into them.

## Acceleration Settings

In `datamodels.conf`, per model:

- `acceleration = 1|0` — enable or disable acceleration.
- `acceleration.earliest_time = <relative time>` — how far back to summarize
  (for example `-7d@d`, `-1mon@d`). This is the dominant cost driver.
- `acceleration.backfill_time` — optional; summarize only back to this point
  even if `earliest_time` is larger (useful to cap an initial backfill).
- `acceleration.max_concurrent` — optional; concurrent summarization searches.
- `acceleration.cron_schedule`, `acceleration.max_time` — advanced tuning (set
  in the UI or conf when needed; not rendered by default).

Stage these overrides into a dedicated app `local/` directory. Never edit
`Splunk_SA_CIM/default`. The rendered `apply.sh` copies the file into
`etc/apps/<app>/local/datamodels.conf`.

## Where To Apply

- Single search head: apply locally.
- Search head cluster: apply through the SHC deployer
  (`splunk-search-head-cluster-setup`), not on individual members.
- Indexer cluster: accelerated summaries are built and stored on the indexers.
  Acceleration is configured on the search tier but consumes indexer storage and
  CPU. Validate capacity before enabling many models or large ranges.

## Rebuild And Backfill

Changing `earliest_time` to a larger range, or enabling acceleration on a model
with existing data, requires a rebuild/backfill to populate historical
summaries. The rendered `rebuild.sh` is gated (requires typing `REBUILD`) and
triggers a rebuild per model. You can also rebuild from
**Settings > Data models > _model_ > Edit > Rebuild**.

Rebuilds consume search and indexer resources; schedule them off-peak.

## Auditing CIM Population And Compliance

Acceleration only summarizes events that the model's constraints, `eventtype`
tags, and field aliases actually match. A model can be accelerated but empty if
the data is not CIM-mapped.

The rendered `audit.sh` runs, per model:

```
| tstats count from datamodel=<Model> where _time>=<range> by index sourcetype
```

- Non-empty results: data is mapped and accelerated.
- Empty results: the model is unaccelerated, or the data is not tagged/aliased
  into the model.

For deeper field-level CIM compliance (required tags, expected fields, eventtype
coverage), use `splunk-data-source-readiness-doctor`, which scores CIM
readiness per data source and emits fix handoffs.

## Summarization Status

`| rest splunk_server=local /services/admin/summarization` reports per-summary
completeness, size, and last access/mod time. The rendered `status.sh` surfaces
this so you can confirm summaries are complete and not stale.

## Relationship To Enterprise Security

Enterprise Security expects the standard security CIM models accelerated:
Authentication, Network_Traffic, Web, Endpoint (Processes/Filesystem/etc.),
Intrusion_Detection, Malware, Network_Sessions, Network_Resolution,
Vulnerabilities, Change, and others depending on enabled content. Align
`acceleration.earliest_time` with your ES detection lookback and data retention.
ES install/config is handled by `splunk-enterprise-security-install` and
`splunk-enterprise-security-config`.

## Out Of Scope

- Data onboarding and CIM tagging/field extraction (fix at the TA/add-on layer;
  diagnose with `splunk-data-source-readiness-doctor`).
- OCSF transforms and ingest-time normalization (see `splunk-ingest-actions`,
  `splunk-spl2-pipeline-kit`).
- Model definition authoring (custom data models beyond CIM acceleration).

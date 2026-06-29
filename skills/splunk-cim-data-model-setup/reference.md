# Splunk CIM Data Model Reference

## Research Basis

Based on current Splunk Common Information Model add-on documentation:

- The CIM add-on ships as `Splunk_SA_CIM` (Splunkbase app 1621) and provides the
  standard CIM data models (Authentication, Network_Traffic, Web, Malware,
  Endpoint, Change, Intrusion_Detection, Vulnerabilities, and others).
- `--acceleration` is three-state: `true` writes `acceleration = 1` (gated by
  `--accept-acceleration`), `false` writes `acceleration = 0` to disable, and the
  default `unset` leaves acceleration unmanaged (only macros/eventtypes/tags are
  governed).
- Data model acceleration is configured in `datamodels.conf` with
  `acceleration = 1` plus `acceleration.earliest_time`,
  `acceleration.backfill_time`, `acceleration.max_concurrent`,
  `acceleration.cron_schedule`, and `acceleration.manual_rebuilds`. Acceleration
  builds tsidx summaries on the indexers and consumes storage proportional to
  the summary range; choose the earliest_time window deliberately.
- Each CIM data model is constrained to a set of indexes through a macro named
  `cim_<ModelName>_indexes` (for example `cim_Network_Traffic_indexes`). Setting
  these macros to your real indexes keeps acceleration efficient and prevents
  scanning unrelated data.
- Data becomes CIM-compliant when events are tagged with the model's required
  tags and normalized to the model's fields. Tagging is typically done by
  defining an `eventtype` and attaching CIM tags to it
  (`[eventtype=<name>]` with `<tag> = enabled` in `tags.conf`).
- Validate with `| tstats count from datamodel=<ModelName>` or
  `| datamodel <ModelName> search`. The CIM add-on also ships a
  `Splunk_CIM_Validation` capability for field-level checks.

## Apply Transport

This skill writes `datamodels.conf`, `macros.conf`, `eventtypes.conf`, and
`tags.conf` stanzas through the REST `configs/conf-*` endpoints in the target
app (default `Splunk_SA_CIM`). The shared `rest_set_conf` helper is search head
cluster deployer-bundle aware. Acceleration changes and knowledge object changes
may require a configuration reload; the skill prints platform-appropriate
restart guidance.

## Decisions

- Use `--app-name Splunk_SA_CIM` to govern the shipped CIM models in place. Use a
  dedicated app when you maintain CIM customizations separately.
- Use `--constrain-indexes` to scope a model to its real source indexes before
  enabling acceleration.
- Use `--allow-custom-datamodel true` only when governing a non-CIM custom data
  model with the same acceleration mechanics.

## Validation

Static validation confirms the rendered assets exist. Live validation runs the
rendered `validate-tstats.sh`, which issues a `tstats` search against the model.

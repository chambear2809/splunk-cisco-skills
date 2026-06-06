# Splunk Ingest Actions Reference

## Research Basis

Based on current Splunk Ingest Actions documentation (verified 2026):

- Ingest Actions routes, filters, and masks data while it streams to the
  indexers. Each transformation is a rule; rules combine into a ruleset, and
  only one ruleset is supported per source type. Rules run in order.
- Rulesets are normally created in Splunk Web (Settings > Data > Ingest Actions)
  or through the supported REST endpoint `/services/data/ingest/rulesets`. The
  Splunk validated architecture guidance notes that rulesets are represented in
  props.conf and transforms.conf and are compatible with existing
  configuration-file management and distribution; this skill renders that
  representation and can write it via the REST `configs/conf-*` endpoints for
  automation, while the UI/endpoint remains the recommended interactive path.
- Ingest Actions adds `RULESET` processing to the indexer/heavy-forwarder
  pipeline. A `RULESET` setting behaves like `TRANSFORMS`; if both apply to the
  same source type, `TRANSFORMS` runs first. Rules are commonly expressed with
  `INGEST_EVAL`.
- S3 destinations are configured in the Ingest Actions Destinations tab or in
  `outputs.conf` using the Remote File System (RFS) stanza `[rfs:<name>]`. RFS
  S3 settings mirror SmartStore S3 settings (`path`, `remote.s3.auth_region`,
  `remote.s3.encryption`, `remote.s3.kms.key_id`, access/secret keys). A Splunk
  deployment supports a maximum of eight S3 destinations, and a destination must
  exist before a "Route to Destination" rule can use it.
- Deployment differs by topology: standalone indexers/forwarders apply
  immediately; indexer clusters require an explicit deploy from the cluster
  manager; heavy forwarders are managed through a dedicated deployment server;
  Splunk Cloud Victoria deploys automatically from the search head.
- CAUTION: transformations are applied before indexing and cannot be reverted
  for already-indexed data. Use the clone-events pattern when you must keep the
  original.

## Rule Types

- `eval` - arbitrary `INGEST_EVAL` expression (props `RULESET-` + transforms).
- `mask` - `_raw = replace(_raw, "<regex>", "<replacement>")`.
- `drop` - `queue = if(match(_raw, "<regex>"), "nullQueue", queue)`.
- `route-s3` - configures the `[rfs:<name>]` S3 destination in `outputs.conf`
  (the verified, apply-able artifact). The matching "Route to Destination" rule
  is authored in the Ingest Actions UI or via `/services/data/ingest/rulesets`;
  this skill does not hand-author the internal RFS routing transform (it is not
  a publicly specified hand-editable form, and `_TCP_ROUTING` is for S2S/tcpout,
  not RFS).

## Secrets

S3 access/secret keys are read from files at apply time and sent only in the
REST POST body, never on argv. Rendered `outputs.conf` contains placeholders.

## Validation

Static validation confirms the rendered assets exist and that `props.conf`
contains a `RULESET-` binding. Live validation lists rulesets through
`/services/data/ingest/rulesets`.

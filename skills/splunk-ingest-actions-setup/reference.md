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
  representation and can write it via the REST `configs/conf-*` endpoints only
  for Splunk Enterprise/customer-managed automation, while the UI/rulesets
  endpoint remains the supported managed Splunk Cloud path.
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
  rulesets authored through the supported Splunk Cloud Victoria workflow deploy
  automatically.
- CAUTION: transformations are applied before indexing and cannot be reverted
  for already-indexed data. Use the clone-events pattern when you must keep the
  original.

## Platform Boundary

`scripts/setup.sh` accepts `--platform auto|cloud|enterprise` and defaults to
`auto`. Before any live apply, `auto` resolves the configured target through the
shared credential helpers. A managed Splunk Cloud target is a hard gate: the
workflow renders review assets, prints the supported handoff, makes no conf-file
REST mutation, and exits `2`.

Use the following Cloud routes:

- `splunk-ingest-actions --platform cloud --phase render` for an Ingest Actions
  ruleset specification and Splunk Web `/services/data/ingest/rulesets` handoff.
- `splunk-ingest-processor-setup` for Splunk Cloud control-plane pipelines.
- `splunk-edge-processor-setup` for transformations on Edge Processors.

The `--platform enterprise` apply path remains available for Splunk Enterprise
and customer-managed heavy-forwarder/indexer targets.

## Rule Types

- `eval` - arbitrary `INGEST_EVAL` expression (props `RULESET-` + transforms).
- `mask` - `_raw = replace(_raw, "<regex>", "<replacement>")`.
- `drop` - `queue = if(match(_raw, "<regex>"), "nullQueue", queue)`.
- `route-s3` - configures the `[rfs:<name>]` S3 destination in `outputs.conf`
  (the verified, apply-able artifact). The matching "Route to Destination" rule
  is authored in the Ingest Actions UI or via `/services/data/ingest/rulesets`;
  this skill does not hand-author the internal RFS routing transform (it is not
  a publicly specified hand-editable form, and `_TCP_ROUTING` is for S2S/tcpout,
  not RFS). Apply therefore exits nonzero after staging the destination and
  printing the handoff; success requires the rule to be authored and verified.

## Secrets

S3 access/secret keys are read from files at apply time and sent only in the
REST POST body, never on argv. Rendered `outputs.conf` contains placeholders.

## Validation

Static validation confirms the rendered assets exist and that `props.conf`
contains a `RULESET-` binding. Live validation lists rulesets through
`/services/data/ingest/rulesets`.

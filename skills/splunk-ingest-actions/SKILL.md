---
name: splunk-ingest-actions
description: >-
  Render, preflight, and validate Splunk Ingest Actions assets: RFS (Remote File
  System) S3 and filesystem destinations in outputs.conf, a ruleset
  specification for filter/mask/set-index/route rules, a manual heavy-forwarder
  props.conf/transforms.conf preview, and ruleset status checks. Use when the
  user asks to filter, mask, redact, or route data at ingest time, set up Splunk
  Ingest Actions rulesets, configure an S3 or filesystem RFS destination, route
  events to an alternate index or to S3, drop noisy events before indexing, or
  audit existing ingest rulesets on Splunk Cloud Platform or Splunk Enterprise.
---

# Splunk Ingest Actions

This skill renders Splunk Ingest Actions assets: RFS (Remote File System)
destinations (`outputs.conf [rfs:<name>]`), a structured ruleset specification
for filter / mask / set-index / route rules, an optional manual
heavy-forwarder `props.conf`/`transforms.conf` preview, and live ruleset status
checks. It is render-first because ingest-time rules permanently change or drop
data before it is indexed.

## Important: How Rulesets Are Managed

Per Splunk, create and modify **rulesets** only through the Ingest Actions page
(**Settings > Ingest Actions**) or the REST endpoint
`/services/data/ingest/rulesets` — not by hand-editing the underlying
`transforms.conf`. This skill therefore:

- Renders **RFS destinations** in `outputs.conf` (documented as directly
  editable for advanced configuration).
- Renders a **ruleset specification** (`ruleset.json`) and a UI/REST handoff for
  creating the ruleset the supported way.
- Renders an optional **manual heavy-forwarder preview** (`props.conf` +
  `transforms.conf`) for classic pre-index filtering/masking outside the Ingest
  Actions UI, clearly labeled as the manual path.

## Agent Behavior

Never ask for S3 access keys in chat. Prefer IAM roles or existing credential
files. If static S3 keys are unavoidable, use local-only files:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/ingest_actions_s3_access_key
bash skills/shared/scripts/write_secret_file.sh /tmp/ingest_actions_s3_secret_key
```

Use `template.example` for non-secret values: destination type and path,
partitioning, format, source type, and rule definitions.

## Quick Start

Render an S3 RFS destination plus a filter+mask ruleset spec:

```bash
bash skills/splunk-ingest-actions/scripts/setup.sh \
  --destination-type s3 \
  --destination-name archive_s3 \
  --s3-path s3://splunk-ingest-archive/prod \
  --s3-auth-region us-east-1 \
  --sourcetype cisco:asa \
  --rules filter,mask \
  --filter-regex 'DEBUG' \
  --mask-regex '\d{16}' --mask-replacement 'XXXXXXXXXXXXXXXX'
```

Audit existing rulesets and destinations (read-only):

```bash
bash skills/splunk-ingest-actions/scripts/validate.sh --live
```

## What It Renders

- `outputs.conf` — `[rfs:<name>]` S3 or filesystem destination with partitioning,
  format, compression, and upload-error handling
- `ruleset.json` — structured ruleset spec for the Ingest Actions UI / REST
- `props_transforms_preview.conf` — manual heavy-forwarder preview (filter to
  nullQueue, mask via INGEST_EVAL/SEDCMD)
- `apply.sh` — stage the RFS destination into `splunk_ingest_actions/local`,
  print the ruleset UI/REST handoff, and exit nonzero until that ruleset is
  authored and verified
- `status.sh` — list rulesets and surface RFS upload errors from `_internal`
- `README.md` / `metadata.json` — review context

## Operating Notes

- A source type can have only one ruleset; rules run in order.
- If a ruleset routes to a destination that does not exist or is invalid, Splunk
  blocks queues and pipelines rather than dropping data. Create destinations
  first.
- On Splunk Cloud (Victoria), rulesets deploy automatically; on Classic and on
  indexer clusters you must deploy explicitly.
- On heavy forwarders managed by a deployment server, configure S3 destinations
  on each forwarder individually.

Read `reference.md` before deploying filter rules (data loss) or routing to S3.

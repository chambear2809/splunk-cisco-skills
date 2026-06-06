---
name: splunk-ingest-actions-setup
description: >-
  Render, validate, and apply Splunk Ingest Actions rulesets that filter, mask,
  evaluate, drop, or route data before indexing, plus Remote File System (RFS)
  S3 destinations for routing to object storage. Renders the equivalent
  props.conf RULESET, transforms.conf INGEST_EVAL, and outputs.conf [rfs:]
  representation and applies them via REST. Use when the user asks to set up
  Ingest Actions, filter or mask data at ingest, drop noisy events before
  indexing, route data to S3 with RFS, or manage ingest-time rulesets. Not for
  Ingest Processor or Edge Processor pipelines, which are separate skills.
---

# Splunk Ingest Actions Setup

This skill renders and applies Splunk Ingest Actions rulesets and RFS S3
destinations. It is render-first because Ingest Actions transform data before
indexing and cannot be reverted for already-indexed events.

## Agent Behavior

Never ask for S3 keys in chat; pass them as files
(`--s3-access-key-file` / `--s3-secret-key-file`) and they are read at apply
time, never placed on argv. Apply refuses to run without
`--accept-irreversible-ingest`.

Ingest Actions rulesets are normally authored in Splunk Web (Settings > Data >
Ingest Actions) or through the `/services/data/ingest/rulesets` REST endpoint.
This skill renders the equivalent props/transforms for review and
config-management distribution and can write them via REST.

## Quick Start

Render a drop rule for a noisy source type:

```bash
bash skills/splunk-ingest-actions-setup/scripts/setup.sh \
  --ruleset-sourcetype cisco:asa --ruleset-name drop_debug --rule-type drop --drop-regex 'level=DEBUG'
```

Apply it live (gated):

```bash
bash skills/splunk-ingest-actions-setup/scripts/setup.sh --phase apply \
  --ruleset-sourcetype cisco:asa --ruleset-name drop_debug \
  --rule-type drop --drop-regex 'level=DEBUG' --accept-irreversible-ingest
```

Route a source type to an S3 destination:

```bash
bash skills/splunk-ingest-actions-setup/scripts/setup.sh --phase apply \
  --ruleset-sourcetype cisco:asa --ruleset-name archive_asa --rule-type route-s3 \
  --s3-destination-name asa_archive --s3-path s3://my-bucket/asa --s3-auth-region us-east-1 \
  --s3-access-key-file /tmp/s3_access --s3-secret-key-file /tmp/s3_secret \
  --accept-irreversible-ingest
```

## What It Renders

- `props.conf` - `RULESET-<name>` binding on the source type (eval/mask/drop)
- `transforms.conf` - INGEST_EVAL rule (eval/mask/drop)
- `outputs.conf` - `[rfs:<name>]` S3 destination (max 8 per deployment)
- `status-rulesets.sh` - lists rulesets via `/services/data/ingest/rulesets`

For `route-s3`, the skill applies only the `[rfs:]` destination; author the
"Route to Destination" rule in the Ingest Actions UI / rulesets endpoint
(the internal RFS routing transform is not hand-authored). Only one ruleset is
supported per source type. Hand ingest-time routing on
Splunk Cloud control planes to `splunk-ingest-processor-setup` and edge
transformation to `splunk-edge-processor-setup`.

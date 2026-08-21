---
name: splunk-ingest-actions-setup
description: "Use when the user asks to set up Ingest Actions, evaluate or mask data at ingest, drop noisy events
  before indexing, or stage an RFS S3 destination for a route handoff. Not for Ingest Processor or Edge
  Processor pipelines. Render, validate, and apply eval, mask, and drop rules as props.conf RULESET and
  transforms.conf INGEST_EVAL through target-app REST endpoints on Splunk Enterprise or a customer-managed
  heavy forwarder. For route-s3, apply stages only outputs.conf [rfs:] and exits 2 with an explicit Splunk
  Web or supported rulesets-API handoff for the route rule. Splunk Cloud is render/handoff-only."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Splunk Ingest Actions Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Set up Ingest Actions, filter or mask data at ingest, drop noisy events before indexing, route data to S3 with
  RFS, or manage ingest-time rulesets. Not for Ingest Processor or Edge Processor pipelines, which are separate
  skills.
- Preview and review the splunk ingest actions setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-ingest-actions-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-ingest-actions-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

This skill renders and applies eval, mask, and drop Ingest Actions rules plus
RFS S3 destination staging. It is render-first because ingest transforms cannot
be reverted for already-indexed events. It does not claim to apply a route-s3
rule through an unverified transport.

## Agent Behavior

Never ask for S3 keys in chat; pass them as files
(`--s3-access-key-file` / `--s3-secret-key-file`) and they are read at apply
time, never placed on argv. Apply refuses to run without
`--accept-irreversible-ingest`.

Ingest Actions rulesets are normally authored in Splunk Web (Settings > Data >
Ingest Actions) or through the `/services/data/ingest/rulesets` REST endpoint.
This skill renders the equivalent props/transforms for review and
config-management distribution. Direct conf-file REST apply is limited to an
explicit Splunk Enterprise/customer-managed target. Before apply, `--platform
auto` resolves the configured target; a managed Splunk Cloud target exits `2`
without writing `props.conf`, `transforms.conf`, or `outputs.conf`.

For Splunk Cloud Platform 10.5.2605, render the supported ruleset handoff with
`splunk-ingest-actions-setup --platform cloud --phase render`. Use
`splunk-ingest-processor-setup` when the request is for a Cloud control-plane
pipeline rather than an Ingest Actions ruleset.

## Quick Start

Render a drop rule for a noisy source type:

```bash
bash skills/splunk-ingest-actions-setup/scripts/setup.sh \
  --ruleset-sourcetype cisco:asa --ruleset-name drop_debug --rule-type drop --drop-regex 'level=DEBUG'
```

Apply it live (gated):

```bash
bash skills/splunk-ingest-actions-setup/scripts/setup.sh --phase apply \
  --platform enterprise \
  --ruleset-sourcetype cisco:asa --ruleset-name drop_debug \
  --rule-type drop --drop-regex 'level=DEBUG' --accept-irreversible-ingest
```

Stage an S3 destination and emit the supported ruleset handoff:

```bash
bash skills/splunk-ingest-actions-setup/scripts/setup.sh --phase apply \
  --platform enterprise \
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

For `route-s3`, the skill applies only the `[rfs:]` destination, emits the
"Route to Destination" handoff, and exits nonzero so that destination staging
cannot be mistaken for completed routing. Author and verify the rule in the
Ingest Actions UI / rulesets endpoint (the internal RFS routing transform is
not hand-authored). Only one ruleset is supported per source type.

For managed Splunk Cloud targets, use `splunk-ingest-actions-setup` for the
rendered UI/rulesets-API handoff, `splunk-ingest-processor-setup` for Cloud control-plane
pipelines, and `splunk-edge-processor-setup` for edge transformation.

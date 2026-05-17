---
name: splunk-ingest-processor-setup
description: >-
  Render, doctor, status-check, and validate Splunk Cloud Platform Ingest
  Processor setup plans with SPL2 pipelines, source types, destinations,
  lifecycle handoffs, queue and monitoring searches, metrics, OCSF, decrypt,
  S3 archive, custom pipeline templates, and downstream readiness checks. Use
  when the user asks to configure Ingest Processor, author Ingest Processor
  pipelines, route or transform data at ingest time, validate Ingest Processor
  readiness, or compare Ingest Processor with Edge Processor and Data Manager.
---

# Splunk Ingest Processor Setup

This skill is a render-first workflow for Splunk Cloud Platform Ingest
Processor. It prepares the complete operator packet for IP readiness,
source-type and destination setup, SPL2 pipeline authoring, monitoring, and
post-ingest data usability.

## Agent Behavior

- Do not claim private or undocumented Ingest Processor CRUD APIs. The apply
  path is a UI/support handoff unless Splunk publishes a stable public API.
- Keep credentials out of chat and rendered files. Use local chmod 600 files
  for HEC tokens, Observability access tokens, cloud keys, and private keys.
- Use `splunk-spl2-pipeline-kit` for SPL2 templates and compatibility linting.
- Hand off Splunk Enterprise destinations to `splunk-edge-processor-setup`;
  Ingest Processor destinations are Splunk Cloud, Observability Cloud, metrics
  indexes, and Amazon S3.
- Hand off post-ingest ES/ITSI/ARI/CIM/OCSF/dashboard validation to
  `splunk-data-source-readiness-doctor` when that skill is present.
- Read `reference.md` before changing coverage, limits, or lifecycle behavior.

## Quick Start

Render a complete offline packet:

```bash
bash skills/splunk-ingest-processor-setup/scripts/setup.sh \
  --phase all \
  --tenant-name acme-prod \
  --stack-url https://acme-prod.scs.splunk.com \
  --source-types "aws:cloudtrail,crowdstrike:fdr,json_app" \
  --destinations "splunk_indexer=type=splunk_cloud;default=true,metrics=type=metrics_index;index=metrics,s3_archive=type=s3;format=parquet;bucket=example-bucket" \
  --pipelines "redact_auth=template=redact;sourcetype=json_app;destination=splunk_indexer,http_metrics=template=metrics;destination=metrics"
```

Validate the skill offline:

```bash
bash skills/splunk-ingest-processor-setup/scripts/validate.sh
```

## Outputs

The default output directory is `splunk-ingest-processor-rendered/`:

- `readiness-report.md` and `coverage-report.json`.
- `apply-plan.json` with `ui_handoff` actions only.
- `source-types/*.json`, `destinations/*.json`, and `pipelines/*.spl2`.
- `spl2-pipeline-kit/` rendered by `splunk-spl2-pipeline-kit`.
- `monitoring/searches.spl` and `monitoring/usage-summary-handoff.md`.
- `lifecycle/*.md` for apply, edit, remove, refresh, delete, and rollback
  review.
- `handoffs/*.md` for HEC, Edge Processor, S3 Federated Search, and data-source
  readiness workflows.

## Coverage Rules

- Ingest Processor is Splunk Cloud Platform Victoria Experience only.
- Verify provisioning, subscription/tier, roles, service account access,
  indexes, lookups, and connection refresh before authoring pipelines.
- Confirm default destination behavior in the UI before applying a pipeline.
- Validate source-type event breaking, sample data, and preview results before
  apply.
- Treat Automated Field Extraction as region-gated UI assistance, not an API
  automation path.
- Treat decrypt as a private-key lookup workflow and warn about throughput.
- Treat S3 Object Lock as unsupported for rendered IP destination plans.
- Render and review known issue guardrails: tenant-admin-only editing, no data
  delivery guarantees under high back pressure or destination outages,
  single-browser-session editing, forwarder `useACK=false`, HEC indexer
  acknowledgement off, and CIDR lookup matching unsupported.

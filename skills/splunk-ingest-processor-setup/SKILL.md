---
name: splunk-ingest-processor-setup
description: "Use when the user asks to configure Ingest Processor, author Ingest Processor pipelines, route or
  transform data at ingest time, validate Ingest Processor readiness, or compare Ingest Processor with
  Edge Processor and Data Manager, including Cisco Data Fabric or telemetry pipeline management requests
  that involve Splunk Cloud ingest-time routing and transformation. Render Cisco Data Fabric ingest-time
  routing workflows and Splunk Cloud Platform Ingest Processor setup plans with SPL2 pipelines, source
  types, destinations, lifecycle handoffs, queue and monitoring searches, metrics, OCSF, decrypt, S3
  archive, custom pipeline templates, AI-powered data management readiness, Automated Field Extraction,
  Guided Onboarding with Auto-Schematization, and downstream readiness checks."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Ingest Processor Setup

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

- Configure Ingest Processor, author Ingest Processor pipelines, route or transform data at ingest time, validate
  Ingest Processor readiness, or compare Ingest Processor with Edge Processor and Data Manager, including Cisco Data
  Fabric or.
- Preview and review the splunk ingest processor setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-ingest-processor-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-ingest-processor-setup/scripts/validate.sh --help
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

This skill is a render-first workflow for Splunk Cloud Platform Ingest
Processor. It prepares the complete operator packet for IP readiness,
source-type and destination setup, SPL2 pipeline authoring, monitoring, and
post-ingest data usability.

For newer Cisco Data Fabric wording, this is the Splunk Cloud ingest-time
pipeline route. Keep native Observability Metrics Pipeline Management requests
in `splunk-observability-deep-native-workflows` unless the user needs
source-type, destination, or SPL2 pipeline assets.

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
- Treat AI-powered Data Management release stages as capability-specific:
  Automated Field Extraction was announced in Controlled Availability, while
  Guided Onboarding with Auto-Schematization was announced in Alpha. Verify
  current tenant access before presenting either workflow. The announcement
  says three capabilities but publicly names only these two; do not infer a
  third capability.

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

`--phase` accepts `render`, `doctor`, `status`, `validate`, and `all`. Because
Ingest Processor exposes no public REST API for live status, `doctor` and
`status` are offline aliases of `validate` (render plus structural validation);
they do not query a live tenant.

`--dry-run` parses and reports the complete plan without creating, deleting, or
rewriting the output directory. Refused destinations (including Splunk
Enterprise/HEC targets and S3 Object Lock) emit their concrete handoff and
return nonzero in every phase; a rendered handoff is not a successful setup.
Normal rendering replaces only an empty directory or one carrying this skill's
ownership marker/legacy README; it refuses to recursively delete an unrelated
nonempty path.

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
- `control-plane-handoffs/ai-powered-data-management.md` with current
  availability, access, review, and no-automation guardrails.
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
- Treat Automated Field Extraction as a Controlled Availability,
  region-gated UI suggestion workflow, not an API automation path. Verify
  tenant entitlement and current feature visibility before use.
- Treat Guided Onboarding with Auto-Schematization as an Alpha, enrollment-
  gated UI workflow. It can recommend CIM mappings and candidate TA or SPL2
  outputs, but this skill does not invoke the service, enroll a tenant,
  generate a TA, install a TA, or apply a generated pipeline.
- Require human review, SPL2 lint/preview, representative sample validation,
  CIM validation, and an explicit apply decision for every AI-generated
  recommendation or artifact.
- Treat decrypt as a private-key lookup workflow and warn about throughput.
- Treat S3 Object Lock as unsupported for rendered IP destination plans.
- Render and review known issue guardrails: tenant-admin-only editing, no data
  delivery guarantees under high back pressure or destination outages,
  single-browser-session editing, forwarder `useACK=false`, HEC indexer
  acknowledgement off, and CIDR lookup matching unsupported.

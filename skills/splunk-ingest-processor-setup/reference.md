# Splunk Ingest Processor Setup Reference

## Product Surface

This skill covers the Splunk Cloud Platform Ingest Processor solution:

- provisioning and first-time readiness
- user, role, service account, index, lookup, and connection refresh readiness
- source types, event breaking/merging, sample data, and preview workflow
- partitions by host, source, sourcetype, and index where supported
- destination setup for paired Splunk Cloud indexes, Observability Cloud,
  metrics indexes, and Amazon S3
- SPL2 pipelines with route, branch, thru, redact, hash, sample, lookup,
  extract, timestamp, JSON/XML, metrics, OCSF, decrypt, stats, and S3 patterns
- custom pipeline templates under `default/data/spl2`
- Automated Field Extraction Controlled Availability UI handoff
- Guided Onboarding with Auto-Schematization Alpha access and review handoff
- AI-powered data management readiness for onboarding, schema, CIM mapping,
  candidate TA packages, and candidate SPL2 pipelines as UI handoffs
- Automated Field Extraction exact region allowlist: `us-east-1`,
  `eu-west-1`, `eu-west-2`, `ap-southeast-1`, `ap-southeast-2`,
  `eu-central-1`, `us-west-2`, and `eu-west-3`
- SPL-to-SPL2 conversion review
- apply, edit, remove, refresh, delete, rollback, and support handoffs
- queue, DLQ, Usage Summary, `_internal`, `_audit`, `_metrics`, and destination
  index validation

## Non-Goals

- No private Data Management or Ingest Processor API CRUD is claimed.
- No AI-powered data management API CRUD is claimed.
- No Alpha or Controlled Availability enrollment is claimed or automated.
- No local TA package or SPL2 pipeline is represented as an output from Guided
  Onboarding. Any candidate generated in the Splunk experience must be
  exported, reviewed, linted, previewed, and explicitly applied by an operator.
- No raw secret values are rendered.
- No Splunk Enterprise destination is rendered for IP. Use Edge Processor for
  Splunk Enterprise destinations.
- No real private keys are generated or stored.
- No known issue is hidden: no delivery guarantee, tenant-admin-only pipeline
  access, single-browser-session editing, forwarder `useACK=false`, HEC
  acknowledgement off, and CIDR lookup unsupported are rendered explicitly.

## AI-Powered Data Management Lifecycle

The release stages below are source snapshots, not permanent entitlement
promises. Re-check current Splunk documentation, tenant region, enrollment,
and feature visibility before use.

- **Automated Field Extraction (AFE): Controlled Availability.** Splunk's
  March 11, 2026 announcement labels AFE Controlled Availability. Current
  Ingest Processor release notes document AFE as a Data Management UI feature
  that suggests ingest-time extraction regexes and limit it to `us-east-1`,
  `eu-west-1`, `eu-west-2`, `ap-southeast-1`, `ap-southeast-2`,
  `eu-central-1`, `us-west-2`, and `eu-west-3`. The skill can render the review
  checklist; it cannot invoke AFE or accept a suggestion. The release-note
  entry does not explicitly promote AFE to General Availability, so its
  presence there is not used to override the later Controlled Availability
  label without a current lifecycle statement from Splunk.
- **Guided Onboarding with Auto-Schematization: Alpha.** The same March 11,
  2026 announcement labels this workflow Alpha and directs interested users
  to Splunk experts. It analyzes sample data, clusters similar events, and can
  recommend CIM mappings plus candidate search-time TA packages or ingest-time
  SPL2 pipelines. No stable public API or Ingest Processor release-note entry
  was found, so this skill provides only an access and review handoff.
- **Lifecycle gate for both capabilities:** verify access, keep representative
  sample data non-sensitive, review proposed fields and CIM mappings, lint and
  preview candidate SPL2, validate destination and event counts, and require
  an explicit human apply decision. A recommendation is never evidence that a
  tenant configuration changed.
- The source introduction says three capabilities but publicly names and
  describes only AFE and Guided Onboarding with Auto-Schematization. This skill
  tracks those two and does not infer an undocumented third capability.

## Destination Policy

Supported Ingest Processor destination families in this skill:

- `splunk_cloud` - paired Splunk Cloud index destinations.
- `observability` - Splunk Observability Cloud deployment destination.
- `metrics_index` - Splunk platform metrics index destination.
- `s3` - Amazon S3 JSON or Parquet archive destination.

Unsupported destination families render a finding and a handoff. The most
important unsupported family is `splunk_enterprise`, which belongs to
`splunk-edge-processor-setup`. Error-severity destination findings return
nonzero even when the handoff packet was rendered. `--dry-run` performs the
same parsing/finding classification but writes no files.

## Limits And Risk Notes

- Pipeline count, lookup size, persistent queue retention, and ingest volume
  limits vary by Splunk Cloud entitlement and service details.
- Branch and route patterns can duplicate data and fill persistent queues when
  one destination is blocked.
- Hashing is not complete anonymization.
- Decrypt is resource-intensive and requires RSA/PKCS#1 v1.5 private-key
  lookup handling.
- `stats` aggregations are batch scoped. Use `sum()/count()` rather than
  `avg()`.
- `logs_to_metrics` requires the documented import command and metric type
  review.
- S3 archives should include downstream Federated Search for Amazon S3 review
  where operators need search access to archived IP output.

## Source Anchors

- About Ingest Processor:
  <https://help.splunk.com/en/data-management/process-data-at-ingest-time/use-ingest-processor/introduction/about-ingest-processor>
- First-time setup:
  <https://help.splunk.com/en/data-management/process-data-at-ingest-time/use-ingest-processor/getting-started/first-time-setup-instructions-for-the-ingest-processor-solution>
- Pipeline syntax:
  <https://help.splunk.com/en/data-management/transform-and-route-data/process-data-at-ingest-time/working-with-pipelines/ingest-processor-pipeline-syntax>
- Create pipelines and use the current custom-template workflow:
  <https://help.splunk.com/en/data-management/process-data-at-ingest-time/use-ingest-processor/working-with-pipelines/create-pipelines-for-ingest-processor>
- Destinations:
  <https://help.splunk.com/en/data-management/process-data-at-ingest-time/use-ingest-processor/send-data-out-from-ingest-processor/how-the-destination-for-ingest-processor-works>
- Queueing:
  <https://help.splunk.com/en/splunk-cloud-platform/process-data-at-ingest-time/use-ingest-processors/monitor-system-health-and-activity/resiliency-and-queueing-in-ingest-processor>
- Release notes:
  <https://help.splunk.com/en/data-management/process-data-at-ingest-time/use-ingest-processor/introduction/release-notes-for-ingest-processor>
- AI-powered Data Management announcement and release-stage source:
  <https://www.splunk.com/en_us/blog/artificial-intelligence/accelerating-data-intelligence-with-ai-powered-data-management.html>

# Splunk Cloud Data Manager Setup Reference

This skill supports Splunk Cloud Platform Data Manager 1.16 onboarding across
AWS, Azure, GCP, and CrowdStrike. It is intentionally render-first. It validates
readiness and Data Manager-generated artifacts, but it does not create Data
Manager inputs through unsupported APIs.

## Core Readiness

Validate these before any provider onboarding:

- Splunk Cloud Platform supports Data Manager: Victoria experience 8.2.2104.1+
  or AWS Classic where Data Manager is available.
- Data Manager is opened on the primary search head.
- The operator has `admin`, `sc_admin`, or the documented capability set.
- Required indexes already exist and the role includes all non-internal indexes
  or the specific destination indexes.
- HEC is enabled.
- Data Manager input count remains below the documented 5000 input limit.
- Use a stable service account for Data Manager work; deleting the setup user
  can interrupt ingestion.
- Provider ingestion regions are in the Data Manager 1.16 supported-region
  lists. CrowdStrike FDR region mappings are US-1 to `us-west-1`, US-2 to
  `us-west-2`, and EU-1 to `eu-central-1`.

## HEC Rules

Do not make universal HEC ACK claims. In Data Manager 1.16, ACK is required only
for CloudTrail, GuardDuty, SecurityHub, IAM Access Analyzer, and CloudWatch
Logs. Validate token existence and enabled state, including source-specific
tokens and the documented special tokens:

- `scdm-scs-hec-token` for AWS S3, Azure Event Hub, and CrowdStrike FDR.
- `scdm-scs-promote-hec-token` for AWS S3 Promote.

## Apply Model

The skill applies only documented artifacts that the user supplies or downloads
from Data Manager:

- AWS: Data Manager-generated CloudFormation or StackSet templates.
- Azure: Data Manager-generated ARM templates, with `what-if` first.
- GCP: Data Manager-generated Terraform templates for apply or destroy.

The generated AWS wrapper can apply a single CloudFormation stack. StackSet
execution remains a rendered handoff because deployment targets, permission
mode, and organization scope require operator review.

Data Manager input creation remains `ui_handoff` unless Splunk publishes a
supported API. The Splunk Cloud Terraform provider `splunk/scp` is adjacent
only; use it for prerequisites such as supported indexes, HEC tokens, roles, or
allowlists, never Data Manager input CRUD.

Amazon Security Lake is not represented as a Data Manager input source in the
1.16 Data Manager manual. If the user needs Security Lake, hand off to the
Splunk Cloud Federated Analytics / Amazon Security Lake provider workflow.

## Guardrails

- Reject raw secret fields; accept only secret file/path references. For
  CrowdStrike FDR, both the AWS access key ID and secret access key must be
  provided by file path.
- Reject duplicate or overlapping AWS account/source, Azure Event Hub migration,
  GCP folder/project/org, and AWS CloudWatch log-group onboarding patterns.
- Warn when AWS `SplunkDMVersion` drift means Data Manager input settings and
  deployed CloudFormation/StackSet resources are mismatched.
- Warn before AWS S3 Promote jobs when Ingest Processor and ingest actions
  routing rules have not been reviewed for historical data.
- For Azure Event Hubs migration, require MSCS 5.4.0+, inactive inputs, Ready
  health, and a duplicate-migration check.

## Output Contract

Every render must emit:

- `coverage-report.json` with only allowed statuses:
  `ui_handoff`, `artifact_validate`, `artifact_apply`, `splunk_validate`,
  `cloud_validate`, `handoff`, `not_applicable`.
- `apply-plan.json` with no secrets and no unsupported Data Manager API or
  Terraform resource claims.
- Provider runbooks and scripts that use placeholders and file paths only.

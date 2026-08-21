---
name: splunk-aws-ta-setup
description: "Use when the user asks about Splunk_TA_aws, the Splunk Add-on for AWS, CloudTrail, AWS Config, or
  GuardDuty log ingestion, SQS-based S3 inputs, or a manual AWS TA configuration alternative to Data
  Manager. Install, render, configure, and validate the Splunk Add-on for AWS (Splunk_TA_aws, Splunkbase
  1876) as the manual TA path that complements splunk-cloud-data-manager-setup. Renders real inputs.conf
  stanzas for CloudTrail and GuardDuty via the SQS-based S3 input and AWS Config via the aws_config input,
  emits an IAM-role or access-key account-setup runbook, creates the aws index, maps source types to CIM,
  and validates ingestion."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Splunk Add-on for AWS Setup

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

- Splunk_TA_aws, the Splunk Add-on for AWS, CloudTrail, AWS Config, or GuardDuty log ingestion, SQS-based S3 inputs,
  or a manual AWS TA configuration alternative to Data Manager.
- Preview and review the splunk aws ta setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-aws-ta-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-aws-ta-setup/scripts/validate.sh --help
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

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first automation for the **Splunk Add-on for AWS** (`Splunk_TA_aws`,
Splunkbase `1876`). This is the **manual TA configuration path**: it renders
the real modular-input stanzas, an account-setup runbook, and the index plan,
then validates ingestion. For fully automated CloudFormation/StackSet
onboarding, use `splunk-cloud-data-manager-setup` instead.

The add-on runs on the search tier or a dedicated heavy forwarder (it needs the
full Splunk Python runtime and is not Universal-Forwarder safe).

## Feeds

| Feed | Modular input | Source type |
| --- | --- | --- |
| CloudTrail | `aws_sqs_based_s3` (decoder `CloudTrail`) | `aws:cloudtrail` |
| AWS Config | `aws_config` | `aws:config` |
| GuardDuty | `aws_sqs_based_s3` (decoder `CustomLogs`) | `aws:cloudwatch:guardduty` |

## Credentials

Never paste an AWS secret key in chat or argv. Prefer an **IAM role** on the
collector host (no stored secret). For access-key mode, write the secret to a
local file and configure the account in the add-on Configuration tab:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/aws_secret_key
```

See the rendered `account-setup.md` for both modes.

## Workflow

1. Render reviewable assets (offline):

```bash
bash skills/splunk-aws-ta-setup/scripts/setup.sh --render \
  --index aws --account-name aws_prod --sqs-region us-east-1
```

2. Install the add-on and create the index:

```bash
bash skills/splunk-aws-ta-setup/scripts/setup.sh --install --create-index --index aws
```

3. Configure the AWS account (IAM role or access key) using `account-setup.md`,
   then enable the rendered inputs in the add-on.

4. Validate:

```bash
bash skills/splunk-aws-ta-setup/scripts/validate.sh --index aws
```

5. Score post-ingest readiness:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack aws_cloudtrail
```

See `reference.md` for the full input/account model, source types, CIM
mapping, placement guardrails, and the Data Manager comparison.

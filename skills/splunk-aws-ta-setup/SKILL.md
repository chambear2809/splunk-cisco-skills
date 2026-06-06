---
name: splunk-aws-ta-setup
description: >-
  Install, render, configure, and validate the Splunk Add-on for AWS
  (Splunk_TA_aws, Splunkbase 1876) as the manual TA path that complements
  splunk-cloud-data-manager-setup. Renders real inputs.conf stanzas for
  CloudTrail and GuardDuty via the SQS-based S3 input and AWS Config via the
  aws_config input, emits an IAM-role or access-key account-setup runbook,
  creates the aws index, maps source types to CIM, and validates ingestion.
  Use when the user asks about Splunk_TA_aws, the Splunk Add-on for AWS,
  CloudTrail, AWS Config, or GuardDuty log ingestion, SQS-based S3 inputs, or a
  manual AWS TA configuration alternative to Data Manager.
---

# Splunk Add-on for AWS Setup

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

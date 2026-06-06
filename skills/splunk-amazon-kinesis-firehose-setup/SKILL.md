---
name: splunk-amazon-kinesis-firehose-setup
description: >-
  Render and validate Amazon Kinesis Firehose to Splunk HEC onboarding for
  CloudTrail, VPC Flow Logs, CloudWatch events, and raw or JSON data, including
  HEC token/index handoffs, delivery stream settings, buffering, retry, S3
  backup, IAM policy stubs, CloudWatch delivery metrics, ACK guidance, and
  strict source/sourcetype readiness evidence. Use when the user asks to send
  AWS Firehose data to Splunk.
---

# Amazon Kinesis Firehose Setup

Render-first workflow for Amazon Kinesis Firehose delivery into Splunk HEC.
The skill emits HEC handoffs, Firehose destination settings, IAM and backup
stubs, delivery metric checks, validation SPL, and readiness evidence. It does
not create HEC tokens, AWS resources, or Splunk indexes directly.

## Workflow

```bash
bash skills/splunk-amazon-kinesis-firehose-setup/scripts/setup.sh --render \
  --index aws --hec-token-name aws_firehose_hec --source-profile cloudtrail \
  --s3-backup-bucket s3://example-firehose-backup --use-ack true
```

Review rendered `firehose-destination-settings.json.template`,
`iam-policy.stub.json`, and `install-commands.sh`, then delegate HEC token work
to `splunk-hec-service-setup` and AWS resource creation to the AWS owner.

## Execute

Preview the executable Splunk-side plan:

```bash
bash skills/splunk-amazon-kinesis-firehose-setup/scripts/setup.sh --all \
  --platform enterprise --token-file /path/to/hec-token-file --dry-run --json
```

Apply the Splunk-side HEC/index setup and run local validation:

```bash
bash skills/splunk-amazon-kinesis-firehose-setup/scripts/setup.sh --all \
  --platform enterprise --token-file /path/to/hec-token-file
```

Use `--platform cloud --write-token-file /path/to/output-token-file` for the
Cloud HEC token workflow. AWS Firehose delivery-stream creation remains an AWS
owner handoff from the rendered templates.

```bash
bash skills/splunk-amazon-kinesis-firehose-setup/scripts/validate.sh \
  --rendered-dir splunk-amazon-kinesis-firehose-rendered --live
```

See `reference.md` for the strict Firehose source/sourcetype matching contract.

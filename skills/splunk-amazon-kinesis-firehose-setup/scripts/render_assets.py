#!/usr/bin/env python3
"""Render Amazon Kinesis Firehose setup assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "shared" / "lib"))

from render_first_app import main  # noqa: E402


FIREHOSE_PAIRS = [
    {"source": "aws:firehose:cloudtrail", "sourcetype": "aws:cloudtrail"},
    {"source": "aws:firehose:vpcflow", "sourcetype": "aws:cloudwatchlogs:vpcflow"},
    {"source": "aws:firehose:cloudwatch-events", "sourcetype": "aws:cloudwatch:events"},
    {"source": "aws:firehose:raw-json", "sourcetype": "_json"},
    {"source": "aws:firehose:raw", "sourcetype": "httpevent"},
]

CONFIG = {
    "skill_name": "splunk-amazon-kinesis-firehose-setup",
    "title": "Amazon Kinesis Firehose Setup",
    "description": "Render Firehose to Splunk HEC setup assets.",
    "default_output_dir": "splunk-amazon-kinesis-firehose-rendered",
    "profile_dir": "splunk-amazon-kinesis-firehose",
    "primary_app_name": "Splunk Add-on for Amazon Kinesis Firehose",
    "primary_splunkbase_id": "N/A",
    "source_types": ["aws:cloudtrail", "aws:cloudwatchlogs:vpcflow", "aws:cloudwatch:events", "_json", "httpevent"],
    "handoff_skills": ["splunk-hec-service-setup", "splunk-data-source-readiness-doctor", "splunk-aws-ta-setup"],
    "arguments": [
        {"flag": "--index", "default": "aws", "help": "Target event index."},
        {"flag": "--hec-token-name", "default": "aws_firehose_hec", "help": "HEC token name to request through the HEC skill."},
        {
            "flag": "--source-profile",
            "default": "cloudtrail",
            "choices": ["cloudtrail", "vpcflow", "cloudwatch-events", "raw-json"],
            "help": "Firehose payload/source profile.",
        },
        {"flag": "--s3-backup-bucket", "default": "s3://example-firehose-backup", "help": "S3 backup bucket URI placeholder."},
        {"flag": "--buffer-size-mb", "default": "5", "help": "Firehose buffer size in MB."},
        {"flag": "--buffer-interval-sec", "default": "60", "help": "Firehose buffer interval in seconds."},
        {"flag": "--use-ack", "default": "true", "choices": ["true", "false"], "help": "Whether HEC ACK should be enabled."},
    ],
    "choice_context": [
        {
            "field": "source_profile",
            "mapping": {
                "cloudtrail": {
                    "selected_source": "aws:firehose:cloudtrail",
                    "selected_sourcetype": "aws:cloudtrail",
                },
                "vpcflow": {
                    "selected_source": "aws:firehose:vpcflow",
                    "selected_sourcetype": "aws:cloudwatchlogs:vpcflow",
                },
                "cloudwatch-events": {
                    "selected_source": "aws:firehose:cloudwatch-events",
                    "selected_sourcetype": "aws:cloudwatch:events",
                },
                "raw-json": {
                    "selected_source": "aws:firehose:raw-json",
                    "selected_sourcetype": "_json",
                },
            },
        }
    ],
    "metadata": {
        "transport": "amazon-kinesis-firehose",
        "index": "{{index}}",
        "hec_token_name": "{{hec_token_name}}",
        "source_profile": "{{source_profile}}",
        "selected_source": "{{selected_source}}",
        "selected_sourcetype": "{{selected_sourcetype}}",
        "s3_backup_bucket": "{{s3_backup_bucket}}",
        "buffer_size_mb": "{{buffer_size_mb}}",
        "buffer_interval_sec": "{{buffer_interval_sec}}",
        "use_ack": "{{use_ack}}",
        "source_sourcetype_pairs": FIREHOSE_PAIRS,
    },
    "plan_md": """# Amazon Kinesis Firehose Setup Plan

Transport: `Amazon Kinesis Firehose`
Index: `{{index}}`
HEC token name: `{{hec_token_name}}`
Source profile: `{{source_profile}}`
Selected source: `{{selected_source}}`
Selected sourcetype: `{{selected_sourcetype}}`
S3 backup bucket: `{{s3_backup_bucket}}`
Buffering: `{{buffer_size_mb}}` MB or `{{buffer_interval_sec}}` seconds
HEC ACK: `{{use_ack}}`

## Destination Settings

- Use the Splunk HEC endpoint for the target Cloud or Enterprise HEC tier.
- Request a HEC token through `splunk-hec-service-setup` with default index
  `{{index}}` and the Firehose source/sourcetype selected for this stream.
- Keep failed delivery backup enabled to `{{s3_backup_bucket}}`; use all-events
  backup when compliance replay is required.
- Monitor Firehose delivery metrics before concluding a Splunk parsing issue.

## Source/Sourcetype Contract

Generic `_json` and `httpevent` are only valid Firehose evidence when the
source is one of the explicit Firehose sources in `readiness-evidence-template`.
""",
    "handoffs_md": """# Amazon Kinesis Firehose Handoffs

## Splunk HEC

Delegate token creation to `splunk-hec-service-setup`:

```bash
bash skills/splunk-hec-service-setup/scripts/setup.sh --phase render \
  --token-name {{hec_token_name}} --default-index {{index}} --allowed-indexes {{index}} \
  --source {{selected_source}} --sourcetype {{selected_sourcetype}} --use-ack {{use_ack}}
```

No token value is rendered. Store HEC token material only through the HEC skill's
secret-file flow or Splunk Cloud ACS.

## AWS Owner

The AWS owner applies the Firehose delivery stream, IAM role, buffering,
retry, S3 backup, and CloudWatch alarm settings from the rendered templates.
""",
    "install_commands": """#!/usr/bin/env bash
set -euo pipefail

# Review before running. This file contains no HEC token value.
bash skills/splunk-hec-service-setup/scripts/setup.sh --phase render --token-name {{hec_token_name}} --default-index {{index}} --allowed-indexes {{index}} --source {{selected_source}} --sourcetype {{selected_sourcetype}} --use-ack {{use_ack}}
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack amazon_kinesis_firehose
""",
    "validation_searches": """# Amazon Kinesis Firehose validation searches

index={{index}} (source="aws:firehose:cloudtrail" sourcetype=aws:cloudtrail OR source="aws:firehose:vpcflow" sourcetype=aws:cloudwatchlogs:vpcflow OR source="aws:firehose:cloudwatch-events" sourcetype=aws:cloudwatch:events OR source="aws:firehose:raw-json" sourcetype=_json OR source="aws:firehose:raw" sourcetype=httpevent)
| stats count min(_time) as first_seen max(_time) as last_seen dc(host) as hosts by source sourcetype
| convert ctime(first_seen) ctime(last_seen)

index=_internal source=*metrics.log* group=tcpin_connections (8088 OR httpinput)
| stats count by host sourceHost destPort

index=_internal source=*splunkd.log* (HttpInputDataHandler OR HEC OR "{{hec_token_name}}")
| stats count values(log_level) as levels by component
""",
    "readiness_evidence": {
        "name": "Amazon Kinesis Firehose",
        "source_pack_id": "amazon_kinesis_firehose",
        "product": "Amazon Kinesis Firehose",
        "expected_indexes": ["{{index}}"],
        "source_profile": "{{source_profile}}",
        "selected_source": "{{selected_source}}",
        "selected_sourcetype": "{{selected_sourcetype}}",
        "expected_sources": [
            "aws:firehose:cloudtrail",
            "aws:firehose:vpcflow",
            "aws:firehose:cloudwatch-events",
            "aws:firehose:raw-json",
            "aws:firehose:raw",
        ],
        "expected_sourcetypes": ["aws:cloudtrail", "aws:cloudwatchlogs:vpcflow", "aws:cloudwatch:events", "_json", "httpevent"],
        "source_sourcetype_pairs": FIREHOSE_PAIRS,
        "handoffs": ["splunk-amazon-kinesis-firehose-setup", "splunk-hec-service-setup"],
    },
    "additional_files": [
        {
            "path": "firehose-destination-settings.json.template",
            "content": """{
  "HECEndpoint": "https://SPLUNK_HEC_HOST:8088/services/collector",
  "HECTokenName": "{{hec_token_name}}",
  "HECAcknowledgmentTimeoutInSeconds": 180,
  "HECAcknowledgmentEnabled": {{use_ack}},
  "RetryOptions": {
    "DurationInSeconds": 300
  },
  "BufferingHints": {
    "SizeInMBs": {{buffer_size_mb}},
    "IntervalInSeconds": {{buffer_interval_sec}}
  },
  "S3BackupMode": "FailedEventsOnly",
  "S3BackupBucket": "{{s3_backup_bucket}}"
}
""",
        },
        {
            "path": "iam-policy.stub.json",
            "content": """{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:AbortMultipartUpload", "s3:GetBucketLocation", "s3:GetObject", "s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:PutObject"],
      "Resource": ["{{s3_backup_bucket}}", "{{s3_backup_bucket}}/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["logs:PutLogEvents"],
      "Resource": "*"
    }
  ]
}
""",
        },
        {
            "path": "cloudwatch-delivery-metrics.spl",
            "content": """# Review these AWS/CloudWatch metrics for the Firehose stream.
# DeliveryToSplunk.Success
# DeliveryToSplunk.DataFreshness
# DeliveryToSplunk.Records
# DeliveryToSplunk.Bytes
# DeliveryToSplunk.DeliveryRejected
# DeliveryToS3.Success
""",
        },
    ],
}


if __name__ == "__main__":
    raise SystemExit(main(CONFIG))

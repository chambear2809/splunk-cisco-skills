# Splunk Add-on for AWS Reference

Grounded in the `Splunk_TA_aws` package (Splunkbase app `1876`, verified
version `8.1.2`).

## Package Model

- App / package id: `Splunk_TA_aws`
- Splunkbase ID: `1876`
- Modular inputs (default `inputs.conf`): `aws_cloudtrail`, `aws_cloudtrail_lake`,
  `aws_cloudwatch`, `aws_cloudwatch_logs`, `aws_s3`, `aws_config`,
  `aws_config_rule`, `aws_description`, `aws_metadata`, `aws_inspector`,
  `aws_inspector_v2`, `aws_kinesis`, `aws_billing`, `aws_billing_cur`,
  `splunk_ta_aws_sqs`, `splunk_ta_aws_logs`, and `aws_sqs_based_s3`.
- Account endpoints (from `restmap.conf`): `account` (`aws_account_rh.py`,
  key-based) and `splunk_ta_aws_iam_role` (IAM role).

## Recommended Feeds

| Feed | Input | Key fields | Source type | CIM |
| --- | --- | --- | --- | --- |
| CloudTrail | `aws_sqs_based_s3` | `aws_account`, `sqs_queue_url`, `sqs_queue_region`, `s3_file_decoder = CloudTrail` | `aws:cloudtrail` | Change, Authentication |
| AWS Config | `aws_config` | `aws_account`, `aws_region`, `sqs_queue` | `aws:config` | Change |
| GuardDuty | `aws_sqs_based_s3` | `aws_account`, `sqs_queue_url`, `s3_file_decoder = CustomLogs` | `aws:cloudwatch:guardduty` | Alerts, Intrusion Detection |

`s3_file_decoder` accepts: CloudTrail, Config, S3 Access Logs, ELB Access Logs,
CloudFront Access Logs, Amazon Security Lake, Transit Gateway Flow Logs, and
CustomLogs. SQS-based S3 is the recommended scalable path: S3 delivery + SNS/SQS
notification, optionally with a Dead Letter Queue (`using_dlq = 1`).

## Account Model

- **IAM role (preferred):** run on EC2/EKS with an attached role; the account is
  marked `iam = 1` (`category`: 1 Global, 2 GovCloud, 4 China). No secret stored.
- **Access key:** key ID + secret key configured in the Configuration tab; the
  secret is stored encrypted in `storage/passwords`, never in a conf file.
- Account REST endpoint: `/servicesNS/nobody/Splunk_TA_aws/account`. IAM role
  endpoint: `/servicesNS/nobody/Splunk_TA_aws/splunk_ta_aws_iam_role`.

## Placement Guardrails

- Run on the search tier or a dedicated heavy forwarder; the add-on needs the
  full Splunk Python runtime and is not Universal-Forwarder safe.
- Prefer SQS-based S3 over legacy generic S3 polling for CloudTrail/GuardDuty.
- Create the event index before enabling inputs.
- Never store AWS secret keys in conf files or argv; use the encrypted account.

## Data Manager Comparison

| Aspect | This skill (`splunk-aws-ta-setup`) | `splunk-cloud-data-manager-setup` |
| --- | --- | --- |
| Onboarding | Manual TA inputs you control | Automated CloudFormation/StackSet |
| Where it runs | Search head / heavy forwarder | Splunk Cloud Data Manager + AWS stacks |
| Best for | Existing TA deployments, fine control | Greenfield Splunk Cloud onboarding |

Both ultimately produce `aws:cloudtrail`, `aws:config`, and GuardDuty data; pick
one onboarding path per source to avoid duplicate ingestion.

## Handoffs

- `splunk-app-install` installs the package from Splunkbase (`1876`).
- `splunk-cloud-data-manager-setup` is the automated AWS onboarding alternative.
- `splunk-hec-service-setup` prepares HEC if you front inputs with Firehose/HEC.
- `splunk-data-source-readiness-doctor` scores readiness with the
  `aws_cloudtrail` and `aws_securityhub_guardduty` source packs.
- `splunk-observability-aws-integration` covers CloudWatch **metrics** into
  Splunk Observability Cloud (a different product surface).

## Sources

- https://splunkbase.splunk.com/app/1876
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/amazon-web-services

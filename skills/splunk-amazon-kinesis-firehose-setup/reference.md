# Amazon Kinesis Firehose Reference

Amazon Kinesis Firehose can deliver CloudTrail, VPC Flow Logs, CloudWatch
events, and raw or JSON data into Splunk HEC. This skill treats Firehose as a
transport and constrains generic `_json` or `httpevent` evidence to known
Firehose sources.

## Source Profiles

| Profile | Source | Source type |
| --- | --- | --- |
| `cloudtrail` | `aws:firehose:cloudtrail` | `aws:cloudtrail` |
| `vpcflow` | `aws:firehose:vpcflow` | `aws:cloudwatchlogs:vpcflow` |
| `cloudwatch-events` | `aws:firehose:cloudwatch-events` | `aws:cloudwatch:events` |
| `raw-json` | `aws:firehose:raw-json` | `_json` |
| `raw-json` raw fallback | `aws:firehose:raw` | `httpevent` |

## Guardrails

- Create the HEC token through `splunk-hec-service-setup`; never render token
  values into Firehose assets.
- Enable indexer acknowledgment when the endpoint and throughput profile support
  it; otherwise document retry/S3 backup expectations.
- Use S3 backup for failed delivery or all events when replay/audit retention is
  required.
- Validate AWS CloudWatch Firehose delivery metrics before scoring Splunk-side
  data readiness.

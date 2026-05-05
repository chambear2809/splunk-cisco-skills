# Connection Options

The AWS integration object (`/v2/integration` with `type=AWSCloudWatch`) is
reachable through four official paths. Pick one based on your latency, cost,
and operational-control trade-offs.

## Decision matrix

| Option | What it is | Latency / cost / control | When to prefer |
|--------|------------|--------------------------|----------------|
| **Polling** (`connection.mode: polling`) | CloudWatch `ListMetrics` (~15 min for metric list) + `GetMetricData` for datapoints; configurable `pollRate` and `metadataPollRate`. | Metrics can be **delayed** vs streams; **easiest** setup; **most granular cost control** via tag filters and longer poll intervals; **short** poll intervals can **cost more** than streams for near-real-time. | **Less time-sensitive** work; you need **tag-based filtering** or fine-grained poll tuning. |
| **Splunk-managed Metric Streams** (`connection.mode: streaming_splunk_managed`) | Splunk drives CloudWatch Metric Streams to Kinesis Data Firehose (you deploy CloudFormation/Terraform in AWS). | **Faster** at scale; **often cheaper than 1-minute polling** for near-real-time; **harder cost management** -- **no tag filtering** on the stream path; **manage stream filters** in Splunk; **per-region** stack deployment. | **Near-real-time**; **many regions**; comfortable with CloudFormation/Terraform and stream filtering model. |
| **AWS-managed Metric Streams** (`connection.mode: streaming_aws_managed`) | You create / manage streams from the AWS CloudWatch console ("Quick AWS Partner setup") to Splunk as a partner destination. | Similar latency/cost to Splunk-managed streams; direct control in AWS; still no tag filtering on Metric Streams; create/configure streams per AWS region in the console. **Only one** external Metric Streams integration per AWS account (all regional streams feed it). | Teams that want AWS-console-first operations and partner-managed destination wiring. |
| **Terraform** (`connection.mode: terraform_only`) | Use `splunk-terraform/signalfx` to automate the Splunk-side integration object; still deploy AWS-side Metric Streams assets via Splunk's CloudFormation or `signalfx/aws-terraform-templates` repo for Firehose. | Same streaming characteristics as Splunk-managed streams once AWS resources exist. | Existing Terraform shops automating org standards. |

## Cross-cutting streaming constraint

CloudWatch Metric Streams can filter by **namespace and metric name**, **not**
by **resource tags**. If you need tag filtering, use the polling path.

## Sources

- [Compare connection options](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/compare-connection-options)
- [Connect via polling](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-via-polling)
- [Splunk-managed Metric Streams](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-with-splunk-managed-metrics-streams)
- [AWS-managed Metric Streams](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-with-aws-managed-metric-streams)
- [Connect to AWS with Terraform](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-to-aws-with-terraform)

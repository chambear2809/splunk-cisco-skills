# CloudFormation Templates

Splunk publishes two CloudFormation templates on the same `o11y-public` S3
bucket, sourced from the [`signalfx/aws-cloudformation-templates`](https://github.com/signalfx/aws-cloudformation-templates)
GitHub repo.

## Template inventory

| Template | URL | Use |
|----------|-----|-----|
| Regional | `https://o11y-public.s3.amazonaws.com/aws-cloudformation-templates/release/template_metric_streams_regional.yaml` | Per-region deployment in a single AWS account (default) |
| StackSets | `https://o11y-public.s3.amazonaws.com/aws-cloudformation-templates/release/template_metric_streams.yaml` | Multi-region StackSets across an AWS Organization |

Each per-region stack provisions:

- Kinesis Data Firehose delivery stream pointing at the Splunk Observability
  Cloud `ingest.<realm>.observability.splunkcloud.com/v2/datapoint/otlp`
  endpoint.
- S3 backup bucket for events Firehose fails to deliver.
- IAM role(s) for Metric Streams and Firehose.

## Regional flow (single account)

```bash
for region in us-east-1 us-east-2 us-west-2; do
  aws cloudformation create-stack \
    --stack-name SplunkObservability-MetricStreams-${region} \
    --template-url https://o11y-public.s3.amazonaws.com/aws-cloudformation-templates/release/template_metric_streams_regional.yaml \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameters ParameterKey=SplunkRealm,ParameterValue=us1 \
    --region ${region}
done
```

After CFN finishes, capture the trust-role ARN from the stack outputs and
PUT it into the Splunk Observability integration's `roleArn` field.

## StackSets flow (multi-account, AWS Organizations)

Two propagation modes:

- **Service-managed (recommended)**: AWS auto-creates
  `AWSServiceRoleForCloudFormationStackSetsOrgAdmin` (control account) and
  `AWSServiceRoleForCloudFormationStackSetsOrgMember` (member accounts).
- **Self-managed**: operator pre-creates `AWSCloudFormationStackSetAdministrationRole`
  (control account) and `AWSCloudFormationStackSetExecutionRole` (member
  accounts) per the Splunk Cloud Platform Data Manager pattern.

```bash
aws cloudformation create-stack-set \
  --stack-set-name SplunkObservability-MetricStreams \
  --template-url https://o11y-public.s3.amazonaws.com/aws-cloudformation-templates/release/template_metric_streams.yaml \
  --permission-model SERVICE_MANAGED \
  --auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters ParameterKey=SplunkRealm,ParameterValue=us1
```

## Override the template URL

If Splunk republishes templates under a different path, pass
`--cfn-template-url URL` to `setup.sh` or set
`metric_streams.cloudformation_template_url` in the spec. The renderer never
hard-codes a version-specific URL beyond the documented `release/` path.

## Sources

- [CloudFormation & Terraform templates](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/cloudformation-and-terraform-templates)
- [Connect to AWS using the Splunk API](https://docs.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-to-aws-using-the-splunk-api)
- [`signalfx/aws-cloudformation-templates`](https://github.com/signalfx/aws-cloudformation-templates)

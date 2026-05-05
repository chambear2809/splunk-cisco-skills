# IAM Permissions

The renderer emits FOUR distinct IAM policy blocks plus a combined view, and
treats the Cassandra/Keyspaces case specially (separate Resource ARN list, not
`Resource: "*"`). Source of truth: [AWS authentication, permissions and regions](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/aws-authentication-permissions-and-regions).

## A. Foundation (always required)

```json
{
  "Effect": "Allow",
  "Action": [
    "ec2:DescribeRegions",
    "iam:ListAccountAliases",
    "organizations:DescribeOrganization",
    "tag:GetResources",
    "cloudformation:ListResources",
    "cloudformation:GetResource"
  ],
  "Resource": "*"
}
```

`organizations:DescribeOrganization` is only required when AWS cost & usage
metrics are activated (`guards.enable_aws_usage: true`).

## B. CloudWatch polling

```json
{
  "Effect": "Allow",
  "Action": [
    "cloudwatch:GetMetricData",
    "cloudwatch:ListMetrics"
  ],
  "Resource": "*"
}
```

Splunk migrated away from `cloudwatch:GetMetricStatistics` server-side per
the [GetMetricStatistics deprecation notice](https://docs.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/migrate-from-the-getmetricstatistics-api).
Customer policies do not need to grant the deprecated action.

## C. Splunk-managed Metric Streams

> NOT required for AWS-managed Metric Streams.

```json
[
  {
    "Effect": "Allow",
    "Action": [
      "cloudwatch:DeleteMetricStream",
      "cloudwatch:GetMetricStream",
      "cloudwatch:ListMetricStreams",
      "cloudwatch:ListMetrics",
      "cloudwatch:PutMetricStream",
      "cloudwatch:StartMetricStreams",
      "cloudwatch:StopMetricStreams"
    ],
    "Resource": "*"
  },
  {
    "Effect": "Allow",
    "Action": ["iam:PassRole"],
    "Resource": "arn:aws:iam::*:role/splunk-metric-streams*"
  }
]
```

The `iam:PassRole` action is intentionally scoped to the
`splunk-metric-streams*` role-name pattern. Splunk's CloudFormation template
provisions the role under that prefix.

## D. Tag and properties sync (per-service)

The full per-service tag-sync action list lives in [`render_assets.py`](../scripts/render_assets.py)
under `TAG_SYNC_IAM_PERMISSIONS`. Highlights:

- **EC2**: `ec2:DescribeInstances`, `ec2:DescribeInstanceStatus`,
  `ec2:DescribeNatGateways`, `ec2:DescribeReservedInstances`,
  `ec2:DescribeReservedInstancesModifications`, `ec2:DescribeTags`,
  `ec2:DescribeVolumes`.
- **EKS**: `eks:DescribeCluster`, `eks:ListClusters`.
- **ELB family**: `elasticloadbalancing:DescribeLoadBalancerAttributes`,
  `elasticloadbalancing:DescribeLoadBalancers`,
  `elasticloadbalancing:DescribeTags`,
  `elasticloadbalancing:DescribeTargetGroups`.
- **RDS**: `rds:DescribeDBInstances`, `rds:DescribeDBClusters`,
  `rds:ListTagsForResource`.
- **S3**: `s3:GetBucketLocation`, `s3:GetBucketLogging`,
  `s3:GetBucketNotification`, `s3:GetBucketTagging`,
  `s3:ListAllMyBuckets`, `s3:ListBucket`, `s3:PutBucketNotification`.
- **Bedrock (GenAI)**: `bedrock:ListTagsForResource`,
  `bedrock:ListFoundationModels`, `bedrock:GetFoundationModel`,
  `bedrock:ListInferenceProfiles`. These four enable Splunk AI
  Infrastructure Monitoring navigators for `AWS/Bedrock`.

## E. Cassandra / Keyspaces (special case)

Cassandra requires a SECOND `Statement` with explicit Resource ARNs (cannot
share `Resource: "*"`):

```json
{
  "Effect": "Allow",
  "Action": ["cassandra:Select"],
  "Resource": [
    "arn:aws:cassandra:*:*:/keyspace/system/table/local",
    "arn:aws:cassandra:*:*:/keyspace/system/table/peers",
    "arn:aws:cassandra:*:*:/keyspace/system_schema/*",
    "arn:aws:cassandra:*:*:/keyspace/system_schema_mcs/table/tags",
    "arn:aws:cassandra:*:*:/keyspace/system_schema_mcs/table/tables",
    "arn:aws:cassandra:*:*:/keyspace/system_schema_mcs/table/columns"
  ]
}
```

The renderer always emits this block when the operator selects `AWS/Cassandra`
in `services.explicit`.

## F. Usage and reports

`enableAwsUsage: true` requires `organizations:DescribeOrganization` plus
`ec2:DescribeRegions` (already in foundation).

## SCP / permission boundary caveats

If integration validation fails with permission errors despite the policy
being correct, check:

- AWS Organizations Service Control Policies (SCPs) at the OU and account
  levels.
- IAM permission boundaries on the IAM role itself.
- Bucket / KMS resource policies for S3 / KMS-related actions.

References:
[AWS SCPs](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html),
[IAM permission boundaries](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html).

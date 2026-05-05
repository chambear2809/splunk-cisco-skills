# Terraform

The renderer emits HCL that uses the `splunk-terraform/signalfx` provider
pinned to `~> 9.0` (latest stable `9.7.2` as of April 2026; `10.0.0-beta4`
exists but we don't ship it as default).

## Provider setup

```hcl
terraform {
  required_providers {
    signalfx = {
      source  = "splunk-terraform/signalfx"
      version = "~> 9.0"
    }
  }
}

provider "signalfx" {
  api_url = "https://api.us1.observability.splunkcloud.com"
  # Set SFX_AUTH_TOKEN environment variable from a chmod-600 token file:
  #   export SFX_AUTH_TOKEN="$(cat ${SPLUNK_O11Y_TOKEN_FILE})"
}
```

The renderer never inlines the token; it always reads from
`${SPLUNK_O11Y_TOKEN_FILE}` via the env var.

## Three-resource workflow

The Splunk Observability AWS integration uses three resources together:

1. `signalfx_aws_external_integration` — creates a placeholder integration
   and returns `external_id` and `signalfx_aws_account` (the Splunk-side
   AWS account ID to put in the IAM trust policy).
2. AWS-side `aws_iam_role` — created with the `external_id` from #1 in the
   trust condition.
3. `signalfx_aws_integration` — wires the role ARN back into the Splunk
   integration and toggles `enabled`.

```hcl
resource "signalfx_aws_external_integration" "this" {
  name = "production-aws-account-1"
}

data "aws_iam_policy_document" "trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [signalfx_aws_external_integration.this.signalfx_aws_account]
    }
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [signalfx_aws_external_integration.this.external_id]
    }
  }
}

resource "aws_iam_role" "splunk_observability" {
  name               = "SplunkObservabilityRole"
  assume_role_policy = data.aws_iam_policy_document.trust.json
}

resource "aws_iam_role_policy" "splunk_observability_policy" {
  name   = "SplunkObservabilityPolicy"
  role   = aws_iam_role.splunk_observability.id
  policy = file("${path.module}/iam-combined.json")
}

resource "signalfx_aws_integration" "this" {
  enabled                           = true
  integration_id                    = signalfx_aws_external_integration.this.id
  external_id                       = signalfx_aws_external_integration.this.external_id
  role_arn                          = aws_iam_role.splunk_observability.arn
  regions                           = ["us-east-1", "us-east-2", "us-west-2"]
  poll_rate                         = 300
  inactive_metrics_poll_rate        = 1200
  import_cloud_watch                = true
  enable_aws_usage                  = false
  enable_check_large_volume         = true
  use_metric_streams_sync           = true
  metric_streams_managed_externally = false
  collect_only_recommended_stats    = true

  services = ["AWS/EC2", "AWS/RDS", "AWS/Lambda", "AWS/ApplicationELB"]

  metric_stats_to_sync {
    namespace = "AWS/Lambda"
    metric    = "Duration"
    stats     = ["mean", "upper"]
  }
}
```

## Issue #452: 1:1 mapping enforced

A single `signalfx_aws_external_integration` cannot back multiple
`signalfx_aws_integration` resources -- only one will be active despite the
provider accepting all configurations. See: https://github.com/splunk-terraform/terraform-provider-signalfx/issues/452.

The renderer enforces 1:1 in its emitted HCL. For multi-account, use
`multi_account` in the spec, which creates one `signalfx_aws_external_integration`
+ `signalfx_aws_integration` pair per member account.

## AWS-side templates: separate

For the per-region Firehose / S3 backup / IAM stacks on the AWS side, use the
[`signalfx/aws-terraform-templates`](https://github.com/signalfx/aws-terraform-templates)
repo. Splunk explicitly notes this is **Metric Streams only -- no logs path**.

## Sources

- [`splunk-terraform/signalfx` on the Terraform Registry](https://registry.terraform.io/providers/splunk-terraform/signalfx/latest)
- [Provider CHANGELOG](https://github.com/splunk-terraform/terraform-provider-signalfx/blob/main/CHANGELOG.md)
- [Connect to AWS with Terraform](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-to-aws-with-terraform)
- [Pulumi `signalfx.aws.Integration` schema](https://www.pulumi.com/registry/packages/signalfx/api-docs/aws/integration/) (canonical schema mirror)

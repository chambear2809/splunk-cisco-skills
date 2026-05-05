# Multi-Account / AWS Organizations

Splunk Observability Cloud has **NO native multi-account aggregation** for AWS
integrations -- each AWS account is one Splunk Observability `AWSCloudWatch`
integration. To monitor an entire AWS Organization, you deploy N integrations,
one per member account. The skill streamlines this with the `multi_account`
spec block.

## Spec shape

```yaml
multi_account:
  enabled: true
  control_account_id: "111111111111"      # AWS Organizations management or delegated admin
  member_accounts:
    - aws_account_id: "222222222222"
      label: prod-us
      regions: [us-east-1, us-east-2]
    - aws_account_id: "333333333333"
      label: prod-eu
      regions: [eu-west-1]
  cfn_stacksets:
    template_url: ""                      # default: template_metric_streams.yaml
    use_org_service_managed: true         # service-linked roles auto-created via AWS Organizations
    fallback_admin_role: AWSCloudFormationStackSetAdministrationRole
    fallback_execution_role: AWSCloudFormationStackSetExecutionRole
```

## What the renderer emits

When `multi_account.enabled: true`:

- `payloads/integration-create.<aws_account_id>.json` per member account.
- `aws/cloudformation-stacksets-stub.sh` instead of N regional stubs (uses
  `template_metric_streams.yaml`).
- If `use_org_service_managed: true`: documents that AWS auto-creates
  `AWSServiceRoleForCloudFormationStackSetsOrgAdmin` (control account) and
  `AWSServiceRoleForCloudFormationStackSetsOrgMember` (member accounts) --
  no manual IAM trust roles needed for StackSets propagation.
- If `use_org_service_managed: false`: `iam/stacksets-admin.json` (the
  manual `AWSCloudFormationStackSetAdministrationRole` JSON) and
  `iam/stacksets-execution.json` (the member-account execution role).

## Apply order

1. Control account: deploy StackSets infrastructure (or rely on AWS
   Organizations service-managed permissions).
2. Per-member: CFN StackSets propagates the IAM trust role + Metric Streams
   stack into each member account.
3. Per-member: `POST /v2/integration` with `type=AWSCloudWatch`, recording
   the resulting `externalId` per member.
4. Per-member: PUT the captured `roleArn` (from each member's CFN output)
   into the corresponding integration.

## Anti-patterns the renderer rejects

- A single Splunk Observability integration with a wildcard / cross-account
  IAM role (Splunk does not support this).
- The same `aws_account_id` across multiple integrations in one Splunk
  Observability org.

## Sources

- [Splunk Cloud Platform Data Manager: configure AWS for onboarding from multiple accounts](https://help.splunk.com/en/splunk-cloud-platform/ingest-data-from-cloud-services/data-manager-user-manual/1.16/amazon-web-services-data/configure-aws-for-onboarding-from-multiple-accounts)
  -- the underlying AWS CFN StackSets pattern is identical, even though that
  doc is for Splunk Cloud Platform's logs path.
- [AWS CloudFormation StackSets and AWS Organizations](https://docs.aws.amazon.com/organizations/latest/userguide/services-that-can-integrate-cloudformation.html)
- [`signalfx/aws-cloudformation-templates`](https://github.com/signalfx/aws-cloudformation-templates)

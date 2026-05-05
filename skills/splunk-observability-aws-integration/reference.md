# Splunk Observability Cloud <-> AWS Integration Reference

This is the operator reference for the
[`splunk-observability-aws-integration`](SKILL.md) skill. It documents the
canonical field set, conflict matrix, regions/realms, IAM policy blocks,
CloudFormation templates, Terraform pattern, AWS PrivateLink, multi-account
flow, drift handling, and troubleshooting catalog. The plan and corrections
that produced this skill are recorded in
`.cursor/plans/splunk_o11y_aws_integration_skill_*.plan.md`.

## Canonical field set

The skill spec is in operator-friendly seconds and snake_case. The renderer
serializes to the raw REST API payload (camelCase, milliseconds for poll
rates) when calling `https://api.<realm>.observability.splunkcloud.com/v2/integration`.

| Spec field | Canonical name | Type / range | Notes |
|------------|----------------|--------------|-------|
| `integration_name` | `name` | string | Display name |
| (constant) | `type` | string | Always `AWSCloudWatch` |
| (computed) | `enabled` | bool | Master on/off; renderer sets to `true` after the IAM trust step |
| `authentication.mode` | `authMethod` | string | `ExternalId` (commercial) or `SecurityToken` (GovCloud / China) |
| (computed from CFN) | `roleArn` | string | Required for `ExternalId`; the customer's IAM role ARN |
| (returned on create) | `externalId` | string | Server-generated; embed in IAM trust policy |
| `--aws-access-key-id-file` | `token` | SECRET (file-only) | `AWS_ACCESS_KEY_ID` value when `authMethod=SecurityToken` |
| `--aws-secret-access-key-file` | `key` | SECRET (file-only) | `AWS_SECRET_ACCESS_KEY` value when `authMethod=SecurityToken` |
| `regions` | `regions` | string[] | Cannot be empty |
| `services.explicit` | `services` | string[] | List of `AWS/*` namespaces; conflicts with `namespaceSyncRules` |
| `connection.poll_rate_seconds` | `pollRate` | int seconds (60-600); raw API ms | Default 300 s; renderer multiplies by 1000 for the JSON payload |
| `connection.metadata_poll_rate_seconds` | `metadataPollRate` | int seconds; raw API ms | Renderer multiplies by 1000 for the JSON payload |
| `connection.adaptive_polling.inactive_seconds` | `inactiveMetricsPollRate` | int seconds (60-3600), default 1200 | Adaptive polling for inactive metrics |
| (computed) | `importCloudWatch` | bool | `true` to ingest CloudWatch metrics |
| `guards.enable_aws_usage` | `enableAwsUsage` | bool | Cost+usage; requires `organizations:DescribeOrganization` |
| `guards.enable_check_large_volume` | `enableCheckLargeVolume` | bool | 100k-metric auto-disable guard |
| `sync_custom_namespaces_only` | `syncCustomNamespacesOnly` | bool | Skip built-ins when `true` |
| `guards.sync_load_balancer_target_group_tags` | `syncLoadBalancerTargetGroupTags` | bool | Adds `aws_tag_tg_*` properties for ALB target groups |
| `custom_namespaces.simple_list` | `customCloudwatchNamespaces` | string[] | Conflicts with `customNamespaceSyncRules` |
| `custom_namespaces.sync_rules` | `customNamespaceSyncRules` | array of `{namespace, filterAction, filterSource, defaultAction}` | Per-custom-namespace SignalFlow filter |
| `services.namespace_sync_rules` | `namespaceSyncRules` | array of `{namespace, filterAction, filterSource, defaultAction}` | Per-built-in-AWS-namespace SignalFlow filter; conflicts with `services` |
| `services.metric_stats_to_syncs` | `metricStatsToSyncs` | array of `{namespace, metric, stats[]}` | Per-namespace per-metric stat allow-list. With Metric Streams active, only extended (percentile) stats are honored; others ignored |
| `services.collect_only_recommended_stats` | `collectOnlyRecommendedStats` | bool | Use Splunk's published recommended stats catalog |
| `metric_streams.use_metric_streams_sync` | `useMetricStreamsSync` | bool | Boolean intent that drives Metric Streams |
| (read-back) | `metricStreamsSyncState` | enum | `ENABLED` / `CANCELLING` / `DISABLED` / `CANCELLATION_FAILED`; server-assigned. Discover/doctor reads this; renderer never writes it. |
| `metric_streams.managed_externally` | `metricStreamsManagedExternally` | bool | `true` for AWS-console-driven streams. Requires `useMetricStreamsSync: true`. |
| `metric_streams.named_token` | `namedToken` | string | Name of the org token to use for INGEST (default token if unset) |
| (rejected) | `enableLogsSync` | bool (DEPRECATED) | Renderer rejects this with a hard error and points to the `Splunk_TA_AWS` handoff |

Conflict rules the renderer enforces:

- `services.explicit` ⇄ `services.namespace_sync_rules` — mutually exclusive
- `custom_namespaces.simple_list` ⇄ `custom_namespaces.sync_rules` — mutually exclusive
- `metric_streams.managed_externally: true` requires `metric_streams.use_metric_streams_sync: true`
- `authentication.mode: security_token` requires `--aws-access-key-id-file` + `--aws-secret-access-key-file`
- `authentication.mode: external_id` requires `aws_account_id` + `iam_role_name`
- GovCloud / China regions force `authentication.mode: security_token`

## API endpoints

Base URL: `https://api.<realm>.observability.splunkcloud.com/v2/integration`
(legacy `https://api.<realm>.signalfx.com/v2/integration` continues to work
through the [domain transition](https://help.splunk.com/en/splunk-observability-cloud/reference/splunk-observability-cloud-domain-transition-guide)).

Auth header: `X-SF-Token: <admin user API access token>`.

| Operation | Method | Path | Notes |
|-----------|--------|------|-------|
| Create | POST | `/integration` | Returns `externalId` + `sfxAwsAccountArn` |
| List | GET | `/integration` | Client-side filter on `type=AWSCloudWatch` |
| Read | GET | `/integration/{id}` | Used by `--discover` |
| Update | PUT | `/integration/{id}` | Full body; renderer strips read-back fields |
| Delete | DELETE | `/integration/{id}` | Only via `--rollback` |

Read-back fields the renderer always strips before PUT: `metricStreamsSyncState`,
`largeVolume`, `created`, `lastUpdated`, `creator`, `lastUpdatedBy`,
`lastUpdatedByName`, `createdByName`, `id`.

## Five connection modes

| Mode | When to pick |
|------|--------------|
| `polling` | Less time-sensitive workloads; you want tag-based filtering or fine-grained poll tuning |
| `streaming_splunk_managed` | Near-real-time at scale; comfortable with CloudFormation/Terraform; OK without tag filtering on the stream path |
| `streaming_aws_managed` | AWS-console-first operations and partner-managed destination wiring (one external integration per AWS account) |
| `terraform_only` | Existing Terraform shops; renderer emits HCL only, never calls the REST API |

## See also

- [`references/connection-options.md`](references/connection-options.md)
- [`references/iam-permissions.md`](references/iam-permissions.md)
- [`references/regions-and-realms.md`](references/regions-and-realms.md)
- [`references/cloudformation-templates.md`](references/cloudformation-templates.md)
- [`references/terraform.md`](references/terraform.md)
- [`references/recommended-stats.yaml`](references/recommended-stats.yaml)
- [`references/namespaces-catalog.md`](references/namespaces-catalog.md)
- [`references/adaptive-polling.md`](references/adaptive-polling.md)
- [`references/metric-streams.md`](references/metric-streams.md)
- [`references/privatelink.md`](references/privatelink.md)
- [`references/multi-account.md`](references/multi-account.md)
- [`references/troubleshooting.md`](references/troubleshooting.md)
- [`references/error-catalog.md`](references/error-catalog.md)
- [`references/api-fields.md`](references/api-fields.md)
- [`references/handoffs.md`](references/handoffs.md)

## Authoritative external sources

- [Connect AWS hub](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws)
- [Connect to AWS using the Splunk API](https://docs.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-to-aws-using-the-splunk-api)
- [AWS authentication, permissions and regions](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/aws-authentication-permissions-and-regions)
- [Cloud services: AWS namespace catalog](https://help.splunk.com/en/splunk-observability-cloud/manage-data/available-data-sources/supported-integrations-in-splunk-observability-cloud/cloud-services-aws)
- [AWS recommended stats (API only)](https://docs.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/aws-recommended-stats-api-only)
- [Adaptive polling](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/adaptive-polling)
- [Splunk-managed Metric Streams](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-with-splunk-managed-metrics-streams)
- [AWS-managed Metric Streams](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-with-aws-managed-metric-streams)
- [Terraform connect path](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-to-aws-with-terraform)
- [CloudFormation & Terraform templates](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/cloudformation-and-terraform-templates)
- [PrivateLink](https://help.splunk.com/en/splunk-observability-cloud/manage-data/private-connectivity/private-connectivity-using-aws-privatelink)
- [Troubleshoot AWS integration](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/troubleshoot-your-aws-integration)
- [Manage AWS data import](https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/monitor-services-and-hosts/monitor-amazon-web-services/manage-aws-data-import)
- [Send AWS logs to Splunk Platform](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/send-aws-logs-to-splunk-platform)
- [Integrations REST + OpenAPI](https://dev.splunk.com/observability/reference/api/integrations/latest)
- [Domain transition guide](https://help.splunk.com/en/splunk-observability-cloud/reference/splunk-observability-cloud-domain-transition-guide)
- [Pulumi `signalfx.aws.Integration` schema](https://www.pulumi.com/registry/packages/signalfx/api-docs/aws/integration/)
- [Terraform `signalfx_aws_integration`](https://registry.terraform.io/providers/splunk-terraform/signalfx/latest/docs/resources/aws_integration)
- [`signalfx/aws-cloudformation-templates`](https://github.com/signalfx/aws-cloudformation-templates)
- [`signalfx/aws-terraform-templates`](https://github.com/signalfx/aws-terraform-templates)
- [Splunk Add-on for AWS (Splunkbase 1876)](https://splunkbase.splunk.com/app/1876)
- [Bedrock collect-metrics doc](https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/supported-ai-components-metrics-and-metadata/configure-your-splunk-observability-cloud-account-to-collect-aws-bedrock-metrics)
- [FedRAMP support doc](https://help.splunk.com/en/splunk-observability-cloud/fedramp-support/fedramp-support-for-splunk-observability-cloud)

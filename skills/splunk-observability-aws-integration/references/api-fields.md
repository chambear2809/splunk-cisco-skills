# API Fields

Pinned canonical field schema for the Splunk Observability Cloud
`AWSCloudWatch` integration object. The renderer's serializer enforces this
schema; if the live integration returned by `--discover` shows a field NOT in
this table, log it to `references/api-fields-observed.md` and gate use behind
`--allow-experimental-fields`.

Schema source of truth: [Pulumi `signalfx.aws.Integration`](https://www.pulumi.com/registry/packages/signalfx/api-docs/aws/integration/)
(mirrors the Splunk REST + Terraform provider).

## Top-level

| Canonical name | Type | Range / default | Notes |
|----------------|------|-----------------|-------|
| `name` | string | required | Integration display name |
| `type` | string | constant `AWSCloudWatch` | Required for create |
| `enabled` | bool | default `false` on create, `true` on PUT | Master on/off |
| `authMethod` | enum | `ExternalId` (commercial) / `SecurityToken` (GovCloud / China) | Required |
| `roleArn` | string | required for `ExternalId` | The customer's IAM role ARN |
| `externalId` | string | server-generated on create | Embed in IAM trust policy `sts:ExternalId` |
| `token` | string SECRET | required for `SecurityToken` | `AWS_ACCESS_KEY_ID` value |
| `key` | string SECRET | required for `SecurityToken` | `AWS_SECRET_ACCESS_KEY` value |
| `regions` | string[] | required, NON-EMPTY | AWS region list |
| `services` | string[] | optional; `[]` = all built-ins | `AWS/*` namespaces; conflicts with `namespaceSyncRules` |
| `pollRate` | int (ms) | 60-600 s expressed as ms; default 300_000 | Renderer multiplies seconds by 1000 |
| `metadataPollRate` | int (ms) | optional | Metadata refresh interval |
| `inactiveMetricsPollRate` | int (ms) | 60-3600 s expressed as ms; default 1_200_000 | Adaptive polling for inactive metrics |
| `importCloudWatch` | bool | default `true` | `true` to ingest CloudWatch metrics |
| `enableAwsUsage` | bool | default `false` | Cost+usage metrics; requires `organizations:DescribeOrganization` |
| `enableCheckLargeVolume` | bool | default `true` | 100k-metric auto-disable guard |
| `syncCustomNamespacesOnly` | bool | default `false` | Skip built-ins when `true` |
| `syncLoadBalancerTargetGroupTags` | bool | default `false` | Adds `aws_tag_tg_*` properties for ALB target groups |
| `customCloudwatchNamespaces` | string[] | optional | Conflicts with `customNamespaceSyncRules` |
| `customNamespaceSyncRules` | array of `{namespace, filterAction, filterSource, defaultAction}` | optional | Conflicts with `customCloudwatchNamespaces` |
| `namespaceSyncRules` | array of `{namespace, filterAction, filterSource, defaultAction}` | optional | Conflicts with `services`; SignalFlow filter |
| `metricStatsToSyncs` | array of `{namespace, metric, stats[]}` | optional | Per-namespace per-metric stat allow-list. With Metric Streams, only extended (percentile) stats are honored. |
| `collectOnlyRecommendedStats` | bool | default `false` | Use Splunk's published recommended stats catalog |
| `useMetricStreamsSync` | bool | default `false` | Boolean intent for Metric Streams |
| `metricStreamsSyncState` | enum (READ-BACK ONLY) | `ENABLED` / `CANCELLING` / `DISABLED` / `CANCELLATION_FAILED` | Server-assigned; renderer never writes |
| `metricStreamsManagedExternally` | bool | default `false` | `true` for AWS-console-driven streams; requires `useMetricStreamsSync=true` |
| `namedToken` | string | optional | INGEST org token name override (default token if unset) |
| `ignoreAllStatusMetrics` | bool | default omitted (i.e. include status checks) | Set `true` to suppress EC2 status checks |
| `enableLogsSync` | bool | DEPRECATED | Renderer rejects this field |
| `largeVolume` | bool (READ-BACK) | server-assigned | Renderer never writes |

## Read-back fields stripped from PUT body

`metricStreamsSyncState`, `largeVolume`, `created`, `lastUpdated`, `creator`,
`lastUpdatedBy`, `lastUpdatedByName`, `createdByName`, `id`.

## SyncRule sub-shape

```json
{
  "namespace": "AWS/EC2",
  "filterAction": "Include",
  "filterSource": "filter('environment', 'production')",
  "defaultAction": "Exclude"
}
```

`filterSource` uses SignalFlow filter expression syntax.

## metricStatsToSyncs sub-shape

```json
{
  "namespace": "AWS/Lambda",
  "metric": "Duration",
  "stats": ["mean", "upper"]
}
```

## Conflict matrix (renderer-enforced)

- `services` ⇄ `namespaceSyncRules`
- `customCloudwatchNamespaces` ⇄ `customNamespaceSyncRules`
- `metricStreamsManagedExternally: true` requires `useMetricStreamsSync: true`
- `authMethod: SecurityToken` requires `token` + `key` files
- `authMethod: ExternalId` requires `roleArn` + `externalId`

## Sources

- [Pulumi `signalfx.aws.Integration`](https://www.pulumi.com/registry/packages/signalfx/api-docs/aws/integration/)
- [Terraform `signalfx_aws_integration`](https://registry.terraform.io/providers/splunk-terraform/signalfx/latest/docs/resources/aws_integration)
- [Connect to AWS using the Splunk API](https://docs.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-to-aws-using-the-splunk-api)
- [Integrations REST + OpenAPI](https://dev.splunk.com/observability/reference/api/integrations/latest)

# API Fields Observed (Live)

This file records field-name spellings, defaults, and Splunk-side AWS account
IDs observed in live `GET /v2/integration?type=AWSCloudWatch` responses. The
renderer's canonical schema in [`api-fields.md`](api-fields.md) is the
write-side source of truth; this file documents read-side variations the
renderer must accept.

## Live observations (2026-04-22, realm us1)

Discovered against the operator's account that has one
`AWSCloudWatch` integration named `AWS`.

### Splunk-side AWS account ID per realm

The `sfxAwsAccountArn` field returned by `POST /v2/integration` is stable per
realm. Observed values:

| Realm | Splunk AWS account ID | sfxAwsAccountArn |
|-------|----------------------|------------------|
| `us1` | `562691491210` | `arn:aws:iam::562691491210:root` |

Encoded into the renderer's `SPLUNK_AWS_ACCOUNT_ID_PER_REALM` table. Other
realms render the placeholder `${SPLUNK_AWS_ACCOUNT_ID_FROM_POST_RESPONSE}`
until we observe their values.

### Field-name spelling variations

| Pulumi/Terraform docs | Live raw REST API | Renderer behavior |
|-----------------------|-------------------|-------------------|
| `customCloudwatchNamespaces` (lowercase w) | `customCloudWatchNamespaces` (capital W) | Write the capital-W form (live API) on POST/PUT; accept lowercase-w on read for back-compat with the IaC layer |

### Fields seen in the live response

All fields below are in the canonical write schema unless flagged otherwise:

- `authMethod`: `ExternalId`
- `collectOnlyRecommendedStats`: `false`
- `created` (read-back): unix-ms timestamp
- `createdByName` (read-back): often `null`
- `creator` (read-back): user ID
- `customCloudWatchNamespaces`: `null` when unset (CAPITAL W on the read side)
- `customNamespaceSyncRules`: `[]` when unset
- `enableAwsUsage`: `true`
- `enableCheckLargeVolume`: `true`
- `enabled`: `true`
- `externalId`: server-generated string
- `id`: server-assigned integration id
- `importCloudWatch`: `true`
- `inactiveMetricsPollRate`: milliseconds (e.g. `1200000` = 20 min)
- `largeVolume` (read-back): `false`
- `lastUpdated` (read-back): unix-ms timestamp
- `lastUpdatedBy` / `lastUpdatedByName` (read-back)
- `metricStreamsManagedExternally`: `true` (AWS-console-driven)
- `metricStreamsSyncState` (read-back): `DISABLED` / `ENABLED` / `CANCELLING` / `CANCELLATION_FAILED`
- `name`: integration name
- `namedToken`: present when set; redacted by `_apply_state.redact`
- `pollRate`: milliseconds (e.g. `300000` = 5 min)
- `regions`: AWS region list
- `roleArn`: customer IAM role ARN
- `services`: `[]` (empty = all built-in)
- `sfxAwsAccountArn`: `arn:aws:iam::<SPLUNK_AWS_ACCOUNT_ID>:root` (per-realm constant; see table above)
- `syncCustomNamespacesOnly`: `false`
- `syncLoadBalancerTargetGroupTags`: `false`
- `type`: `AWSCloudWatch`

### Fields NOT seen in the live response (omitted by the API)

- `useMetricStreamsSync`: not echoed back even though `metricStreamsManagedExternally: true` is set (write-only intent; state is reported via `metricStreamsSyncState`).
- `metricStatsToSyncs`: omitted when not configured.
- `namespaceSyncRules`: omitted when not configured.
- `metadataPollRate`: omitted when set to default.

## How this file gets updated

Run `bash setup.sh --discover --realm <realm>` to refresh. Each new realm
discovered adds an entry here; each new field name encountered triggers a
WARN and is logged here for the renderer maintainer to triage.

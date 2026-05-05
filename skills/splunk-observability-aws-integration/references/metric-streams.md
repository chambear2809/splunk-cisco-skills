# CloudWatch Metric Streams

Two flavors: Splunk-managed (recommended for most teams) and AWS-managed
(AWS-console-first operators).

## Field model

| Spec field | Canonical name | Notes |
|------------|----------------|-------|
| `metric_streams.use_metric_streams_sync` | `useMetricStreamsSync` | The boolean **intent** that drives Metric Streams |
| `metric_streams.managed_externally` | `metricStreamsManagedExternally` | `true` when AWS-console-driven |
| `metric_streams.named_token` | `namedToken` | INGEST org token name override (default token if unset) |
| (server-assigned, read-only) | `metricStreamsSyncState` | Enum: `ENABLED` / `CANCELLING` / `DISABLED` / `CANCELLATION_FAILED` |

CONSTRAINT: `metricStreamsManagedExternally: true` requires
`useMetricStreamsSync: true` per the canonical schema. The renderer enforces
this and FAILs render on violations.

## OTel payload version

AWS-managed Metric Streams support **OpenTelemetry 0.7 and 1.0 only**. JSON
and other OTel versions are rejected. The renderer defaults stream
configuration to OTel 1.0.

## State machine

The `metricStreamsSyncState` field is server-assigned and never written by the
renderer. Discover/doctor reads it.

```
       (POST/PUT useMetricStreamsSync=true)
                ┌─────────────┐
       create   │   ENABLED   │
       ─────────►             │
                └──────┬──────┘
                       │ (PUT useMetricStreamsSync=false)
                       ▼
                ┌─────────────┐
                │  CANCELLING │
                └──────┬──────┘
                       │
            success    │     failure
              ┌────────┴────────┐
              ▼                 ▼
       ┌──────────┐     ┌──────────────────────┐
       │ DISABLED │     │ CANCELLATION_FAILED  │
       └──────────┘     └──────────────────────┘
```

A `CANCELLATION_FAILED` state usually requires a fresh AWS-managed stream or
Splunk Support to reset. See:
https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/troubleshoot-splunk-managed-metric-streams

## Splunk-managed flow

1. Render with `connection.mode: streaming_splunk_managed`.
2. The renderer emits the per-region CloudFormation deploy stub
   (`aws/cloudformation-stub.sh`) and IAM Metric Streams policy block
   (`iam/iam-streams.json`).
3. Operator deploys the IAM trust role and the per-region Firehose stack
   (Splunk's `template_metric_streams_regional.yaml`).
4. `bash setup.sh --apply integration` does `POST /v2/integration` with
   `useMetricStreamsSync: true`, then PUT with the captured `roleArn`.

## AWS-managed flow

1. Render with `connection.mode: streaming_aws_managed` and
   `metric_streams.managed_externally: true`.
2. `bash setup.sh --apply integration` does `POST /v2/integration` with
   `useMetricStreamsSync: true` and `metricStreamsManagedExternally: true`.
3. Operator opens the AWS CloudWatch console -> Metrics -> Streams ->
   "Quick AWS Partner setup" -> "Splunk Observability Cloud" partner ->
   pastes the realm-specific ingest endpoint and an INGEST-scope access
   token.
4. **Hard limit**: ONE external Metric Streams integration per AWS account
   (per the AWS-managed streams doc).

## Sources

- [Splunk-managed Metric Streams](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-with-splunk-managed-metrics-streams)
- [AWS-managed Metric Streams](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-with-aws-managed-metric-streams)
- [Connect to AWS using the Splunk API](https://docs.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-to-aws-using-the-splunk-api)
- [Troubleshoot Splunk-managed Metric Streams](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/troubleshoot-splunk-managed-metric-streams)

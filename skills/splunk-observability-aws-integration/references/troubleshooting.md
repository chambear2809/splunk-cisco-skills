# Troubleshooting

The doctor catalog for this skill mirrors the documented Splunk troubleshooting
matrices. Run `bash setup.sh --doctor` to write `doctor-report.md` into the
rendered tree.

## Symptom -> fix

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `POST /v2/integration` returns HTTP 400 | IAM policy missing actions or trust policy ExternalId mismatch | Compare your trust policy ExternalId to the value returned by the create response; review IAM policy completeness against `iam/iam-combined.json` |
| `POST /v2/integration` returns HTTP 401 | Token type wrong | Use an **admin user API access token** (not an org access token); pass via `--token-file` |
| `GET /v2/integration` returns HTTP 403 | Token lacks admin scope OR realm wrong | Confirm `SPLUNK_O11Y_REALM` matches the org that owns the integration |
| Integration appears but no metrics arrive | `enabled: false` or `importCloudWatch: false` | Renderer always sends `enabled=true` after the trust step; PUT to flip if stuck |
| Status check metrics missing (e.g. `StatusCheckFailed`) | `ignoreAllStatusMetrics: true` (default in some legacy integrations) | Set `guards.ignore_all_status_metrics: false` and re-PUT |
| API Gateway charts empty | Detailed CloudWatch metrics not enabled AWS-side | In the AWS console: API Gateway -> Stages -> Logs/Tracing -> Detailed CloudWatch metrics -> ON |
| Splunk-managed Streams stuck in `CANCELLATION_FAILED` | Firehose / IAM cleanup race | Open Splunk Support; usually requires fresh CFN stack |
| AWS-managed Streams: a second integration won't create | Hard limit: ONE external Streams integration per AWS account | Reuse the existing one OR delete it first |
| Unexpected default regions | `ec2:DescribeRegions` missing | Add to IAM policy; the renderer always emits it in foundation |
| 100k metric auto-deactivate | `enableCheckLargeVolume: true` (default) tripped | Reduce regions/services scope OR set `guards.enable_check_large_volume: false` (with capacity confirmation) |
| Tag with characters Splunk strips | Splunk Observability normalizes tag chars (spaces -> `_`, `.` / `:` / `/` / `=` / `+` / `@` not supported) | Pre-normalize tags AWS-side OR rely on the `aws_tag_` prefix lookup |
| `enableLogsSync` rejected by renderer | Field is deprecated | Use the `Splunk_TA_AWS` handoff (Splunkbase 1876) for AWS log ingestion |
| `regions: []` rejected by renderer | Canonical schema rejects empty regions | Enumerate explicitly |
| GovCloud / China region with `external_id` auth | Region forces SecurityToken auth | Set `authentication.mode: security_token`; pass `--aws-access-key-id-file` + `--aws-secret-access-key-file` |
| Cassandra metrics missing | Cassandra IAM permissions block uses `Resource: "*"` instead of explicit ARN list | Renderer always emits the correct shape; copy `iam/iam-tag-sync.json` Cassandra block |
| `metricStatsToSyncs` ignored when streaming | Metric Streams API supports percentile stats only; other stats ignored when streaming | Use polling for non-percentile per-metric stat selection |
| OTel payload version error from AWS-managed stream | Splunk supports OTel 0.7 and 1.0 only | Reconfigure the AWS-managed stream to OTel 1.0 |
| FedRAMP customer cannot use AWS integration | Splunk Observability Cloud is NOT yet FedRAMP-authorized | Wait for Splunk to publish FedRAMP authorization for Observability |

## Sources

- [Troubleshoot AWS integration](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/troubleshoot-your-aws-integration)
- [Troubleshoot AWS CloudWatch polling](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/troubleshoot-aws-cloudwatch-polling)
- [Troubleshoot Splunk-managed Metric Streams](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/troubleshoot-splunk-managed-metric-streams)
- [Manage AWS data import](https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/monitor-services-and-hosts/monitor-amazon-web-services/manage-aws-data-import)

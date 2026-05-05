# Hand-offs

This skill is **standalone reusable** but has clean hand-offs to other skills
for adjacent surfaces.

## Logs (Splunk Add-on for AWS, Splunkbase 1876)

`enableLogsSync` is **deprecated** at the Splunk Observability Cloud layer.
AWS log ingestion goes through the Splunk Platform side via the Splunk Add-on
for AWS, then surfaces in Splunk Observability via Log Observer Connect.

Apply order (rendered into `09-handoff.md` when `handoffs.logs_via_splunk_ta_aws: true`):

1. Preflight: uninstall `Splunk_TA_amazon_security_lake` if present.
   `Splunk_TA_AWS` v7.0+ absorbed it; running both causes data duplication.
2. Install: `bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 1876`
   (minimum version `8.1.1`, April 2026).
3. Configure CloudTrail / VPC Flow Logs / S3 access logs in `Splunk_TA_AWS`
   (per Splunkbase docs).
4. Surface logs in Splunk Observability via Log Observer Connect:
   `bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh --apply log_observer_connect`.

Splunk Add-on for AWS compatibility floor: Splunk Enterprise / Cloud 9.3+,
including 10.x.

## Lambda APM (future companion skill `splunk-observability-aws-lambda-apm-setup`)

The Splunk OpenTelemetry Lambda layer (publisher AWS account
`254067382080`) provides automatic APM instrumentation for AWS Lambda
functions in Java, Node.js, Python, .NET. Required Lambda env vars include
`SPLUNK_REALM`, `SPLUNK_ACCESS_TOKEN`, `AWS_LAMBDA_EXEC_WRAPPER`,
`OTEL_SERVICE_NAME`. Optional Lambda Extension for Metrics:
[`signalfx/splunk-extension-wrapper`](https://github.com/signalfx/splunk-extension-wrapper).

This is OUT OF SCOPE for the AWSCloudWatch integration skill -- a separate
companion skill `splunk-observability-aws-lambda-apm-setup` will own the
Lambda APM lifecycle. Until that skill ships, see:
https://help.splunk.com/en/splunk-observability-cloud/manage-data/instrument-serverless-functions/instrument-serverless-functions/instrument-aws-lambda-functions

## AWS dashboards

[`splunk-observability-dashboard-builder`](../../splunk-observability-dashboard-builder/SKILL.md)
owns dashboard CRUD. Splunk ships pre-built AWS dashboards for every `AWS/*`
namespace in the supported integrations table; use this hand-off when you
need custom rendering on top.

## AutoDetect detectors

[`splunk-observability-native-ops`](../../splunk-observability-native-ops/SKILL.md)
owns detector CRUD. Default-enabled AutoDetect detectors for AWS include:

- AWS / RDS free disk space about to exhaust
- AWS ALB sudden change in HTTP 5xx server errors
- AWS EC2 disk utilization expected to reach the limit
- AWS Route 53 health checkers' connection time over 9 seconds
- AWS Route 53 unhealthy status of health check endpoint

Reference: [List of available AutoDetect detectors](https://help.splunk.com/en/splunk-observability-cloud/create-alerts-detectors-and-service-level-objectives/create-alerts-and-detectors/use-and-customize-autodetect-alerts-and-detectors/list-of-available-autodetect-detectors).

## OTel collector for EC2 / EKS

[`splunk-observability-otel-collector-setup`](../../splunk-observability-otel-collector-setup/SKILL.md)
owns the Splunk Distribution of OpenTelemetry Collector lifecycle. Use this
when:

- `CWAgent` host metrics are insufficient (the OTel collector ships much
  richer host telemetry through OTLP rather than CloudWatch).
- You want to run the OTel collector on EC2 instances or EKS clusters
  without paying for CloudWatch metric publishing.

## ITSI Content Pack (optional)

If the operator wants AWS data in Splunk ITSI services, hand off to
[`splunk-itsi-config`](../../splunk-itsi-config/SKILL.md).

## Splunk Observability Cloud pairing (separate concern)

The Splunk Cloud Platform <-> Splunk Observability Cloud pairing (Unified
Identity, Centralized RBAC, Discover app, Related Content, Log Observer
Connect, Splunk Infrastructure Monitoring Add-on) lives in
[`splunk-observability-cloud-integration-setup`](../../splunk-observability-cloud-integration-setup/SKILL.md).
That skill is a prerequisite ONLY when you also want to navigate from Splunk
Platform into Splunk Observability or surface AWS logs in Log Observer
Connect.

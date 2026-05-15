# Splunk Lambda APM Feature Matrix

Snapshot of documented features from:
https://help.splunk.com/en/splunk-observability-cloud/manage-data/instrument-serverless-functions/instrument-serverless-functions/instrument-aws-lambda-functions

Source repo: https://github.com/signalfx/splunk-otel-lambda (beta)
Layer ARN registry: https://github.com/signalfx/lambda-layer-versions

## Layer publisher

AWS account: `254067382080`  
Layers: `splunk-apm` (x86_64), `splunk-apm-arm` (arm64)

## Supported runtimes

| Runtime | Layer suffix |
|---------|-------------|
| Node.js 18 / 20 / 22 | x86_64 and arm64 |
| Python 3.9 / 3.10 / 3.11 / 3.12 / 3.13 | x86_64 and arm64 |
| Java 8 (al2) / 11 / 17 / 21 | x86_64 and arm64 |

**Unsupported (no published layers):** Go, Ruby, .NET, provided.al2

## Exec-wrapper paths (AWS_LAMBDA_EXEC_WRAPPER)

| Runtime | Exec wrapper | Handler type |
|---------|-------------|--------------|
| Node.js | `/opt/nodejs-otel-handler` | default |
| Python | `/opt/otel-instrument` | default |
| Java | `/opt/otel-handler` | default RequestHandler |
| Java | `/opt/otel-stream-handler` | StreamHandler |
| Java | `/opt/otel-proxy-handler` | API Gateway proxy |
| Java | `/opt/otel-sqs-handler` | SQS handler |

## Required environment variables

| Variable | Description |
|----------|-------------|
| `SPLUNK_ACCESS_TOKEN` | Splunk Observability Cloud ingest token (deliver via Secrets Manager or SSM; never inline) |
| `SPLUNK_REALM` | Observability Cloud realm (e.g. `us1`) |
| `AWS_LAMBDA_EXEC_WRAPPER` | Runtime exec wrapper path from table above |
| `OTEL_SERVICE_NAME` | Service name for APM |

## Optional environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SPLUNK_LAMBDA_LOCAL_COLLECTOR_ENABLED` | `true` | Enable Lambda Extension wrapper (local OTel collector) |
| `SPLUNK_EXTENSION_WRAPPER_ENABLED` | `true` | Enable extension-side batch export |
| `SPLUNK_METRICS_ENABLED` | `false` | Enable Lambda execution metrics via OTel |
| `OPENTELEMETRY_COLLECTOR_CONFIG_URI` | (built-in) | Custom collector config path for embedded collector |
| `OTEL_PROPAGATORS` | `tracecontext,baggage` | Propagator chain |
| `OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION` | `false` | Set `true` when X-Ray active tracing is on to avoid trace ID collision |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `https://ingest.<realm>.observability.splunkcloud.com` | OTLP endpoint (set by layer from SPLUNK_REALM when local collector enabled) |
| `OTEL_EXPORTER_OTLP_HEADERS` | (derived from SPLUNK_ACCESS_TOKEN) | `X-SF-TOKEN=<token>` (set by layer) |
| `SPLUNK_PROFILER_ENABLED` | `false` | AlwaysOn Profiling (not available for Lambda; emits a WARN if set) |

## OTLP ingest endpoint

Direct (local collector disabled):
```
https://ingest.<realm>.observability.splunkcloud.com/v2/trace/otlp
Header: X-SF-TOKEN: <access-token>
```

Default (local collector enabled): runtime SDK sends to `http://localhost:4318`; the Lambda Extension forwards OTLP to Splunk.

## Lambda span attributes

Validated present on a properly instrumented Lambda:
- `cloud.platform = aws_lambda`
- `faas.name` — function name
- `faas.version` — function version / $LATEST
- `cloud.region` — AWS region
- `cloud.account.id` — AWS account ID

## Known limitations

- **Beta status**: `signalfx/splunk-otel-lambda` is beta; gate behind `accept_beta: true`
- **No AlwaysOn Profiling**: profiling is not available for Lambda functions
- **No Go / Ruby / .NET layers**: those runtimes have no published layer from this publisher
- **GovCloud / China**: no published layers; region `us-gov-*` and `cn-*` are refused
- **X-Ray coexistence**: requires `OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION=true`
- **ADOT conflict**: the AWS Distro for OpenTelemetry (ADOT) Lambda layer conflicts; both layers cannot run simultaneously
- **Cold start overhead**: the Lambda Extension adds approximately 150-300 ms cold start latency
- **VPC functions with local collector disabled**: must have egress to `https://ingest.<realm>.observability.splunkcloud.com` via NAT Gateway or VPC endpoint
- **Timeout risk**: Lambda Extension flushes on SHUTDOWN; under very low function timeouts (< 3 s) traces may be dropped

## Vendor coexistence detection

The doctor and renderer refuse (or warn with `--allow-vendor-coexistence`) when the function config contains:
- Datadog: `DD_` env vars or `datadog` layer name
- New Relic: `NEW_RELIC_LAMBDA_HANDLER` env var or `NewRelicLambdaExtension` layer
- AppDynamics: `APPDYNAMICS_` env vars
- Dynatrace: `DT_TENANT` env var or `Dynatrace_` layer name
- ADOT: `aws-otel-*` layer name (publisher `901920570463`)

## Secret delivery

`SPLUNK_ACCESS_TOKEN` must never appear as a literal value in Lambda env config, CloudFormation, or CLI commands. Deliver via:
- AWS Secrets Manager: `{{resolve:secretsmanager:<secret-arn>:SecretString:::}}`
- AWS SSM Parameter Store SecureString: `{{resolve:ssm-secure:<parameter-name>}}`

The skill renders a one-time helper script that reads the token from `--token-file` and writes it to the chosen backend without exposing it in shell history.

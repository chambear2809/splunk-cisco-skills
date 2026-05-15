# Splunk Observability Cloud — AWS Lambda APM Reference

Operator reference for the
[`splunk-observability-aws-lambda-apm-setup`](SKILL.md) skill.

## Layer publisher and manifest

- Publisher AWS account: `254067382080`
- x86_64 layer name: `splunk-apm`
- arm64 layer name: `splunk-apm-arm`
- Layer ARN format: `arn:aws:lambda:<region>:254067382080:layer:splunk-apm[-arm]:<version>`
- Manifest source: `signalfx/lambda-layer-versions` (GitHub)
- Baked snapshot: `references/layer-versions.snapshot.json`
- Live refresh: `--refresh-layer-manifest` or `SPLUNK_LAMBDA_LAYER_MANIFEST_URL`

## Supported runtimes

| Runtime family | Versions | Exec wrapper |
|---------------|----------|-------------|
| Node.js | 18.x, 20.x, 22.x | `/opt/nodejs-otel-handler` |
| Python | 3.8 (⚠ AWS-deprecated 2024-10), 3.9, 3.10, 3.11, 3.12, 3.13 | `/opt/otel-instrument` |
| Java (default RequestHandler) | 8, 8.al2, 11, 17, 21 | `/opt/otel-handler` |
| Java (StreamRequestHandler) | 8, 8.al2, 11, 17, 21 | `/opt/otel-stream-handler` |
| Java (API Gateway proxy) | 8, 8.al2, 11, 17, 21 | `/opt/otel-proxy-handler` |
| Java (SQS trigger) | 8, 8.al2, 11, 17, 21 | `/opt/otel-sqs-handler` |

**Not supported (no published layers):** Go, Ruby (.NET, provided.al2/al2023)

## Environment variables

### Required

| Variable | Description |
|----------|-------------|
| `AWS_LAMBDA_EXEC_WRAPPER` | Runtime exec wrapper path (see table above) |
| `SPLUNK_REALM` | Splunk Observability Cloud realm (e.g. `us1`) |
| `SPLUNK_ACCESS_TOKEN` | Ingest token — delivered via `{{resolve:secretsmanager:...}}` or `{{resolve:ssm-secure:...}}` |
| `OTEL_SERVICE_NAME` | Service name for APM (default: function name) |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `SPLUNK_LAMBDA_LOCAL_COLLECTOR_ENABLED` | `true` | Enable Lambda Extension wrapper (embedded OTel collector) |
| `SPLUNK_EXTENSION_WRAPPER_ENABLED` | `true` | Enable extension-side batch export |
| `SPLUNK_METRICS_ENABLED` | `false` | Enable Lambda execution metrics |
| `OPENTELEMETRY_COLLECTOR_CONFIG_URI` | (built-in) | Custom embedded collector config |
| `OTEL_PROPAGATORS` | `tracecontext,baggage` | Propagator chain |
| `OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION` | `false` | Set `true` when X-Ray active tracing is on |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | (auto from SPLUNK_REALM) | Direct OTLP endpoint when local collector disabled |
| `SPLUNK_TRACE_RESPONSE_HEADER_ENABLED` | `true` | **Node.js only.** Adds `Server-Timing: traceparent` to API Gateway responses for RUM↔APM linking. Has no effect on Python or Java. |

## OTLP ingest endpoint

**With local collector enabled (default):**
Runtime SDK → `http://localhost:4318` → Lambda Extension → Splunk ingest

**With local collector disabled:**
```
https://ingest.<realm>.observability.splunkcloud.com/v2/trace/otlp
Header: X-SF-TOKEN: <access-token>
```

## Secret delivery

`SPLUNK_ACCESS_TOKEN` must never be a literal value. Two supported methods:

### Secrets Manager (default, `secret_backend: secretsmanager`)
```yaml
SPLUNK_ACCESS_TOKEN: "{{resolve:secretsmanager:splunk-lambda-access-token:SecretString:::}}"
```
Write once:
```bash
TOKEN_FILE=/tmp/splunk_o11y_token \
  bash splunk-observability-aws-lambda-apm-rendered/scripts/write-splunk-token.sh
```

### SSM SecureString (`secret_backend: ssm`)
```yaml
SPLUNK_ACCESS_TOKEN: "{{resolve:ssm-secure:/splunk/lambda/access-token}}"
```
Write once:
```bash
TOKEN_FILE=/tmp/splunk_o11y_token \
  bash splunk-observability-aws-lambda-apm-rendered/scripts/write-splunk-token.sh
```

## Span attributes

A correctly instrumented Lambda emits:

| Attribute | Value |
|-----------|-------|
| `cloud.platform` | `aws_lambda` |
| `faas.name` | function name |
| `faas.version` | function version or `$LATEST` |
| `cloud.region` | AWS region |
| `cloud.account.id` | AWS account ID |

## Supported regions

x86_64 layers are published in 20 regions (see `references/layer-versions.snapshot.json`).
arm64 layers are published in 10 regions. Renderer refuses arm64 in unpublished regions.

**Not supported:** `us-gov-east-1`, `us-gov-west-1`, `cn-north-1`, `cn-northwest-1`
(GovCloud / China have no published layers).

## Vendor coexistence

The skill refuses (or warns with `--allow-vendor-coexistence`) when:

| Vendor | Detection signal |
|--------|-----------------|
| Datadog | `DD_*` env vars or `datadog` in layer name |
| New Relic | `NEW_RELIC_LAMBDA_HANDLER` env var or `NewRelicLambdaExtension` layer |
| AppDynamics | `APPDYNAMICS_*` env vars |
| Dynatrace | `DT_TENANT` env var or `Dynatrace_` layer |
| ADOT | `aws-otel-*` layer or publisher `901920570463` |

## Container-image instrumentation

When `package_type: image` is set on a target, `AWS_LAMBDA_EXEC_WRAPPER` is NOT
honored (Lambda ignores it for container functions). The renderer emits a
`container-image/Dockerfile.<runtime>` snippet instead:

| Runtime | Approach |
|---------|---------|
| Python | `pip install splunk-opentelemetry[all]` + `splunk-py-trace` entrypoint |
| Node.js | `npm install @splunk/otel` + `NODE_OPTIONS=--require @splunk/otel/instrument` |
| Java | Download `splunk-otel-javaagent.jar` + `JAVA_TOOL_OPTIONS=-javaagent:/var/task/splunk-otel-javaagent.jar` |

## SAM / CDK / SAR

| Target | Output |
|--------|--------|
| SAM | `sam/template.yaml` — `AWS::Serverless::Function` with `Layers`, `Environment`, optional `SnapStart` + `ProvisionedConcurrencyConfig` |
| CDK TypeScript | `cdk/lambda-apm-stack.ts` — `lambda.LayerVersion.fromLayerVersionArn` + `addEnvironment` |
| CDK Python | `cdk/lambda_apm_stack.py` — `_lambda.LayerVersion.from_layer_version_arn` + `add_environment` |
| SAR | `sar/README.md` — advisory: Splunk does NOT publish a SAR application; use layer ARNs directly |

## Splunk Lambda Metrics Extension

Set `metrics_extension: true` in the spec to emit a second layer ARN
(`splunk-lambda-metrics` / `splunk-lambda-metrics-arm`) alongside the APM layer.
This is a separate Lambda Extension (NOT a wrapper); it subscribes to the AWS
Lambda Telemetry API and ships execution metrics to Splunk O11y.

AWS enforces a hard limit of 5 layers per function. The renderer validates the
combined layer count (APM + Metrics ≤ 5 remaining slots).

## Execution-mode guardrails

| Mode | Behavior |
|------|---------|
| `execution_modes.snapstart: true` | Java only; renderer emits `SnapStart: ApplyOn: PublishedVersions` in SAM. Warns if combined with `OTEL_JAVA_AGENT_FAST_STARTUP_ENABLED=true`. |
| `execution_modes.provisioned_concurrency: N` | Emits `ProvisionedConcurrencyConfig` in SAM (requires `AutoPublishAlias`). |
| `execution_modes.lambda_at_edge: true` | **Refused.** Lambda@Edge does not support environment variable injection or layer attachment the same way. Renderer exits with error. |

## Known limitations

| Limitation | Notes |
|-----------|-------|
| BETA status | `signalfx/splunk-otel-lambda` is beta; gate with `accept_beta: true` |
| No AlwaysOn Profiling | Not officially supported for Lambda; `SPLUNK_PROFILER_ENABLED=true` may be silently ignored |
| No Go / Ruby / .NET layers | No published layers from publisher 254067382080 |
| python3.8 deprecated | AWS EOL 2024-10; layer published but no new development; upgrade when possible |
| GovCloud / China | No published layers; renderer refuses with `not_applicable` |
| arm64 region gaps | Only 10 regions publish arm64 layers; renderer refuses unavailable regions |
| Cold start overhead | Lambda Extension adds ~150–300 ms cold start latency |
| X-Ray coexistence | Requires `OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION=true` to avoid trace ID collision |
| ADOT conflict | ADOT + Splunk layer cannot run simultaneously (both init a collector) |
| VPC egress | When local collector disabled, function needs NAT GW or VPC endpoint to reach Splunk ingest |
| Low timeout risk | Lambda Extension flushes on SHUTDOWN; timeouts < 3 s may drop final traces |
| Container-image apply | `--apply` not supported for `package_type: image`; operators build images themselves |
| SAR | Splunk does not publish a SAR application; use layer ARNs from the snapshot |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Traces not appearing in APM | `SPLUNK_ACCESS_TOKEN` resolve fails | Verify secret exists in chosen backend |
| Traces not appearing in APM | Wrong realm | Check `SPLUNK_REALM` matches your org realm |
| Cold start spike | Lambda Extension overhead | Expected; 150-300 ms; consider provisioned concurrency |
| `Task timed out` | Extension SHUTDOWN flush | Increase function timeout by at least 3 s |
| X-Ray traces + OTel traces mixed | X-Ray coexistence not set | Set `OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION=true` |
| Layer ARN not found | arm64 in unpublished region | Use x86_64 or choose a supported arm64 region |
| Layer ARN stale | Snapshot >90 days old | Run `--refresh-layer-manifest` or update snapshot |

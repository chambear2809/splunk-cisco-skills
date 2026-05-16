---
name: splunk-observability-aws-lambda-apm-setup
description: >-
  Render, validate, and optionally apply Splunk OpenTelemetry Lambda layer
  (signalfx/splunk-otel-lambda, beta, publisher 254067382080) APM
  instrumentation for AWS Lambda functions into Splunk Observability Cloud.
  Covers Node.js 18/20/22, Python 3.8(deprecated)/3.9–3.13, Java 8/8.al2/11/17/21
  on x86_64 and arm64; per-runtime AWS_LAMBDA_EXEC_WRAPPER wiring
  (/opt/nodejs-otel-handler|otel-instrument|otel-handler|otel-stream-handler|
  otel-proxy-handler|otel-sqs-handler); SPLUNK_TRACE_RESPONSE_HEADER_ENABLED
  for Node.js RUM<->APM Server-Timing traceparent linking; secret-safe
  SPLUNK_ACCESS_TOKEN delivery via AWS Secrets Manager or SSM SecureString
  ({{resolve:secretsmanager:...}}/{{resolve:ssm-secure:...}} — token never
  in files or argv); layer ARN baked snapshot with opt-in live refresh; separate
  splunk-lambda-metrics extension layer (BETA, gated behind metrics_extension:
  true) for Lambda Telemetry API metrics; container-image instrumentation path
  (package_type: image, no exec wrapper, emit per-runtime Dockerfile snippet);
  SAM template.yaml, CDK TypeScript + Python snippets, and SAR advisory note
  alongside existing Terraform + CloudFormation + AWS CLI render targets;
  execution-mode spec block per target (SnapStart Java warning, Provisioned
  Concurrency SAM/CFN emission, Lambda@Edge refusal); vendor-coexistence
  detection (Datadog/New Relic/AppDynamics/Dynatrace/ADOT); X-Ray coexistence
  flag; GovCloud/China refusal; IAM egress stub; rollback for layer, env, iam,
  and all sections; discover-functions; doctor (snapshot freshness, ADOT
  conflict, vendor conflict, VPC egress reminder); cross-skill handoffs to
  splunk-observability-aws-integration (CloudWatch metrics),
  splunk-observability-dashboard-builder (Lambda APM dashboards),
  splunk-observability-native-ops (cold-start/error/latency detectors),
  splunk-connect-for-otlp-setup (Lambda log ingestion), and
  splunk-observability-otel-collector-setup (gateway collector path).
  Use when the user asks to instrument AWS Lambda functions for APM/tracing in
  Splunk Observability Cloud, attach the Splunk OTel Lambda layer, wire
  SPLUNK_ACCESS_TOKEN safely, set up Lambda APM dashboards or detectors, or
  migrate from Datadog/New Relic/ADOT to Splunk OTel.
---

# Splunk Observability Cloud — AWS Lambda APM Setup

Render-first skill that owns the complete lifecycle of Splunk OTel Lambda
layer attachment. The workflow is render-first by default. AWS Lambda function
changes only happen when the operator explicitly runs `--apply` after reviewing
the rendered plan.

The skill is the live fulfillment of the `handoffs.lambda_apm` stub emitted by
`splunk-observability-aws-integration` (previously marked "future companion").

## Coverage Model

| Section | Coverage status |
|---------|----------------|
| Beta acknowledgement | `api_validate` |
| Target function validation | `api_validate` |
| Layer ARN resolution (snapshot) | `api_validate` |
| Exec-wrapper wiring | `api_validate` |
| Token delivery (Secrets Manager / SSM) | `handoff` |
| X-Ray coexistence flag | `api_validate` |
| IAM ingest-egress policy (local collector disabled) | `api_validate` / `not_applicable` |
| Terraform variant | `handoff` |
| CloudFormation variant | `handoff` |
| SAM template variant | `handoff` |
| CDK TypeScript + Python variant | `handoff` |
| SAR advisory | `handoff` |
| Container-image Dockerfile snippet | `handoff` (image targets only) |
| AWS CLI apply plan | `api_validate` |
| Span attribute validation | `api_validate` |
| Vendor-coexistence check | `api_validate` |
| SnapStart guidance (Java) | `api_validate` |
| Lambda@Edge | `not_applicable` (refused) |
| Provisioned Concurrency (SAM/CFN emit) | `api_validate` |
| `splunk-lambda-metrics` extension layer | `api_validate` (opt-in) |
| GovCloud / China | `not_applicable` (refused) |
| Cross-skill handoffs | `handoff` / `not_applicable` |

## Safety Rules

- Never ask for the Splunk O11y access token in conversation.
- Never pass `SPLUNK_ACCESS_TOKEN` as a literal value. Use `--token-file` for
  live API calls. For Lambda function config, the renderer emits
  `{{resolve:secretsmanager:...}}` or `{{resolve:ssm-secure:...}}` references.
- Token files must be `chmod 600`. Use `write_secret_file.sh` to create one
  without shell-history exposure.
- Reject direct-secret flags: `--token`, `--access-token`, `--api-token`,
  `--o11y-token`, `--sf-token`, `--password`.
- `signalfx/splunk-otel-lambda` is BETA. Gate all operations behind
  `accept_beta: true` in the spec or `--accept-beta` on the CLI.
- GovCloud (`us-gov-*`) and China (`cn-*`) regions have no published layers.
  The renderer fails with `not_applicable` coverage; do not fabricate ARNs.

## Five-mode UX

| Mode | Flag | Purpose |
|------|------|---------|
| render | `--render` (default) | Produces the plan tree. No AWS calls. |
| apply | `--apply [SECTIONS]` | Runs the rendered aws-cli plan. Sections: `layer,env,iam,validation`. |
| validate | `--validate [--live]` | Static + optional ingest-endpoint probe. |
| doctor | `--doctor` | Vendor conflict, ADOT, X-Ray, snapshot-freshness checks. |
| quickstart | `--quickstart` | Render + print exact `--apply` command. |

## Primary Workflow

### 1. Copy and edit the spec

```bash
cp skills/splunk-observability-aws-lambda-apm-setup/template.example my-lambda-spec.yaml
# fill in realm, targets (function names, regions, runtimes, arches)
```

### 2. Render

```bash
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh \
  --render \
  --spec my-lambda-spec.yaml \
  --realm us1
```

### 3. Review the plan

```
splunk-observability-aws-lambda-apm-rendered/
  01-overview.md               # plan summary + apply command
  02-targets.md                # per-function targets + resolved layer ARNs
  03-layers.md                 # layer attachment plan
  04-env.md                    # environment variable plan
  05-validation.md             # validation steps
  aws-cli/apply-plan.sh        # AWS CLI commands (review before running)
  terraform/main.tf            # Terraform resource snippets
  cloudformation/snippets.yaml # CloudFormation snippets
  sam/template.yaml            # AWS SAM template snippet
  cdk/lambda-apm-stack.ts      # CDK TypeScript snippet
  cdk/lambda_apm_stack.py      # CDK Python snippet
  sar/README.md                # SAR advisory (Splunk does not publish SAR)
  container-image/             # Dockerfile.<runtime> (image-package targets only)
  iam/                         # IAM policy (local collector disabled only)
  scripts/write-splunk-token.sh # one-time token write to secret backend
  scripts/handoffs.sh           # cross-skill handoff drivers
  coverage-report.json          # per-section coverage status
```

### 4. Write the access token to the secret backend (once)

```bash
# Prepare the token file (never put the value in shell history):
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_o11y_token

# Write token to Secrets Manager (or SSM if secret_backend: ssm):
TOKEN_FILE=/tmp/splunk_o11y_token \
  bash splunk-observability-aws-lambda-apm-rendered/scripts/write-splunk-token.sh

# Delete the local temp file:
rm /tmp/splunk_o11y_token
```

### 5. Apply

```bash
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh \
  --apply \
  --spec my-lambda-spec.yaml \
  --realm us1 \
  --token-file /tmp/splunk_o11y_token
```

Or apply only specific sections:

```bash
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh \
  --apply layer,env \
  --spec my-lambda-spec.yaml
```

## Quickstart (single command)

```bash
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh \
  --quickstart \
  --spec my-lambda-spec.yaml \
  --realm us1 \
  --accept-beta
```

The quickstart renders the plan and prints the exact `--apply` command to run
next. No AWS calls happen until you explicitly run `--apply`.

## GitOps mode (Terraform / CloudFormation only)

```bash
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh \
  --render \
  --gitops-mode \
  --spec my-lambda-spec.yaml
```

`--gitops-mode` suppresses the `aws-cli/` directory and produces only
`terraform/` and `cloudformation/` artifacts.

## Doctor

```bash
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh \
  --doctor \
  --target my-function \
  --realm us1
```

Doctor checks: beta status, snapshot freshness, vendor conflicts (Datadog /
New Relic / AppDynamics / Dynatrace), ADOT conflict, X-Ray coexistence flag,
and VPC egress reminder when `local_collector_enabled: false`.

## Rollback

```bash
# Detach layer only:
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh \
  --rollback layer \
  --target my-function

# Remove env vars only:
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh \
  --rollback env \
  --target my-function

# Detach IAM ingest-egress policy (only when local_collector_enabled=false):
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh \
  --rollback iam \
  --target my-function

# Full rollback (layer → env → iam in sequence):
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/setup.sh \
  --rollback all \
  --target my-function
```

Each rollback section renders idempotent AWS CLI commands for review; the skill
never mutates AWS without operator review.

## Hand-offs

- CloudWatch Lambda metrics → [`splunk-observability-aws-integration`](../splunk-observability-aws-integration/SKILL.md)
- Lambda APM dashboards → [`splunk-observability-dashboard-builder`](../splunk-observability-dashboard-builder/SKILL.md)
- Cold-start / error / latency detectors → [`splunk-observability-native-ops`](../splunk-observability-native-ops/SKILL.md)
- Lambda log ingestion → [`splunk-connect-for-otlp-setup`](../splunk-connect-for-otlp-setup/SKILL.md)
- Gateway OTel Collector path → [`splunk-observability-otel-collector-setup`](../splunk-observability-otel-collector-setup/SKILL.md) (set `handoffs.gateway_otel_collector: true` and `local_collector_enabled: false`)
- FROM `splunk-observability-aws-integration` → this skill is the fulfillment of `handoffs.lambda_apm: true`

## Out of Scope

- Lambda log ingestion (handed off to `splunk-connect-for-otlp-setup`)
- CloudWatch metrics for AWS/Lambda namespace (handed off to `splunk-observability-aws-integration`)
- AppDynamics serverless instrumentation (handled by `splunk-appdynamics-apm-setup`)
- AlwaysOn Profiling for Lambda (not officially supported in `signalfx/splunk-otel-lambda`)
- Go, Ruby, .NET Lambda runtimes (no published layers from publisher 254067382080)
- GovCloud / China regions (no published layers; renderer refuses with `not_applicable`)
- Lambda@Edge (no env-var injection support in the Lambda@Edge execution model; renderer refuses)

## Validation

```bash
bash skills/splunk-observability-aws-lambda-apm-setup/scripts/validate.sh \
  --output-dir splunk-observability-aws-lambda-apm-rendered
```

Static checks: required files, IAM JSON shape, secret-leak scan.
With `--live`: probes the Splunk ingest endpoint.

See [`references/splunk-doc-feature-matrix.md`](references/splunk-doc-feature-matrix.md) for the full feature matrix and limitations.

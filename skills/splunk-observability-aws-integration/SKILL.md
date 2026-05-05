---
name: splunk-observability-aws-integration
description: >-
  Render, preflight, apply, validate, discover, and diagnose the Splunk
  Observability Cloud `AWSCloudWatch` integration end-to-end across all four
  documented connection paths (polling, Splunk-managed Metric Streams,
  AWS-managed Metric Streams, and Terraform), including IAM trust policy and
  per-use-case CloudWatch / Metric Streams / tag-sync / Cassandra-Keyspaces
  policy emission, External-ID and SecurityToken auth flows, regional and
  StackSets CloudFormation stubs from `signalfx/aws-cloudformation-templates`,
  Splunk-side Terraform with `signalfx_aws_external_integration` +
  `signalfx_aws_integration` pinned to provider `~> 9.0`, full canonical field
  set (`pollRate` / `metadataPollRate` / `inactiveMetricsPollRate` (seconds with
  millisecond serialization) / `services` / `customCloudwatchNamespaces` /
  `customNamespaceSyncRules` / `namespaceSyncRules` / `metricStatsToSyncs` /
  `collectOnlyRecommendedStats` / `useMetricStreamsSync` /
  `metricStreamsManagedExternally` / `enableCheckLargeVolume` /
  `enableAwsUsage` / `syncCustomNamespacesOnly` /
  `syncLoadBalancerTargetGroupTags` / `ignoreAllStatusMetrics` / `namedToken`),
  conflict-matrix enforcement (`services` vs `namespaceSyncRules`,
  `customCloudwatchNamespaces` vs `customNamespaceSyncRules`,
  `metricStreamsManagedExternally` requires `useMetricStreamsSync`), adaptive
  polling tuning, AWS-recommended-stats catalog, AWS PrivateLink ingest stubs
  with the legacy `signalfx.com` domain default, multi-account / AWS
  Organizations CloudFormation StackSets emission, drift detection +
  `--quickstart-from-live` adoption, and the documented troubleshooting
  catalog. Live validation against the operator's existing integration via the
  Splunk Observability Cloud REST API at
  `https://api.<realm>.observability.splunkcloud.com/v2/integration` with
  `X-SF-Token` admin user API access tokens. Hand-offs to a future
  `splunk-observability-aws-lambda-apm-setup` skill (Lambda APM via the Splunk
  OpenTelemetry Lambda layer publisher 254067382080), to `splunk-app-install`
  for the Splunk Add-on for AWS (Splunkbase 1876, min v8.1.1; uninstall
  `Splunk_TA_amazon_security_lake` first if present) and on to
  `splunk-observability-cloud-integration-setup` for Log Observer Connect, to
  `splunk-observability-dashboard-builder` for AWS dashboards, to
  `splunk-observability-native-ops` for AutoDetect detectors, and to
  `splunk-observability-otel-collector-setup` for EC2 / EKS host telemetry.
  Use when the user asks to connect AWS to Splunk Observability Cloud, set up
  CloudWatch Metric Streams (Splunk-managed or AWS-managed), render IAM
  policies for the Splunk Observability AWS integration, configure the
  `AWSCloudWatch` integration object via REST or Terraform, enable the
  AWS-recommended-stats catalog, configure namespace sync rules with
  SignalFlow filters, monitor Amazon Bedrock metrics, set up multi-account /
  AWS Organizations integration with CloudFormation StackSets, configure AWS
  PrivateLink ingest, audit an existing AWS integration for drift, or migrate
  from CloudWatch polling to Metric Streams.
---

# Splunk Observability Cloud <-> AWS Integration

Render-first skill that owns the entire `AWSCloudWatch` integration object in
Splunk Observability Cloud. The skill is **standalone reusable** and does not
require any other Splunk Observability skill to run, but it hands off to other
skills for adjacent surfaces (logs, Lambda APM, dashboards, detectors, OTel
collectors).

The workflow is render-first by default. Live API changes only happen when the
user explicitly asks for `--apply`.

## Coverage Model

Every rendered section gets an explicit coverage status in
`coverage-report.json`:

- `api_apply` — a documented public REST API supports create / update / delete /
  validate (e.g. `POST /v2/integration`).
- `api_validate` — a documented public REST API supports read or validation only
  (e.g. preflighting `ec2:DescribeRegions` permission via the live integration's
  reported region list).
- `deeplink` — the skill renders a deterministic Splunk Observability Cloud UI
  link and validates referenced data where an API allows (e.g. the AWS
  guided-setup deeplink for AWS-managed Metric Streams).
- `handoff` — the skill renders deterministic operator steps for cross-skill
  workflows (e.g. logs path -> `splunk-app-install` for `Splunk_TA_AWS`).
- `not_applicable` — the section does not apply to the chosen target (e.g.
  Splunk-managed Metric Streams permissions when `connection.mode` is `polling`,
  or any AWS integration on `realm: us2-gcp` because that realm is GCP-hosted
  and has no AWS STS region mapping).

## Safety Rules

- Never ask for Splunk Observability tokens, AWS access keys, or AWS secret
  access keys in conversation.
- Never pass any secret on the command line or as an environment-variable
  prefix.
- Use `--token-file` for the Splunk Observability Cloud admin user API access
  token. Token files must be `chmod 600`. Override only with
  `--allow-loose-token-perms` (emits a WARN — use only for short-lived scratch
  tokens).
- For `authentication.mode: security_token` (GovCloud / China), use
  `--aws-access-key-id-file` and `--aws-secret-access-key-file`. Both files
  must be `chmod 600`.
- Reject direct secret flags: `--token`, `--access-token`, `--api-token`,
  `--o11y-token`, `--admin-token`, `--sf-token`, `--external-id`,
  `--aws-access-key-id`, `--aws-secret-access-key`, `--aws-secret-key`,
  `--password`.
- Prefer `SPLUNK_O11Y_REALM` and `SPLUNK_O11Y_TOKEN_FILE` from the repo
  `credentials` file when present; these store only realms and token-file
  paths, never token values.
- Strip every secret from `00-09-*.md`, `apply-plan.json`, `payloads/`,
  `current-state.json`, `state/apply-state.json`, and any other rendered
  artifact on disk. The Splunk Observability admin token is referenced as
  `${SPLUNK_O11Y_TOKEN_FILE}` everywhere, never inlined.
- The renderer FAILs render when the operator passes the deprecated
  `enableLogsSync` field with a clear pointer to the `Splunk_TA_AWS` handoff.
- The renderer FAILs render when `regions: []` (the canonical schema rejects an
  empty list and Splunk highly discourages it because new AWS regions
  auto-onboard and inflate cost).
- `bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_o11y_token`
  helps the user create a token file without exposing the secret in shell
  history.

## Five-mode UX

| Mode | Flag | Purpose |
|------|------|---------|
| quickstart | `--quickstart` | Single-shot: render + apply for the most common External-ID + Splunk-managed Metric Streams scenario. Always runs `--discover` first; pivots to `--quickstart-from-live` if an integration already exists. |
| render | `--render` (default) | Produces the numbered plan tree under `--output-dir`. Never touches live state. |
| discover | `--discover` | Read-only sweep that polls `GET /v2/integration?type=AWSCloudWatch`, writes `current-state.json`, and emits a `drift-report.md` against the rendered plan. |
| doctor | `--doctor` | Runs the troubleshooting catalog and emits `doctor-report.md` with prioritized fixes and the exact `setup.sh --apply` command for each fix. |
| apply | `--apply [SECTIONS]` | Applies the rendered plan; without arguments runs every section in dependency order; with `--apply integration,iam,streams` runs only the named sections. |

Plus quality-of-life flags:

- `--quickstart-from-live` — turn the live integration into a `template.observed.yaml`
  the operator can edit; never overwrites their `template.example`.
- `--explain` — print the apply plan in plain English, no API calls; for
  change-management approvals.
- `--rollback <section>` — render (do not auto-run) the reverse-engineered
  commands for steps that have a public reversible API.
- `--list-namespaces` — print the supported AWS service / namespace catalog
  (mirrors `references/namespaces-catalog.md`).
- `--list-recommended-stats` — print the per-namespace per-metric stat catalog
  used by `collect_only_recommended_stats: true`.
- `--privatelink-domain {legacy,new}` — pick `signalfx.com` (default; matches
  current Splunk-published PrivateLink doc) vs `observability.splunkcloud.com`
  PrivateLink hostnames.
- `--cfn-template-url URL` — override the default
  `https://o11y-public.s3.amazonaws.com/aws-cloudformation-templates/release/template_metric_streams_regional.yaml`
  (or the StackSets equivalent when `metric_streams.use_stack_sets: true`).
- `--accept-drift FIELD[,FIELD...]` — needed for `--apply` when discover shows
  the live integration differs from the rendered spec on a field with side
  effects (e.g. flipping `useMetricStreamsSync`).

## Primary Workflow

1. Collect non-secret values: realm, integration name, AWS account ID(s),
   IAM role name, regions, services list (or `all_built_in`), connection
   mode (polling vs Splunk-managed Metric Streams vs AWS-managed Metric
   Streams), custom namespaces, multi-account toggle.

2. Create or update a JSON / YAML spec from `template.example`.

3. Render and validate:

   ```bash
   bash skills/splunk-observability-aws-integration/scripts/setup.sh \
     --render \
     --spec skills/splunk-observability-aws-integration/template.example \
     --output-dir splunk-observability-aws-integration-rendered
   ```

4. Review `splunk-observability-aws-integration-rendered/`:
   - `README.md` — TL;DR and ordered next-step commands.
   - `architecture.mmd` — Mermaid topology of the rendered integration.
   - `00-prerequisites.md` through `09-handoff.md` — numbered per-section plans.
   - `coverage-report.json` — per-section coverage status.
   - `apply-plan.json` — apply ordering with idempotency keys (no secrets).
   - `payloads/` — per-step request bodies for REST calls and CFN parameters.
   - `aws/` — CloudFormation template stubs (regional or StackSets) and
     Terraform `.tf` files for the AWS-side resources and the Splunk-side
     integration object.
   - `iam/` — per-use-case IAM JSON (foundation, polling, streams, tag-sync,
     Cassandra-special-case, GovCloud security-token).
   - `scripts/` — per-step apply scripts and cross-skill handoff drivers.
   - `support-tickets/` — pre-filled tickets when Splunk Support is required.

5. Apply only when explicitly requested:

   ```bash
   bash skills/splunk-observability-aws-integration/scripts/setup.sh \
     --apply \
     --spec skills/splunk-observability-aws-integration/template.example \
     --realm us1 \
     --token-file /tmp/splunk_o11y_admin_token
   ```

   To run only a subset of sections:

   ```bash
   bash skills/splunk-observability-aws-integration/scripts/setup.sh \
     --apply integration,iam \
     --spec my-aws-integration.yaml
   ```

## Supported Sections

Specs use `api_version: splunk-observability-aws-integration/v1` and can
include the following top-level blocks (full reference in
[reference.md](reference.md)):

- `prerequisites` — region/realm preflight, FedRAMP/GovCloud/GCP carve-out,
  IAM permission check stubs, CFN template URL HTTP HEAD probe.
- `authentication` — `external_id` or `security_token` mode, AWS account ID,
  IAM role name, returned external ID.
- `connection` — polling vs Splunk-managed vs AWS-managed vs Terraform-only
  mode; `pollRate`, `metadataPollRate`, `inactiveMetricsPollRate`.
- `regions` — explicit AWS region list (cannot be empty).
- `services` — `all_built_in` / `explicit` / `namespace_filtered` /
  `custom_only`; `collect_only_recommended_stats`; `metric_stats_to_syncs`;
  `namespace_sync_rules` (for built-in `AWS/*` namespaces).
- `custom_namespaces` — `simple_list` (serializes to `customCloudwatchNamespaces`)
  OR `sync_rules` (serializes to `customNamespaceSyncRules`); they conflict.
  `sync_custom_namespaces_only` toggle.
- `guards` — `enable_check_large_volume`, `ignore_all_status_metrics`,
  `sync_load_balancer_target_group_tags`, `enable_aws_usage`.
- `metric_streams` — `use_metric_streams_sync`, `managed_externally`,
  `named_token`, `cloudformation`, `cloudformation_template_url`,
  `use_stack_sets`, `terraform`.
- `private_link` — `enable`, `endpoint_types`, `service_name_overrides`.
- `terraform_provider` — `source` (`splunk-terraform/signalfx`), `version`
  (`~> 9.0` default).
- `multi_account` — `enabled`, `control_account_id`, `member_accounts`,
  `cfn_stacksets`.
- `handoffs` — `lambda_apm`, `logs_via_splunk_ta_aws`, `dashboards`,
  `detectors`, `otel_collector_for_ec2_eks`.

## Hand-offs to Other Skills

- AWS log ingestion -> `bash skills/splunk-app-install/scripts/install_app.sh
  --source splunkbase --app-id 1876` (Splunk Add-on for AWS, Splunkbase 1876,
  min v8.1.1). Renderer preflights for `Splunk_TA_amazon_security_lake` and
  emits an uninstall step before the v7+ upgrade.
- Log Observer Connect to surface those logs in O11y ->
  [`splunk-observability-cloud-integration-setup`](../splunk-observability-cloud-integration-setup/SKILL.md).
- Native O11y dashboards for AWS namespaces ->
  [`splunk-observability-dashboard-builder`](../splunk-observability-dashboard-builder/SKILL.md).
- Detectors / AutoDetect alerting ->
  [`splunk-observability-native-ops`](../splunk-observability-native-ops/SKILL.md).
- OTel collector on EC2 / EKS for richer host telemetry than `CWAgent` ->
  [`splunk-observability-otel-collector-setup`](../splunk-observability-otel-collector-setup/SKILL.md).
- Lambda APM via the Splunk OpenTelemetry Lambda layer (publisher
  `254067382080`) -> deferred to a future companion skill
  `splunk-observability-aws-lambda-apm-setup`. Renderer emits a hand-off stub
  in `09-handoff.md` only.

## Out of Scope

- AWS log collection via the Splunk AWS log collector Lambda (handed off to
  `Splunk_TA_AWS`; the `enableLogsSync` API field is deprecated and rejected
  by the renderer).
- Lambda APM instrumentation via the OpenTelemetry Lambda layer (deferred to
  the future `splunk-observability-aws-lambda-apm-setup` companion skill).
- Native O11y AWS dashboard / detector CRUD (handed off to
  `splunk-observability-dashboard-builder` and
  `splunk-observability-native-ops`).
- AppDynamics for AWS workloads (separate AppDynamics SaaS workflow).
- Splunk Cloud Platform Data Manager AWS log onboarding (different product;
  Splunk Cloud Platform side, not Splunk Observability Cloud).

## Validation

```bash
bash skills/splunk-observability-aws-integration/scripts/validate.sh \
  --output-dir splunk-observability-aws-integration-rendered
```

Static checks: required-files, IAM JSON shape, secrets-leak scan across every
rendered file, CFN template URL HTTP HEAD probe (`--live`).

With `--live`: `GET /v2/integration?type=AWSCloudWatch` round-trip, drift
report against `template.example`.

See `reference.md` and the focused references under `references/` for full
detail. The plan and corrections that produced this skill are recorded in
`.cursor/plans/splunk_o11y_aws_integration_skill_*.plan.md`.

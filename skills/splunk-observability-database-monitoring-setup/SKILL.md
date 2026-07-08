---
name: splunk-observability-database-monitoring-setup
description: >-
  Render, validate, apply, verify, and roll back production Splunk
  Observability Cloud Database Monitoring configurations for Microsoft SQL
  Server, MySQL, MariaDB, Oracle Database, and PostgreSQL through the Splunk
  Distribution of OpenTelemetry Collector. Covers Kubernetes, Linux, and
  Windows outputs; query samples and top queries; infrastructure metrics;
  product UI validation; APM query correlation handoffs; and DBMon query AI
  Assistant readiness. Use when handling DBMon receiver setup, database query analysis,
  explain-plan readiness, or database collector lifecycle work, including
  version-aware MySQL and MariaDB feature gaps.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  collector_release: "0.155.0"
  helm_chart_release: "0.155.0"
  compatibility_verified: "2026-07-02"
---

# Splunk Observability Database Monitoring Setup

Use this skill to take DBMon from a reviewed target specification through a
validated collector deployment and product evidence. Render first. Apply only
with the platform-specific acceptance gate. Do not report success merely
because the collector starts.

## Audited baseline and production matrix

Pin new deployments to Splunk OTel Collector `v0.155.0` and Helm chart
`0.155.0`. Enforce these receiver-specific floors and platform/version pairs:

| Engine | Production support | Collector floor |
|---|---|---|
| Microsoft SQL Server | 2016/2017/2019/2022 on Azure Managed Instance, Azure SQL Database, AWS RDS, or self-hosted | `v0.148.0` |
| MySQL | Product floor 5.7+ on AWS RDS or standalone; pinned receiver verifies 5.7.x, 8.0.x, 8.4.x, and 9.x; explain plans require 8.0+ | `v0.154.0` |
| MariaDB | Product floor 10.5+ on AWS RDS or standalone; pinned receiver verifies 10.5.x–10.11.x and 11.x; explain plans are unavailable | `v0.154.0` |
| Oracle Database | 19c/26ai on AWS RDS, Oracle RAC, or self-hosted; one target per RAC node | `v0.148.0` |
| PostgreSQL | Azure Flexible Server 14.20/17.7 or Amazon RDS 14.15/17.5; keep versions paired with their provider | `v0.147.0` |

MySQL 5.7+ and MariaDB 10.5+ are production-supported product targets. Enforce
the narrower pinned-receiver rows above and preserve their version-aware
evidence: metrics and query events are available, but explain plans are not
produced for MySQL 5.7 or MariaDB. Continue to use
`--allow-unsupported-targets` only for platforms or versions outside the
verified matrix; generated production apply helpers refuse that mode.

Required production evidence schema:

```yaml
sizing_evidence:
  reference: CHANGE-1234-load-test-report
  reviewed_by: db-platform-owner
  reviewed_at: "2026-07-07"
  peak_memory_mib: 3072
  peak_cpu_cores: 1.5
  target_count: 4
```

Direct self-managed SQL Server/Oracle connections have no receiver TLS knobs
and therefore also require an explicit `transport_exception` with exactly
`reason`, `reference`, `reviewed_by`, and ISO `reviewed_at`. Managed SQL
Server/Oracle never accepts that exception and must use a secret-backed,
URL-form datasource with certificate verification.

## Primary workflow

1. Read `reference.md`. Confirm the realm, DBMon entitlement, target matrix,
   collector topology, explicit CPU/memory sizing evidence, database prerequisites, and required product
   features. Set `scrape_owner` to exactly one enabled runtime; multiple output
   packets may be rendered for review, but only the owner packet can apply.
2. Copy `template.example` outside the repository. Enter non-secret target
   data and credential reference names only. Set `collector.kube_context` for
   Kubernetes and review each non-secret target `validation_filters` identity;
   datasource and loopback targets require an explicit expected identity. Add
   sizing reference/reviewer/date plus measured peak memory, peak CPU, and
   benchmark target count. Managed
   SQL Server/Oracle targets require datasource mode with runtime-verified TLS.
3. Render and run static plus pinned-collector configuration validation:

   ```bash
   bash skills/splunk-observability-database-monitoring-setup/scripts/setup.sh \
     --render --validate --collector-validate \
     --spec /secure/path/dbmon.yaml \
     --output-dir splunk-observability-database-monitoring-rendered
   ```

4. Review `metadata.json`, the coverage report, validation plan, database
   prerequisite runbooks, platform config, action packet, and rollback packet.
   Resolve every failure and explicitly accept every documented gap.
5. Create the database users/grants and real Kubernetes Secrets or host
   environment variables through the owning systems. This skill never applies
   database grants or renders secret values.
6. Apply the reviewed target platform only after authorization:

   ```bash
   # Kubernetes
   bash skills/splunk-observability-database-monitoring-setup/scripts/setup.sh \
     --apply-k8s --accept-k8s-apply --collector-validate \
     --spec /secure/path/dbmon.yaml

   # Linux
   bash skills/splunk-observability-database-monitoring-setup/scripts/setup.sh \
     --apply-linux --accept-linux-apply --collector-validate \
     --spec /secure/path/dbmon.yaml \
     --db-credentials-env-file /secure/path/dbmon.env
   ```

   `--apply` remains a Kubernetes compatibility alias. Use the explicit target
   mode in new automation. Windows is a reviewed PowerShell handoff, not an
   unattended mutation path. An action helper refuses to run when its platform
   does not equal the spec's `scrape_owner`, preventing duplicate scrapes.
7. Run live and tenant-side read-only validation:

   ```bash
   bash skills/splunk-observability-database-monitoring-setup/scripts/validate.sh \
     --output-dir splunk-observability-database-monitoring-rendered \
     --api
   ```

   Add `--live` for a Kubernetes packet. It is a scoped Kubernetes pod/log
   probe, not a host-service check. It keeps connection, authentication,
   required-system-view permission, scrape, and export failures fatal while
   recognizing the upstream PostgreSQL receiver's two best-effort
   per-statement EXPLAIN messages. For Linux or Windows, run the rendered
   platform status step and then the API validation above.

8. Complete the product validation plan. Prove the target in Infrastructure >
   Datastores and APM > Database monitoring, then verify Queries, Query samples,
   Query metrics, Dependencies, Metadata, eligible explain plans, and any
   requested APM/AI features.
9. If apply validation fails, use the captured rollback state:

   ```bash
   bash skills/splunk-observability-database-monitoring-setup/scripts/setup.sh \
     --rollback-k8s --accept-k8s-rollback \
     --output-dir splunk-observability-database-monitoring-rendered

   bash skills/splunk-observability-database-monitoring-setup/scripts/setup.sh \
     --rollback-linux --accept-linux-rollback \
     --output-dir splunk-observability-database-monitoring-rendered
   ```

   Rollback requires the owner-only apply-state file and refuses if the live
   Helm revision or applied Linux files drifted. An explicit
   `--rollback-revision N` must equal the state-recorded previous revision;
   otherwise perform a separately reviewed manual recovery. Never improvise a
   destructive Helm or filesystem reset.

Run `setup.sh --help` before production execution; it is authoritative for the
current flags and acceptance requirements.

## Required collector shape

- Render `metrics/dbmon` and `logs/dbmon` for a core-engine-only or
  MySQL-family-only packet. For mixed packets, render the deterministic
  `metrics/dbmon_core`, `logs/dbmon_core`, `metrics/dbmon_mysql`, and
  `logs/dbmon_mysql` pipelines so MySQL and MariaDB retain their documented
  processor order.
- Export infrastructure metrics through the isolated `signalfx/dbmon` exporter.
- Export query samples and top-query events through the canonical
  `otlp_http/dbmon` exporter to
  `https://ingest.<realm>.observability.splunkcloud.com/v3/event`.
- Set `X-splunk-instrumentation-library: dbmon` and obtain `X-SF-Token` only
  from a runtime secret environment variable. Kubernetes reuses the chart's
  `SPLUNK_OBSERVABILITY_ACCESS_TOKEN`; Linux, Windows, and standalone gateways
  use `SPLUNK_ACCESS_TOKEN`.
- Enable `db.server.query_sample` and `db.server.top_query` by default.
- Preserve stable `service.instance.id`; MySQL and MariaDB require the
  `mysql.instance.endpoint` identity processor.
- Keep the production receiver interval fixed at `10s`. Default to `100`
  query-sample rows, a `60s` top-query interval, and a `1000` top-query sample
  limit. A reviewed load test can justify only documented advanced changes
  within the renderer's enforced bounds; `100` query-sample rows is a ceiling,
  so an override may lower it but never raise it.
- Reject legacy `otlphttp/dbmon`, a generic `metrics` DBMon pipeline, invented
  suffixes, deprecated `*.signalfx.com` endpoints, and receiver configurations
  that omit the event pipeline.

## Platform rules

### Kubernetes

- Place external database receivers only under `clusterReceiver`; never put
  them in the node `agent` DaemonSet. Chart `0.155.0` does not accept a
  `clusterReceiver.replicas` value, so use its singleton mode and verify exactly
  one ready cluster-receiver pod after apply.
- Render generic Kubernetes with a blank chart `distribution` value. Reject EKS
  Fargate and use a supported non-Fargate or external collector runtime.
- Before apply, prove active context, release/namespace/chart ownership,
  existing database Secrets, current Helm values, and a clean config
  validation. Every Helm and kubectl call is bound to the reviewed context.
  Merge with the current release and use the major-version-specific
  transactional Helm upgrade below.
- Support both Helm 3 and Helm 4 semantics: Helm 3 uses the owner-only
  executable post-renderer with `--wait`; Helm 4 uses an ephemeral local
  `postrenderer/v1` subprocess plugin plus watcher wait and
  `--server-side=false`. Do not enable Helm's built-in `--atomic` or
  `--rollback-on-failure`: this action owns rollback so it can first quiesce
  the fixed-node singleton and avoid overlapping old/new pods. The Helm 4
  client-side three-way update is needed
  to remove `rollingUpdate` while changing the singleton Deployment to
  `Recreate`; Helm 4 server-side apply otherwise retains an invalid field.
  Scope the Helm 4 plugin path to template/upgrade commands only, and retain
  `--hide-secret` for server-side upgrade dry-runs.
- If the installed chart is not `0.155.0`, stop for an upgrade review; only
  continue with the separate `--accept-collector-upgrade` gate. The same gate
  applies if the global image pin changes any existing collector workload.
- For an accepted chart or image upgrade, derive the target distribution's
  receiver, processor, exporter, connector, and extension inventory from the
  exact pinned image. Inspect existing role configs diagnostically, then fail
  before Secret reads or Helm mutation if the final rendered agent, gateway,
  or cluster-receiver config retains an unavailable component type. Existing
  defaults that the target chart removes are not false-blocked.
- Chart `0.155.0` also rejects deprecated custom component aliases through its
  `failOnDeprecatedNames` gate. Before template rendering, fail on exporter
  `otlp`/`otlphttp`, processor `k8sattributes`, or receiver
  `filelog`/`hostmetrics`/`k8sobjects` definitions and pipeline references,
  including suffixed IDs. Do not mechanically rename a live topology; hand the
  full-release migration to `splunk-observability-otel-collector-setup`.
- Fail on database receivers already assigned to agent/gateway placement.
  Replacing or removing an existing cluster-receiver DBMon slice additionally
  requires `--accept-dbmon-reconfigure` after duplicate-load review.
- The helper inventories only the named Helm release. Before migration, attach
  evidence that any external collector, host service, or prior release scraping
  the same databases is disabled; the action cannot discover every external
  scraper.
- Preserve chart-owned processors, normal Kubernetes pipelines, existing env
  entries, realm, cluster name, and distribution. Database Secrets must be in
  the collector namespace with every referenced key nonempty.
- For secure datasource options that name a SQL Server `certificate` file or
  Oracle `WALLET` directory, configure a read-only Secret volume in the base
  `clusterReceiver`. The guarded apply verifies that each secret-derived,
  absolute trust path is covered by a rendered cluster-receiver mount before
  Helm mutation; it never prints the datasource or credential values. SQL
  Server certificate paths must end in `.pem`; the pinned driver rejects a
  PEM trust certificate whose path uses a `.crt` suffix.
- Verify desired replicas, ready replicas, and selected pod count all equal
  one. Persist owner-only revision/image/config-fingerprint state outside the
  rendered packet, and roll back only when the live revision still matches it.

### Linux

- Require the pinned collector, systemd, the configured environment file,
  adequate effective host/cgroup memory, and permission to manage only
  `splunk-otel-collector.service`.
- Refuse a base config that already has any database receiver. Audit the
  effective systemd `ExecStart` and fail closed rather than discarding existing
  feature gates, providers, arguments, or additional configs.
- Back up and integrity-record the existing config/environment before atomic
  replacement. Validate the new config before restart; persist `preparing`
  state before any backup or credential staging, then use durable `applying`,
  `restoring`, and `finalizing` transitions around every mutation. Restore on
  any uncommitted failure. Rollback verifies both backup checksums and hashes
  of the currently applied files, refusing stale state after operator drift.

### Windows

- Render collector YAML, environment-variable names, prerequisites, and a
  PowerShell action/rollback handoff.
- Validate with the pinned Windows collector before restarting the service.
- Use Windows Performance Counters only for applicable SQL Server collection;
  other targets use direct network connections.
- Do not mutate Windows from this skill without a future explicit, guarded
  action implementation.

## Sizing and topology gates

- Refuse more than 30 targets per collector instance.
- Require at least `2048 MiB` for any collector that monitors SQL Server.
- Require at least `512 MiB` for an Oracle-only collector; mixed SQL
  Server/Oracle uses `2048 MiB`.
- Require explicit `collector.memory_mib`, `collector.cpu_limit`, and reviewed
  `sizing_evidence` for every packet. Splunk publishes no equivalent
  performance baseline for PostgreSQL, MySQL, or MariaDB; require a
  representative load test instead of inventing a support claim.
- Allow only DBMon realms `us0`, `us1`, `eu0`, `eu1`, `eu2`, `au0`, `jp0`, and
  `sg0`; reject `us2` and unknown realms.

## Product completion gate

Record these states separately: `configured`, `collector validated`,
`telemetry observed`, and `product UI verified`.

- Confirm stable database instance identity and receiver metrics in
  Infrastructure Monitoring.
- Require one positive SignalFlow metric probe per configured target, filtered
  by that target's expected identity. A tenant-wide metric match is never
  telemetry proof for a specific target.
- Confirm every intended target in the DBMon Overview and all applicable
  navigator tabs.
- Confirm only event surfaces enabled for each target. MySQL explain plans
  require 8.0+; supported MySQL 5.7 and MariaDB targets provide metrics and
  query events but not explain plans in the pinned receiver.
- Confirm stored-procedure views when used; Splunk exposes them for SQL Server
  and Oracle.
- Treat Oracle `db.server.session.wait_sample` as an explicit opt-in. The
  upstream `v0.155.0` receiver documents it, but Splunk's DBMon Oracle product
  page does not yet document its UI/support behavior; record and validate that
  gap.
- When APM correlation is requested, use only Splunk's published matrix: .NET
  with SQL Server; Java JDBC with SQL Server, MySQL, Oracle, or PostgreSQL.
  Prove a sampled query-to-trace link and trace-to-normalized-query link.
- Do not promise MySQL database instances in the APM service map; Splunk
  explicitly excludes that feature. Treat MariaDB APM correlation as a gap.
- The DBMon Query statement AI Assistant can summarize normalized queries and
  generate recommendations, but Splunk Support must activate it. Mark it
  `ui_handoff_required` until a human verifies it.
- Hand custom dashboards and detectors to
  `splunk-observability-dashboard-builder` and
  `splunk-observability-native-ops`; do not treat their absence as collector
  failure unless they were in the requested scope.

## Non-negotiable guardrails

- Never ask for or display token, password, datasource, private-key, or
  connection-string values. Reject direct secret flags and inline secret
  fields recursively.
- Read the tenant API token only from `SPLUNK_O11Y_TOKEN_FILE`. For collector
  ingest, reuse the Kubernetes chart Secret or read `SPLUNK_ACCESS_TOKEN` from
  the private Linux/Windows runtime environment. Require private, non-symlink
  files and never pass a token value on argv.
- Render only Kubernetes Secret key references and Linux/Windows environment
  variable names. Placeholder Secret manifests are documentation, never apply
  input.
- Collector config validation, `--live`, and `--api` are read-only and do not
  authorize apply.
- Require separate explicit gates for Kubernetes apply, Linux apply, and every
  rollback. Do not broaden one approval to another platform.
- Do not auto-apply database users/grants, managed-database parameter changes,
  database restarts, application instrumentation, DBMon entitlement changes,
  AI activation, dashboards, or detectors.
- Treat query samples as potentially sensitive. Redact product evidence under
  the organization's data-handling policy.

## Rendered evidence

Expect the packet to contain:

- Kubernetes singleton cluster-receiver values, placeholder-only Secret stubs,
  base-collector handoff, `scripts/apply-dbmon-overlay.sh`, and
  `scripts/rollback-dbmon-k8s.sh`.
- `linux/collector-dbmon.yaml`, its environment-name template and base handoff,
  `scripts/apply-dbmon-linux.sh`, and `scripts/rollback-dbmon-linux.sh`.
- `windows/collector-dbmon.yaml`, its environment-name template,
  `scripts/apply-dbmon-windows.ps1`, and
  `scripts/rollback-dbmon-windows.ps1` as fail-closed validation/handoff
  packets. They do not persist plaintext credentials in the service registry.
- Per-engine prerequisite runbooks, APM-correlation handoff, product validation
  plan, coverage report, gateway reference, and `metadata.json`.

Static validation must fail on malformed YAML, unsupported target pairs,
version-floor violations, more than 30 targets, insufficient documented memory,
non-singleton Kubernetes placement, missing platform artifacts, legacy
component names, secret material, or incomplete coverage/validation evidence.

See `reference.md` for the full support gaps, receiver prerequisites, advanced
controls, product/APM/AI feature matrix, action behavior, and official source
ledger. See `references/gateway-routing.sqlserver.md` for the supported SQL
Server gateway pattern.

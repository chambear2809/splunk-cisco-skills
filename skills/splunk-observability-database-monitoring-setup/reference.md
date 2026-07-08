# Splunk Observability Database Monitoring Reference

This reference records the production contract for the
`splunk-observability-database-monitoring-setup` skill. It was verified against
the official Splunk Database Monitoring documentation and the Splunk
OpenTelemetry Collector/chart `0.155.0` pair on 2026-07-07. Repository
frontmatter records the collector compatibility date as its 2026-07-02 release
date; the later date is the completed chart/documentation audit.

## Audited release baseline

- Default Splunk Distribution of OpenTelemetry Collector: `v0.155.0`.
- Default Splunk OTel Collector Helm chart: `0.155.0`.
- Audited collector commit: `f8afa6bcb28ea383b3c36aa23784594d864b39e0`;
  audited chart commit: `a03399ca43ba5bd7e3eb2665a81139e214c7f0b2`.
- Keep the collector and chart on matching versions unless the chart release
  explicitly adopts a different collector version.
- Treat the per-receiver version below as a minimum, not as the recommended
  production pin. New renders default to the audited `0.155.0` pair.
- Review release notes before upgrading. In `v0.155.0`, for example, Oracle
  query events changed `db.namespace` to the database name and moved the
  service name to `oracle.db.service`; Oracle plans added
  `oracledb.plan.first_load` plus `OBJECT_NAME`, `OBJECT_TYPE`,
  `FILTER_PREDICATES`, `PARTITION_START`, and `PARTITION_STOP` plan-step
  fields; SQL Server plans added
  `sqlserver.query.plan.creation_time`; and SQL Server resource attributes
  added `service.name`/`service.namespace` with reviewed override support.
  Oracle also improved SQL obfuscation so approved leading-comment tags remain
  extractable while query text is anonymized, and clamps negative query and
  session-duration values to zero.
- Upstream OpenTelemetry Collector Contrib `v0.156.0` is not the current Splunk
  production target. Do not adopt its additional Oracle/PostgreSQL/SQL Server
  schema or grant changes until matching Splunk collector and chart releases
  are published and audited.

## Official Database Monitoring support matrix

| Engine | Database versions | Published platforms | Minimum collector |
|---|---|---|---|
| Microsoft SQL Server | 2016, 2017, 2019, 2022 | Azure Managed Instance, Azure SQL Database, AWS RDS, self-hosted | `v0.148.0` |
| MySQL | Product floor 5.7+; pinned `v0.155.0` receiver verifies 5.7.x, 8.0.x, 8.4.x, and 9.x | AWS RDS, standalone | `v0.154.0` |
| MariaDB | Product floor 10.5+; pinned `v0.155.0` receiver verifies 10.5.x–10.11.x and 11.x | AWS RDS, standalone | `v0.154.0` |
| Oracle Database | 19c, 26ai | AWS RDS, Oracle RAC, self-hosted | `v0.148.0` |
| PostgreSQL | Azure Flexible Server 14.20 or 17.7; Amazon RDS 14.15 or 17.5 | Azure Flexible Server or Amazon RDS, paired with the listed provider versions | `v0.147.0` |

Interpret the matrix conservatively:

- PostgreSQL versions are provider-specific pairs. Do not treat the four
  numbers as interchangeable between Azure and AWS.
- For Oracle RAC, define a separate target and receiver connection for every
  node.
- The generic architecture page mentions additional hosting examples, but the
  receiver-specific pages above are the production allow-list for this skill.
  A generic example such as Google Cloud SQL does not widen a receiver's
  published matrix.
- `--allow-unsupported-targets` is for a lab or proof of concept only. It keeps
  receiver, version-floor, pipeline, secret, target-count, and topology checks,
  but records `unsupported_opt_in` in the rendered metadata and coverage
  report. Generated apply helpers refuse it. Never describe that result as
  Splunk-supported production coverage.

### MySQL and MariaDB version-dependent gaps

The upstream `v0.155.0` receiver compatibility table documents these
version-aware feature boundaries inside the production matrix:

- MySQL 5.7+ is a supported DBMon target for metrics and query events, but does
  not expose executable sample text for explain plans. MySQL 8.0+ supports
  plans and requires schema-level `SELECT` grants for the schemas involved.
- MariaDB 10.5+ is a supported DBMon target for metrics and query events. The
  pinned receiver does not provide MariaDB explain plans because MariaDB lacks
  MySQL's `query_sample_text`; record that feature as not supported.
- Client and peer ports are reported as `0` on MySQL before 8.0.22 and on the
  currently listed MariaDB versions.
- Splunk's APM correlation matrix lists MySQL with Java, but does not list
  MariaDB as a separate supported correlation target. Treat MariaDB APM
  correlation as a documented gap even though the receiver can parse a
  propagated `@traceparent` variable.
- Splunk's APM service-map database-instance view explicitly excludes MySQL.
  Do not promise that service-map feature for MySQL or infer MariaDB support.

## Required review evidence

Every packet must set explicit `collector.memory_mib` and
`collector.cpu_limit`. PostgreSQL, MySQL, and MariaDB additionally require a
representative-load record, and the production template carries the same
schema for consistent review:

```yaml
sizing_evidence:
  reference: CHANGE-1234-load-test-report
  reviewed_by: db-platform-owner
  reviewed_at: "2026-07-07"
  peak_memory_mib: 3072
  peak_cpu_cores: 1.5
  target_count: 4
```

A direct self-managed SQL Server or Oracle path has no receiver-level TLS
controls and must include exactly this non-secret exception evidence; managed
platforms cannot use it:

```yaml
transport_exception:
  reason: externally protected private transport
  reference: CHANGE-1234
  reviewed_by: security-owner
  reviewed_at: "2026-07-07"
```

Free-text evidence is single-line, placeholder-free, and rejected when it
resembles secret material.

## Canonical collector contract

Use these exact component and pipeline identifiers in newly rendered Splunk
Distribution configurations:

- Database receiver IDs: `sqlserver/<name>`, `mysql/<name>`,
  `oracledb/<name>`, or `postgresql/<name>`. MariaDB uses the `mysql` receiver.
- Single-family infrastructure metrics pipeline: `metrics/dbmon`.
- Single-family query-event pipeline: `logs/dbmon`.
- DBMon event exporter: `otlp_http/dbmon`.

When a packet combines MySQL/MariaDB with any other engine, split the pipelines
deterministically:

- `metrics/dbmon_core` and `logs/dbmon_core` contain PostgreSQL, SQL Server,
  and Oracle receivers.
- `metrics/dbmon_mysql` and `logs/dbmon_mysql` contain MySQL and MariaDB
  receivers.

The split preserves Splunk's documented MySQL processor shape: its metrics
pipeline includes `resourcedetection` plus
`resource/mysql_service_instance_id`, while its event pipeline includes the
identity processor without `resourcedetection`. Core receiver metrics and logs
keep identical processor lists in the same order. Do not split a single-family
packet or invent any other suffix.

Do not emit the generic `metrics` pipeline name for DBMon or the old
`otlphttp/dbmon` component spelling. Some Splunk examples still contain both
spellings in one page; `otlp_http` is the canonical `v0.155.0` Splunk
Distribution component ID used by this skill.

The event exporter must use this shape (the Kubernetes token environment is
shown; host/gateway naming follows below):

```yaml
exporters:
  otlp_http/dbmon:
    headers:
      X-SF-Token: "${env:SPLUNK_OBSERVABILITY_ACCESS_TOKEN}"
      X-splunk-instrumentation-library: dbmon
    logs_endpoint: "https://ingest.<realm>.observability.splunkcloud.com/v3/event"
    sending_queue:
      batch:
        flush_timeout: 15s
        max_size: 10485760
        sizer: bytes
```

Export every `metrics/dbmon*` pipeline through the isolated `signalfx/dbmon`
exporter and every
`logs/dbmon*` pipeline through `otlp_http/dbmon`. Keep the DBMon processors in
their documented deterministic order. The MySQL/MariaDB path must insert
`mysql.instance.endpoint` into `service.instance.id`; without stable instance
identity, product navigation and correlation are unreliable.

Use the current `*.observability.splunkcloud.com` endpoints. Do not introduce
new `*.signalfx.com` endpoints.

The token environment name is runtime-specific:

- Kubernetes reuses the chart-provided
  `SPLUNK_OBSERVABILITY_ACCESS_TOKEN`. Do not guess a Secret name or create a
  second token environment variable.
- Linux, Windows, and the standalone gateway use
  `SPLUNK_ACCESS_TOKEN`, populated by the owning service environment or secret
  manager.

## Receiver defaults and advanced controls

Enable both events unless the operator explicitly opts out:

```yaml
events:
  db.server.query_sample:
    enabled: true
  db.server.top_query:
    enabled: true
```

Splunk recommends these defaults for every documented receiver:

| Setting | Default |
|---|---|
| Receiver `collection_interval` | `10s` |
| `query_sample_collection.max_rows_per_query` | `100` |
| `top_query_collection.collection_interval` | `60s` |
| `top_query_collection.max_query_sample_count` | `1000` |

SQL Server's `top_query_count` default is `250`; Oracle and MySQL/MariaDB use
`200`, while PostgreSQL exposes `top_n_query` (default `200`). Validate limits
against the selected receiver schema rather than applying one synthetic cap to
all engines. Keep the v0.155 MySQL receiver's audited
`allow_native_passwords: true` default unless the database account's actual
authentication plugin has been reviewed; the example does not force it off.

Changing advanced event-collection frequency or row/count limits can increase database load,
collector load, event volume, and ingest throttling. The skill renders explicit
advanced overrides within its production-safe bounds and flags non-default
values in the coverage and validation reports. Review them with the database
owner and load-test before production. The `100`-row query-sample and Oracle
session-wait limits are intentional non-overridable production ceilings in this
skill. MySQL, MariaDB, and Oracle top-query counts are likewise capped at `200`;
SQL Server permits a reviewed value up to `10000`. These conservative skill
ceilings remain enforced even where an upstream receiver schema has no maximum.

Other supported advanced controls include:

- PostgreSQL supports CA/client-certificate files, ciphers, curves, and the
  system CA pool (`include_system_ca_certs_pool`), but its v0.155 receiver rejects server-name and min/max TLS
  controls. MySQL and MariaDB also support server-name and TLS
  version controls. `cipher_suites` and `curve_preferences` are strict string
  lists; `include_insecure_cipher_suites` must remain false. Use file paths,
  never in-memory PEM values. SQL Server and
  Oracle do not accept that generic receiver-level TLS block; put their
  driver-specific TLS/trust options in a secret-backed datasource string.
- Optional receiver metrics and basic resource-attribute enablement (plus SQL
  Server `override_value`). Per-metric attribute/aggregation tuning and SQL
  Server's experimental include/exclude resource filters are intentionally
  gated from production. `postgresql.wal.delay` is the audited default; legacy
  `postgresql.wal.lag` needs an unaudited feature gate and is rejected. SQL Server built-in
  content requires `sqlserver.instance.name`; Azure-managed SQL targets must
  disable `sqlserver.database.count` because the current receiver does not
  support it there.
- Target-specific `databases` and exclusion lists where the receiver supports
  them.
- Top-query lookback/count controls and query-plan cache size/TTL where the
  receiver exposes them.
- Oracle's optional `db.server.session.wait_sample` event and
  `session_wait_event_collection.max_rows_per_query`. Keep it disabled unless
  explicitly requested: the upstream `v0.155.0` receiver documents the event
  and extra `V_$SESSION_EVENT`/related grants, but Splunk's DBMon Oracle product
  page does not yet describe its product UI or support behavior. Mark the
  result as an explicit upstream-component coverage gap and validate it in the
  tenant UI.
- Oracle leading-SQL-comment extraction through an allow-list of
  `allowed_comment_keys`. Review every key for sensitivity; extracted values
  become telemetry attributes.
- Oracle `v0.155.0` query-plan/event metadata, including plan hash, SQL ID,
  child cursor, `oracledb.plan.first_load`, the `OBJECT_NAME`, `OBJECT_TYPE`,
  `FILTER_PREDICATES`, `PARTITION_START`, and `PARTITION_STOP` plan-step
  fields, database namespace, and `oracle.db.service`, plus best-effort
  instance version/role/open-mode/PDB and hosting-type metadata. The latter
  requires the additional catalog/dynamic-view grants listed by the upstream
  receiver; treat missing optional metadata separately from core DBMon health.
- Multiple instances by assigning every receiver a unique target name.

Managed SQL Server and Oracle require a datasource; direct self-managed mode
requires a recorded `transport_exception`. Render only an environment-variable reference such as
`${env:DBMON_PROD_DATASOURCE}` and source its value from an existing Kubernetes
Secret or protected host environment. Never put the datasource value in the
spec, generated YAML, environment template, metadata, or command line. Encode
special characters according to URL rules. Runtime preflight accepts only
certificate-verifying URL forms, for example
`sqlserver://user:pass@host:1433?database=db&encrypt=true&trustservercertificate=false&certificate=%2Fetc%2Fdbmon%2Fsql-ca.pem`
and
`oracle://user:pass@host:2484/service?SSL=enable&SSL%20Verify=true&WALLET=%2Fetc%2Fdbmon%2Foracle-wallet`.
In the `go-mssqldb` URL grammar used by Collector `v0.155.0`, the URL path is
a named SQL Server instance, not a database name; select the database with the
`database` query option. A `certificate` trust-file path must end in `.pem`;
the pinned driver rejects a PEM certificate mounted with a `.crt` suffix.
When `certificate` or `WALLET` names a container path,
the existing base collector release must mount the referenced CA file or Oracle
wallet directory into `clusterReceiver`; Kubernetes apply verifies that every
declared trust path is covered by a read-only cluster-receiver mount before it
mutates Helm.
Percent-encode reserved characters in credentials; duplicate TLS query keys,
semicolon-form SQL Server DSNs, disabled encryption, and trust bypass are
rejected without printing the datasource.

Every target also has a non-secret validation identity. Direct network targets
derive `service.instance.id` in the receiver's exact format; datasource and
loopback targets must set `validation_filters` explicitly because the secret
datasource or collector hostname determines the runtime value. MySQL/MariaDB
copy the endpoint verbatim, including IPv6 brackets. The API validator emits
one filtered SignalFlow probe per target and never treats an organization-wide
metric match as proof for another database.

## Database prerequisites

The skill emits engine-specific prerequisite runbooks; it does not execute
database grants or restart a database server.

### Microsoft SQL Server

- Create a dedicated non-admin, read-only login.
- Grant `VIEW ANY DATABASE` as the least-privileged receiver requirement among
  `CREATE DATABASE`, `ALTER ANY DATABASE`, or `VIEW ANY DATABASE`; do not rely
  on the default `public` grant remaining present.
- Grant `VIEW SERVER PERFORMANCE STATE` for SQL Server 2022 and later; grant
  `VIEW SERVER STATE` for earlier versions.
- Grant only the additional metadata permissions required for the selected
  features, such as `VIEW ANY DEFINITION`.
- A Windows collector can use Windows Performance Counters. A non-Windows
  collector connects directly with server, port, and credentials.
- Named-instance collection on Windows requires both `computer_name` and
  `instance_name`.

### MySQL and MariaDB

- Enable `performance_schema`; Splunk strongly recommends setting digest and
  SQL text limits to `4096` to reduce query truncation.
- Grant the monitoring user `REPLICATION CLIENT` (or the documented MariaDB
  replacement privileges) and `SELECT` on `performance_schema.*`.
- Grant schema-level `SELECT` only where explain plans are required. Queries
  can appear without those grants, but eligible explain plans cannot.
- Query samples include wait duration only when the
  `events_waits_current` Performance Schema consumer is enabled. It is off by
  default and resets after AWS RDS restart/failover; use reviewed DBA/provider
  startup automation and verify it again after failover. The collector account
  requires `PROCESS` for InnoDB buffer-pool metrics, but does not receive broad
  Performance Schema update privileges by default.
- MariaDB 10.5.2 renamed `REPLICATION CLIENT` to `BINLOG MONITOR`; from 10.5.9,
  replica status uses `SLAVE MONITOR`/`REPLICA MONITOR`. Follow the generated
  version-specific runbook rather than copying MySQL grants blindly.

### Oracle Database

- Create a dedicated non-administrative user.
- Grant `CREATE SESSION`; object-level `SELECT` grants alone do not permit the
  receiver account to connect.
- Grant read access only to the documented dynamic performance and catalog
  views. AWS RDS uses `rdsadmin.rdsadmin_util.grant_sys_object`; self-hosted
  Oracle uses direct `GRANT SELECT` statements. The generated `v0.155.0`
  runbook includes the complete metric-query view set, including
  `V_$ROWCACHE`, `V_$SYSMETRIC`, `V_$PARAMETER`, `DBA_FREE_SPACE`, and
  `DBA_RECYCLEBIN`, plus the event views enabled by the target.
- Configure every RAC node independently.

### PostgreSQL

- Create a dedicated user, grant `pg_monitor`, and grant `SELECT` on
  `pg_stat_database`.
- Load and create `pg_stat_statements` in every database that must provide top
  queries. Azure Flexible Server also needs its documented server parameters
  and a restart.
- Treat query-plan collection as best effort. The upstream `v0.155.0`
  receiver deliberately logs `failed to explain statement` and `failed to
  explain query` for individual statements the read-only monitoring user
  cannot execute, caches that result to avoid log flooding, and still records
  the top-query event. The generated health checks exclude only those exact
  source messages; connection, authentication, system-view permission,
  scrape, and export failures remain fatal. Grant application-object access
  only when the organization explicitly wants plans for those objects.
- Require TLS for managed providers unless a formally reviewed exception says
  otherwise. A documentation example with `tls.insecure: true` is not a
  production recommendation.

## Deployment platforms and actions

The spec must assign `scrape_owner` to exactly one enabled runtime. It is safe
to render Kubernetes, Linux, and Windows packets together for review, but
applying more than one packet to the same targets creates duplicate database
load and duplicate telemetry. Every generated apply helper therefore refuses
to mutate unless its runtime is the declared owner. Change ownership only in a
reviewed migration that removes or rolls back the previous scraper first.

### Kubernetes

- Put all external database receivers under `clusterReceiver` and keep them out
  of the node `agent` DaemonSet. Agent placement duplicates every scrape on
  every node, inflates usage, and adds avoidable load to the database. Chart
  `0.155.0` does not accept a `clusterReceiver.replicas` value; use its
  singleton non-Fargate mode and verify exactly one ready cluster-receiver pod
  after apply instead of rendering an invalid replicas field.
- The generic `kubernetes` distribution renders the chart distribution value
  as blank, matching the chart's generic mode. Do not write the literal
  `kubernetes` value into chart values.
- Accepted chart selectors are generic Kubernetes, AKS, EKS, EKS Auto Mode,
  GKE, GKE Autopilot, and OpenShift. Validate the selected chart mode against
  the actual cluster; a label is not evidence of runtime compatibility.
- Preserve chart-owned `memory_limiter`, `batch`, `resourcedetection`, normal
  Kubernetes pipelines, and existing `extraEnvs` (merge env entries by name).
  The DBMon overlay adds dedicated pipelines and the MySQL identity processor;
  it must not replace `k8s_cluster` collection or the chart's dynamic limits.
- Reuse the chart-provided Observability token environment. Require every
  database credential Secret and referenced nonempty key in the collector
  namespace because `secretKeyRef` cannot cross namespaces.
- Reject EKS Fargate for this workflow. It cannot satisfy the reviewed
  singleton cluster-receiver runtime contract. Use a supported non-Fargate
  collector runtime or an external Linux/Windows collector.
- Apply only after checking the active kube-context, release name, namespace,
  chart identity, current Helm values, Secret existence, and the rendered
  merged values. Preserve the installed realm, cluster name, and distribution
  unless the reviewed spec explicitly changes them. Use the action-owned
  transaction and retain the previous revision for a quiesced rollback.
- Detect the Helm major version before rendering. Helm 3 invokes the
  owner-only executable post-renderer with `--wait`. Helm 4 creates an
  owner-only temporary `postrenderer/v1` subprocess plugin, exposes its
  isolated `HELM_PLUGINS` root only to template/upgrade invocations, and uses
  `--wait=watcher --server-side=false`. Neither path uses Helm's built-in
  `--atomic` or `--rollback-on-failure`; the generated transaction helper
  quiesces the singleton Deployment before an action-owned rollback, verifies
  the restored release, and retains trusted state if recovery is incomplete.
  The explicit client-side three-way update is required for the owned cluster-receiver
  Deployment: Helm 4 server-side apply drops the explicit null needed to
  remove the chart's `rollingUpdate` field while changing the strategy to
  `Recreate`, and Kubernetes otherwise rejects the retained field. Helm 4
  upgrade dry-run uses
  `--dry-run=server --hide-secret`; never log post-renderer input because Secret
  filtering occurs after post-rendering.
- Require `collector.kube_context`; compare it to the active context and pass it
  explicitly to every Helm and kubectl command. Inventory bare and named DB
  receiver IDs under agent, gateway, and clusterReceiver before merge. Agent
  or gateway duplicates must be migrated first; a reviewed cluster DBMon
  replacement/removal requires `--accept-dbmon-reconfigure`.
- The overlay pins the global collector image, so compare all current and
  rendered collector workload images. Any release-wide image change uses the
  same explicit `--accept-collector-upgrade` gate as a chart change.
- Before an accepted chart or image upgrade, obtain the authoritative
  component-type inventory from the exact target image and inspect the
  existing and final rendered agent, gateway, and cluster-receiver configs.
  Existing-manifest findings are diagnostic because the target chart can
  legitimately remove old defaults; final rendered configs are authoritative
  and any unavailable receiver, processor, exporter, connector, or extension
  fails before credential Secret reads, transaction state, or Helm mutation.
  Raw configs and Collector diagnostics remain suppressed.
- The chart `0.155.0` `failOnDeprecatedNames` contract applies these exact
  section-specific mappings to both component definitions and pipeline
  references while preserving the meaning of any `/suffix`: exporters
  `otlp` to `otlp_grpc` and `otlphttp` to `otlp_http`; processor
  `k8sattributes` to `k8s_attributes`; receivers `filelog` to `file_log`,
  `hostmetrics` to `host_metrics`, and `k8sobjects` to `k8s_objects`. The DBMon
  action reports only base-name mappings and counts, then fails before template
  rendering. It never auto-renames these aliases because a syntax rename can
  conceal an agent/gateway topology change; use
  `splunk-observability-otel-collector-setup` for the reviewed release migration.
- Set and verify both the cluster-receiver memory request and limit. After
  apply, require desired replicas, ready replicas, and selected pod count all
  equal one, then scan scoped logs for receiver authentication, permission,
  connection, query, scrape, TLS, and Oracle failures.
- Require `--accept-k8s-apply` for apply, the separate
  `--accept-collector-upgrade` gate when the installed chart is not `0.155.0`,
  and `--accept-k8s-rollback` for rollback. Apply state lives by default under
  `${XDG_STATE_HOME:-$HOME/.local/state}/splunk-dbmon`, not in the rendered
  packet. It records prior/applied revisions, context, image identity, and an
  overlay fingerprint. Rollback requires owner-only state, refuses live Helm
  revision drift, and consumes the state only after success. An explicit
  `--rollback-revision` must equal the recorded previous revision.
- Never create real database Secrets from the placeholder stub.

### Linux

- Use the rendered standalone `collector-dbmon.yaml`, environment-variable
  name template, systemd action packet, and prerequisite runbooks.
- Preflight the exact `v0.155.0` collector binary with its configuration
  validation command before changing a service.
- Verify effective host/cgroup memory, reject any pre-existing bare or named DB
  receiver in the base config, and audit the effective systemd `ExecStart`.
  Fail closed on additional flags, feature gates, providers, or configs rather
  than silently replacing them; use the manual host handoff for those units.
- Apply only with the explicit Linux acceptance gate. The helper pins
  `/usr/bin/otelcol`, trusts only root-owned state/config/binary paths, refuses
  unowned pre-existing managed files, and writes durable `preparing` state
  before creating any backup or credential-bearing staging file. It fsyncs the
  complete backup and staged files before advancing to `applying` and before
  the first replacement. Recovery advances through resumable `restoring` and
  `finalizing` phases, accepts an interrupted mix only when every file matches
  an applied or backup hash, and retains state until the service is active and
  the current transaction's tracked artifacts are removed.
- Transaction state schema v2 intentionally refuses legacy state. Before using
  this packet on a host with older DBMon state, run the rollback helper from the
  packet that created that state; the current helper will not guess at a legacy
  backup chain or silently adopt it.
- Pass database values only through the private file named by
  `--db-credentials-env-file`; require a single-link, owner-only, non-symlink
  regular file (for example mode `0400` or `0600`). `--accept-linux-apply` and
  `--accept-linux-rollback` are independent gates.
- Rollback verifies backup checksums, restores through same-filesystem staged
  replacements, and can resume after interruption. It deletes a consumed
  credential-bearing backup after service recovery but before rebasing the
  state chain, refuses unrecognized drift, and never deletes unrelated content.

### Windows

- Render the Windows collector configuration, environment-variable name
  template, prerequisite runbooks, and a PowerShell action handoff.
- Validate the configuration with the pinned Windows collector before a
  service restart.
- This skill does not perform Windows mutation. The rendered PowerShell packet
  validates then fails closed because the receiver requires process environment
  credentials and writing those values into the service registry is not an
  approved protected-secret mechanism. Provision the service through the
  owning Windows secret workflow, then run tenant/product validation. The
  rendered rollback packet is intentionally non-mutating for the same reason.
- SQL Server local/named-instance Performance Counter mode is Windows-only.
  PostgreSQL, Oracle, MySQL, MariaDB, and remote SQL Server use network
  receiver connections even when the collector runs on Windows.

### Gateway routing

Splunk's published dedicated-gateway pattern is specifically documented for
Microsoft SQL Server. Use a dedicated OTLP/HTTP listener, normally port `7276`,
for DBMon event logs and keep the gateway's `logs/dbmon` path isolated from
general logs. See `references/gateway-routing.sqlserver.md`.

Do not claim the same pattern is product-documented for every engine. For
non-SQL Server targets, direct-to-Splunk remains the production default unless
Splunk Support approves a gateway design. Secure any non-loopback listener with
network policy and TLS; never expose unauthenticated OTLP/HTTP broadly.

## Sizing gates

- Cap one collector instance at 30 database targets. Split larger estates into
  multiple independently sized collectors.
- For any collector monitoring SQL Server, allocate at least `2048 MiB` to the
  collector. Splunk tested up to 30 SQL Server targets on an `m5.large`-class
  host (2 vCPU, 8 GB RAM) and calls out the 2048 MiB collector minimum.
- For an Oracle-only collector, allocate at least `512 MiB`; Splunk's test host
  was also `m5.large` class. A mixed SQL Server/Oracle collector uses the higher
  `2048 MiB` gate.
- Every packet must set explicit collector CPU/memory. SQL Server and Oracle
  should start from the published 2-vCPU host guidance while distinguishing
  host capacity from the collector memory limit.
- Splunk's published performance page does not provide equivalent sizing tests
  for PostgreSQL, MySQL, or MariaDB. Record that gap, benchmark representative
  workloads, and do not extrapolate the SQL/Oracle test result as a support
  guarantee.
- Keep the production receiver sample interval fixed at `10s`. The advanced
  top-query interval defaults to `60s` and may change only within enforced
  bounds after a measured capacity review.

## Realm and entitlement checks

Database Monitoring is listed in `us0`, `us1`, `eu0`, `eu1`, `eu2`, `au0`,
`jp0`, and `sg0`. It is not listed for `us2`. Fail closed on unknown or
unlisted realms rather than sending DBMon events and hoping the product is
enabled.

A Database Monitoring subscription is required for the full product. Without
the entitlement, a database can still appear in Infrastructure Monitoring but
the DBMon navigator is incomplete. If only the three query-oriented tabs are
visible, also verify the `metrics/dbmon` pipeline; Splunk documents a broken
metrics path as another cause of partial navigation.

## Product and feature completion gate

Collector startup is not completion. The rendered coverage artifact,
validation plan, and product runbook separate configuration from observed
product behavior.

| Surface | Required evidence |
|---|---|
| Collector | Pinned-binary configuration validation passes; service/pod is healthy; recent logs have no receiver auth, required-system-view permission, connection, export, throttle, or duplicate-scrape failures. PostgreSQL per-statement best-effort EXPLAIN denials are recorded separately and do not make the receiver unhealthy. |
| Infrastructure Monitoring | Every target appears under Infrastructure > Datastores with stable instance identity and expected infrastructure metrics. |
| DBMon Overview | Every network DBMon target appears under APM > Database monitoring > Overview; Windows Performance Counter targets are infrastructure-metrics-only. |
| Navigator | Queries, Query samples, Query metrics, Dependencies, and Metadata are validated only when the target's rendered event controls enable them; disabled surfaces are recorded as not applicable. |
| Query analysis | Normalized statements, execution/duration/CPU/wait-state data, query samples, and eligible explain plans are visible. SQL Server and Oracle also require a stored-procedure review when used. |
| Alerts | The instance navigator exposes associated alerts; custom detector creation is handed to `splunk-observability-native-ops`. |
| APM correlation | For an explicitly supported language/engine pair, a sampled query links to a trace and the trace links back to normalized query details. |
| AI query help | When licensed and enabled by Splunk Support, the Query statement flyout can summarize a normalized query and generate recommendations. Record `ui_handoff_required` until a human verifies it. |

Query samples are collected every 10 seconds by default. Correlation exists
only for sampled queries, so a missing link on an arbitrary trace is not by
itself a failure. Validate with a known test transaction that runs long/often
enough to be sampled.

### Published APM correlation matrix

| Application instrumentation | Database | Minimum app agent | Minimum collector |
|---|---|---|---|
| Splunk OTel .NET | Microsoft SQL Server | `v1.11.0` | `v0.148.0` |
| Splunk OTel Java JDBC | Microsoft SQL Server | `v2.20.1` | `v0.148.0` |
| Splunk OTel Java JDBC | MySQL | `v2.26.1` | `v0.154.0` |
| Splunk OTel Java JDBC | Oracle Database | `v2.20.1` | `v0.148.0` |
| Splunk OTel Java JDBC | PostgreSQL | `v2.22.0` | `v0.147.0` |

Application-side propagation is a separate mutation and requires its own
approval. Java requires
`OTEL_INSTRUMENTATION_SPLUNK_JDBC_ENABLED=true`. SQL Server adds a
`SET context_info` round trip, Oracle uses `V$SESSION.ACTION`, PostgreSQL sets
`application_name` once per session, and MySQL uses a lowercase
`@traceparent` user variable. The skill renders a handoff; it does not silently
change an application runtime.

The DBMon query AI Assistant is distinct from the general Observability AI
Assistant. The query feature is UI-only and must be activated through Splunk
Support. Do not represent a collector or API validation as AI enablement.

## Credential and mutation guardrails

- Accept the tenant API token for `--api` only through
  `SPLUNK_O11Y_TOKEN_FILE`. Accept a Linux collector ingest token only as
  `SPLUNK_ACCESS_TOKEN` inside the private file passed through
  `--db-credentials-env-file`; Kubernetes reuses the installed chart Secret,
  and Windows/gateways use their owning runtime secret workflow. Require every
  token file to be a non-symlink, single-link, owner-only regular file (for
  example mode `0400` or `0600`), with
  nonempty content and no newline/NUL/whitespace in a token value. Never put a
  token in argv, collector YAML, metadata, logs, or a generated template.
- Reference database usernames/passwords through existing Kubernetes Secret
  keys or named Linux/Windows environment variables. Render names and
  placeholders only; never render values.
- Reject inline password, token, datasource, connection-string, in-memory PEM,
  private-key, and client-secret fields recursively, including `--flag=value`
  forms.
- Apply and rollback are separate, explicit operations. Render, static
  validation, live read-only validation, API validation, and collector config
  validation do not authorize mutation.
- Kubernetes apply mutates only the named owned Helm release. Linux apply
  mutates only the reviewed collector files/service after backup. Windows is a
  manual handoff. Database grants, managed-service parameter groups, database
  restarts, application instrumentation, entitlement changes, AI activation,
  dashboards, and detectors are never silently applied.
- Redact usernames, endpoints containing credentials, query text, database
  names, and tokens from evidence where organizational policy requires it.
  Query samples can contain sensitive business data even when normalized
  queries do not.

## Validation layers

1. Static asset validation checks YAML, exact pipeline/exporter IDs (including
   deterministic mixed-family suffixes), endpoint, headers, event enablement,
   target support, provider/version pairings, version floors, target count,
   memory gates, singleton placement, Secret/env references, platform outputs,
   and absence of secret values.
2. Collector validation loads the rendered config with the pinned
   `quay.io/signalfx/splunk-otel-collector:0.155.0` image through Docker or
   Podman and proves that the distribution contains the named receivers,
   processors, and `otlp_http` exporter. Never substitute `latest`. YAML
   parsing alone is not enough.
3. `--live` runtime validation is a read-only, release/namespace-scoped
   Kubernetes check bound to `collector.kube_context`. It requires one desired
   replica and exactly one ready `0.155.0` cluster-receiver pod, then scans
   recent exact DBMon component logs for critical failures. Raw log lines are
   suppressed because driver errors can contain DSNs or query text; the helper
   reports scoped counts/categories instead. Only the two upstream PostgreSQL
   best-effort per-statement EXPLAIN messages are excluded from the fatal
   scan; broader permission or query failures still fail validation. Linux and
   Windows use their rendered platform status/action handoff instead of
   `--live`.
4. Observability API validation reads a token from
   `SPLUNK_O11Y_TOKEN_FILE`, checks each target's metric in the metric catalog,
   and requires positive data from a SignalFlow query with that target's
   rendered identity filters. Global `--api-filter KEY=VALUE` entries may only
   add nonconflicting constraints. Ad-hoc `--api-metric` probes require an
   explicit filter and never replace the default per-target proof. The token
   is never passed on the command line and filter values are redacted in
   output/errors.

The API token must have API permission. Splunk's SignalFlow `POST /execute`
reference requires an admin or power role; use the least-privileged token that
satisfies that documented requirement and revoke/rotate it under normal token
policy.
5. Product validation follows the completion table above and records each
   surface as `verified`, `failed`, `not_applicable`, or
   `ui_handoff_required`. A metric API success does not prove query events,
   explain plans, APM correlation, or AI features.

## Official source URLs

Product and collection:

- DBMon introduction: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/introduction-to-splunk-database-monitoring>
- Architecture and deployment options: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/get-data-in/architecture-and-deployment-options>
- Performance overhead and sizing: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/get-data-in/performance-overhead>
- Microsoft SQL Server receiver: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/get-data-in/configure-receivers/microsoft-sql-server-receiver>
- MySQL and MariaDB DBMon receiver/product support (MySQL 5.7+, MariaDB 10.5+, AWS RDS and standalone; Collector 0.154.0+): <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/get-data-in/configure-receivers/mysql-receiver>
- Oracle Database receiver: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/get-data-in/configure-receivers/oracle-database-receiver>
- AWS RDS Oracle SYS-object grants: <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.Oracle.CommonDBATasks.TransferPrivileges.html>
- Upstream Oracle receiver at `v0.155.0`: <https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.155.0/receiver/oracledbreceiver/README.md>
- PostgreSQL receiver: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/get-data-in/configure-receivers/postgresql-receiver>
- Gateway best practices: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/get-data-in/best-practices-for-configuring-gateway-opentelemetry-collectors>
- Collection troubleshooting: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/get-data-in/troubleshoot-data-collection>

Product UI, APM, and AI:

- Monitor database instances: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/monitor-database-platform-instances>
- Queries and query details: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/monitor-database-platform-instances/queries>
- Query samples: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/monitor-database-platform-instances/query-samples>
- Query metrics: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/monitor-database-platform-instances/query-metrics>
- Dependencies: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/monitor-database-platform-instances/dependencies>
- Metadata: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/monitor-database-platform-instances/metadata>
- DBMon query AI Assistant: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/monitor-database-platform-instances/ai-assistant>
- APM query correlation matrix: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/correlate-database-queries-with-splunk-apm-traces>
- Java query correlation: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/correlate-database-queries-with-splunk-apm-traces/correlate-database-queries-with-java-traces>
- .NET query correlation: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/correlate-database-queries-with-splunk-apm-traces/correlate-database-queries-with-.net-traces>
- APM service-map database dependencies: <https://help.splunk.com/en/splunk-observability-cloud/monitor-application-performance/manage-services-spans-and-traces-in-splunk-apm/view-dependencies-in-the-service-map>
- Metrics metadata API: <https://dev.splunk.com/observability/reference/api/metrics_metadata/latest>
- SignalFlow API: <https://dev.splunk.com/observability/reference/api/signalflow/latest>

Release and component provenance:

- Splunk OTel Collector `v0.155.0`: <https://github.com/signalfx/splunk-otel-collector/releases/tag/v0.155.0>
- Splunk OTel Collector chart `0.155.0`: <https://github.com/signalfx/splunk-otel-collector-chart/releases/tag/splunk-otel-collector-0.155.0>
- Upstream MySQL receiver compatibility at `v0.155.0`: <https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.155.0/receiver/mysqlreceiver/README.md>
- Realm/component availability: <https://help.splunk.com/en/splunk-observability-cloud/get-started/service-description/splunk-observability-cloud-service-description>
- Splunk OTel Collector repository: <https://github.com/signalfx/splunk-otel-collector>
- Splunk OTel Collector chart repository: <https://github.com/signalfx/splunk-otel-collector-chart>

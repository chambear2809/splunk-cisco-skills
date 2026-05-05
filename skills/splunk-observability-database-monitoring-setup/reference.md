# Splunk Observability Database Monitoring Reference

This skill follows Splunk's Database Monitoring collection pages for Microsoft
SQL Server, Oracle Database, and PostgreSQL, plus the Splunk OTel Collector and
Helm chart repositories.

## Official Support Matrix

| Target | Versions | Platforms | Collector floor |
|---|---|---|---|
| Microsoft SQL Server | 2016, 2017, 2019, 2022 | Azure Managed Instance, Azure SQL Database, AWS RDS, self-hosted | v0.148.0 |
| Oracle Database | 19c, 26ai | AWS RDS, Oracle RAC, self-hosted | v0.148.0 |
| PostgreSQL | Azure Flexible Server 14.20 / 17.7, Amazon RDS 14.15 / 17.5 | Azure Flexible Server, AWS RDS | v0.147.0 |

MySQL is excluded from v1. The upstream receiver has query-event support, but
Splunk does not publish a DBMon MySQL collection page and its MySQL integration
docs are deprecated/end-of-support.

## Unsupported Lab Target Opt-In

By default, the renderer rejects targets outside the official support matrix.
For labs and demos, pass `--allow-unsupported-targets` or set
`allow_unsupported_targets: true` in the spec. This keeps all receiver, secret,
pipeline, realm, and collector-version-floor validation, but renders supported
receiver types even when their declared platform/version is outside Splunk's
published DBMon matrix.

Example: a self-hosted PostgreSQL 16 demo is outside Splunk DBMon's published
PostgreSQL matrix, but the Splunk PostgreSQL OTel receiver documentation states
that the receiver itself supports PostgreSQL 9.6 and higher. In that case, the
skill can render the collector configuration as `unsupported_opt_in` and records
the support gap in `metadata.json`.

MySQL/MariaDB remain excluded even in unsupported-target mode.

## Required DBMon Collector Shape

- Database receivers are added to the metrics pipeline for infrastructure
  metrics.
- Query sample and top query events are emitted as logs through `logs/dbmon`.
- `logs/dbmon` exports through `otlphttp/dbmon`.
- The DBMon event endpoint is
  `https://ingest.<realm>.observability.splunkcloud.com/v3/event`.
- The exporter must set `X-splunk-instrumentation-library: dbmon`.
- The metrics and `logs/dbmon` pipelines must use identical processors in the
  same order.

## Kubernetes Placement

External database receivers must run under the Splunk OTel chart
`clusterReceiver` Deployment with `replicas: 1`. Do not place them under
`agent`, because the DaemonSet would scrape each database once per node and
produce duplicate metrics/events.

## Realm Availability

Splunk Database Monitoring is available in these Observability realms:

`us0`, `us1`, `eu0`, `eu1`, `eu2`, `au0`, `jp0`, `sg0`

The skill rejects `us2` and any unknown realm until Splunk lists DBMon
availability there.

## Credential Handling

Use only file/env/Secret references:

- Kubernetes: `credentials.kubernetes_secret` points to an existing Secret.
- Linux: `credentials.linux_env` names env vars to populate outside the repo.
- Observability token: base collector Secret or `SPLUNK_ACCESS_TOKEN` env var.

Never put passwords, datasource strings, access tokens, or API keys in the spec,
conversation, CLI arguments, rendered files, or checked-in docs.

## Read-Only API Validation

`validate.sh --api` adds a tenant-side check after collector validation:

- Metric metadata: `GET https://api.<realm>.observability.splunkcloud.com/v2/metric`
  with `query=name:<metric>`.
- SignalFlow: `POST https://stream.<realm>.signalfx.com/v2/signalflow/execute`
  with a `text/plain` SignalFlow program body.

The default metric is `postgresql.database.count`. When `metadata.json`
contains `cluster_name`, the probe adds a `k8s.cluster.name=<cluster>` filter.
The probe reads `SPLUNK_O11Y_TOKEN_FILE` and sets `X-SF-TOKEN` inside the Python
process, so the token value is not passed as a shell argument.

## Source URLs

- Splunk DBMon overview: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/introduction-to-splunk-database-monitoring>
- SQL Server collection: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/collect-data-from-your-database-platforms/collect-data-from-microsoft-sql-server>
- Oracle collection: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/collect-data-from-your-database-platforms/collect-data-from-oracle-database>
- PostgreSQL collection: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/collect-data-from-your-database-platforms/collect-data-from-postgresql>
- DBMon troubleshooting: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/collect-data-from-your-database-platforms/troubleshoot-data-collection>
- Gateway DBMon routing: <https://help.splunk.com/en/splunk-observability-cloud/monitor-databases/collect-data-from-your-database-platforms/best-practices-for-configuring-gateway-opentelemetry-collectors>
- Realm availability: <https://help.splunk.com/en/splunk-observability-cloud/get-started/service-description/splunk-observability-cloud-service-description>
- Metrics and metadata: <https://help.splunk.com/en?resourceId=metrics-and-metadata_metrics>
- SignalFlow analytics: <https://help.splunk.com/splunk-observability-cloud/signalflow-analytics/analyze-incoming-data-using-signalflow>
- Splunk OTel Collector: <https://github.com/signalfx/splunk-otel-collector>
- Splunk OTel Collector chart: <https://github.com/signalfx/splunk-otel-collector-chart>
- Splunk PostgreSQL receiver: <https://help.splunk.com/en/splunk-observability-cloud/manage-data/available-data-sources/supported-integrations-in-splunk-observability-cloud/opentelemetry-receivers/postgresql-receiver>

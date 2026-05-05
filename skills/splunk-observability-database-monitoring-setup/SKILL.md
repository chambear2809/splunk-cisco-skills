---
name: splunk-observability-database-monitoring-setup
description: Render and validate Splunk Observability Cloud Database Monitoring collector configuration for PostgreSQL, Microsoft SQL Server, and Oracle Database using the Splunk Distribution of OpenTelemetry Collector. Use when a user asks to set up Splunk Database Monitoring, DBMon, database query samples, top query events, or database receiver wiring through the Splunk OTel Collector on Kubernetes or Linux.
---

# Splunk Observability Database Monitoring Setup

Use this skill to render and validate Splunk Database Monitoring (DBMon)
configuration for the Splunk Distribution of OpenTelemetry Collector. This is a
render-first workflow; v1 does not mutate clusters, hosts, or Splunk tenants.

## Supported Targets

v1 supports only the official Splunk Database Monitoring collection pages:

- Microsoft SQL Server: 2016, 2017, 2019, 2022 on Azure Managed Instance,
  Azure SQL Database, AWS RDS, or self-hosted.
- Oracle Database: 19c or 26ai on AWS RDS, Oracle RAC, or self-hosted.
  For RAC, declare one target per node.
- PostgreSQL: Azure Database for PostgreSQL Flexible Server 14.20 or 17.7,
  and Amazon RDS for PostgreSQL 14.15 or 17.5.

MySQL is intentionally out of scope for this skill. The upstream MySQL receiver
has query-event support, but Splunk does not publish a DBMon MySQL collection
page and Splunk's MySQL integration docs remain deprecated/end-of-support.

For lab and demo targets only, `--allow-unsupported-targets` or
`allow_unsupported_targets: true` can render supported receiver types outside
Splunk's published DBMon support matrix, such as a self-hosted PostgreSQL 16
demo. The rendered `metadata.json` marks those targets as
`unsupported_opt_in`. Do not use this mode to claim Splunk-supported production
coverage.

## Safe First Commands

```bash
bash skills/splunk-observability-database-monitoring-setup/scripts/setup.sh --help
```

```bash
bash skills/splunk-observability-database-monitoring-setup/scripts/setup.sh \
  --render --validate \
  --spec skills/splunk-observability-database-monitoring-setup/template.example \
  --output-dir splunk-observability-database-monitoring-rendered
```

```bash
bash skills/splunk-observability-database-monitoring-setup/scripts/validate.sh \
  --output-dir splunk-observability-database-monitoring-rendered \
  --live --live-since 2m
```

```bash
bash skills/splunk-observability-database-monitoring-setup/scripts/validate.sh \
  --output-dir splunk-observability-database-monitoring-rendered \
  --api --api-metric postgresql.database.count
```

## Workflow

1. Copy `template.example` to a local spec and fill in non-secret values only.
2. Reference database credentials by Kubernetes Secret keys and Linux env var
   names. Never put passwords, datasource strings, or tokens in the spec.
3. Render and validate the assets.
4. Review `metadata.json` warnings, including the DBMon license reminder and
   any support-matrix notes.
5. Hand off the rendered collector overlay to
   `splunk-observability-otel-collector-setup`.

## Rendered Output

- `k8s/values.dbmon.clusterreceiver.yaml` - Splunk OTel chart override that
  places DB receivers under `clusterReceiver` with `replicas: 1`.
- `k8s/secrets.dbmon.stub.yaml` - placeholder-only Secret manifests.
- `k8s/handoff-base-collector.sh` - render/merge guidance for the base chart.
- `linux/collector-dbmon.yaml` - collector fragment for Linux hosts.
- `linux/dbmon.env.template` - env var names for DB credentials and the O11y
  token placeholder.
- `linux/handoff-base-collector.sh` - Linux collector handoff guidance.
- `references/gateway-routing.sqlserver.md` - SQL Server gateway-mode pattern.
- `metadata.json` - normalized targets, warnings, and support facts.

## Guardrails

- DBMon realms are allow-listed to `us0`, `us1`, `eu0`, `eu1`, `eu2`, `au0`,
  `jp0`, and `sg0`.
- Collector version floors are enforced: PostgreSQL requires `v0.147.0+`;
  SQL Server and Oracle require `v0.148.0+`.
- Unsupported target opt-in preserves receiver, secret, pipeline, and version
  floor validation but records explicit support warnings.
- `logs/dbmon` must export through `otlphttp/dbmon` to
  `https://ingest.<realm>.observability.splunkcloud.com/v3/event`.
- The `metrics` and `logs/dbmon` pipelines must use identical processors in
  the same order.
- Kubernetes database receivers must run in `clusterReceiver`, never `agent`,
  to avoid duplicate scrapes and inflated usage.
- `validate.sh --live` is read-only. It checks live cluster-receiver pods and
  fails when recent DBMon log lines contain errors, warnings, authentication
  failures, authorization failures, or connection denials.
- `validate.sh --api` is read-only. It uses `SPLUNK_O11Y_TOKEN_FILE` to query
  the Observability metric catalog and execute a SignalFlow computation for a
  DBMon metric in the rendered cluster scope. The token value never appears in
  command-line arguments.

## References

- `reference.md` - official-source notes, support matrix, and troubleshooting.
- `references/gateway-routing.sqlserver.md` - dedicated DBMon event routing
  through a gateway collector.

# Splunk DB Connect Setup Reference

This skill covers Splunk DB Connect 4.2 planning and validation for JDBC
ingestion, enrichment, lookup, and export use cases. It is intentionally
render-first: the scripts produce reviewed assets and helper commands, then
delegate package installation to `splunk-app-install`.

## Audited App Metadata

| Package | Splunkbase ID | App ID | Latest audited version | Latest audited date |
| --- | --- | --- | --- | --- |
| Splunk DB Connect | `2686` | `splunk_app_db_connect` | `4.2.4` | April 20, 2026 |

## Supported JDBC Add-Ons

| Driver add-on | Splunkbase ID | Latest audited version | Notes |
| --- | --- | --- | --- |
| Amazon Redshift JDBC Driver Add-on for Splunk DB Connect | `6149` | `1.2.2` / September 3, 2025 | Splunk-supported add-on |
| Microsoft SQL Server JDBC Driver Add-on for Splunk DB Connect | `6150` | `1.3.2` / August 8, 2025 | Includes SQL Server auth planning, stored procedures, Windows/Kerberos, and Entra notes |
| Oracle JDBC Driver Add-on for Splunk DB Connect | `6151` | `2.2.2` / September 3, 2025 | Wallet and client-certificate planning stays file-based |
| PostgreSQL JDBC Driver Add-on for Splunk DB Connect | `6152` | `1.2.2` / September 3, 2025 | Splunk-supported add-on |
| Snowflake JDBC Driver Add-on for Splunk DB Connect | `6153` | `1.2.4` / March 19, 2026 | Splunk-supported add-on |
| MySQL JDBC Driver Add-on for Splunk DB Connect | `6154` | `1.1.3` / September 3, 2025 | Splunk-supported add-on |
| IBM DB2 JDBC Driver Add-on for Splunk DB Connect | `6332` | `1.1.1` / September 22, 2025 | Splunk-supported add-on |
| MongoDB JDBC Driver Add-on for Splunk DB Connect | `7095` | `1.3.0` / September 3, 2025 | Splunk-supported add-on |
| Amazon Athena JDBC Driver Add-on for Splunk DB Connect | `8133` | `1.0.1` / December 16, 2025 | Splunk-supported add-on |

InfluxDB (`6759`) is tracked only as archived/not-supported driver catalog
metadata. It is not part of normal install coverage.

## Custom Driver Coverage

Manual or custom JDBC-compatible drivers are rendered as review handoffs for:

- Informix
- SAP SQL Anywhere
- Sybase ASE and Sybase IQ
- Hive
- BigQuery
- Databricks
- Unsupported JDBC-compatible databases

For Splunk Cloud, custom drivers are packaged as a separate app skeleton under
`drivers/custom-driver-app/`. The Cloud package layout uses
`lib/dbxdrivers/<driver-name>.jar`, optional
`lib/dbxdrivers/<driver-name>-libs/`, and optional
`default/db_connection_types.conf`; the operator must add the reviewed JAR and
submit through the supported Cloud app workflow.

## Splunk DB Connect 4.2 Feature Coverage

The rendered packet explicitly covers the 4.2 line's HA and driver changes:

- DB Connect `4.2.4` is tracked as the latest audited maintenance release.
- DB Connect `4.2.0` added Databricks as a data source, Java diagnostics,
  multi-line JVM options, better HA checkpoint synchronization, prevention of
  parallel input execution in HA clusters, automatic HA leader re-election,
  table-level filtering search, opening connections from Input/Output/Lookup
  and Query Explorer views, and automatic JDBC driver version retrieval.
- HF HA remains etcd-backed. Plan at least three DB Connect instances and an
  etcd cluster, and keep JDBC add-ons identical because DB Connect HA does not
  replicate driver add-ons.
- Health validation includes Monitoring Console DB Connect checks for
  connection configuration, data lab configuration, JDBC driver installation,
  DBX file permissions, JVM installation, Java server configuration, and
  Kerberos environment.

## Spec Contract

The spec version is `splunk-db-connect-setup/v1`.

Supported sections:

- `platform`
- `topology`
- `install`
- `java`
- `drivers`
- `settings`
- `identities`
- `connections`
- `inputs`
- `outputs`
- `lookups`
- `indexes`
- `hec`
- `cloud_network`
- `ha`
- `security`
- `validation`

Live DBX object mutation is not supported in v1. Rendered `dbx/*.preview`
files are intentionally non-executable review artifacts.

## Guardrails

The renderer refuses:

- Deployment Server distribution
- universal forwarder or indexer DBX install targets
- plaintext secret material
- fake DBX encrypted identity values such as `$7$...`
- Splunk Cloud Classic self-service installs
- archived JDBC driver installs without an explicit archived-driver opt-in
- Java versions other than `17` or `21` for Enterprise/customer-managed
  runtimes
- SHC member targeting without a deployer
- Splunk Cloud Victoria plans without outbound database allowlist entries
- Splunk Cloud Victoria specs that target heavy forwarders directly
- FIPS requests without a fresh manual install plan
- automated app install handoffs for FIPS DB Connect

## Cloud And FIPS Notes

Splunk Cloud Victoria DB Connect runs on Cloud search heads and needs ACS to
open outbound database ports before DBX connections can work. Splunk Cloud
Classic deployments must route through Splunk Support, IDM, or a
customer-managed heavy forwarder.

For Enterprise and customer-managed heavy forwarders, require Java `17` or
`21`. For Splunk Cloud Victoria search heads, the JRE is Splunk-managed; verify
it through DB Connect setup or Configuration > Settings > General and file a
support ticket for Cloud JRE issues.

FIPS DB Connect requires a fresh manual install path, `fipsEnabled: true` for
the task and dbxquery servers or `SPLUNK_DBX_FIPS_ENABLED=true`, and PKCS12
keystore/truststore handling. The automated install handoff is blocked when
`security.fips_mode` is true.

## Validation Assets

Rendered validation assets include:

- `preflight.sh` for local Java, file permission, and app-layout checks
- `validation/rest-checks.sh` for read-only REST probes
- `validation/btool-checks.sh` for DBX configuration inspection
- `validation/validation.spl` for DBX health, input, and data-path searches
- `topology/shc-deployer.md` for SHC deployment sequencing
- `topology/hf-ha-etcd-plan.md` for HF HA and etcd planning
- `operations/upgrade-backup-health.md` for health, backup/restore, upgrade,
  downgrade, and migration notes
- `operations/federated-search.md` for DB Connect over Federated Search saved
  search handoffs
- `security/auth-handoffs.md` for SQL Server auth, Kerberos, Entra, CyberArk,
  and Vault planning
- `security/fips-plan.md` and `security/client-cert-plan.md` for FIPS and
  `requireClientCert=true` planning
- `troubleshooting/runbook.md` for Java, driver, KV Store, auth, TLS, and
  scheduler triage

## Source Anchors

- Splunkbase DB Connect app `2686`
- DB Connect 4.2 system requirements
- DB Connect 4.2 distributed deployment guidance
- DB Connect 4.2 database driver installation guidance
- DB Connect 4.2 Splunk Cloud custom JDBC driver packaging guidance
- DB Connect 4.2 heavy forwarder high availability guidance
- DB Connect 4.2 release notes

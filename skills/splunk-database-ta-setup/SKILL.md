---
name: splunk-database-ta-setup
description: >-
  Render, install, and validate package-verified Splunk Supported Add-ons for
  Microsoft SQL Server, MySQL, and Oracle Database. Uses extracted Splunkbase
  packages as source of truth for app IDs, versions, source types, DB Connect
  handoffs, SQL Server file/perfmon inputs, and validation searches. Use when
  the user asks to onboard SQL Server, MySQL, Oracle Database, database logs, or
  supported database TA readiness in Splunk.
---

# Database Supported Add-ons Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first workflow for verified database add-ons:

- `Splunk_TA_microsoft-sqlserver` `3.1.0`, Splunkbase `2648`
- `Splunk_TA_mysql` `3.2.0`, Splunkbase `2848`
- `Splunk_TA_oracle` `4.2.0`, Splunkbase `1910`

## Workflow

```bash
bash skills/splunk-database-ta-setup/scripts/setup.sh --phase render \
  --products mssql,mysql,oracle --index database
```

Review the rendered DB Connect handoff, SQL Server host input overlay, install
commands, and validation SPL.

```bash
bash skills/splunk-database-ta-setup/scripts/setup.sh --install \
  --products mssql,mysql,oracle --no-restart
```

```bash
bash skills/splunk-database-ta-setup/scripts/validate.sh --index database
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack mssql_database,mysql_database,oracle_database
```

Secrets stay in DB Connect identities, add-on account storage, or protected
local secret files. This skill never accepts database credentials as flags.

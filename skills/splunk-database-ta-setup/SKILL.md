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

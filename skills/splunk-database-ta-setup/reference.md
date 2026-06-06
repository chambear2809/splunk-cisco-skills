# Database Supported Add-ons Reference

Package source of truth:

| Product | App | Splunkbase | Verified |
| --- | --- | --- | --- |
| Microsoft SQL Server | `Splunk_TA_microsoft-sqlserver` | `2648` | `3.1.0` |
| MySQL | `Splunk_TA_mysql` | `2848` | `3.2.0` |
| Oracle Database | `Splunk_TA_oracle` | `1910` | `4.2.0` |

## Package-Derived Source Types

SQL Server source types include `mssql:errorlog`, `mssql:agentlog`,
`mssql:audit`, `mssql:instance`, `mssql:os:dm_os_sys_info`,
`mssql:execution:dm_exec_sessions`,
`mssql:execution:dm_exec_query_stats`, and
`mssql:transaction:dm_tran_locks`.

MySQL source types include `mysql:errorLog`, `mysql:generalQueryLog`,
`mysql:slowQueryLog`, `mysql:audit`, `mysql:status`, `mysql:variables`,
`mysql:instance:stats`, and `mysql:connection:stats`.

Oracle source types include `oracle:audit:unified`, `oracle:audit:text`,
`oracle:audit:xml`, `oracle:listener:text`, `oracle:alert:text`,
`oracle:database`, `oracle:instance`, `oracle:session`, `oracle:sysPerf`,
and `oracle:query`.

## Guardrails

- Use `splunk-db-connect-setup` for JDBC identities, connection validation,
  inputs, and output ownership.
- SQL Server package host inputs include ERRORLOG, SQLAGENT.OUT, and Perfmon
  stanzas. Deploy those only to reviewed Windows collection owners.
- Do not pass database usernames, passwords, wallet passwords, private keys, or
  tokens as command-line arguments.
- Use the readiness doctor source packs `mssql_database`, `mysql_database`, and
  `oracle_database` after ingestion starts.

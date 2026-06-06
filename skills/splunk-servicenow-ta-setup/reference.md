# Splunk Add-on for ServiceNow Reference

Grounded in the `Splunk_TA_snow` package (Splunkbase app `1928`, verified
version `10.0.1`).

## Package Model

- App / package id: `Splunk_TA_snow`
- Splunkbase ID: `1928`
- Modular input: `snow://<table>` (one stanza per ServiceNow table). The package
  ships defaults for `incident`, `problem`, `em_event`, `change_request`,
  `change_task`, `sys_user`, `sys_user_group`, `cmn_location`, `cmdb`,
  `cmdb_ci`, `cmdb_ci_server`, `cmdb_ci_vm`, `cmdb_ci_app_server`, `sys_choice`,
  `sysevent`, and more.
- Input fields (`inputs.conf.spec`): `account`, `table`, `interval`,
  `timefield` (default `sys_updated_on`), `id_field` (default `sys_id`),
  `since_when`, `include`, `exclude`, `filter_data`, `delay`, `reuse_checkpoint`.
- Account endpoints (`restmap.conf`): `splunk_ta_snow_account` and
  `splunk_ta_snow_oauth`.

## Source Types

Each `snow://<table>` input emits `snow:<table>` (for example `snow:incident`,
`snow:change_request`, `snow:problem`, `snow:em_event`, `snow:sys_user`,
`snow:cmdb_ci`).

## Account Model

Account fields (`splunk_ta_snow_account.conf.spec`): `url`
(`https://yourinstance.service-now.com`), `username`, `password` (basic), and
for OAuth `auth_type`, `client_id`, `client_secret`, `access_token`,
`refresh_token`, `record_count`.

- **Basic auth:** dedicated read-only integration user; password stored encrypted.
- **OAuth:** register an OAuth app in ServiceNow (Application Registry); the
  add-on manages access/refresh tokens.

## Checkpointing

The add-on checkpoints on `timefield` (default `sys_updated_on`) and dedups on
`id_field` (default `sys_id`). Use `since_when` for an initial backfill window
and `filter_data` / `include` / `exclude` to scope columns and rows.

## Index Model

| Index | Purpose | Default |
| --- | --- | --- |
| Event index | ServiceNow table records | `snow` |

## Placement Guardrails

- Install on all search heads where ServiceNow knowledge management is required.
- Run each `snow://<table>` input on a single node (search tier or one heavy
  forwarder) to avoid duplicate ingestion.
- Not Universal-Forwarder or indexer scoped.
- Use a read-only ServiceNow integration user scoped to the collected tables.
- Store the password / OAuth secret only via the add-on account (encrypted);
  never in conf files or argv.

## Handoffs

- `splunk-app-install` installs the package from Splunkbase (`1928`).
- `splunk-itsi-config` consumes incident/change data for service and KPI
  modeling.

## Sources

- https://splunkbase.splunk.com/app/1928
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/servicenow

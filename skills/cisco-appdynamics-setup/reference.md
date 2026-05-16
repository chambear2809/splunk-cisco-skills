# Cisco AppDynamics Add-on Reference

Reference for the `Splunk_TA_AppDynamics` package. Install from Splunkbase ID
`3471` first so users get the latest compatible release; use local
`cisco-splunk-add-on-for-appdynamics_*.tar.gz` archives only as a fallback.

## Controller Connection Fields

Configured through `Splunk_TA_AppDynamics_account`:

| Field | Required | Encrypted | Description |
|-------|----------|-----------|-------------|
| `name` | Yes | No | Connection stanza name |
| `appd_controller_url` | Yes | No | AppDynamics controller URL |
| `appd_client_name` | Yes | No | AppDynamics API client name |
| `appd_client_secret` | Yes | Yes | AppDynamics API client secret |
| `authentication` | Yes | No | `oauth` |

REST endpoints:

- `GET/POST /servicesNS/nobody/Splunk_TA_AppDynamics/Splunk_TA_AppDynamics_account`
- `GET/POST/DELETE /servicesNS/nobody/Splunk_TA_AppDynamics/Splunk_TA_AppDynamics_account/<name>`

## Analytics Connection Fields

Configured through `Splunk_TA_AppDynamics_analytics_account`:

| Field | Required | Encrypted | Description |
|-------|----------|-----------|-------------|
| `name` | Yes | No | Analytics connection stanza name |
| `appd_analytics_account_name` | Yes | No | AppDynamics global account name |
| `appd_analytics_endpoint` | Yes | No | SaaS analytics endpoint, or `None` for on-prem |
| `appd_onprem_analytics_url` | No | No | On-prem analytics URL when endpoint is `None` |
| `appd_analytics_secret` | Yes | Yes | Analytics API secret |

Supported SaaS analytics endpoints:

- `https://analytics.api.appdynamics.com`
- `https://gru-ana-api.saas.appdynamics.com`
- `https://azure-ana-api.saas.appdynamics.com`
- `https://fra-ana-api.saas.appdynamics.com`
- `https://lon-ana-api.saas.appdynamics.com`
- `https://bom-ana-api.saas.appdynamics.com`
- `https://sin-ana-api.saas.appdynamics.com`
- `https://syd-ana-api.saas.appdynamics.com`

REST endpoints:

- `GET/POST /servicesNS/nobody/Splunk_TA_AppDynamics/Splunk_TA_AppDynamics_analytics_account`
- `GET/POST/DELETE /servicesNS/nobody/Splunk_TA_AppDynamics/Splunk_TA_AppDynamics_analytics_account/<name>`

## Settings

Configured in `splunk_ta_appdynamics_settings.conf`:

### `additional_parameters`

| Setting | Default | Description |
|---------|---------|-------------|
| `index` | `appdynamics` | Default index for inputs |
| `timeout` | `15` | Request timeout |
| `max_workers` | `25` | Thread pool size |
| `verify_ssl` | `True` | Vendor default SSL verification behavior |

### `logging`

| Setting | Default | Description |
|---------|---------|-------------|
| `loglevel` | `INFO` | Add-on log level |

### `proxy`

| Setting | Description |
|---------|-------------|
| `proxy_enabled` | Enable proxy |
| `proxy_type` | `http`, `https`, `socks4`, `socks5` |
| `proxy_url` | Proxy host |
| `proxy_port` | Proxy port |
| `proxy_username` | Proxy username |
| `proxy_password` | Proxy password |
| `proxy_rdns` | Proxy reverse DNS behavior |

## Input Types

### High Level Status

Input type: `appdynamics_status`

Default values:

- `interval=300`
- `duration=5`
- `application_list=` blank means all active APM apps
- `metrics_to_collect=` dynamic status categories

Recommended script default:

`Application Status~Business Transactions~Tier Node Status~Remote Services Status~Database Status~Server Status~Application Security Status~Web User Experience~Mobile User Experience`

### Database Metrics

Input type: `appdynamics_database_metrics`

Default values:

- `interval=300`
- `duration=5`
- `database_list=` blank means all available databases
- `metrics_to_collect=custom_metrics~hardware~kpi~performance~server_stats`
- `collect_baselines_radio=default`
- `compress_data_flag=true`

### Hardware Metrics

Input type: `appdynamics_hardware_metrics`

Default values:

- `interval=300`
- `duration=5`
- `application_list=` blank means all active APM apps
- `metrics_to_collect=cpu~disk~memory~network~system`
- `tiernode_radio=tier`
- `collect_baselines_radio=default`
- `compress_data_flag=true`

### Application Snapshots

Input type: `appdynamics_application_snapshots`

Default values:

- `interval=300`
- `duration=5`
- `application_list=` blank means all active APM apps
- `metrics_to_collect=SLOW~VERY_SLOW~STALL~ERROR~NORMAL`
- `need_props=true`
- `need_exit_calls=true`
- `first_in_chain=false`
- `archived=false`
- `execution_time_in_milis=0`

### Analytics Search

Input type: `appdynamics_analytics_api`

Required fields:

- `analytics_account`
- `query`

Defaults:

- `global_account=N/A (Analytics)`
- `interval=300`
- `duration=5`
- `source_entry=appdynamics_analytics`

### Secure Application Data

Input type: `appdynamics_security`

Default values:

- `interval=300`
- `duration=5`
- `application_list=` blank means all active security apps
- `metrics_to_collect=attack_counts~business_risk~vulnerabilities`

### Events Data

Input type: `appdynamics_events_policy`

Default values:

- `interval=300`
- `duration=5`
- `application_list=` blank means all discovered applications

Default selected event filters in the shipped UI:

`POLICY_OPEN_WARNING~POLICY_OPEN_CRITICAL~ANOMALY_OPEN_WARNING~ANOMALY_OPEN_CRITICAL~SLOW~VERY_SLOW~STALL~BUSINESS_ERROR`

### Custom Metrics

Input type: `appdynamics_custom_metrics`

Required fields:

- `metrics_to_collect` (comma-separated metric paths)
- `source_entry`
- `source_type_entry`

Behavior notes:

- The add-on can default to all active applications when `application_list` is blank.
- Default custom source name: `appdynamics_custom_metric`
- Default custom source type: `appdynamics_custom_data`

### Controller Audit Logs

Input type: `appdynamics_audit`

Default values:

- `interval=300`
- `duration=5`

### Controller License Usage

Input type: `appdynamics_licenses`

Default values:

- `interval=3600`
- `duration=1440`

## Sourcetypes

Built-in sourcetypes defined by the package:

| Sourcetype | Purpose |
|------------|---------|
| `appdynamics_status` | High-level status entities |
| `appdynamics_databases` | Database metrics |
| `appdynamics_hardware` | Hardware metrics |
| `appdynamics_snapshots` | Business transaction snapshots |
| `appdynamics_analytics` | Analytics search results |
| `appdynamics_security` | Secure Application data |
| `appdynamics_events` | AppDynamics events |
| `appdynamics_audit` | Controller audit logs |
| `appdynamics_licenses` | License usage data |
| `appdynamics_custom_data` | Default custom metrics sourcetype |

## Eventtypes

Representative eventtypes shipped with the add-on:

- `application_performance`
- `business_transactions`
- `infrastructure_performance`
- `application_events`
- `healthrule_violations`
- `application_security_status`
- `database_status`
- `application_tier_status`
- `application_node_status`
- `hardware_metrics`
- `database_metrics`
- `secureapp_data`
- `application_snapshots`
- `appdynamics_audit`
- `appdynamics_licenses`

## Dashboards and Views

Built-in navigation views:

| View | Label |
|------|-------|
| `inputs` | Inputs |
| `configuration` | Configuration |
| `dashboard` | Monitoring Dashboard |
| `ingestion_statistics` | Ingestion Statistics |
| `status` | High Level Status |
| `events` | AppDynamics Events |
| `license_usage` | License Usage |
| `audit_log` | Controller Audit Log |
| `troubleshooting` | TA Logs & Troubleshooting |

All shipped dashboard forms use an inline `index_token` text field with default
value `appdynamics`. There is no macro indirection for the index.

## Package Identity

| Item | Value |
|------|-------|
| App name | `Splunk_TA_AppDynamics` |
| Package label | Cisco Splunk Add-on for AppDynamics |
| Latest verified Splunkbase version | `3.2.1` |
| Local fallback archive pattern | `cisco-splunk-add-on-for-appdynamics_*.tar.gz` |
| Splunkbase ID | `3471` |

## Optional Follow-on Content

If the user wants service modeling in ITSI or ITE Work, the supported follow-on
path is the **Content Pack for Splunk AppDynamics**. That is separate from this
skill and depends on ITSI/ITE Work plus the Splunk App for Content Packs.

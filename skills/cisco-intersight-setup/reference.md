# Cisco Intersight TA — Input Reference

Complete catalog of all data inputs, account fields, sourcetypes, and sizing.

## Account Configuration

Single account type: Intersight (OAuth2).

REST endpoint: `/servicesNS/nobody/Splunk_TA_Cisco_Intersight/Splunk_TA_Cisco_Intersight_account`

### Account Fields

| Field | Description | Required |
|---|---|---|
| `name` | Account stanza name (e.g., `CVF_Intersight`) | Yes |
| `intersight_hostname` | Intersight FQDN (`intersight.com` for SaaS, custom for on-prem) | Yes |
| `client_id` | OAuth2 Client ID from Intersight API Keys | Yes |
| `client_secret` | OAuth2 Client Secret (encrypted by REST handler) | Yes |
| `create_default_inputs` | Create default inputs on account creation (`0`/`1`) | No |
| `intersight_account_moid` | Auto-populated Intersight account MOID | Auto |
| `intersight_account_name` | Auto-populated Intersight account display name | Auto |
| `valid_until` | API key expiration date | Auto |

## Audit & Alarms Inputs

Input type: `audit_alarms`

| Input Stanza | Content | Default Interval |
|---|---|---|
| `audit_alarms://<name>_audit_logs` | Audit records (login, logout, CRUD) | 900s |
| `audit_alarms://<name>_alarms` | Active and historical alarms | 900s |

### Audit & Alarms Input Fields

| Field | Description | Default |
|---|---|---|
| `global_account` | Intersight account name | (required) |
| `index` | Target index | `intersight` |
| `interval` | Collection interval (300–3600s) | 900 |
| `date_input` | Lookback period in days (0/7/30/180) | 7 |
| `enable_aaa_audit_records` | Collect audit records | 1 |
| `enable_alarms` | Collect alarms | 1 |
| `acknowledge` | Include acknowledged alarms | 1 |
| `suppressed` | Include suppressed alarms | 1 |
| `info_alarms` | Include informational alarms | 1 |

### Audit & Alarms Sourcetypes

| Sourcetype | Content |
|---|---|
| `cisco:intersight:auditrecords` | Login, logout, create, modify, delete, permission changes |
| `cisco:intersight:alarms` | Active/historical alarms with severity and affected objects |

## Inventory Inputs

Input type: `inventory`

| Input Stanza | Content | Default Interval |
|---|---|---|
| `inventory://<name>_intersight_inventory` | Core inventory (compute, network, fabric, targets, contracts, licenses, advisories) | 1800s |
| `inventory://<name>_intersight_ports_and_interfaces_inventory` | Port and interface inventory | 1800s |
| `inventory://<name>_intersight_pools_inventory` | Resource pool inventory | 1800s |

### Inventory Categories

| Category Value | What It Collects |
|---|---|
| `compute` | Physical servers (blades, rack units), boards, processors, memory, storage |
| `network` | Fabric Interconnects, network elements, supervisor cards |
| `fabric` | Server/chassis/switch profiles, cluster profiles |
| `target` | Connected targets and claimed devices |
| `contract` | Device contract and warranty information |
| `license` | License entitlements and account license data |
| `advisories` | Security advisories (PSIRTs), advisory instances and definitions |
| `ports` | Ethernet/FC host ports, network ports, physical ports, port channels, VFCs, vEthernets |
| `pools` | FC, IP, IQN, MAC, UUID, resource pools, rack unit identities, fabric element identities |

### Inventory Input Fields

| Field | Description | Default |
|---|---|---|
| `global_account` | Intersight account name | (required) |
| `index` | Target index | `intersight` |
| `interval` | Collection interval (900–86400s) | 1800 |
| `inventory` | Comma-separated category list | (varies) |

### Inventory Sub-Options (enable flags)

Each inventory category has granular enable flags. Key ones:

| Flag | Category | Object |
|---|---|---|
| `enable_compute_bladeidentities` | compute | Blade identities |
| `enable_server_profiles` | fabric | Server profiles |
| `enable_chassis_profiles` | fabric | Chassis profiles |
| `enable_switch_cluster_profiles` | fabric | Switch cluster profiles |
| `enable_processorunits` | compute | Processor units |
| `enable_memoryunits` | compute | Memory units |
| `enable_storage_virtualdrives` | compute | Virtual drives |
| `enable_storage_physicaldisks` | compute | Physical disks |
| `enable_hclstatuses` | compute | HCL compliance status |
| `enable_devicecontractinformations` | contract | Device contracts |
| `enable_security_advisories` | advisories | PSIRTs |
| `enable_advisory_instances` | advisories | Advisory instances per device |
| `enable_ether_hostports` | ports | Ethernet host ports |
| `enable_fc_physicalports` | ports | FC physical ports |
| `enable_fcpool_pools` | pools | FC address pools |
| `enable_ippool_pools` | pools | IP address pools |
| `enable_macpool_pools` | pools | MAC address pools |

### Inventory Sourcetypes

| Sourcetype | Content |
|---|---|
| `cisco:intersight:compute` | Server inventory with model extraction |
| `cisco:intersight:networkelements` | Fabric Interconnects and network devices |
| `cisco:intersight:profiles` | Server/chassis/switch profiles |
| `cisco:intersight:targets` | Connected targets |
| `cisco:intersight:contracts` | Contract and warranty data |
| `cisco:intersight:licenses` | License entitlements |
| `cisco:intersight:advisories` | Security advisories |
| `cisco:intersight:networkobjects` | Network configuration objects |
| `cisco:intersight:pools` | Resource pool status |
| `cisco:intersight:custom:inventory` | Custom API inventory results |

## Metrics Inputs

Input type: `metrics`

| Input Stanza | Metrics Collected | Default Interval |
|---|---|---|
| `metrics://<name>_device_metrics` | temperature, cpu_utilization, memory, host, fan | 900s |
| `metrics://<name>_network_metrics` | network | 900s |

### Metrics Categories

| Metric Value | What It Measures |
|---|---|
| `fan` | Fan speed and status |
| `host` | Host-level power and health |
| `memory` | Memory utilization |
| `network` | Network interface throughput and errors |
| `temperature` | Component temperatures |
| `cpu_utilization` | CPU utilization percentages |

### Metrics Input Fields

| Field | Description | Default |
|---|---|---|
| `global_account` | Intersight account name | (required) |
| `index` | Target index | `intersight` |
| `interval` | Collection interval (900–3600s) | 900 |
| `metrics` | Comma-separated metric list | (varies) |

### Metrics Sourcetypes

| Sourcetype | Content |
|---|---|
| `cisco:intersight:metrics` | All performance metrics with field aliases per source |

Metric-specific field aliases are applied based on `source` value:
- `source::fan` — fan speed fields
- `source::host` — host power fields
- `source::memory` — memory utilization fields
- `source::network` — network throughput fields
- `source::temperature` — temperature fields
- `source::cpu_utilization` — CPU utilization fields

## Custom Inputs

Input type: `custom_input` (up to 10 total)

| Field | Description |
|---|---|
| `global_account` | Intersight account name |
| `index` | Target index |
| `interval` | Collection interval |
| `api_type` | `normal_inventory` or `telemetry` |
| `api_endpoint` | Intersight API endpoint path |
| `filter` | OData filter expression |
| `select` | OData select fields |
| `expand` | OData expand relations |
| `metrics_name` | Metric name (for telemetry) |
| `metrics_type` | Metric type (for telemetry) |
| `groupby` | Group-by field (for telemetry) |

### Custom Sourcetypes

| Sourcetype | Content |
|---|---|
| `cisco:intersight:custom:inventory` | Custom inventory API results |
| `cisco:intersight:custom:metrics` | Custom telemetry API results |

## CIM Mapping

| CIM Data Model | Eventtype | Sourcetype | Events |
|---|---|---|---|
| Alerts | `alerts` | `cisco:intersight:alarms` | All alarms |
| Authentication | `authentication` | `cisco:intersight:auditRecords` | Login, Logout |
| Change | `change` | `cisco:intersight:auditRecords` | Created, Modified, Deleted, Permission changes |
| Performance (Facilities) | `performance_facilities` | `cisco:intersight:metrics` | fan, host, temperature |
| Performance (Memory) | `performance_memory` | `cisco:intersight:metrics` | memory |
| Performance (Network) | `performance_network` | `cisco:intersight:metrics` | network |

## Global Settings

Configured via REST endpoint: `/servicesNS/nobody/Splunk_TA_Cisco_Intersight/Splunk_TA_Cisco_Intersight_settings`

| Setting | Stanza | Default | Description |
|---|---|---|---|
| `proxy_enabled` | `[proxy]` | (empty) | Enable proxy |
| `proxy_type` | `[proxy]` | `http` | Proxy protocol (http/socks5) |
| `proxy_url` | `[proxy]` | (empty) | Proxy hostname |
| `proxy_port` | `[proxy]` | (empty) | Proxy port |
| `loglevel` | `[logging]` | `INFO` | Log level (DEBUG/INFO/WARNING/ERROR/CRITICAL) |
| `ssl_validation` | `[verify_ssl]` | `true` | Validate SSL certificates |
| `collection_type` | `[splunk_rest_host]` | `index` | KVStore collection type |
| `splunk_rest_host_url` | `[splunk_rest_host]` | `localhost` | Splunk REST host for KV lookups |
| `splunk_rest_port` | `[splunk_rest_host]` | `8089` | Splunk REST port |
| `MAX_INPUT_LIMIT` | `[custom_input]` | `10` | Maximum custom inputs allowed |

## Index Sizing Guidelines

| Index | Recommended Max Size | Retention | Notes |
|---|---|---|---|
| `intersight` | 512 GB | 90 days | All Intersight data (audit, inventory, metrics, alarms) |

## KVStore Collections

The TA uses extensive KVStore collections for inventory data used by dashboards:

- Compute: `cisco_intersight_compute_physicalsummaries`, `cisco_intersight_compute_bladeidentities`, `cisco_intersight_compute_rackunitidentities`
- Equipment: `cisco_intersight_equipment_fans`, `cisco_intersight_equipment_fanmodules`, `cisco_intersight_equipment_psus`, `cisco_intersight_equipment_chasses`, `cisco_intersight_equipment_transceivers`, `cisco_intersight_equipment_frus`
- Network: `cisco_intersight_network_elements`, `cisco_intersight_ether_hostports`, `cisco_intersight_ether_networkports`, `cisco_intersight_fc_physicalports`, `cisco_intersight_fc_portchannels`
- Profiles: `cisco_intersight_server_profiles`, `cisco_intersight_chassis_profiles`, `cisco_intersight_fabric_switchclusterprofiles`
- Licensing: `cisco_intersight_license_accountlicensedata`, `cisco_intersight_license_licenseinfos`
- Security: `cisco_intersight_tam_securityadvisories`, `cisco_intersight_tam_advisoryinstances`, `cisco_intersight_cond_hclstatuses`
- Contracts: `cisco_intersight_asset_devicecontractinformations`, `cisco_intersight_asset_targets`
- Pools: `cisco_intersight_fcpool_pools`, `cisco_intersight_ippool_pools`, `cisco_intersight_macpool_pools`, `cisco_intersight_uuidpool_pools`, `cisco_intersight_iqnpool_pools`, `cisco_intersight_resourcepool_pools`

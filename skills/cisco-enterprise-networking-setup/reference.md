# Cisco Enterprise Networking App — Reference

Complete reference for macros, saved searches, dashboards, data model, and lookups.

## Macros

### cisco_catalyst_app_index

Controls which indexes the dashboards search.

| Property | Value |
|---|---|
| Default definition | `index IN ("main")` |
| Recommended | `index IN ("catalyst", "ise", "sdwan", "cybervision")` |
| Description | All indices where Cisco data is stored |
| Location | `local/macros.conf` |

### cisco_catalyst_app_sourcetypes

Controls which sourcetypes the dashboards include.

| Property | Value |
|---|---|
| Default definition | `sourcetype IN ("cisco:ise*", "cisco:sdwan*", "cisco:dnac*", "stream:netflow", "cisco:cybervision:*", "meraki:*", "cisco:ios", "cisco:thousandeyes:test", "cisco:sgacl:logs")` |
| Description | All Cisco sourcetypes |
| Location | `default/macros.conf` (typically no override needed) |

### summariesonly

Controls whether dashboards use accelerated data model summaries.

| Property | Value |
|---|---|
| Default definition | `summariesonly=false` |
| Production | `summariesonly=true` (when data model acceleration is enabled) |

## Saved Searches

| Name | Schedule | Purpose | Lookup Built |
|---|---|---|---|
| `cisco_catalyst_location` | `0 * * * *` (hourly) | Extracts ISE auth/device locations | `cisco_catalyst_ise_location.csv` |
| `cisco_catalyst_sdwan_netflow` | `0 */24 * * *` (daily) | Maps apps to tags for NetFlow | `cisco_catalyst_sdwan_application_tag` (KV Store) |
| `cisco_catalyst_sdwan_policy` | `0 */24 * * *` (daily) | Maps policies to rules for NetFlow | `cisco_catalyst_sdwan_policy_mapping` (KV Store) |
| `cisco_catalyst_meraki_organization_mapping` | `0 */24 * * *` (daily) | Maps Meraki org IDs to names | `meraki_org_id_name_lookup.csv` |
| `cisco_catalyst_meraki_devices_serial_mapping` | `0 */24 * * *` (daily) | Maps Meraki serials to devices | `cisco_catalyst_meraki_device_serial_mapping.csv` |

## Dashboards

| View File | Label | Description |
|---|---|---|
| `overview.xml` | Overview | Cross-product summary: health, issues, authentication |
| `network_insights.xml` | Network Insights | Network health, topology, SD-WAN tunnel status |
| `security_insights.xml` | Security Insights | ISE auth trends, failed auths, policy hits |
| `events_and_incident_viewer.xml` | Events And Incident Viewer | Timeline of security and network events |
| `endpoint.xml` | Endpoints (Clients) | Client health, connectivity, profiling |
| `usersandapplication.xml` | Users And Applications | User activity, application usage, NetFlow |
| `performance.xml` | Performance | Network performance, latency, throughput |
| `sensors.xml` | Sensors | Environmental sensors, device telemetry |
| `cyber_vision_syslog_vulnerability_overview.xml` | Vulnerability Overview | Cyber Vision OT vulnerabilities (drilldown) |

## Data Model

| Property | Value |
|---|---|
| Name | `Cisco_Catalyst_App` |
| Base search | `` `cisco_catalyst_app_index` `cisco_catalyst_app_sourcetypes` `` |
| Acceleration | Disabled by default |
| Objects | 64 search-based objects under `Cisco_Catalyst_Dataset` |

## KV Store Collections

| Collection | Fields | Purpose |
|---|---|---|
| `cisco_catalyst_sdwan_app_tag` | `app`, `app_tag` | NetFlow application tagging |
| `cisco_catalyst_sdwan_policy` | `policy`, `policy_rule` | SD-WAN policy mapping |

## Lookup Files

| Lookup | Type | Source |
|---|---|---|
| `cisco_catalyst_ise_location.csv` | CSV | Built by saved search |
| `meraki_org_id_name_lookup.csv` | CSV | Built by saved search |
| `cisco_catalyst_meraki_device_serial_mapping.csv` | CSV | Built by saved search |
| `cisco_ise_message_catalog_420.csv` | CSV | Shipped with TA |
| `cisco_ise_service.csv` | CSV | Shipped with TA |

## Dependencies

| Dependency | App ID | Required For |
|---|---|---|
| Cisco Catalyst Add-on | `TA_cisco_catalyst` | Data collection (required) |
| Splunk Add-on for Stream | `splunk_app_stream` | NetFlow data (optional) |
| Cisco Catalyst Enhanced Netflow | `splunk_app_stream_ipfix_cisco_hsl` | Enhanced NetFlow (optional) |
| Cisco Meraki Add-on | `Splunk_TA_cisco_meraki` | Meraki data (optional) |
| Cisco ThousandEyes Add-on | `ta_cisco_thousandeyes` | ThousandEyes data (optional) |

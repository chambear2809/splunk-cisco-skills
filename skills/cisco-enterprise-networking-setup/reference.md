# Cisco Enterprise Networking App — Reference

Complete reference for macros, saved searches, dashboards, data model, and lookups.

## Platform Compatibility

- Repo-verified package: `3.2.20`, which is also the current public listing as
  observed August 20, 2026. It was downloaded, unpacked, and inspected here.
- `3.2.20` advertises Splunk `10.5` and is Cloud-compatible, so the default
  install path works on a `10.5` stack with no review override.
- History, because older stacks and older notes still reference it: the previous
  pin `3.1.0` no longer advertises `10.5` in its release record, the `3.2.0`
  release listed versions only through `10.4`, and the intermediate `3.2.10`
  package advertises `10.4`, `10.3`, and `10.2`. Only `3.2.20` and later restore
  `10.5`, so do not downgrade below `3.2.20` on a `10.5` stack.
- The setup wrapper accepts `--target-splunk-version` and `--app-version` and
  defaults the package contract to `3.2.20`. Before any mutation it reads the
  actual installed version, then refuses an unverified package unless
  `--accept-unsupported-platform` is backed by documented vendor approval for
  that exact version and stack.
- This release-level boundary belongs to visualization app `7539`; assess
  companion TA `7538` separately.

## Macros

### cisco_catalyst_app_index

Controls which indexes the dashboards search.

| Property | Value |
|---|---|
| Default definition | `index IN (*)` |
| Recommended | `index IN ("catalyst", "ise", "sdwan", "cybervision")` |
| Description | All indices where Cisco data is stored |
| Location | `local/macros.conf` |

Completion validation requires an explicit list of safe Splunk index names. It
accepts either package-style unquoted names or the quoted form written by
`setup.sh`; it refuses wildcard, empty, and arbitrary SPL definitions.

### cisco_catalyst_sdwan_index

Controls the app's SD-WAN raw dashboard searches.

| Property | Value |
|---|---|
| Default definition | `index IN (*)` |
| Setup default | `index IN ("sdwan")` |
| Description | SD-WAN-only indexes used by raw dashboards, especially audit logs |
| Location | `local/macros.conf` |

The same canonical index set must be written to the companion TA's
`cisco_sdwan_index` eventtype. The TA ships that eventtype with `search = ()`
as a fail-closed placeholder; leaving it unchanged prevents dependent SD-WAN
firewall, ACL, and SGACL eventtypes from matching data.

### cisco_catalyst_app_sourcetypes

Controls which sourcetypes the dashboards include.

| Property | Value |
|---|---|
| Package and setup-managed definition | `sourcetype IN ("cisco:ise*", "cisco:sdwan*", "cisco:dnac*", "stream:netflow", "cisco:cybervision:*", "meraki:*", "cisco:ios", "cisco:thousandeyes:metric", "cisco:sgacl:logs", "cisco:catalyst:center:*", "cisco:ise:analytics*", "tenable:sc*")` |
| Description | All Cisco sourcetypes |
| Location | Package default in `default/macros.conf`; setup-managed override in `local/macros.conf` |

Package `3.2.20` uses the exact ThousandEyes metric and SGACL source types shown
above; `cisco:sgacl:logs` is current package content, not a retired alias.
`setup.sh --macros-only` mirrors the complete package definition so Catalyst
Center reports, ISE analytics, and Tenable data are not silently excluded.

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
| Cisco Catalyst Add-on | `TA_cisco_catalyst` | Data collection (required; auto-installed alongside app ID `7539` when missing) |
| Splunk Add-on for Stream | `splunk_app_stream` | NetFlow data (optional) |
| Cisco Catalyst Enhanced Netflow | `splunk_app_stream_ipfix_cisco_hsl` | Enhanced NetFlow parsing for additional dashboards (optional) |
| Cisco Meraki Add-on | `Splunk_TA_cisco_meraki` | Meraki data (optional) |
| Cisco ThousandEyes Add-on | `ta_cisco_thousandeyes` | ThousandEyes data (optional) |

## Completion Validation

`validate.sh --completion` (alias `--strict`) treats missing or disabled
dashboard dependencies, unsafe or divergent index scopes, missing exact
package source families, an empty/misaligned TA `cisco_sdwan_index` eventtype,
and zero data in the configured dashboard indexes as failures. Direct no-flag
validation remains diagnostic.

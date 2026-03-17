# Cisco Meraki TA — Input Reference

Complete catalog of all data inputs, account fields, and recommended index mapping.

## Organization Account Fields

Configured in `splunk_ta_cisco_meraki_organization.conf`:

| Field | Required | Encrypted | Description |
|-------|----------|-----------|-------------|
| `organization_api_key` | Yes | Yes | Meraki Dashboard API key |
| `organization_id` | Yes | No | Meraki organization ID (numeric) |
| `region` | Yes | No | `global`, `india`, `canada`, `china`, `fedramp` |
| `base_url` | Yes | No | API base URL (auto-set from region) |
| `max_api_calls_per_second` | No | No | 1–10 (default 5) |
| `auth_type` | No | No | `basic` (API key) or `oauth` |
| `automatic_input_creation` | No | No | `1` to auto-create all inputs |
| `automatic_input_creation_index` | No | No | Index for auto-created inputs |

### Region to Base URL Mapping

| Region | Base URL |
|--------|----------|
| `global` | `https://api.meraki.com` |
| `india` | `https://api.meraki.in` |
| `canada` | `https://api.meraki.ca` |
| `china` | `https://api.meraki.cn` |
| `fedramp` | `https://api.gov-meraki.com` |

### OAuth Fields (when auth_type=oauth)

| Field | Encrypted | Description |
|-------|-----------|-------------|
| `client_id` | No | OAuth client ID |
| `client_secret` | Yes | OAuth client secret |
| `domain` | No | OAuth domain |
| `endpoint` | No | OAuth endpoint (default `as.meraki.com`) |
| `scope` | No | OAuth scopes |
| `redirect_url` | No | OAuth redirect URL |
| `access_token` | Yes | OAuth access token |
| `refresh_token` | Yes | OAuth refresh token |

## Core Inputs (7)

| Input Stanza | Sourcetype | Default Interval | Description |
|---|---|---|---|
| `cisco_meraki_accesspoints://<name>` | `meraki:accesspoints` | 86400s | Access point data |
| `cisco_meraki_airmarshal://<name>` | `meraki:airmarshal` | 86400s | Air Marshal wireless IDS |
| `cisco_meraki_audit://<name>` | `meraki:audit` | 86400s | Configuration audit log |
| `cisco_meraki_cameras://<name>` | `meraki:cameras` | 86400s | Camera data |
| `cisco_meraki_organizationsecurity://<name>` | `meraki:organizationsecurity` | 360s | Organization security events |
| `cisco_meraki_securityappliances://<name>` | `meraki:securityappliances` | 360s | MX appliance data |
| `cisco_meraki_switches://<name>` | `meraki:switches` | 86400s | Switch data |

## Device Inputs (5)

| Input Stanza | Sourcetype | Default Interval | Description |
|---|---|---|---|
| `cisco_meraki_devices://<name>` | `meraki:devices` | 86400s | Device inventory |
| `cisco_meraki_device_availabilities_change_history://<name>` | `meraki:devicesavailabilitieschangehistory` | 3600s | Availability history |
| `cisco_meraki_device_uplink_addresses_by_device://<name>` | `meraki:devicesuplinksaddressesbydevice` | 86400s | Uplink addresses |
| `cisco_meraki_power_modules_statuses_by_device://<name>` | `meraki:powermodulesstatusesbydevice` | 3600s | Power module status |
| `cisco_meraki_firmware_upgrades://<name>` | `meraki:firmwareupgrades` | 86400s | Firmware upgrades |

## Wireless Inputs (6)

| Input Stanza | Sourcetype | Default Interval | Description |
|---|---|---|---|
| `cisco_meraki_wireless_devices_ethernet_statuses://<name>` | `meraki:wirelessdevicesethernetstatuses` | 86400s | Wireless ethernet status |
| `cisco_meraki_wireless_packet_loss_by_device://<name>` | `meraki:wirelessdevicespacketlossbydevice` | 86400s | Packet loss per device |
| `cisco_meraki_wireless_controller_availabilities_change_history://<name>` | `meraki:wirelesscontrolleravailabilitieschangehistory` | 86400s | Controller availability |
| `cisco_meraki_wireless_controller_devices_interfaces_usage_history_by_interval://<name>` | `meraki:wirelesscontrollerdevicesinterfacesusagehistorybyinterval` | 86400s | Interface usage |
| `cisco_meraki_wireless_controller_devices_interfaces_packets_overview_by_device://<name>` | `meraki:wirelesscontrollerdevicesinterfacespackets overviewbydevice` | 86400s | Interface packets |
| `cisco_meraki_wireless_devices_wireless_controllers_by_device://<name>` | `meraki:wirelessdeviceswirelesscontrollersbydevice` | 86400s | Device-controller mapping |

## Summary Inputs (5)

| Input Stanza | Sourcetype | Default Interval | Description |
|---|---|---|---|
| `cisco_meraki_summary_appliances_top_by_utilization://<name>` | `meraki:summarytopappliancesbyutilization` | 86400s | Top appliances by utilization |
| `cisco_meraki_summary_switch_power_history://<name>` | `meraki:summaryswitchpowerhistory` | 86400s | Switch power history |
| `cisco_meraki_summary_top_clients_by_usage://<name>` | `meraki:summarytopclientsbyusage` | 86400s | Top clients by usage |
| `cisco_meraki_summary_top_devices_by_usage://<name>` | `meraki:summarytopdevicesbyusage` | 86400s | Top devices by usage |
| `cisco_meraki_summary_top_switches_by_energy_usage://<name>` | `meraki:summarytopswitchesbyenergyusage` | 86400s | Top switches by energy |

## API & Assurance Inputs (4)

| Input Stanza | Sourcetype | Default Interval | Description |
|---|---|---|---|
| `cisco_meraki_api_request_history://<name>` | `meraki:apirequestshistory` | 86400s | API request history |
| `cisco_meraki_api_request_response_code://<name>` | `meraki:apirequestsresponsecodes` | 86400s | API response codes |
| `cisco_meraki_api_request_overview://<name>` | `meraki:apirequestsoverview` | 86400s | API overview |
| `cisco_meraki_assurance_alerts://<name>` | `meraki:assurancealerts` | 3600s | Assurance alerts |

## VPN Inputs (2)

| Input Stanza | Sourcetype | Default Interval | Description |
|---|---|---|---|
| `cisco_meraki_appliance_vpn_stats://<name>` | `meraki:appliancesdwanstatistics` | 86400s | VPN statistics |
| `cisco_meraki_appliance_vpn_statuses://<name>` | `meraki:appliancesdwanstatuses` | 86400s | VPN statuses |

## License Inputs (4)

| Input Stanza | Sourcetype | Default Interval | Description |
|---|---|---|---|
| `cisco_meraki_licenses_overview://<name>` | `meraki:licensesoverview` | 86400s | License overview |
| `cisco_meraki_licenses_coterm_licenses://<name>` | `meraki:licensescotermlicenses` | 86400s | Coterm licenses |
| `cisco_meraki_licenses_subscription_entitlements://<name>` | `meraki:licensessubscriptionentitlements` | 86400s | Subscription entitlements |
| `cisco_meraki_licenses_subscriptions://<name>` | `meraki:licensessubscriptions` | 86400s | Subscriptions |

## Switch Inputs (3)

| Input Stanza | Sourcetype | Default Interval | Description |
|---|---|---|---|
| `cisco_meraki_switch_port_overview://<name>` | `meraki:switchportsoverview` | 86400s | Switch port overview |
| `cisco_meraki_switch_ports_transceivers_readings_history_by_switch://<name>` | `meraki:portstransceiversreadingshistorybyswitch` | 86400s | Transceiver readings |
| `cisco_meraki_switch_ports_by_switch://<name>` | `meraki:switchportsbyswitch` | 86400s | Switch ports by switch |

## Organization Inputs (2)

| Input Stanza | Sourcetype | Default Interval | Description |
|---|---|---|---|
| `cisco_meraki_organization_networks://<name>` | `meraki:organizationsnetworks` | 86400s | Organization networks |
| `cisco_meraki_organizations://<name>` | `meraki:organizations` | 86400s | Organization details |

## Sensor Input (1)

| Input Stanza | Sourcetype | Default Interval | Description |
|---|---|---|---|
| `cisco_meraki_sensor_readings_history://<name>` | `meraki:sensorreadingshistory` | 86400s | Sensor readings |

## Webhook Inputs (special)

| Input Stanza | Sourcetype | Description |
|---|---|---|
| `cisco_meraki_webhook_logs://<name>` | `meraki:webhooklogs:api` | Webhook logs via API polling |
| `cisco_meraki_webhook://<name>` | `meraki:webhook` | Webhook events via HEC (requires HEC setup) |

The webhook input requires HEC token configuration and is not part of the standard
polling inputs. Use the TA's UI to configure webhooks.

## Common Input Fields

| Field | Description |
|---|---|
| `organization_name` | Organization account name (stanza from organization.conf) |
| `index` | Target index |
| `interval` | Collection interval in seconds |
| `start_from_days_ago` | How far back to collect on first run (where applicable) |
| `top_count` | Number of top items for summary inputs (default 10) |

## Input Naming Convention

Input stanzas follow the pattern:
```
cisco_meraki_<input_type>://<input_type>_<ORGANIZATION_NAME>
```

Example: `cisco_meraki_devices://devices_CVF`

## Index Sizing Guidelines

| Index | Recommended Max Size | Retention | Notes |
|---|---|---|---|
| `meraki` | 512 GB | 90 days | All Meraki Dashboard data (35+ sourcetypes) |

## Global Settings

Configured in `local/splunk_ta_cisco_meraki_settings.conf`:

| Setting | Default | Description |
|---|---|---|
| `loglevel` | `INFO` | Logging level |
| `proxy_enabled` | `0` | Enable HTTP proxy |
| `proxy_url` | (empty) | Proxy URL |
| `proxy_port` | (empty) | Proxy port (1–65535) |
| `proxy_username` | (empty) | Proxy username |
| `proxy_password` | (encrypted) | Proxy password |

## REST API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/servicesNS/nobody/Splunk_TA_cisco_meraki/Splunk_TA_cisco_meraki_account` | Create account |
| GET | `/servicesNS/nobody/Splunk_TA_cisco_meraki/Splunk_TA_cisco_meraki_account` | List accounts |
| POST | `/servicesNS/nobody/Splunk_TA_cisco_meraki/Splunk_TA_cisco_meraki_account/<name>` | Update account |
| DELETE | `/servicesNS/nobody/Splunk_TA_cisco_meraki/Splunk_TA_cisco_meraki_account/<name>` | Delete account |
| POST/GET | `/servicesNS/nobody/Splunk_TA_cisco_meraki/Splunk_TA_cisco_meraki_settings` | Manage settings |

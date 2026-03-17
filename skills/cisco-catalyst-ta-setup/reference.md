# Cisco Catalyst TA — Input Reference

Complete catalog of all data inputs, default arguments, and recommended index mapping.

## Catalyst Center (DNAC) Inputs

Input type prefix: `cisco_catalyst_dnac_`

| Input Stanza | Sourcetype | Default Interval | Index |
|---|---|---|---|
| `cisco_catalyst_dnac_issue://<name>` | `cisco:dnac:issue` | 900s | `catalyst` |
| `cisco_catalyst_dnac_clienthealth://<name>` | `cisco:dnac:clienthealth` | 900s | `catalyst` |
| `cisco_catalyst_dnac_devicehealth://<name>` | `cisco:dnac:devicehealth` | 900s | `catalyst` |
| `cisco_catalyst_dnac_compliance://<name>` | `cisco:dnac:compliance` | 900s | `catalyst` |
| `cisco_catalyst_dnac_networkhealth://<name>` | `cisco:dnac:networkhealth` | 900s | `catalyst` |
| `cisco_catalyst_dnac_securityadvisory://<name>` | `cisco:dnac:securityadvisory` | 900s | `catalyst` |
| `cisco_catalyst_dnac_client://<name>` | `cisco:dnac:client` | 3600s | `catalyst` |
| `cisco_catalyst_dnac_audit_logs://<name>` | `cisco:dnac:audit:logs` | 300s | `catalyst` |
| `cisco_catalyst_dnac_site_topology://<name>` | `cisco:dnac:site:topology` | 3600s | `catalyst` |

### Catalyst Center Input Fields

| Field | Description |
|---|---|
| `cisco_dna_center_account` | Account name (stanza from ta_cisco_catalyst_account.conf) |
| `index` | Target index |
| `interval` | Collection interval in seconds |
| `logging_level` | INFO, DEBUG, WARNING, ERROR |

### Catalyst Center Account Fields

| Field | Description |
|---|---|
| `cisco_dna_center_host` | Catalyst Center URL (e.g., `https://10.100.0.60`) |
| `username` | Username |
| `password` | Password (encrypted by REST handler) |
| `use_ca_cert` | Use custom CA certificate (`true`/`false`) |
| `custom_certificate` | CA certificate content |

## ISE Inputs

Input type: `cisco_catalyst_ise_administrative_input`

| Input Stanza | Data Types | Default Interval | Index |
|---|---|---|---|
| `cisco_catalyst_ise_administrative_input://<name>` | `security_group_tags,authz_policy_hit,ise_tacacs_rule_hit` | 86400s | `ise` |

### ISE Input Fields

| Field | Description |
|---|---|
| `ise_account` | Account name (stanza from ta_cisco_catalyst_ise_account.conf) |
| `data_type` | Comma-separated: `security_group_tags`, `authz_policy_hit`, `ise_tacacs_rule_hit` |
| `index` | Target index |
| `interval` | Collection interval in seconds |
| `logging_level` | INFO, DEBUG, WARNING, ERROR |

### ISE Account Fields

| Field | Description |
|---|---|
| `hostname` | ISE host URL (e.g., `https://10.100.0.10/admin/login.jsp`) |
| `username` | Username |
| `password` | Password (encrypted by REST handler) |
| `use_ca_cert` | Use custom CA certificate |
| `custom_certificate` | CA certificate content |
| `enable_proxy` | Enable proxy (`true`/`false`) |
| `proxy_type` | Proxy protocol |
| `proxy_url` | Proxy host |
| `proxy_port` | Proxy port |
| `proxy_username` | Proxy username |
| `proxy_password` | Proxy password |
| `pxgrid_host` | pxGrid host URL |
| `pxgrid_client_username` | pxGrid client username |
| `pxgrid_cert_auth` | pxGrid certificate auth (`true`/`false`) |
| `client_cert` | Client certificate |
| `client_key` | Client secret key |

## SD-WAN Inputs

Input type prefix: `cisco_catalyst_sdwan_`

| Input Stanza | Health Type | Default Interval | Index |
|---|---|---|---|
| `cisco_catalyst_sdwan_health://<name>` | varies | 86400s | `sdwan` |
| `cisco_catalyst_sdwan_site_and_tunnel_health://<name>` | varies | 3600s | `sdwan` |

### SD-WAN Input Fields

| Field | Description |
|---|---|
| `sdwan_account` | Account name (stanza from ta_cisco_catalyst_sdwan_account.conf) |
| `health_type` | Health data type to collect |
| `index` | Target index |
| `interval` | Collection interval in seconds |
| `logging_level` | INFO, DEBUG, WARNING, ERROR |

### SD-WAN Account Fields

| Field | Description |
|---|---|
| `hostname` | SD-WAN portal URL |
| `username` | Username |
| `password` | Password (encrypted by REST handler) |
| `use_ca_cert` | Use custom CA certificate |
| `custom_certificate` | CA certificate content |
| `enable_proxy` | Enable proxy |
| `proxy_type` | Proxy protocol |
| `proxy_url` | Proxy host |
| `proxy_port` | Proxy port |
| `proxy_username` | Proxy username |
| `proxy_password` | Proxy password |

## Cyber Vision Inputs

Input type prefix: `cisco_catalyst_cybervision_`

| Input Stanza | Sourcetype | Default Interval | Index |
|---|---|---|---|
| `cisco_catalyst_cybervision_activities://<name>` | `cisco:cybervision:activities` | 60s | `cybervision` |
| `cisco_catalyst_cybervision_components://<name>` | `cisco:cybervision:components` | 60s | `cybervision` |
| `cisco_catalyst_cybervision_devices://<name>` | `cisco:cybervision:devices` | 60s | `cybervision` |
| `cisco_catalyst_cybervision_events://<name>` | `cisco:cybervision:events` | 60s | `cybervision` |
| `cisco_catalyst_cybervision_flows://<name>` | `cisco:cybervision:flows` | 60s | `cybervision` |
| `cisco_catalyst_cybervision_vulnerabilities://<name>` | `cisco:cybervision:vulnerabilities` | 60s | `cybervision` |

### Cyber Vision Input Fields

| Field | Description |
|---|---|
| `cyber_vision_account` | Account name |
| `start_date` | Collection start date |
| `page_size` | API page size (default: 100) |
| `index` | Target index |
| `logging_level` | INFO, DEBUG, WARNING, ERROR |

### Cyber Vision Account Fields

| Field | Description |
|---|---|
| `ip_address` | Cyber Vision portal URL (e.g., `https://192.168.1.100`) |
| `api_token` | API token (not username/password) |
| `use_ca_cert` | Use custom CA certificate |
| `custom_certificate` | CA certificate content |
| `enable_proxy` | Enable proxy |
| `proxy_type` | Proxy protocol |
| `proxy_url` | Proxy host |
| `proxy_port` | Proxy port |
| `proxy_username` | Proxy username |
| `proxy_password` | Proxy password |

## Index Sizing Guidelines

| Index | Recommended Max Size | Retention | Notes |
|---|---|---|---|
| `catalyst` | 512 GB | 90 days | Catalyst Center health, compliance, advisories |
| `ise` | 512 GB | 90 days | Authentication, admin logs, SGT mappings |
| `sdwan` | 512 GB | 90 days | WAN health, tunnel status |
| `cybervision` | 512 GB | 90 days | OT activities, flows, vulnerabilities (high frequency) |

## Global Settings

Configured in `local/ta_cisco_catalyst_settings.conf`:

| Setting | Default | Description |
|---|---|---|
| `loglevel` | `INFO` | Logging level |
| `verify_ssl` | `True` | SSL certificate verification |
| `ca_certs_path` | (empty) | Custom CA bundle path |
| `splunk_mgmt_env_type` | `local_instance` | Splunk management environment |
| `splunk_mgmt_host` | `localhost` | Splunk management host |
| `splunk_mgmt_port` | `8089` | Splunk management port |

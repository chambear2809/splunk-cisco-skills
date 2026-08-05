# Cisco Catalyst TA — Input Reference

Complete catalog of all 29 modular input types, default arguments, and
recommended index mapping from the inspected TA `3.2.44` source contract.

> Note: The "Default Interval" columns below reflect the TA package's shipped
> per-input defaults. `setup.sh` preserves these defaults for every
> parameter-complete dedicated input it creates.

## SCAN Canonicalization Boundary

The pinned SCAN `2026_07_09_1837` source treats `cisco:dnac:*`,
`cisco:ise:*`, and `cisco:sdwan:*` as the current output families. It no
longer advertises the older Catalyst Center `cisco:catalyst:*` aliases,
unqualified `cisco:dnac:custom` (the current wildcard is
`cisco:dnac:custom:*`), unqualified `cisco:ise`, `cisco:ise:custom`,
`cisco:sdwan:custom`, `cisco:sdwan:sytem:logs`, or `cisco:sgacl:logs`.

The repo-inspected Catalyst TA `3.2.44` still contains compatibility parser
stanzas for several old inputs and normalizes them to canonical outputs such as
`cisco:ise:syslog`, `cisco:sdwan:system:logs`, and
`cisco:sdwan:sgacl:logs`. Treat those old names as parser compatibility, not as
current dashboard or completion-search contracts.

## Catalyst Center (DNAC) Inputs

Input type prefix: `cisco_catalyst_dnac_`

| Input Stanza | Sourcetype | Default Interval | Index |
|---|---|---|---|
| `cisco_catalyst_center_reports://<name>` | `cisco:catalyst:center:*:report` | 3600s | `catalyst` |
| `cisco_catalyst_dnac_api://<name>` | `cisco:dnac:custom:*` | 3600s | `catalyst` |
| `cisco_catalyst_dnac_application_traffic://<name>` | `cisco:dnac:application:traffic` | 900s | `catalyst` |
| `cisco_catalyst_dnac_audit_logs://<name>` | `cisco:dnac:audit:logs` | 300s | `catalyst` |
| `cisco_catalyst_dnac_client://<name>` | `cisco:dnac:client` | 3600s | `catalyst` |
| `cisco_catalyst_dnac_clienthealth://<name>` | `cisco:dnac:clienthealth` | 300s | `catalyst` |
| `cisco_catalyst_dnac_compliance://<name>` | `cisco:dnac:compliance` | 900s | `catalyst` |
| `cisco_catalyst_dnac_devicehealth://<name>` | `cisco:dnac:devicehealth` | 300s | `catalyst` |
| `cisco_catalyst_dnac_issue://<name>` | `cisco:dnac:issue` | 300s | `catalyst` |
| `cisco_catalyst_dnac_networkhealth://<name>` | `cisco:dnac:networkhealth` | 300s | `catalyst` |
| `cisco_catalyst_dnac_securityadvisory://<name>` | `cisco:dnac:securityadvisory` | 3600s | `catalyst` |
| `cisco_catalyst_dnac_site_topology://<name>` | `cisco:dnac:site:topology` | 3600s | `catalyst` |
| `cisco_catalyst_dnac_swim://<name>` | `cisco:dnac:swim` | 3600s | `catalyst` |

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
| `verify_ssl` | Validate this account's remote TLS certificate (`true` by default) |
| `use_ca_cert` | Use custom CA certificate (`true`/`false`) |
| `custom_certificate` | CA certificate content |

## ISE Inputs

Input type prefix: `cisco_catalyst_ise_`

| Input Stanza | Data Types / Sourcetype | Default Interval | Index |
|---|---|---|---|
| `cisco_catalyst_ise_administrative_input://<name>` | `security_group_tags,authz_policy_hit,ise_tacacs_rule_hit` | 3600s | `ise` |
| `cisco_catalyst_ise_analytics_reports://<name>` | `cisco:ise:analytics*` | 3600s | `ise` |
| `cisco_catalyst_ise_api://<name>` | `cisco:ise:custom:*` or canonical dedicated source types | 3600s | `ise` |

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
| `verify_ssl` | Validate this account's remote TLS certificate (`true` by default) |
| `use_ca_cert` | Use custom CA certificate |
| `custom_certificate` | CA certificate content |
| `enable_proxy` | Enable proxy (`true`/`false`) |
| `proxy_type` | Proxy protocol |
| `proxy_url` | Proxy host |
| `proxy_port` | Proxy port |
| `proxy_username` | Proxy username |
| `proxy_password` | Proxy password |

## SD-WAN Text-Syslog Contract

Text syslog, vManage API polling, and NetFlow/IPFIX are separate collection
paths. The TA does not open UDP sockets from Python; it configures supported
Splunk inputs or monitors files written by a system relay.

| Producer | Cisco-side behavior | Splunk collection |
|---|---|---|
| Ordinary IOS-XE system logger | Remote TCP, UDP, or TLS transport and port are configurable | SC4S/HEC or TA-managed relay/direct listener with ingress `cisco:firewall:logs` |
| Traditional ZBFW text logger | Emits supported `%FW-*` messages when policy logging is enabled; rate-limited under load | Same text-syslog ingress, then named `cisco:sdwan:*` outputs |
| UTD external syslog | Separate UTD producer for IPS/IDS, URL filtering, AMP/file, and TLS-decryption events; affected releases/templates expose no alternate transport or port | Receiver must accept UDP 514; matching events become `cisco:sdwan:utd:logs` |
| HSL / Unified Logging through FNF | Edge devices export NetFlow v9/IPFIX records directly to a collector | Splunk Stream plus the Cisco Catalyst Enhanced NetFlow Add-on; not the TA text-syslog listener |

For a one-socket text-syslog design that includes UTD, use UDP 514. Standard
IOS-XE and ZBFW text syslog may use another supported port, but changing that
port does not move the separate UTD feed. HSL is preferred for production
ZBFW pass/drop/inspect coverage when text-syslog rate limiting matters. HSL
does not disable ordinary system or UTD syslog, and equivalent `%FW-*`
duplicates must not be assumed for each HSL record.

`cisco:sdwan:utd:logs` is the UTD external text-event sourcetype.
`cisco:sdwan:utdhealth` is a separate vManage REST/API health snapshot; it does
not prove that IPS, URL filtering, AMP/file, or TLS-decryption events are being
exported through syslog.

The SD-WAN Syslog UI documents four collection designs:

1. External SC4S receives the edge text-syslog feed and sends HEC events with
   ingress sourcetype `cisco:firewall:logs`.
2. A local `rsyslog` or `syslog-ng` service owns UDP 514 and writes raw files
   that Splunk monitors. This is the TA-managed production default.
3. A Linux administrator redirects UDP 514 to an unprivileged Splunk UDP port.
4. Splunk listens directly only when the preflight proves UDP 514 permission
   and availability; this is intended for small deployments.

The TA never runs `sudo`, changes `/etc`, restarts a service, or modifies a
firewall. Splunk Cloud requires a customer-managed collection tier such as
SC4S or a Heavy Forwarder; it cannot host the local privileged listener.

### SD-WAN index-time sourcetype routing

The add-on must be present on the first full parsing tier. Rewrites apply only
to newly indexed events.

| Ingress or signal | Final searchable sourcetype |
|---|---|
| Dedicated SD-WAN listener/HEC metadata | `cisco:firewall:logs` (ingress contract) |
| Generic IOS-XE `%FAC-SEV-MNEM:` | `cisco:sdwan:syslog` with `event_id`, `facility`, `severity_id`, and `mnemonic` |
| Unmatched SD-WAN text | `cisco:sdwan:system:logs` |
| `%FW-6-SESS_AUDIT_TRAIL_START` | `cisco:sdwan:session:audit:trail:start` |
| `%FW-6-SESS_AUDIT_TRAIL` | `cisco:sdwan:session:audit:trail` |
| `%FW-6-PASS_PKT` / `%FW-6-DROP_PKT` | `cisco:sdwan:pass:pkt` / `cisco:sdwan:drop:pkt` |
| `%FW-6-LOG_SUMMARY` | `cisco:sdwan:log:summary` |
| UTD `[**]` sections and flow arrow | `cisco:sdwan:utd:logs` |
| SGACL / ACL signals | `cisco:sdwan:sgacl:logs` / `cisco:sdwan:acl:logs` |

`cisco:catalyst:syslog` remains a compatibility ingress for older mixed ISE
and IOS/SD-WAN deployments; do not use it for new dedicated SD-WAN receivers.
SC4S defaults such as `cisco:viptela`, `cisco:ios`, or generic `syslog` must be
overridden only for the isolated SD-WAN sender population so the events enter
the `cisco:firewall:logs` split chain.
| `pxgrid_host` | pxGrid host URL |
| `pxgrid_client_username` | pxGrid client username |
| `pxgrid_cert_auth` | pxGrid certificate auth (`true`/`false`) |
| `client_cert` | Client certificate |
| `client_key` | Client secret key |

## SD-WAN Inputs

Input type prefix: `cisco_catalyst_sdwan_`

| Input Stanza | Health Type | Default Interval | Index |
|---|---|---|---|
| `cisco_catalyst_sdwan_api://<name>` | `cisco:sdwan:custom:*` | 3600s | `sdwan` |
| `cisco_catalyst_sdwan_audit_logs://<name>` | `cisco:sdwan:audit:logs` | 300s | `sdwan` |
| `cisco_catalyst_sdwan_energy_stats://<name>` | `cisco:sdwan:energy:stats` | 300s | `sdwan` |
| `cisco_catalyst_sdwan_health://<name>` | `utd_health,link_health,sse_tunnel_health` | 900s | `sdwan` |
| `cisco_catalyst_sdwan_site_and_tunnel_health://<name>` | `site_health,tunnel_health,sse_tunnels` | 3600s | `sdwan` |

### SD-WAN Input Fields

| Field | Description |
|---|---|
| `sdwan_account` | Account name (stanza from ta_cisco_catalyst_sdwan_account.conf) |
| `health_type` | Health data type to collect |
| `index` | Target index |
| `interval` | Collection interval in seconds |
| `logging_level` | INFO, DEBUG, WARNING, ERROR |

All five SD-WAN API input forms allow `interval` changes during edit. Values
below the form's recommended interval require explicit confirmation.

The `cisco_catalyst_sdwan_api` **API Endpoint Collection** input also uses:

| Field | Description |
|---|---|
| `endpoint_path` | Cataloged read-only vManage `/dataservice/*` GET endpoint |
| `device_scope` | `single`, `selected`, or `all` for endpoints requiring `deviceId` |
| `device_ids` | Selected WAN Edge system IPs; omitted for `all` scope |
| `query_params` | Additional non-device query parameters |

Device-scoped events are enriched with `target_device_id`. A focused BFD
example uses one stanza per endpoint:

| Endpoint | Sourcetype | Purpose |
|---|---|---|
| `/dataservice/device/bfd/summary` | `cisco:sdwan:custom:device_bfd_summary` | Per-device summary |
| `/dataservice/device/bfd/synced/sessions` | `cisco:sdwan:custom:device_bfd_synced_sessions` | Current synchronized sessions |
| `/dataservice/device/bfd/history` | `cisco:sdwan:custom:device_bfd_history` | Session history |

These are structured REST snapshots, not arbitrary CLI execution. Do not add
every `/dataservice/device/bfd/*` endpoint unless a distinct data requirement
justifies the additional controller load and overlapping records.

### SD-WAN Account Fields

| Field | Description |
|---|---|
| `hostname` | SD-WAN portal URL |
| `username` | Username |
| `password` | Password (encrypted by REST handler) |
| `verify_ssl` | Validate this account's remote TLS certificate (`true` by default) |
| `use_ca_cert` | Use custom CA certificate |
| `custom_certificate` | CA certificate content |
| `enable_proxy` | Enable proxy |
| `proxy_type` | Proxy protocol |
| `proxy_url` | Proxy host |
| `proxy_port` | Proxy port |
| `proxy_username` | Proxy username |
| `proxy_password` | Proxy password |

## Cisco IOS-XE CLI Input (Beta)

Input type: `cisco_catalyst_cli_command`

This bounded direct-device collector fills validated API gaps; it is not a
generic SSH automation framework. One account represents one IOS-XE device and
one input polls one backend-allowlisted command. The collector uses a
non-interactive SSH exec session, pins the device's SHA-256 host key, and does
not issue `enable`. The login must already return the full command output.

| Command ID | Command | Default / recommended interval | Sourcetype |
|---|---|---|---|
| `dspfarm_profile` | `show dspfarm profile` | 900s | `cisco:iosxe:cli:dspfarm:profile` |
| `sdwan_bfd_sessions` | `show sdwan bfd sessions` | 300s | `cisco:iosxe:cli:sdwan:bfd:sessions` |
| `sdwan_bfd_history` | `show sdwan bfd history` | 900s | `cisco:iosxe:cli:sdwan:bfd:history` |
| `version` | `show version` | 3600s | `cisco:iosxe:cli:version` |
| `inventory` | `show inventory` | 3600s | `cisco:iosxe:cli:inventory` |

For SD-WAN BFD, prefer `cisco_catalyst_sdwan_api` structured collection unless
raw device output is explicitly required. Free-form commands, pipes,
redirects, configuration mode, shell execution, controller-wide discovery,
and interactive privilege escalation are not supported. Adding a command
requires a reviewed TA code change and a new build.

### IOS-XE CLI Account Fields

| Field | Description |
|---|---|
| `host` | Bare device hostname or IP address; no scheme or path |
| `port` | SSH port, default `22` |
| `username` | Dedicated least-privilege device user |
| `password` | Encrypted by the TA account REST handler |
| `host_key_fingerprint` | Verified SHA-256 pin in `SHA256:<base64>` format |

Each JSON event includes `device`, `command_id`, `command`, `category`,
`exit_status`, and raw multiline `output`. The execution timeout is 90 seconds
and combined output is limited to 1 MiB. Validate platform/release output shape
and privilege behavior before production use.

## Cyber Vision Inputs

Input type prefix: `cisco_catalyst_cybervision_`

| Input Stanza | Sourcetype | Default Interval | Index |
|---|---|---|---|
| `cisco_catalyst_cybervision_activities://<name>` | `cisco:cybervision:activities` | 300s | `cybervision` |
| `cisco_catalyst_cybervision_api://<name>` | `cisco:cybervision:custom:*` | 3600s | `cybervision` |
| `cisco_catalyst_cybervision_components://<name>` | `cisco:cybervision:components` | 900s | `cybervision` |
| `cisco_catalyst_cybervision_devices://<name>` | `cisco:cybervision:devices` | 900s | `cybervision` |
| `cisco_catalyst_cybervision_events://<name>` | `cisco:cybervision:events` | 300s | `cybervision` |
| `cisco_catalyst_cybervision_flows://<name>` | `cisco:cybervision:flows` | 300s | `cybervision` |
| `cisco_catalyst_cybervision_vulnerabilities://<name>` | `cisco:cybervision:vulnerabilities` | 900s | `cybervision` |

### Cyber Vision Input Fields

| Field | Description |
|---|---|
| `cyber_vision_account` | Account name |
| `start_date` | Collection start date |
| `page_size` | API page size (default: 100) |
| `index` | Target index |
| `interval` | Collection interval in seconds; editable on all seven API input forms |
| `logging_level` | INFO, DEBUG, WARNING, ERROR |

### Cyber Vision Account Fields

| Field | Description |
|---|---|
| `ip_address` | Cyber Vision portal URL (e.g., `https://192.168.1.100`) |
| `api_token` | API token (not username/password) |
| `verify_ssl` | Validate this account's remote TLS certificate (`true` by default) |
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
| `sdwan` | 512 GB | 90 days | WAN API data and text syslog; size high-volume NetFlow/HSL separately |
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

## Completion Validation

`validate.sh --completion` (alias `--strict`) exits nonzero when no Catalyst
product account, enabled TA input or recent external SD-WAN syslog evidence,
recent canonical event evidence, required index, or usable TA Data Collection
Health dashboard is available. Dashboard usability requires both a visible view
and recent `poll-complete` events from its collection-health search. The check
also reports SD-WAN text-syslog receiver/event readiness and includes IOS-XE CLI
accounts, inputs, internal poll status, and `cisco:iosxe:cli:*` event evidence.
The optional Cisco Enterprise Networking companion app is macro-validated only
when installed. The no-flag form remains diagnostic.

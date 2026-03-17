# Cisco DC Networking TA — Input Reference

Complete catalog of all data inputs, their default arguments, and recommended index mapping.

## ACI (APIC) Inputs

Input type prefix: `cisco_nexus_aci://`

| Input Stanza | Type | Default Arguments | Interval | Index |
|---|---|---|---|---|
| `authentication` | authentication | `aaaSessionLR` | 300s | `cisco_aci` |
| `classInfo_faultInst` | classInfo | `faultInst topSystem compVm compHv fvCEp fvRsCons fvRsProv fvRsVm fvRsHyper fvnsRtVlanNs fvnsEncapBlk fvRsPathAtt vmmCtrlrP compHostStats1h compRcvdErrPkts1h compTrnsmtdErrPkts1h` | 300s | `cisco_aci` |
| `classInfo_aaaModLR` | classInfo | `aaaModLR faultRecord eventRecord` | 300s | `cisco_aci` |
| `classInfo_fvRsCEpToPathEp` | classInfo | `fvRsCEpToPathEp dbgEpgToEpgRslt dbgEpToEpRslt dbgAcTrail aaaUser aaaRemoteUser l1PhysIf eqptStorage procEntry procContainer acllogPermitL2Pkt acllogPermitL3Pkt acllogDropL2Pkt acllogDropL3Pkt` | 300s | `cisco_aci` |
| `fex` | fex | `eqptExtCh eqptSensor eqptExtChHP eqptExtChFP eqptExtChCard` | 300s | `cisco_aci` |
| `health_fabricHealthTotal` | health | `fabricHealthTotal eqptFabP eqptLeafP eqptCh eqptLC eqptFt eqptPsu eqptSupC ethpmPhysIf eqptcapacityPolEntry5min infraWiNode` | 300s | `cisco_aci` |
| `health_fvTenant` | health | `fvTenant fvAp fvEPg fvAEPg fvBD vzFilter vzEntry vzBrCP fvCtx l3extOut fabricNode` | 300s | `cisco_aci` |
| `microsegment` | microsegment | `fvRsDomAtt fvVmAttr fvIpAttr fvMacAttr` | 300s | `cisco_aci` |
| `stats` | stats | `eqptEgrTotal15min eqptIngrTotal15min fvCEp l2IngrBytesAg15min l2EgrBytesAg15min procCPU15min procMem15min` | 300s | `cisco_aci` |

### ACI Account Configuration Fields

| Field | Description |
|---|---|
| `apic_hostname` | Comma-separated APIC controller IPs/hostnames |
| `apic_port` | HTTPS port (default: 443) |
| `apic_authentication_type` | `password_authentication` or `certificate_authentication` |
| `apic_login_domain` | APIC login domain (optional) |
| `apic_username` | APIC username |
| `apic_password` | APIC password (stored encrypted by Splunk) |
| `apic_certificate_name` | Certificate name (for cert auth) |
| `apic_certificate_path` | Certificate file path (for cert auth) |
| `apic_proxy_enabled` | `0` or `1` |
| `apic_proxy_type` | Proxy protocol type |
| `apic_proxy_url` | Proxy URL |
| `apic_proxy_port` | Proxy port |
| `apic_proxy_username` | Proxy username |
| `apic_proxy_password` | Proxy password |

## Nexus Dashboard Inputs

Input type prefix: `cisco_nexus_dashboard://`

| Input Stanza | Alert Type | Default Arguments | Interval | Index |
|---|---|---|---|---|
| `advisories` | advisories | `nd_advisories_category=* nd_severity=* nd_time_range=4` | 300s | `cisco_nd` |
| `anomalies` | anomalies | `nd_anomalies_category=* nd_severity=* nd_time_range=4` | 300s | `cisco_nd` |
| `congestion` | congestion | — | 300s | `cisco_nd` |
| `endpoints` | endpoints | `nd_start_date=1h` | 300s | `cisco_nd` |
| `flows` | flows | `nd_flow_start_date=1m nd_time_slice=5` | 300s | `cisco_nd` |
| `protocols` | protocols | `nd_start_date=1h` | 300s | `cisco_nd` |
| `fabrics` | fabrics | — | 300s | `cisco_nd` |
| `switches` | switches | — | 300s | `cisco_nd` |
| `mso_tenant_site_schema` | Orchestrator | `orchestrator_arguments=tenant site schema` | 300s | `cisco_nd` |
| `mso_fabric_policy` | Orchestrator | `orchestrator_arguments=fabric policy` | 300s | `cisco_nd` |
| `mso_audit_user` | Orchestrator | `orchestrator_arguments=audit user` | 300s | `cisco_nd` |

### Nexus Dashboard Account Configuration Fields

| Field | Description |
|---|---|
| `nd_hostname` | Nexus Dashboard hostname/IP |
| `nd_port` | HTTPS port (default: 443) |
| `nd_authentication_type` | `password_authentication` |
| `nd_username` | Dashboard username |
| `nd_password` | Dashboard password |
| `nd_login_domain` | Login domain (optional) |
| `nd_enable_proxy` | `0` or `1` |

## Nexus 9K Inputs

Input type prefix: `cisco_nexus_9k://`

| Input Stanza | CLI Command | Component | Interval | Index |
|---|---|---|---|---|
| `nxhostname` | `show hostname` | nxhostname | 300s | `cisco_nexus_9k` |
| `nxversion` | `show version` | nxversion | 300s | `cisco_nexus_9k` |
| `nxmodule` | `show module` | nxinventory | 300s | `cisco_nexus_9k` |
| `nxinventory` | `show inventory` | nxinventory | 300s | `cisco_nexus_9k` |
| `nxtemperature` | `show environment temperature` | nxtemperature | 300s | `cisco_nexus_9k` |
| `nxinterface` | `show interface` | nxinterface | 300s | `cisco_nexus_9k` |
| `nxneighbor` | `show cdp neighbors detail` | nxneighbor | 300s | `cisco_nexus_9k` |
| `nxtransceiver` | `show interface transceiver details` | nxtransceiver | 300s | `cisco_nexus_9k` |
| `nxpower` | `show environment power` | nxpower | 300s | `cisco_nexus_9k` |
| `nxresource` | `show system resource` | nxresource | 300s | `cisco_nexus_9k` |

### Nexus 9K Account Configuration Fields

| Field | Description |
|---|---|
| `nexus_9k_device_ip` | Switch management IP |
| `nexus_9k_port` | NX-API HTTPS port (default: 443) |
| `nexus_9k_username` | Switch username |
| `nexus_9k_password` | Switch password |
| `nexus_9k_enable_proxy` | `0` or `1` |

## Index Sizing Guidelines

| Index | Recommended Max Size | Retention | Notes |
|---|---|---|---|
| `cisco_aci` | 512 GB | 90 days | Heaviest volume — faults, health, endpoints, stats |
| `cisco_nd` | 512 GB | 90 days | Anomalies, advisories, flows |
| `cisco_nexus_9k` | 512 GB | 90 days | CLI output from switches |

Adjust `maxTotalDataSizeMB` and `frozenTimePeriodInSecs` based on your fabric size,
number of switches, and compliance requirements.

## Search Macros

| Macro | Definition | Purpose |
|---|---|---|
| `cisco_dc_aci_index` | `index IN ("cisco_aci")` | Filter searches to ACI data |
| `cisco_dc_nd_index` | `index IN ("cisco_nd")` | Filter searches to Nexus Dashboard data |
| `cisco_dc_nexus_9k_index` | `index IN ("cisco_nexus_9k")` | Filter searches to Nexus 9K data |

## Global Settings

Configured in `local/cisco_dc_networking_app_for_splunk_settings.conf`:

| Setting | Default | Description |
|---|---|---|
| `loglevel` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `verify_ssl` | `False` | SSL certificate verification for API calls |
| `ca_certs_path` | (empty) | Custom CA bundle path |

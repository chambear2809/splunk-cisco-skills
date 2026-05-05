# Cisco UCS Package Reference

Source: Splunk Add-on for Cisco UCS `4.3.1` package inspection and published
Splunk documentation.

## Package

| Splunkbase ID | App | Workloads | Default sourcetype |
|---|---|---|---|
| `2731` | `Splunk_TA_cisco-ucs` | `_search_heads`, `_forwarders` | `cisco:ucs` |

## REST Surfaces

| Handler | Purpose |
|---|---|
| `splunk_ta_cisco_ucs_servers` | UCS Manager server URL, username, encrypted password, SSL verification |
| `splunk_ta_cisco_ucs_templates` | Class-ID collections |
| `cisco_ucs_task` | Data inputs tying servers + templates to an index/interval |
| `splunk_ta_cisco_ucs_settings` | Add-on logging/settings |

## Default Templates

| Template | Class IDs |
|---|---|
| `UCS_Fault` | `faultInst` |
| `UCS_Inventory` | `equipmentFex,equipmentIOCard,equipmentSwitchCard,equipmentChassis,equipmentPsu,computeBlade,computeRackUnit,fabricDceSwSrvEp,etherPIo,fabricEthLanEp,fabricEthLanPc,fabricEthLanPcEp,fabricVlan,fabricVsan,lsServer,vnicEtherIf,vnicFcIf,storageLocalDisk,firmwareRunning,statsCollectionPolicy` |
| `UCS_Performance` | `topSystem,equipmentChassisStats,computeMbPowerStats,computeMbTempStats,processorEnvStats,equipmentPsuStats,adaptorVnicStats,etherErrStats,etherLossStats,etherRxStats,etherPauseStats,etherTxStats,swSystemStats` |

## Defaults

- Index: `cisco_ucs`
- Input interval: `300`
- Sourcetype: `cisco:ucs`
- Server URL field accepts host-style values, not full paths.
- `disable_ssl_verification=true` is supported but should be an explicit choice.

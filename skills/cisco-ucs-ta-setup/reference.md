# Cisco UCS Package Reference

Source: Splunk Add-on for Cisco UCS `5.0.0` package inspection and published
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

## Completion Validation

`validate.sh --completion`/`--strict` makes absent templates, server records,
enabled task inputs, index, or event evidence fail. No-flag validation remains
diagnostic. The inspected package ships Monitoring Dashboard, Inputs, and
Configuration views; live `cisco:ucs` events remain required before those views
are considered ready.

The `dashboard.xml` view is the UCC **Monitoring Dashboard**, not a UCS
inventory/performance business dashboard. Its implementation under
`appserver/static/js/build/custom/` queries `_internal` license usage and
`source=*splunk_ta_cisco-ucs*` logs plus `_introspection` resource data.
Completion checks the exact three REST view IDs and real
`index=cisco_ucs sourcetype=cisco:ucs` ingest. Health-log availability is
diagnostic: a healthy collector with restrictive logging or separately forwarded
internal logs may have no matching recent local log events.
Open the Monitoring Dashboard with the intended operator role and validate
its panels, including permissions to these internal indexes; REST view
presence alone cannot prove browser rendering. No standalone UCS business
dashboard is claimed. Use downstream CIM/ES/ITSI content or a separately
reviewed UCS visualization app for that use case.

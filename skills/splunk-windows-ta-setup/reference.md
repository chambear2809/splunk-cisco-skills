# Splunk Add-on for Microsoft Windows Reference

Grounded in the `Splunk_TA_windows` package (Splunkbase app `742`, verified
version `10.0.1`). The add-on is input-only on Windows forwarders; it ships
`[ui] is_visible = false` and has no account or custom REST configuration.

## Package Model

- App / package id: `Splunk_TA_windows`
- Splunkbase ID: `742`
- Collection: Windows Event Log (`WinEventLog://`), performance counters
  (`perfmon://`), host monitoring (`WinHostMon://`), registry (`WinRegMon://`),
  network (`WinNetMon://`), print (`WinPrintMon://`), AD (`admon://`), and
  scripted/PowerShell inputs.
- No modular-input accounts and no `admin_external` REST handlers; all inputs
  are classic `inputs.conf` stanzas enabled on Windows forwarders.

## Index Model

| Index | Purpose | Default in this skill |
| --- | --- | --- |
| Event index | WinEventLog, WinHostMon, scripted inputs | `wineventlog` |
| Perfmon index | `perfmon://` counter events | `perfmon` |

Both default to event indexes. Perfmon data is event data in this add-on (the
`Perfmon:*` source types), not metric-store data, so a standard event index is
correct. Create a metrics index only if you separately use `mcollect`/`mstats`
pipelines.

## Source Types And CIM Coverage

| Input | Source type | CIM data models |
| --- | --- | --- |
| `WinEventLog://Security` | `WinEventLog:Security` | Authentication, Change |
| `WinEventLog://System` | `WinEventLog:System` | Change, Inventory |
| `WinEventLog://Application` | `WinEventLog:Application` | Change |
| `WinEventLog://Microsoft-Windows-Windows Defender/Operational` | `WinEventLog:Microsoft-Windows-Windows Defender/Operational` | Malware |
| `WinEventLog://Microsoft-Windows-PowerShell/Operational` | `WinEventLog:Microsoft-Windows-PowerShell/Operational` | Endpoint |
| `perfmon://CPU` (and Memory, LogicalDisk, PhysicalDisk, Network, System) | `Perfmon:CPU` (etc.) | Performance |
| `WinHostMon://*` | `WinHostMon` | Endpoint, Inventory |

To collect XML event records instead of classic text, set `renderXml = true`
on the `WinEventLog://` stanza; the source type becomes `XmlWinEventLog:<channel>`.

## Placement Guardrails

- Install on the search tier and indexers for parsing, knowledge objects, and
  CIM. Install on Windows Universal Forwarders for inputs.
- Enable inputs with local configuration files on the forwarder, not the Splunk
  Web setup page.
- Copy only the stanzas you need into `local/inputs.conf`; do not copy the whole
  default file.
- Keep the add-on hidden on search heads (the package default).
- Sysmon is a separate add-on (Splunk Add-on for Sysmon) and is not bundled
  here; install it separately if you need `XmlWinEventLog:Microsoft-Windows-Sysmon/Operational`.

## Handoffs

- `splunk-app-install` installs the package from Splunkbase (`742`).
- `splunk-agent-management-setup` distributes `Splunk_TA_windows` to Windows
  forwarders as a deployment app.
- `splunk-universal-forwarder-setup` bootstraps the Windows UF runtime.
- `splunk-data-source-readiness-doctor` scores CIM/data readiness with the
  `windows_security` source pack.

## Sources

- https://splunkbase.splunk.com/app/742
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/microsoft-windows

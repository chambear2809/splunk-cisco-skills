# Splunk_TA_microsoft_sysmon Reference

Package source of truth: `splunk-ta/_unpacked/Splunk_TA_microsoft_sysmon-5.0.0/Splunk_TA_microsoft_sysmon`.

## Package Defaults

| Mode | Stanza | Package source / source type |
| --- | --- | --- |
| endpoint | `[WinEventLog://Microsoft-Windows-Sysmon/Operational]` | `source = XmlWinEventLog:Microsoft-Windows-Sysmon/Operational` |
| WEC | `[WinEventLog://WEC-Sysmon]` | `source = XmlWinEventLog:Microsoft-Windows-Sysmon/Operational`, `sourcetype = XmlWinEventLog:WEC-Sysmon` |

The package ships props and transforms keyed to
`source::XmlWinEventLog:Microsoft-Windows-Sysmon/Operational` plus eventtypes
such as `ms-sysmon-process`, `ms-sysmon-network`, `ms-sysmon-filemod`,
`ms-sysmon-regmod`, `ms-sysmon-wmimod`, `ms-sysmon-dns`, and
`ms-sysmon-service`.

## Guardrails

- Do not deploy direct endpoint collection and WEC collection for the same host
  population.
- Keep readiness source-constrained to the Sysmon Operational source. Broad
  Windows `XmlWinEventLog` alone should not match the Sysmon source pack.
- Use UF/deployment-server skills for endpoint rollout.

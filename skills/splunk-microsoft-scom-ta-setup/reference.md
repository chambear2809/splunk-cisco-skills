# Microsoft SCOM Supported Add-on Reference

Package source of truth: `Splunk_TA_microsoft-scom` `4.5.0`, Splunkbase
`2729`.

## Package-Derived Inputs And Source Types

PowerShell input stanzas include `powershell://scom_Events`,
`powershell://scom_Internal`, `powershell://scom_Management_Network`,
`powershell://scom_alert`, `powershell://scom_commands`,
`powershell://scom_diagnostic`, `powershell://scom_discovery`,
`powershell://scom_event`, `powershell://scom_mgmt`,
`powershell://scom_network`, `powershell://scom_perf_command`, and
`powershell://scom_task`.

Representative source types include `microsoft:scom`,
`microsoft:scom:alert`, `microsoft:scom:events`,
`microsoft:scom:performance`, and `microsoft:scom:cmd`.

## Guardrails

- Configure SCOM connection details through the add-on account/configuration
  flow; do not pass credentials to setup scripts.
- Run collection on one approved search-tier or heavy-forwarder owner per SCOM
  environment.
- Validate package eventtypes and lookups before using SCOM data in ITSI or ES.

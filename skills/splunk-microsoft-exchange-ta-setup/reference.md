# Microsoft Exchange Supported Add-on Reference

Package source of truth:

| Package | App directory | Splunkbase | Verified |
| --- | --- | --- | --- |
| Exchange bundle | `TA-Exchange-ClientAccess` | `3225` | `4.1.0` |
| Exchange bundle | `TA-Exchange-Mailbox` | `3225` | `4.1.0` |
| Exchange bundle | `TA-SMTP-Reputation` | `3225` | `4.1.0` |
| Exchange bundle | `TA-Windows-Exchange-IIS` | `3225` | `4.1.0` |
| Exchange Indexes | `SA-ExchangeIndex` | `5663` | `4.0.4` |

`SA-ExchangeIndex` defines `msexchange`, `perfmon`, `windows`,
`wineventlog`, and `msad`.

## Package-Derived Source Types

Representative source types include:

- `MSExchange:2013:MessageTracking`
- `MSExchange:2013:MailboxAudit`
- `MSExchange:2013:AdminAudit`
- `MSExchange:2013:RPCClientAccess`
- `MSExchange:2013:Topology`
- `MSExchange:Reputation`
- `WinEventLog:Exchange`
- `MSWindows:2013EWS:IIS`

## Guardrails

- Deploy Exchange collection stanzas only to reviewed Windows collection owners.
- Keep the Exchange bundle components and `SA-ExchangeIndex` version pinned until
  package extraction is refreshed.
- Use the Windows TA readiness path for general Windows Event Log and Perfmon
  prerequisites.
- Validate with source type and index coverage before handing data to ES or ITSI.

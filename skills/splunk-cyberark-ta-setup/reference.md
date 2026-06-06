# CyberArk Splunk Add-ons Reference

## Package Identity

| Product | App directory | Splunkbase | Verified | Support note |
| --- | --- | --- | --- | --- |
| CyberArk EPM | `Splunk_TA_cyberark_epm` | `5160` | `4.0.0` | Supported API collection path |
| CyberArk EPV/PTA | `Splunk_TA_cyberark` | `2891` | `1.2.0` | Archived/not-supported parser-only path |

## EPM Inputs And Source Types

Inputs verified from the package include `application_events`, `inbox_events`,
`admin_audit_logs`, `account_admin_audit_logs`, `policy_audit`,
`policy_audit_events`, `threat_detection`, and `policies_and_computers`.

Package source types include `cyberark:epm:raw:events`,
`cyberark:epm:raw:policy:events`, `cyberark:epm:admin:audit`,
`cyberark:epm:account:admin:audit`, `cyberark:epm:application:events`,
`cyberark:epm:policy:audit`, and `cyberark:epm:threat:detection`.

## EPV/PTA Parser Source Types

- `cyberark:epv:cef`
- `cyberark:pta:cef`

The EPV/PTA package has no modular inputs. Own transport through SC4S, syslog,
or a reviewed file/HEC pipeline and stamp the exact package source type.

## Guardrails

- Do not hide the archived EPV/PTA status in plans or metadata.
- Store EPM API credentials only through the add-on account handler.
- Avoid generic `cef`/`syslog` readiness matching; require the exact CyberArk
  package source type or a constrained source/source-type pair.

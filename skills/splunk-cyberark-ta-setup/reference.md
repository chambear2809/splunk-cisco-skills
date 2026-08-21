# CyberArk Splunk Add-ons Reference

## Package Identity

| Product | App directory | Splunkbase | Verified | Support note |
| --- | --- | --- | --- | --- |
| CyberArk EPM | `Splunk_TA_cyberark_epm` | `5160` | `5.0.0` | Supported API collection path |
| CyberArk EPV/PTA | `Splunk_TA_cyberark` | `2891` | `1.2.0` | Archived/not-supported parser-only path |

## EPM Inputs And Source Types

Inputs verified from the `5.0.0` package are `inbox_events`,
`policy_audit_events`, `policies_and_computers`, `admin_audit_logs`, and
`account_admin_audit_logs`.

Package source types are `cyberark:epm:raw:events`,
`cyberark:epm:aggregated:events`, `cyberark:epm:raw:policy:audit`,
`cyberark:epm:aggregated:policy:audit`, `cyberark:epm:policies`,
`cyberark:epm:computers`, `cyberark:epm:computer:groups`,
`cyberark:epm:admin:audit`, and `cyberark:epm:account:admin:audit`.

### 4.0.0 To 5.0.0 Migration

`5.0.0` is a breaking major release. It removes the `application_events`,
`policy_audit`, and `threat_detection` modular inputs together with their
`splunk_ta_cyberark_epm_application_events`,
`splunk_ta_cyberark_epm_policy_audit`, and
`splunk_ta_cyberark_epm_threat_detection` REST handlers, drops the
`cyberark:epm:application:events`, `cyberark:epm:policy:audit`, and
`cyberark:epm:threat:detection` source types, and renames
`cyberark:epm:raw:policy:events` to `cyberark:epm:raw:policy:audit`. Retune any
saved search, dashboard, or CIM mapping that still references the removed or
renamed names before upgrading. `5.0.0` adds the
`splunk_ta_cyberark_epm_settings` and `splunk_ta_cyberark_epm_fetch_set_ids`
handlers.

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

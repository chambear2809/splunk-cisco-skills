# Cisco ASA TA Reference

Primary package: `Splunk_TA_cisco-asa` (Splunkbase `1620`, verified docs
version `6.0.1`).

## Data Contract

| Item | Value |
| --- | --- |
| Default index | `cisco_asa` |
| Source type | `cisco:asa` |
| Devices | Cisco ASA and Cisco Firepower Threat Defense syslog |
| CIM targets | `Network_Traffic`, `Intrusion_Detection` |

## Guardrails

- Collect ASA/FTD logs through SC4S, syslog-ng, rsyslog, or another reviewed
  syslog receiver; the TA does not receive network syslog by itself.
- Install parser/search-time knowledge on the search tier and any parsing tier
  used by the selected receiver path.
- Do not treat generic `syslog` as readiness evidence unless receiver metadata
  proves Cisco ASA ownership and events normalize to `cisco:asa`.
- Hand off CIM acceleration and ES detection readiness to
  `splunk-cim-data-model-setup` and `splunk-enterprise-security-config`.

# Security Appliance Supported Add-ons Reference

Package source of truth:

| Selector | App | Splunkbase | Verified |
| --- | --- | --- | --- |
| `carbon_black` | `Splunk_TA_bit9-carbonblack` | `2790` | `3.0.0` |
| `symantec_endpoint_protection` | `Splunk_TA_symantec-ep` | `2772` | `4.0.0` |

## Package-Derived Source Types

Carbon Black source type: `bit9:carbonblack:json`.

Symantec Endpoint Protection file source types include
`symantec:ep:admin:file`, `symantec:ep:risk:file`,
`symantec:ep:security:file`, and `symantec:ep:traffic:file`. Syslog source
types include `symantec:ep:syslog`, `symantec:ep:admin:syslog`,
`symantec:ep:risk:syslog`, `symantec:ep:security:syslog`, and
`symantec:ep:traffic:syslog`.

## Guardrails

- Carbon Black package input is a JSON file monitor; the upstream export/script
  or pub/sub process owns delivery to the monitored directory.
- Symantec Endpoint Protection may be file monitor or syslog/SC4S. Do not leave
  the data stamped as generic `syslog`.
- Imperva, McAfee/Trellix, Sophos, DLP, Websense DLP, RSA DLP, and OSSEC remain
  install-only in the supported-addons router until exact packages are
  extracted and verified.

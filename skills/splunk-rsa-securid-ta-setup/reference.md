# RSA SecurID Splunk Add-ons Reference

## Package Identity

| Product | App directory | Splunkbase | Verified | Path |
| --- | --- | --- | --- | --- |
| RSA SecurID AM | `Splunk_TA_rsa-securid` | `2958` | `1.5.0` | Syslog/parser |
| RSA SecurID CAS | `Splunk_TA_rsa_securid_cas` | `5210` | `1.2.2` | API modular input |

## CAS Inputs And Source Types

The CAS package defines `cloud_administration_api://<name>` inputs for
administration, user event, and high-risk user collection. Package source types:

- `rsa:securid:cas:adminlog:json`
- `rsa:securid:cas:usereventlog:json`
- `rsa:securid:cas:riskuser:json`

## AM Parser Source Types

- `rsa:securid:syslog`
- `rsa:securid:admin:syslog`
- `rsa:securid:runtime:syslog`
- `rsa:securid:system:syslog`

## Guardrails

- Store CAS API credentials only through the add-on account handler.
- Own AM transport through syslog/SC4S and stamp exact package source types.
- Do not use generic `syslog` as readiness evidence without a constrained RSA
  AM source and normalized package source type.

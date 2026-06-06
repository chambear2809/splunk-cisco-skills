---
name: splunk-rsa-securid-ta-setup
description: >-
  Umbrella render, install, and validation workflow for RSA SecurID Splunk
  add-ons: RSA SecurID Authentication Manager syslog parsing
  (Splunk_TA_rsa-securid, Splunkbase 2958) and RSA SecurID Cloud
  Authentication Service API collection (Splunk_TA_rsa_securid_cas,
  Splunkbase 5210). Renders CAS inputs, AM syslog handoffs, encrypted account
  setup, metadata, and validation SPL. Use when the user asks to onboard,
  configure, render, or validate RSA SecurID data in Splunk.
---

# RSA SecurID Splunk Add-on Setup

Render-first umbrella workflow for RSA SecurID Authentication Manager and RSA
SecurID Cloud Authentication Service. CAS is API-driven; AM is syslog/parser
based.

## Workflow

```bash
bash skills/splunk-rsa-securid-ta-setup/scripts/setup.sh --render \
  --products cas,am --index rsa
```

Configure the CAS account from `account-setup.md`, and use
`transport-handoff.md` for AM syslog ownership.

```bash
bash skills/splunk-rsa-securid-ta-setup/scripts/validate.sh --index rsa
```

Readiness handoffs: `rsa_securid_cas` and `rsa_securid_am`.

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

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

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

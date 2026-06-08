---
name: splunk-cyberark-ta-setup
description: >-
  Umbrella render, install, and validation workflow for CyberArk Splunk add-ons:
  supported CyberArk EPM API collection (Splunk_TA_cyberark_epm, Splunkbase
  5160) and archived/not-supported CyberArk EPV/PTA CEF parsing
  (Splunk_TA_cyberark, Splunkbase 2891). Renders product-specific inputs,
  syslog/SC4S handoffs, encrypted account setup, metadata, and validation SPL.
  Use when the user asks to onboard, configure, render, or validate CyberArk
  data in Splunk.
---

# CyberArk Splunk Add-on Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first umbrella workflow for CyberArk EPM and legacy EPV/PTA parsing.
The skill keeps the support boundary explicit: `Splunk_TA_cyberark_epm`
(Splunkbase `5160`, verified `4.0.0`) is the supported API path, while
`Splunk_TA_cyberark` (Splunkbase `2891`, verified `1.2.0`) is archived and
parser-only.

## Workflow

```bash
bash skills/splunk-cyberark-ta-setup/scripts/setup.sh --render \
  --products epm,epv_pta --index cyberark
```

Configure the EPM account from `account-setup.md`, and use `transport-handoff.md`
for EPV/PTA CEF transport ownership.

```bash
bash skills/splunk-cyberark-ta-setup/scripts/validate.sh --index cyberark
```

Readiness handoffs: `cyberark_epm` and `cyberark_epv_pta`.

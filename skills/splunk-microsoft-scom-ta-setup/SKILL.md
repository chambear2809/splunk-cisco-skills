---
name: splunk-microsoft-scom-ta-setup
description: >-
  Render, install, and validate the package-verified Splunk Add-on for
  Microsoft SCOM (Splunk_TA_microsoft-scom, Splunkbase 2729). Covers
  package-derived PowerShell inputs, microsoft:scom* source types, eventtypes,
  lookups, index readiness, and readiness-doctor handoffs. Use when the user
  asks to onboard, configure, or validate Microsoft System Center Operations
  Manager data in Splunk.
---

# Microsoft SCOM Supported Add-on Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first workflow for `Splunk_TA_microsoft-scom` `4.5.0`, Splunkbase
`2729`.

## Workflow

```bash
bash skills/splunk-microsoft-scom-ta-setup/scripts/setup.sh --phase render \
  --index scom --account-name scom_prod
```

Review `inputs.local.conf.template`, `account-setup.md`, install commands, and
validation SPL.

```bash
bash skills/splunk-microsoft-scom-ta-setup/scripts/setup.sh --install --create-index \
  --index scom --no-restart
```

```bash
bash skills/splunk-microsoft-scom-ta-setup/scripts/validate.sh --index scom
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack microsoft_scom
```

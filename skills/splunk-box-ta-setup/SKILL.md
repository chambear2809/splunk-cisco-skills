---
name: splunk-box-ta-setup
description: >-
  Install, render, configure, and validate the Splunk Add-on for Box
  (Splunk_TA_box, Splunkbase 2679). Renders Box historical event, live
  monitoring, and file-ingestion inputs, encrypted OAuth account handoffs, Box
  index creation, package-backed box:* source-type validation SPL, and
  readiness-doctor source-pack coverage. Use when the user asks to onboard,
  configure, render, or validate Box data in Splunk.
---

# Splunk Add-on for Box Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first automation for `Splunk_TA_box` (Splunkbase `2679`, verified
`4.0.0`). The renderer emits reviewable Box service inputs, an OAuth account
runbook, install commands, metadata, and validation SPL. It never handles Box
secret values.

## Workflow

```bash
bash skills/splunk-box-ta-setup/scripts/setup.sh --render \
  --index box --account-name box_prod
```

Configure the Box account from `account-setup.md`, review
`inputs.local.conf.template`, and enable selected inputs.

```bash
bash skills/splunk-box-ta-setup/scripts/validate.sh --index box
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack box
```

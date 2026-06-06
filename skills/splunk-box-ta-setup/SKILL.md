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

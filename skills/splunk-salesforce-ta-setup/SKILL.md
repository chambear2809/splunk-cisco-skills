---
name: splunk-salesforce-ta-setup
description: >-
  Install, render, configure, and validate the Splunk Add-on for Salesforce
  (Splunk_TA_salesforce, Splunkbase 3549). Renders Salesforce object and event
  log inputs, encrypted account setup handoffs, Salesforce index creation,
  package-backed sfdc:* source-type validation SPL, and readiness-doctor source
  pack coverage. Use when the user asks to onboard, configure, render, or
  validate Salesforce data in Splunk.
---

# Splunk Add-on for Salesforce Setup

Render-first automation for `Splunk_TA_salesforce` (Splunkbase `3549`, verified
`6.0.2`). The renderer emits reviewable object/event-log inputs, an OAuth or
connected-app account runbook, install commands, metadata, and validation SPL.
It never handles Salesforce secret values.

## Workflow

```bash
bash skills/splunk-salesforce-ta-setup/scripts/setup.sh --render \
  --index salesforce --account-name salesforce_prod
```

Configure the add-on account from `account-setup.md`, review
`inputs.local.conf.template`, and enable selected inputs.

```bash
bash skills/splunk-salesforce-ta-setup/scripts/validate.sh --index salesforce
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack salesforce
```

See `reference.md` for package-derived inputs, source types, REST handlers, and
CIM guardrails.

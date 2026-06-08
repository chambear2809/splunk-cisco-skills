---
name: splunk-security-appliance-ta-setup
description: >-
  Render, install, and validate first-pass package-verified security appliance
  supported add-ons for Carbon Black and Symantec Endpoint Protection. Covers
  Splunk_TA_bit9-carbonblack and Splunk_TA_symantec-ep app IDs, versions,
  package-derived source types, file/syslog transport ownership, eventtypes,
  lookups, and readiness-doctor handoffs. Use when the user asks for Carbon
  Black or Symantec EP supported add-on onboarding when package extraction has
  verified coverage.
---

# Security Appliance Supported Add-ons Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first workflow for the verified security appliance packages:

- `Splunk_TA_bit9-carbonblack` `3.0.0`, Splunkbase `2790`
- `Splunk_TA_symantec-ep` `4.0.0`, Splunkbase `2772`

Other security products remain supported-addons install-only until their exact
packages are resolved and extracted.

## Workflow

```bash
bash skills/splunk-security-appliance-ta-setup/scripts/setup.sh --phase render \
  --products carbon_black,symantec_endpoint_protection --index endpoint
```

Review `transport-handoff.md`, `inputs.local.conf.template`, install commands,
and validation SPL.

```bash
bash skills/splunk-security-appliance-ta-setup/scripts/setup.sh --install --create-index \
  --index endpoint --no-restart
```

```bash
bash skills/splunk-security-appliance-ta-setup/scripts/validate.sh --index endpoint
```

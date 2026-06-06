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

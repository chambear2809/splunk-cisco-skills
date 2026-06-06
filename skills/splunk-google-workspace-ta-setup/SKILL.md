---
name: splunk-google-workspace-ta-setup
description: >-
  Install, render, configure, and validate the Splunk Add-on for Google
  Workspace (Splunk_TA_Google_Workspace, Splunkbase 5556). Renders
  package-backed activity_report, gws_gmail_logs, gws_gmail_logs_migrated,
  gws_user_identity, gws_alert_center, and gws_usage_report inputs; emits a
  service-account certificate runbook, proxy/logging settings, the
  google_workspace readiness handoff, and validation SPL. Use for Google
  Workspace, G Suite, Gmail logs, Google Admin reports, Workspace Alert Center,
  or Splunk_TA_Google_Workspace onboarding. Use when the user asks to onboard,
  configure, render, or validate Google Workspace data in Splunk.
---

# Splunk Add-on for Google Workspace Setup

Render-first automation for `Splunk_TA_Google_Workspace` (Splunkbase `5556`,
verified `4.0.0`). The renderer emits reviewable `inputs.conf` and settings
overlays for the six package input families and a service-account/certificate
runbook. It never handles certificate material.

## Workflow

1. Render offline assets:

```bash
bash skills/splunk-google-workspace-ta-setup/scripts/setup.sh --render \
  --index google_workspace --account-name gws_prod
```

2. Install the add-on and create the index:

```bash
bash skills/splunk-google-workspace-ta-setup/scripts/setup.sh --install --create-index --index google_workspace
```

3. Configure the Google Workspace account from the rendered
   `account-setup.md`, review `inputs.local.conf.template`, and enable only the
   desired input stanzas.

4. Validate:

```bash
bash skills/splunk-google-workspace-ta-setup/scripts/validate.sh --index google_workspace
```

5. Score data readiness:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack google_workspace
```

See `reference.md` for source types, package handlers, and guardrails.

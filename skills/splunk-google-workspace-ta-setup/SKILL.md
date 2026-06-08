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

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

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

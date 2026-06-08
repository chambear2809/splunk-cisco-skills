---
name: splunk-microsoft-security-ta-setup
description: >-
  Install, render, configure, and validate the Splunk Add-on for Microsoft
  Security (Splunk_TA_MS_Security, Splunkbase 6207). Renders package-backed
  Defender incidents, endpoint alerts, machines, simulations, Event Hub /
  Advanced Hunting, and Threat Intelligence inputs; emits Entra app account
  runbooks, Splunk Cloud UI-only and Event Hub egress caveats, macros for
  package dashboards/searches, migration notes, and validation SPL. Use for
  Microsoft 365 Defender, Defender for Endpoint, Microsoft Security, or
  Splunk_TA_MS_Security onboarding. Use when the user asks to onboard,
  configure, render, or validate Microsoft Security / Defender data in Splunk.
---

# Splunk Add-on for Microsoft Security Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first automation for `Splunk_TA_MS_Security` (Splunkbase `6207`,
verified `3.0.0`). The renderer emits reviewable inputs, macro overlays for
package-shipped searches, an Entra app/client-secret account runbook, and
validation SPL. It never handles Microsoft client secrets.

## Workflow

```bash
bash skills/splunk-microsoft-security-ta-setup/scripts/setup.sh --render \
  --index microsoft_security --account-name ms_security_prod
```

```bash
bash skills/splunk-microsoft-security-ta-setup/scripts/setup.sh \
  --install --create-index --index microsoft_security
```

Configure the account from `account-setup.md`, review
`inputs.local.conf.template` and `macros.local.conf.template`, then enable the
selected inputs.

```bash
bash skills/splunk-microsoft-security-ta-setup/scripts/validate.sh --index microsoft_security
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack microsoft_security
```

See `reference.md` for input/source-type mapping and package alert actions.

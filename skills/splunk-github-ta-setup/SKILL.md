---
name: splunk-github-ta-setup
description: >-
  Install, render, configure, and validate the Splunk Add-on for GitHub
  (Splunk_TA_github, Splunkbase 6254). Renders GitHub Cloud audit, user, and
  code/dependabot/secret scanning alert inputs; emits PAT and HEC token
  runbooks, GitHub Cloud HEC audit streaming guidance, GHES syslog/SC4S
  handoffs, expanded github_audit readiness coverage, and validation SPL. Use
  for GitHub audit logs, GitHub Enterprise Cloud, GHES audit, GitHub security
  scanning alerts, or Splunk_TA_github onboarding. Use when the user asks to
  onboard, configure, render, or validate GitHub audit/security data in Splunk.
---

# Splunk Add-on for GitHub Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first automation for `Splunk_TA_github` (Splunkbase `6254`, verified
`3.3.0`). The renderer emits reviewable GitHub Cloud API inputs, a PAT account
runbook, HEC/syslog handoffs, and validation SPL. It never handles PAT or HEC
token values.

## Workflow

```bash
bash skills/splunk-github-ta-setup/scripts/setup.sh --render \
  --index github --account-name github_prod
```

```bash
bash skills/splunk-github-ta-setup/scripts/setup.sh --install --create-index --index github
```

Configure the GitHub account from `account-setup.md`, review
`inputs.local.conf.template`, and enable selected inputs.

```bash
bash skills/splunk-github-ta-setup/scripts/validate.sh --index github
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack github_audit
```

See `reference.md` for source types and HEC/GHES guardrails.

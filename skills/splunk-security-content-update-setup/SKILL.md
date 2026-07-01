---
name: splunk-security-content-update-setup
description: >-
  Render, install, and validate Splunk Enterprise Security Content Update
  readiness for DA-ESS-ContentUpdate, ES search-head placement, package delivery,
  Analytic Story Detail navigation, content inventory checks, correlation-search
  activation review, and ES configuration handoff. Use when the user asks to
  install, upgrade, review, or validate ESCU or Splunk security content.
---

# Splunk Security Content Update Setup

## Shared add-on completion gate

Whenever this workflow installs, configures, or hands off ESCU, follow the
[shared completion gate](../shared/ta_completion_gate.md). Package delivery
alone is not success; validate content prerequisites, enabled searches, and
shipped views against data.

Render-first workflow for `DA-ESS-ContentUpdate` (ESCU). It produces a
reviewable install/upgrade plan, ES placement checks, analytic-story inventory
SPL, correlation-search activation review, and handoffs to ES configuration.
Its explicit `--install` and `--all` modes install the ESCU package; search
enablement and content mutation remain outside this skill.

## Workflow

```bash
bash skills/splunk-security-content-update-setup/scripts/setup.sh --render \
  --platform auto --es-app SplunkEnterpriseSecuritySuite
```

## Execute

Preview the package-install plan:

```bash
bash skills/splunk-security-content-update-setup/scripts/setup.sh --all \
  --dry-run --json
```

Install ESCU and run validation:

```bash
bash skills/splunk-security-content-update-setup/scripts/setup.sh --all --live
```

This installs the app package only. Correlation-search enablement and ES content
changes remain delegated to `splunk-enterprise-security-config`.

```bash
bash skills/splunk-security-content-update-setup/scripts/validate.sh \
  --rendered-dir splunk-security-content-update-rendered --live
```

See `reference.md` for ESCU placement and activation-review guardrails.

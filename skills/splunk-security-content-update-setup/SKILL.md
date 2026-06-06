---
name: splunk-security-content-update-setup
description: >-
  Render and validate Splunk Enterprise Security Content Update readiness for
  DA-ESS-ContentUpdate, ES search-head placement, install or upgrade planning,
  Analytic Story Detail navigation, content inventory checks, correlation-search
  activation review, and ES configuration handoff. Use when the user asks to
  install, upgrade, review, or validate ESCU or Splunk security content.
---

# Splunk Security Content Update Setup

Render-first workflow for `DA-ESS-ContentUpdate` (ESCU). It produces a
reviewable install/upgrade plan, ES placement checks, analytic-story inventory
SPL, correlation-search activation review, and handoffs to ES configuration.
No ESCU app install, search enablement, or content mutation is performed here.

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

---
name: splunk-fraud-analytics-setup
description: >-
  Render, install, and validate Splunk App for Fraud Analytics readiness,
  including ES dependency checks, Lookup File Editing prerequisite, fraud use-case intake,
  risk index and RBA prerequisites, correlation-search review, data-model
  prerequisites, package handoff, and validation SPL. Use when the user asks to
  install, plan, configure, or validate Splunk Fraud Analytics.
---

# Splunk Fraud Analytics Setup

Render-first workflow for Splunk App for Fraud Analytics. It emits prerequisite
checks, use-case intake, ES/RBA and lookup-editor handoffs, correlation-search
review, data-model validation SPL, and readiness evidence. Its explicit
`--install` and `--all` modes install an operator-supplied local package; it
does not enable detections or mutate ES/RBA and lookup content.

## Workflow

```bash
bash skills/splunk-fraud-analytics-setup/scripts/setup.sh --render \
  --platform auto --fraud-use-case account-takeover --risk-index risk
```

## Execute

Fraud Analytics install execution requires a local package file:

```bash
bash skills/splunk-fraud-analytics-setup/scripts/setup.sh --all \
  --file /path/to/fraud-analytics-package.tgz --dry-run --json
```

Run the package install and validation:

```bash
bash skills/splunk-fraud-analytics-setup/scripts/setup.sh --all \
  --file /path/to/fraud-analytics-package.tgz --live
```

ES/RBA activation and lookup changes remain delegated to the owning ES and
Lookup File Editing workflows.

```bash
bash skills/splunk-fraud-analytics-setup/scripts/validate.sh \
  --rendered-dir splunk-fraud-analytics-rendered --live
```

See `reference.md` for prerequisites and review gates.

---
name: splunk-pci-compliance-setup
description: >-
  Render, install, and validate Splunk App for PCI Compliance readiness,
  including package delivery, cardholder data environment index and macro intake,
  Enterprise Security or standalone installer selection, CIM/data-model
  prerequisites, roles, reports, dashboard evidence, and dependency handoffs.
  Use when the user asks to install, configure, prepare, or validate PCI
  Compliance for Splunk.
---

# Splunk PCI Compliance Setup

## Shared add-on completion gate

Whenever this workflow installs, configures, or hands off the PCI app or one of
its add-on dependencies, follow the
[shared completion gate](../shared/ta_completion_gate.md). Package delivery
alone is not success; validate CDE ingest, macros, reports, and shipped
dashboards against data.

Render-first workflow for the Splunk App for PCI Compliance. It emits
installer-selection guidance, CDE index/macro intake, CIM prerequisites,
role/report checks, dashboard readiness SPL, and handoffs. Its explicit
`--install` and `--all` modes install the selected PCI package; it does not
alter compliance content, CDE macros, CIM acceleration, roles, or reports.

## Workflow

```bash
bash skills/splunk-pci-compliance-setup/scripts/setup.sh --render \
  --platform auto --cde-indexes cardholder,netfw --pci-macro pci_indexes
```

## Execute

Preview the selected installer path:

```bash
bash skills/splunk-pci-compliance-setup/scripts/setup.sh --all \
  --installer-profile enterprise-security --dry-run --json
```

Install and validate:

```bash
bash skills/splunk-pci-compliance-setup/scripts/setup.sh --all \
  --installer-profile enterprise-security --live
```

Use `--installer-profile enterprise` for the standalone Splunk Enterprise app.
CDE macros, CIM acceleration, and report governance remain delegated.

```bash
bash skills/splunk-pci-compliance-setup/scripts/validate.sh \
  --rendered-dir splunk-pci-compliance-rendered --live
```

See `reference.md` for installer and CDE guardrails.

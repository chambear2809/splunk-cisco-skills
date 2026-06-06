---
name: splunk-pci-compliance-setup
description: >-
  Render and validate Splunk App for PCI Compliance readiness, including app
  install planning, cardholder data environment index and macro intake,
  Enterprise Security or standalone installer selection, CIM/data-model
  prerequisites, roles, reports, dashboard evidence, and dependency handoffs.
  Use when the user asks to install, configure, prepare, or validate PCI
  Compliance for Splunk.
---

# Splunk PCI Compliance Setup

Render-first workflow for the Splunk App for PCI Compliance. It emits
installer-selection guidance, CDE index/macro intake, CIM prerequisites,
role/report checks, dashboard readiness SPL, and handoffs. It does not install
PCI packages or alter compliance content.

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

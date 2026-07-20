---
name: splunk-pci-compliance-setup
description: "Use when the user asks to install, configure, prepare, or validate PCI Compliance for Splunk. Render,
  install, and validate Splunk App for PCI Compliance readiness, including package delivery, cardholder
  data environment index and macro intake, Enterprise Security or standalone installer selection,
  CIM/data-model prerequisites, roles, reports, dashboard evidence, and dependency handoffs."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk PCI Compliance Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Install, configure, prepare, or validate PCI Compliance for Splunk.
- Preview and review the splunk pci compliance setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-pci-compliance-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-pci-compliance-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

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

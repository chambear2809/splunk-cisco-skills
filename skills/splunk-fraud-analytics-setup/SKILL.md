---
name: splunk-fraud-analytics-setup
description: "Use when the user asks to install, plan, configure, or validate Splunk Fraud Analytics. Render, install,
  and validate Splunk App for Fraud Analytics readiness, including ES dependency checks, Lookup File
  Editing prerequisite, fraud use-case intake, risk index and RBA prerequisites, correlation-search
  review, data-model prerequisites, package handoff, and validation SPL."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Fraud Analytics Setup

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

- Install, plan, configure, or validate Splunk Fraud Analytics.
- Preview and review the splunk fraud analytics setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-fraud-analytics-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-fraud-analytics-setup/scripts/validate.sh --help
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

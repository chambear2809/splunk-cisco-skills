---
name: splunk-microsoft-exchange-ta-setup
description: "Use when the user asks for Splunk Supported Add-on for Microsoft Exchange onboarding and validation.
  Render, install, and validate the package-verified Microsoft Exchange supported add-on bundle and
  Exchange Indexes package. Covers TA-Exchange-ClientAccess, TA-Exchange-Mailbox, TA-SMTP-Reputation, TA-
  Windows-Exchange-IIS, SA-ExchangeIndex, package-derived source types, Windows collection placement,
  msexchange/perfmon/windows/wineventlog/msad index readiness, and readiness-doctor handoffs."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Microsoft Exchange Supported Add-on Setup

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

- The user asks for Splunk Supported Add-on for Microsoft Exchange onboarding and validation.
- Preview and review the splunk microsoft exchange ta setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-microsoft-exchange-ta-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-microsoft-exchange-ta-setup/scripts/validate.sh --help
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

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first workflow for the verified Microsoft Exchange packages:

- Exchange bundle `4.1.0`, Splunkbase `3225`
- Exchange Indexes `SA-ExchangeIndex` `4.0.4`, Splunkbase `5663`

## Workflow

```bash
bash skills/splunk-microsoft-exchange-ta-setup/scripts/setup.sh --phase render \
  --index msexchange --windows-index windows --perfmon-index perfmon
```

Review `collection-placement.md`, `inputs.local.conf.template`,
`install-commands.sh`, and `validation-searches.spl`.

```bash
bash skills/splunk-microsoft-exchange-ta-setup/scripts/setup.sh --install --no-restart
```

```bash
bash skills/splunk-microsoft-exchange-ta-setup/scripts/validate.sh --index msexchange
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack microsoft_exchange
```

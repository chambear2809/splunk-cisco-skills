---
name: splunk-salesforce-ta-setup
description: "Use when the user asks to onboard, configure, render, or validate Salesforce data in Splunk. Install,
  render, configure, and validate the Splunk Add-on for Salesforce (Splunk_TA_salesforce, Splunkbase
  3549). Renders Salesforce object and event log inputs, encrypted account setup handoffs, Salesforce
  index creation, package-backed sfdc:* source-type validation SPL, and readiness-doctor source pack
  coverage."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Splunk Add-on for Salesforce Setup

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

- Onboard, configure, render, or validate Salesforce data in Splunk.
- Preview and review the splunk salesforce ta setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-salesforce-ta-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-salesforce-ta-setup/scripts/validate.sh --help
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

Render-first automation for `Splunk_TA_salesforce` (Splunkbase `3549`, verified
`7.0.0`). The renderer emits reviewable object/event-log inputs, an OAuth or
connected-app account runbook, install commands, metadata, and validation SPL.
It never handles Salesforce secret values.

## Package Verification Boundary

The package-derived baseline is `7.0.0`, the current public release, which
advertises Splunk 10.5. Both `6.0.2` and `7.0.0` were unpacked and diffed here,
and the rendered templates follow `7.0.0`, so the shared installer's default pin
needs no review override. When Splunkbase publishes a newer release, re-check
its input schema, REST handlers, source types, and shipped views before
advancing the pin.

## Workflow

```bash
bash skills/splunk-salesforce-ta-setup/scripts/setup.sh --render \
  --index salesforce --account-name salesforce_prod
```

Configure the add-on account from `account-setup.md`, review
`inputs.local.conf.template`, and enable selected inputs.

```bash
bash skills/splunk-salesforce-ta-setup/scripts/validate.sh --index salesforce
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack salesforce
```

See `reference.md` for package-derived inputs, source types, REST handlers, and
CIM guardrails.

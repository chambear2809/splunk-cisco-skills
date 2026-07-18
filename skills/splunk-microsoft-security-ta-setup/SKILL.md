---
name: splunk-microsoft-security-ta-setup
description: "Use when the user asks to onboard, configure, render, or validate Microsoft Security / Defender data in
  Splunk. Install, render, configure, and validate the Splunk Add-on for Microsoft Security
  (Splunk_TA_MS_Security, Splunkbase 6207). Renders package-backed Defender incidents, endpoint alerts,
  machines, simulations, Event Hub / Advanced Hunting, and Threat Intelligence inputs; emits Entra app
  account runbooks, Splunk Cloud UI-only and Event Hub egress caveats, macros for package
  dashboards/searches, migration notes, and validation SPL. Use for Microsoft 365 Defender, Defender for
  Endpoint, Microsoft Security, or Splunk_TA_MS_Security onboarding."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Add-on for Microsoft Security Setup

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

- Onboard, configure, render, or validate Microsoft Security / Defender data in Splunk.
- Preview and review the splunk microsoft security ta setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-microsoft-security-ta-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-microsoft-security-ta-setup/scripts/validate.sh --help
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

Render-first automation for `Splunk_TA_MS_Security` (Splunkbase `6207`,
verified `3.0.0`). The renderer emits reviewable inputs, macro overlays for
package-shipped searches, an Entra app/client-secret account runbook, and
validation SPL. It never handles Microsoft client secrets.

## Workflow

```bash
bash skills/splunk-microsoft-security-ta-setup/scripts/setup.sh --render \
  --index microsoft_security --account-name ms_security_prod
```

```bash
bash skills/splunk-microsoft-security-ta-setup/scripts/setup.sh \
  --install --create-index --index microsoft_security
```

Configure the account from `account-setup.md`, review
`inputs.local.conf.template` and `macros.local.conf.template`, then enable the
selected inputs.

```bash
bash skills/splunk-microsoft-security-ta-setup/scripts/validate.sh --index microsoft_security
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack microsoft_security
```

See `reference.md` for input/source-type mapping and package alert actions.

---
name: splunk-security-appliance-ta-setup
description: "Use when the user asks for Carbon Black or Symantec EP supported add-on onboarding when package
  extraction has verified coverage. Render, install, and validate first-pass package-verified security
  appliance supported add-ons for Carbon Black and Symantec Endpoint Protection. Covers
  Splunk_TA_bit9-carbonblack and Splunk_TA_symantec-ep app IDs, versions, package-derived source types,
  file/syslog transport ownership, eventtypes, lookups, and readiness-doctor handoffs."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Security Appliance Supported Add-ons Setup

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

- The user asks for Carbon Black or Symantec EP supported add-on onboarding when package extraction has verified
  coverage.
- Preview and review the splunk security appliance ta setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-security-appliance-ta-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-security-appliance-ta-setup/scripts/validate.sh --help
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

Render-first workflow for the verified security appliance packages:

- `Splunk_TA_bit9-carbonblack` `3.0.0`, Splunkbase `2790`
- `Splunk_TA_symantec-ep` `4.0.0`, Splunkbase `2772`

Other security products remain supported-addons install-only until their exact
packages are resolved and extracted.

## Workflow

```bash
bash skills/splunk-security-appliance-ta-setup/scripts/setup.sh --phase render \
  --products carbon_black,symantec_endpoint_protection --index endpoint
```

Review `transport-handoff.md`, `inputs.local.conf.template`, install commands,
and validation SPL.

```bash
bash skills/splunk-security-appliance-ta-setup/scripts/setup.sh --install --create-index \
  --index endpoint --no-restart
```

```bash
bash skills/splunk-security-appliance-ta-setup/scripts/validate.sh --index endpoint
```

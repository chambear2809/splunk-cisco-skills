---
name: splunk-rsa-securid-ta-setup
description: "Use when the user asks to onboard, configure, render, or validate RSA SecurID data in Splunk. Umbrella
  render, install, and validation workflow for RSA SecurID Splunk add-ons: RSA SecurID Authentication
  Manager syslog parsing (Splunk_TA_rsa-securid, Splunkbase 2958) and RSA SecurID Cloud Authentication
  Service API collection (Splunk_TA_rsa_securid_cas, Splunkbase 5210). Renders CAS inputs, AM syslog
  handoffs, encrypted account setup, metadata, and validation SPL."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# RSA SecurID Splunk Add-on Setup

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

- Onboard, configure, render, or validate RSA SecurID data in Splunk.
- Preview and review the splunk rsa securid ta setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-rsa-securid-ta-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-rsa-securid-ta-setup/scripts/validate.sh --help
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

Render-first umbrella workflow for RSA SecurID Authentication Manager and RSA
SecurID Cloud Authentication Service. CAS is API-driven; AM is syslog/parser
based.

## Workflow

```bash
bash skills/splunk-rsa-securid-ta-setup/scripts/setup.sh --render \
  --products cas,am --index rsa
```

Configure the CAS account from `account-setup.md`, and use
`transport-handoff.md` for AM syslog ownership.

```bash
bash skills/splunk-rsa-securid-ta-setup/scripts/validate.sh --index rsa
```

Readiness handoffs: `rsa_securid_cas` and `rsa_securid_am`.

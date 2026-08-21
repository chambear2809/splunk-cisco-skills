---
name: splunk-netapp-ontap-ta-setup
description: "Use when the user asks to onboard or validate NetApp Data ONTAP, ONTAP extractions, or ONTAP indexes in
  Splunk. Render, install, and validate package-verified NetApp ONTAP supported add-ons: Splunk_TA_ontap,
  TA-ONTAP-FieldExtractions, and SA-ONTAPIndex. Covers scheduler/worker placement, ontap index creation,
  ontap:* and Hydra source type validation, troubleshooting checks, and ITSI storage handoffs."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# NetApp ONTAP Supported Add-ons Setup

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

- Onboard or validate NetApp Data ONTAP, ONTAP extractions, or ONTAP indexes in Splunk.
- Preview and review the splunk netapp ontap ta setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-netapp-ontap-ta-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-netapp-ontap-ta-setup/scripts/validate.sh --help
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

Render-first workflow for verified ONTAP packages:

- `Splunk_TA_ontap` `3.2.1`, Splunkbase `3418`
- `TA-ONTAP-FieldExtractions` `3.0.3`, Splunkbase `5615`
- `SA-ONTAPIndex` `3.0.3`, Splunkbase `5616`

## Workflow

```bash
bash skills/splunk-netapp-ontap-ta-setup/scripts/setup.sh --phase render \
  --products ontap,extractions,indexes --index ontap
```

Review `scheduler-worker-placement.md`, install commands, and validation SPL.

```bash
bash skills/splunk-netapp-ontap-ta-setup/scripts/setup.sh --install --create-index \
  --index ontap --no-restart
```

```bash
bash skills/splunk-netapp-ontap-ta-setup/scripts/validate.sh --index ontap
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack netapp_ontap
```

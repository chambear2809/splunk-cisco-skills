---
name: splunk-observability-metrics-pipeline-setup
description: "Use when the user asks about MPM, metrics pipeline management, metric cardinality, MTS reduction, or
  Observability metric routing and aggregation. Render and validate focused Splunk Observability Cloud
  Metrics Pipeline Management plans, including metric usage review, cardinality and MTS controls,
  drop/archive/route/aggregate intent, exception planning, dashboard and detector handoffs, and deep-
  native-workflow delegated specs."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Splunk Observability Metrics Pipeline Setup

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

- MPM, metrics pipeline management, metric cardinality, MTS reduction, or Observability metric routing and
  aggregation.
- Preview and review the splunk observability metrics pipeline setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-observability-metrics-pipeline-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-observability-metrics-pipeline-setup/scripts/validate.sh --help
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

Focused Metrics Pipeline Management wrapper over
`splunk-observability-deep-native-workflows`. It renders reviewable MPM intent
and downstream specs; broader ingestion pipeline work still belongs to OTel
Collector, Edge Processor, Ingest Processor, or SPL2 pipeline skills.

```bash
bash skills/splunk-observability-metrics-pipeline-setup/scripts/setup.sh --render \
  --name "Checkout metric cardinality review" \
  --metric service.request.duration \
  --action aggregate \
  --realm us1
```

Then execute the generated deep-native renderer and follow its exact UI and
downstream pipeline handoffs:

```bash
bash splunk-observability-metrics-pipeline-rendered/delegate-deep-native-workflows.sh
```

The delegate explicitly rejects `--apply`: this repository has no verified
public MPM mutation API, so it does not report a successful write for a UI-only
operation.

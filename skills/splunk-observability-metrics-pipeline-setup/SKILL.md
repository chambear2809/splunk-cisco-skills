---
name: splunk-observability-metrics-pipeline-setup
description: >-
  Render and validate focused Splunk Observability Cloud Metrics Pipeline
  Management plans, including metric usage review, cardinality and MTS controls,
  drop/archive/route/aggregate intent, exception planning, dashboard and detector
  handoffs, and deep-native-workflow delegated specs. Use when the user asks
  about MPM, metrics pipeline management, metric cardinality, MTS reduction, or
  Observability metric routing and aggregation.
---

# Splunk Observability Metrics Pipeline Setup

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

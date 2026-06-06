# Splunk Observability Metrics Pipeline Setup Reference

Use this skill for Observability Cloud Metrics Pipeline Management planning:
metric usage, MTS/cardinality review, drop/archive/route/aggregate decisions,
and exception lists.

## Boundaries

- This is an Observability Cloud MPM wrapper.
- Use `splunk-observability-otel-collector-setup` for collector-side processors.
- Use `splunk-spl2-pipeline-kit`, `splunk-ingest-processor-setup`, or
  `splunk-edge-processor-setup` for Splunk Platform ingest pipelines.

## Rendered Assets

- `metrics-pipeline-plan.md`
- `mpm-intent.json`
- `deep-native-workflow-spec.json`
- `delegate-deep-native-workflows.sh`
- `metadata.json`

## Source Anchors

- https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/metrics-pipeline-management/introduction-to-metrics-pipeline-management

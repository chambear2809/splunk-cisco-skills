# Splunk Observability SLO Setup Reference

This skill exists for discoverability and focused SLO intake. It delegates
public API validation and apply planning to
`splunk-observability-deep-native-workflows`. The generated delegate accepts
`--render` or `--apply`; pass `--dry-run` to preview actions and `--token-file`
for a live apply.

The focused wrapper can construct a complete request-based SLO payload from an
APM service and environment. Endpoint, custom-metric, and Synthetics SLI modes
remain explicit completion handoffs because their SignalFlow inputs need
additional source-specific fields.

## Required SLO Decisions

- SLI source: APM service spans, endpoint spans, custom metric, or Synthetic
  metric.
- Window and target.
- Burn-rate detector strategy.
- Dashboard and team ownership.
- Error-budget review cadence.

## Rendered Assets

- `slo-plan.md`
- `deep-native-workflow-spec.json`
- `slo-payload-intent.json`
- `delegate-deep-native-workflows.sh`
- `metadata.json`

## Source Anchors

- https://help.splunk.com/en/splunk-observability-cloud/create-alerts-detectors-and-service-level-objectives/create-service-level-objectives-slos
- https://dev.splunk.com/observability/reference/api/slo/latest

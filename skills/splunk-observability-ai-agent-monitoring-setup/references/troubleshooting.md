# Troubleshooting Reference

The doctor report is generated from validation errors and warnings. Keep fix commands exact.

## Common Findings

| Finding | Severity | Fix |
|---------|----------|-----|
| Histograms disabled | FAIL | Set `deployment.send_otlp_histograms=true` and re-render. |
| Content capture not accepted | FAIL | Add `accept_content_capture: true` only after the operator approves prompt/response capture. |
| Evaluations not accepted | FAIL | Add `accept_evaluation_cost: true` only after the operator approves LLM-as-judge content and cost risk. |
| OpenAI evals run in-process | FAIL | Set `evals_separate_process: true`. |
| Unsupported package | FAIL | Replace with the verified package name from `references/package-catalog.md`. |
| LOC wizard incomplete | HANDOFF | Complete Observability UI wizard and AI Agent Monitoring connection/index selection. |
| Missing HEC/LOC prerequisites | FAIL/HANDOFF | Apply `hec` and `loc` sections, then complete UI-only connection selection. |

## Verification Targets

- APM > Agents shows the service.
- Collector values include `signalfx.send_otlp_histograms: true`.
- Runtime env includes `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=delta`.
- Evaluation telemetry uses `span_metric_event,splunk` only when the Splunk emitter package is installed.

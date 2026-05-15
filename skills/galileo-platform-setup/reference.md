# Galileo Platform Setup Reference

## Official References

- Galileo overview: `https://docs.galileo.ai/what-is-galileo`
- Galileo REST API overview: `https://docs.galileo.ai/api/getting-started`
- Galileo export records API: `https://docs.galileo.ai/api-reference/trace/export-records`
- Galileo agentic metrics: `https://docs.galileo.ai/concepts/metrics/agentic/agentic-overview`
- Galileo Protect invoke API: `https://docs.galileo.ai/api-reference/protect/invoke`
- Splunk HEC REST endpoints:
  `https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-enterprise/http-event-collector-rest-api-endpoints`
- Splunk HEC event format:
  `https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-enterprise/format-events-for-http-event-collector`

Re-check these docs before changing endpoint paths, header names, exporter
schema, HEC envelope shape, or collector handoff flags.

## Apply Sections

| Section | Owner | Purpose |
| --- | --- | --- |
| `readiness` | `galileo-platform-setup` | Render endpoint derivation, `/v2/healthcheck`, auth/RBAC/Luna/Protect/Evaluate coverage checks. |
| `observe-export` | `galileo-platform-setup` | Pull Galileo records through `export_records` and send HEC JSON events. |
| `observe-runtime` | `galileo-platform-setup` | Provide Python and Kubernetes OTel/OpenInference bootstrap snippets. |
| `protect-runtime` | `galileo-platform-setup` | Provide a Python `/v2/protect/invoke` helper. |
| `evaluate-assets` | `galileo-platform-setup` | Render Evaluate, experiment, dataset, metric, annotation, feedback, Signals, and Trends handoffs. |
| `splunk-hec` | `splunk-hec-service-setup` | Prepare Splunk HEC service/token configuration. |
| `splunk-otlp` | `splunk-connect-for-otlp-setup` | Configure the Splunk Platform OTLP receiver and sender handoff assets. |
| `otel-collector` | `splunk-observability-otel-collector-setup` | Render Splunk OTel Collector Kubernetes/Linux assets. |
| `dashboards` | `splunk-observability-dashboard-builder` | Render/apply Observability dashboard specs. |
| `detectors` | `splunk-observability-native-ops` | Render/apply Observability detector specs. |

## Splunk Observability Cloud-only Mode

Use `--o11y-only` when Galileo telemetry should go to Splunk Observability
Cloud without pairing the workflow to Splunk Platform HEC. In this mode, a
default render/apply selects only:

- `readiness`
- `observe-runtime`
- `protect-runtime`
- `evaluate-assets`
- `otel-collector`
- `dashboards`
- `detectors`

Explicit Splunk Platform sections (`observe-export`, `splunk-hec`,
`splunk-otlp`) are rejected when `--o11y-only` is set.

## Galileo REST Export

The bridge script uses:

- `POST /v2/projects/{project_id}/export_records`
- `root_type`: `session`, `trace`, or `span`
- `export_format`: `jsonl` by default
- `redact`: `true` by default
- optional `log_stream_id`, `experiment_id`, and `metrics_testing_id`

The Splunk event defaults are:

- `source=galileo`
- `sourcetype=galileo:observe:json`
- `index=galileo`

Preferred record fields:

- `galileo_record_key`
- `galileo_project_id`
- `galileo_log_stream_id`
- `galileo_record_id`
- `galileo_record_type`
- `galileo_trace_id`
- `galileo_session_id`
- `galileo_parent_id`
- `metrics`
- `metric_info`
- `feedback_rating_info`
- `annotations`
- `redacted_input`
- `redacted_output`

Raw prompt/response fields are excluded unless the operator explicitly passes
`--include-raw` to the bridge script and confirms Splunk is an approved
destination.

## HEC Event Shape

Use `/services/collector/event` for JSON objects. The `event` field is a JSON
object, while `fields` is optional and flat:

```json
{
  "time": 1770000000.0,
  "source": "galileo",
  "sourcetype": "galileo:observe:json",
  "index": "galileo",
  "event": {
    "galileo_record_key": "project:log-stream:trace:record",
    "galileo_record_type": "trace",
    "redacted_input": "<redacted>",
    "redacted_output": "<redacted>"
  }
}
```

## Troubleshooting

- Galileo 401/403: verify the API key file, project permissions, API base, and
  project sharing.
- Galileo empty results: verify project ID, log stream ID, root type, export
  filters, and `log_stream_id`/`experiment_id`/`metrics_testing_id`.
- Splunk 401/403: verify the HEC token file, token enablement, allowed indexes,
  and HEC URL.
- Splunk 400: verify the HEC URL ends in `/services/collector/event`, the
  payload has an `event` key, and indexed fields are flat.
- Duplicate events: search by `galileo_record_key`; use a cursor file for
  scheduled jobs.
- Missing prompt/response text: expected unless raw fields were explicitly
  approved and `--include-raw` was used.

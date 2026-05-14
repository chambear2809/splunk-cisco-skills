# Splunk Galileo Integration Reference

## Official References

- Galileo OpenTelemetry/OpenInference integration recommendations:
  `https://docs.galileo.ai/sdk-api/third-party-integrations/opentelemetry-and-openinference/integration-recommendations`
- Galileo Python OTel walkthrough:
  `https://docs.galileo.ai/sdk-api/third-party-integrations/opentelemetry-and-openinference/how-to-integrate`
- Galileo REST API overview:
  `https://docs.galileo.ai/api-reference`
- Galileo trace/span/session export and query APIs:
  `https://docs.galileo.ai/api-reference/trace/export-records`
- Splunk HEC REST endpoints:
  `https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-enterprise/http-event-collector-rest-api-endpoints`
- Splunk HEC event format:
  `https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-enterprise/format-events-for-http-event-collector`
- Splunk Connect for OTLP:
  `https://splunkbase.splunk.com/app/8704`
- Splunk Distribution of the OpenTelemetry Collector:
  `https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector`

Re-check these docs before changing endpoint paths, header names, exporter
schema, HEC envelope shape, or collector handoff flags.

## Apply Sections

| Section | Owner | Purpose |
| --- | --- | --- |
| `hec-service` | `splunk-hec-service-setup` | Prepare Splunk HEC service/token configuration. |
| `hec-export` | `splunk-galileo-integration` | Pull Galileo records through REST and send HEC JSON events. |
| `otlp-input` | `splunk-connect-for-otlp-setup` | Configure the Splunk Platform OTLP receiver and sender handoff assets. |
| `otel-collector` | `splunk-observability-otel-collector-setup` | Render Splunk OTel Collector Kubernetes/Linux assets. |
| `python-runtime` | `splunk-galileo-integration` | Provide Python OTel/OpenInference bootstrap snippets. |
| `kubernetes-runtime` | `splunk-galileo-integration` | Provide Kubernetes env and annotation helpers. |
| `dashboards` | `splunk-observability-dashboard-builder` | Render/apply Observability dashboard specs. |
| `detectors` | `splunk-observability-native-ops` | Render/apply Observability detector specs. |

## Splunk Observability Cloud-only Mode

Use `--o11y-only` when Galileo telemetry should go to Splunk Observability
Cloud without pairing the workflow to Splunk Platform HEC. In this mode, a
default render/apply selects only:

- `otel-collector`
- `python-runtime`
- `kubernetes-runtime`
- `dashboards`
- `detectors`

The OTel Collector handoff still delegates to
`splunk-observability-otel-collector-setup`, but it omits
`--render-platform-hec-helper`, `--platform-hec-token-file`,
`--platform-hec-url`, and `--platform-hec-index`. Explicit Splunk Platform
sections (`hec-service`, `hec-export`, `otlp-input`) are rejected when
`--o11y-only` is set.

## Galileo REST Export

The bridge script supports `session`, `trace`, and `span` root types. It queries
Galileo search endpoints under:

- `/v2/projects/{project_id}/sessions/search`
- `/v2/projects/{project_id}/traces/search`
- `/v2/projects/{project_id}/spans/search`

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

## OpenTelemetry/OpenInference Runtime

The rendered runtime assets use file-backed secrets and environment variables.
They are snippets, not automatic app patches. To install the Python snippet into
an app tree, render with `--runtime-target-dir` or run:

```bash
RUNTIME_TARGET_DIR=/path/to/app \
  bash splunk-galileo-rendered/scripts/apply-python-runtime.sh
```

For Kubernetes, render the ConfigMap and annotation helper, then pass a target
deployment name:

```bash
KUBE_NAMESPACE=default KUBE_WORKLOAD=my-api \
  bash splunk-galileo-rendered/scripts/apply-kubernetes-runtime.sh
```

## Troubleshooting

- Galileo 401/403: verify the API key file, project permissions, and API base.
- Galileo empty results: verify project ID, log stream ID, root type, time
  bounds, and whether the filter should use `name` or `column_id`.
- Splunk 401/403: verify the HEC token file, token enablement, allowed indexes,
  and HEC URL.
- Splunk 400: verify the HEC URL ends in `/services/collector/event`, the
  payload has an `event` key, and indexed fields are flat.
- Duplicate events: search by `galileo_record_key`; use a cursor file for
  scheduled jobs.
- Missing prompt/response text: expected unless raw fields were explicitly
  approved and `--include-raw` was used.

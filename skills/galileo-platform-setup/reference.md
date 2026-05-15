# Galileo Platform Setup Reference

## Official References

- Galileo overview: `https://docs.galileo.ai/what-is-galileo`
- Galileo REST API overview: `https://docs.galileo.ai/api/getting-started`
- Galileo Python SDK projects: `https://docs.galileo.ai/sdk-api/python/reference/projects`
- Galileo Python SDK log streams: `https://docs.galileo.ai/sdk-api/python/reference/log_streams`
- Galileo datasets: `https://docs.galileo.ai/sdk-api/experiments/datasets`
- Galileo prompts: `https://docs.galileo.ai/sdk-api/experiments/prompts`
- Galileo experiments: `https://docs.galileo.ai/sdk-api/python/reference/experiments`
- Galileo OpenTelemetry/OpenInference: `https://docs.galileo.ai/sdk-api/third-party-integrations/opentelemetry-and-openinference`
- Galileo Agent Control target resolution: `https://docs.galileo.ai/sdk-api/python/reference/agent_control`
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
| `object-lifecycle` | `galileo-platform-setup` | Create or validate Galileo projects, log streams, datasets, prompts, experiments, metrics, Protect stages, and Agent Control target resolution. |
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
- `object-lifecycle`
- `observe-runtime`
- `protect-runtime`
- `evaluate-assets`
- `otel-collector`
- `dashboards`
- `detectors`

Explicit Splunk Platform sections (`observe-export`, `splunk-hec`,
`splunk-otlp`) are rejected when `--o11y-only` is set.

## Galileo Object Lifecycle

Use `object-lifecycle` before Observe exports or runtime handoff when a new
tenant/project needs isolated Galileo assets. The apply wrapper reads only
`--galileo-api-key-file`, sets `GALILEO_CONSOLE_URL` and API-base environment
variables for custom deployments, and runs `scripts/galileo_object_lifecycle.py`.

Lifecycle inputs:

- `--lifecycle-manifest`: primary YAML/JSON manifest for all Galileo objects.
- `--dataset-dir`: directory of `.json`, `.jsonl`, or `.csv` datasets to create.
- `--prompt-manifest`: list or mapping of prompt templates to create.
- `--experiment-manifest`: experiment definitions; `mode: create_only` is the
  safe default, while `mode: run` opts into executing an SDK experiment.
- `--protect-stage-manifest`: Protect stage definitions; stages are created
  only where `create: true`.
- `--metrics`: comma-separated built-in metric names to enable on the log
  stream or attach to experiment definitions.

Rendered lifecycle assets:

- `lifecycle/object-lifecycle-manifest.example.json`
- `lifecycle/product-coverage-matrix.json`
- `lifecycle/product-coverage-matrix.md`
- `scripts/apply-object-lifecycle.sh`
- `scripts/galileo_object_lifecycle.py`

Product coverage surfaces tracked in the matrix:

- API keys, auth modes, users, groups, project/dataset/integration
  collaborators, and RBAC
- REST API base URL derivation, custom deployment routing, and healthcheck
  validation
- SSO/OIDC/SAML and enterprise identity readiness
- Projects and RBAC/project-sharing handoff
- Log streams and metric enablement
- Datasets, dataset versions, sharing, prompt-evaluation datasets, and
  synthetic extension
- Prompts and prompt-version review
- Experiments, experiment groups, tags, comparison, search, metric settings,
  and optional experiment runs
- Evaluate workflow runs
- Python and TypeScript SDK parity, Observe/Evaluate workflow classes, package
  versioning, and runtime package handoffs
- Metric taxonomy across agentic, RAG, response-quality, safety/compliance,
  expression/readability, model-confidence, multimodal-quality, text-to-SQL,
  and Autotune/metric-improvement handoffs
- Evaluate metrics, built-in scorers, custom scorers, scorer validation, and
  scorer settings
- Luna Enterprise, model/provider integrations, model aliases, costs, and
  pricing readiness
- Luna-2 fine-tuning, Luna metric evaluation, experiment use, and feature
  availability readiness
- Observe traces, sessions, spans, OpenTelemetry, and OpenInference
- Tags, metadata, run labels, and filter hygiene for sessions, traces, spans,
  prompt runs, and Splunk fields
- Enterprise data retention, TTL, redacted inputs/outputs, PII/privacy
  controls, and compliance handoffs
- Trace query, columns, recompute, update, delete, and organization-job
  maintenance handoffs
- Agent Graph, Logs UI, Messages UI, large-log filtering, and console
  debugging views
- Distributed tracing and multi-service trace propagation
- Multimodal observability for images, audio, and documents
- Third-party framework integrations and wrappers including A2A, CrewAI,
  Google ADK, LangChain/LangGraph, Microsoft Agent Framework, OpenAI,
  OpenAI Agents SDK, Mastra, Pydantic AI, Strands Agents, Vercel AI SDK,
  custom spans, and OpenInference
- MCP tool-call logging and tool spans
- Galileo alerts, email notifications, Slack webhooks, and Splunk detector
  mapping
- Protect stages, rules, rulesets, actions, notifications, and invocation
  runtime
- Agent Control log stream target resolution
- Annotation templates, ratings, queues, feedback templates, feedback ratings,
  Signals, and Trends dashboards/widgets/sections
- Run insights, health scores, token usage, search, runs, traces SDK utilities,
  decorators, handlers, and wrappers
- Jobs, async tasks, validation status, and progress polling
- Enterprise deployment, system users, and organization jobs
- Galileo MCP Server and IDE developer tooling
- Playgrounds, sample projects, unit-test experiments, and CI experiment gates
- Official cookbooks, use-case guides, starter examples, and applied agent/RAG
  playbooks
- Error catalog, troubleshooting, and project-key diagnostics
- Release notes and version compatibility
- Splunk HEC, OTLP, OTel Collector, dashboards, and detectors

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

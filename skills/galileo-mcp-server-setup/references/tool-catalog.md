# Galileo MCP Tool Catalog

Source of truth: live `tools/list` from
`https://api.galileo.ai/mcp/http/mcp`, reviewed August 20, 2026.

The server reported `EvalsInIDEServer` version `1.29.0` and 9 tools. The nine
tool names, required arguments, property keys, and canonical input-schema
SHA-256 fingerprints below were all unchanged from the `1.28.1` review on
July 8, 2026; only the server version string moved. Treat
unknown future tools, prompts, resources, or schema changes as
manual-approval-only until this catalog is updated. The renderer also emits
`coverage/tool-catalog.json` so `probe_mcp.py --fail-on-drift` can compare live
server name/version, tool names, required args, property keys, and canonical
input-schema SHA-256 fingerprints against the checked-in catalog.

## Guidance/Public Tools

These tools can be used for docs and implementation guidance. They do not
require tenant object mutation by design.

| Tool | Required args | Optional schema keys | Product coverage |
| --- | --- | --- | --- |
| `search_docs` | `query` | none | Galileo docs search and API/reference discovery |
| `integrate_galileo_with_openai` | `language` | none | OpenAI SDK wrapper guidance for Python/TypeScript |
| `integrate_galileo_with_langchain` | `language` | none | LangChain/LangGraph observability guidance |
| `setup_galileo_experiment` | none | `language` | Experiment setup guidance, not a direct experiment runner |

## Tenant Read Tools

These require a valid Galileo API key and may reveal tenant data. Do not
auto-allow broadly in shared environments.

| Tool | Required args | Optional schema keys | Product coverage |
| --- | --- | --- | --- |
| `get_logstream_insights` | `project`, `log_stream` | none | Signals/insights for a named log stream |
| `get_logstream_signals` | `project`, `log_stream` | none | Alias-like signals/insights path; present live but absent from the SDK example output |
| `validate_dataset` | `dataset_id` | none | Synthetic dataset job status and first-row preview |

## Tenant Write/Generation Tools

These create tenant objects or generated content. Keep manual approval on by
default.

| Tool | Required args | Optional schema keys | Product coverage | Risk |
| --- | --- | --- | --- | --- |
| `create_galileo_dataset` | `description` | `count`, `csv_content`, `data_source_type`, `data_types`, `json_data`, `model`, `name`, `project_id`, `sample_data` | Synthetic/CSV/JSON dataset creation | Creates data and may generate synthetic edge cases |
| `create_prompt_template` | `name`, `template` | `frequency_penalty`, `max_tokens`, `model_alias`, `output_type`, `presence_penalty`, `project_id`, `raw`, `temperature`, `top_p` | Global prompt template creation | Creates reusable organization/project prompt assets |

## Known Gaps

- The MCP server does not expose full project, log stream, dataset, prompt,
  experiment, experiment-group, scorer, Luna Studio, annotation, feedback,
  trends, Agent Graph, saved-view, SDK-reference, metric recomputation,
  SQL/Text-to-SQL metric, Protect, Agent Control, or Splunk wiring APIs.
- The July 7-August 7 AI Assistant, global dashboard, alert webhook, batched
  experiment, Annotation Queue, metric/cost, hosted-model, console-theme, and
  product-documentation changes are platform capabilities or documentation
  boundaries, not new live MCP tools. `search_docs` can locate documentation;
  it does not turn those features into MCP lifecycle APIs.
- `setup_galileo_experiment` remains guidance-only. Experiment groups require
  Galileo Python SDK 2.2.0 or later, and group lifecycle/ranking is not exposed
  by the MCP server.
- Public Trends APIs remain project/log-stream scoped, and no public Assistant,
  global-dashboard, or alert-webhook CRUD endpoint is documented. Do not infer
  automation from the corresponding console features.
- Use `galileo-platform-setup` for complete lifecycle automation.
- Use `galileo-agent-control-setup` for policy enforcement and Cursor hook
  governance.
- Use the Splunk handoff skills for HEC, OTLP, OTel Collector, dashboards, and
  detectors.

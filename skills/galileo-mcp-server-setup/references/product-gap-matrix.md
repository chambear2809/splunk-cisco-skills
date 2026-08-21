# Galileo MCP Product Gap Matrix

| Product area | MCP coverage | Handoff |
| --- | --- | --- |
| MCP client setup | First-class in `galileo-mcp-server-setup` | None |
| Tool inventory and drift | First-class no-secret probe | None |
| Dataset creation/status | Partial MCP coverage | `galileo-platform-setup` for complete dataset lifecycle |
| Dataset versioning, content update, download, sharing, and collaborators | Not MCP server setup | `galileo-platform-setup` for dataset lifecycle and access governance |
| Prompt template creation | Partial MCP coverage | `galileo-platform-setup` for prompt manifests/versioning |
| Experiment setup | Guidance only | `galileo-platform-setup` for create/run assets |
| AI Assistant beta, evidence-linked investigation, criticality, and organization-wide debugging | Docs-search only; no public Assistant API or MCP tool documented | `galileo-platform-setup` for AI Assistant readiness, enablement, and console evidence |
| Splunk Agent Observability naming and pre-/post-August 7 documentation epoch | Docs-search only; the correct documentation set depends on onboarding date | Select `docs.galileo.ai` for customers onboarded before August 7, 2026 and `agent-observability-docs.splunk.com` for later onboarding; do not mix product-era assumptions |
| Annotation Queues GA, templates, users, records, and human-feedback operations | Docs-search only; no observed MCP lifecycle tool | `galileo-platform-setup` for queue access, assignment, annotation, export, and validation workflows |
| AI-assisted custom-code metrics, organization billing usage, model pricing, and integration costs | Docs-search only; no observed MCP lifecycle or billing tool | `galileo-platform-setup` for scorer review, cost governance, and console evidence |
| Trace Count alerts and multimodal out-of-the-box evaluation metrics | Docs-search only; no observed MCP alert or metric-configuration tool | `galileo-platform-setup` for alert and metric configuration/validation |
| Hosted-model availability and light, dark, or system console themes | Docs-search only; no observed MCP configuration tool | `galileo-platform-setup` for model availability checks; console theme remains an operator preference |
| Global dashboards across projects and log streams | Docs-search only; public Trends API remains log-stream scoped | `galileo-platform-setup` for global-dashboard UI readiness and evidence |
| Generic alert webhooks, payload v1.0, authentication, testing, and deduplication | Docs-search only; no public alert/webhook CRUD API or MCP tool documented | `galileo-platform-setup` for webhook runbooks, receiver/relay design, and validation |
| Experiment groups (Python SDK >=2.2.0), comparison, ranking, playground runs, and unit-test gates | Guidance or docs-search only | `galileo-platform-setup` for experiment group and CI workflow handoffs |
| Large-dataset batched Playground and experiment metric processing | Dataset creation/status only; no batched experiment-execution MCP tool | `galileo-platform-setup` for batched execution, progress, and result validation; do not claim an undocumented exact maximum |
| Projects, project sharing, users, groups, RBAC, SSO, and API keys | Not MCP server setup | `galileo-platform-setup` for enterprise/admin readiness |
| Log stream signals/insights | Tenant-read MCP coverage | `galileo-platform-setup` for metrics/trends/export context |
| Observe traces, sessions, spans, exports, metrics, run insights, and alerts | Not MCP server setup | `galileo-platform-setup` for Observe runtime/export and Splunk wiring |
| Evaluate metrics, custom scorers, Luna-2, annotations, and feedback | Not MCP server setup | `galileo-platform-setup` for Evaluate/Luna/annotation handoffs |
| Luna Studio tutorials, metric training datasets, and scorer development workflows | Docs-search only | `galileo-platform-setup` for Luna/scorer workflow handoffs |
| Text-to-SQL metrics, preset metric benchmarks/examples, and metric recomputation | Docs-search only | `galileo-platform-setup` for metric/scorer readiness and recomputation handoffs |
| Agentic metrics, metric settings, scorer health scores, and Autotune | Docs-search only | `galileo-platform-setup` for metric/scorer readiness |
| Provider integrations, model aliases, model pricing, and costs | Not MCP server setup | `galileo-platform-setup` for provider/cost readiness |
| Trends dashboards, health scores, and organization jobs | Not MCP server setup | `galileo-platform-setup` for Trends/run-insights/admin handoffs |
| Agent Graph traffic analytics, aggregate graph, search, and metric overlays | Not MCP server setup | `galileo-platform-setup` for Agent Graph and console-debugging handoffs |
| Log stream and experiment saved views, table columns, and shared/private filters | Not MCP server setup | `galileo-platform-setup` for console-view and analysis handoffs |
| Protect stages, rulesets, notifications, and invoke runtime | Not MCP server setup | `galileo-platform-setup` for Protect runtime/assets |
| OpenAI/LangChain integration | MCP guidance | `galileo-platform-setup` for runtime snippets and Splunk handoffs |
| Other framework integrations | Docs-search only | `galileo-platform-setup` for OpenTelemetry/OpenInference handoffs |
| Python/TypeScript SDK reference, wrappers, decorators, async logging, and release compatibility | Docs-search only | `galileo-platform-setup` for SDK parity and runtime-snippet handoffs |
| Multimodal logging, distributed tracing, tags, and metadata | Docs-search only | `galileo-platform-setup` for runtime logging handoffs |
| Cookbooks, sample projects, playgrounds, unit tests, and CI experiment gates | Docs-search only | `galileo-platform-setup` for sample/CI workflow handoffs |
| MCP tool-call logging | Rendered handoff | `galileo-platform-setup` for full runtime/Splunk wiring |
| Agent Control / Cursor hooks | Not MCP server setup | `galileo-agent-control-setup` |
| Splunk HEC/OTLP/O11y dashboards/detectors | Not MCP server setup | Existing Splunk skills |
| Enterprise retention, TTL, privacy, custom deployments, and release checks | Not MCP server setup | `galileo-platform-setup` for enterprise/custom deployment readiness |

The skill must make these boundaries explicit in generated README files so an
operator does not mistake MCP registration for complete Galileo onboarding.

# Galileo MCP Product Gap Matrix

| Product area | MCP coverage | Handoff |
| --- | --- | --- |
| MCP client setup | First-class in `galileo-mcp-server-setup` | None |
| Tool inventory and drift | First-class no-secret probe | None |
| Dataset creation/status | Partial MCP coverage | `galileo-platform-setup` for complete dataset lifecycle |
| Dataset versioning, content update, download, sharing, and collaborators | Not MCP server setup | `galileo-platform-setup` for dataset lifecycle and access governance |
| Prompt template creation | Partial MCP coverage | `galileo-platform-setup` for prompt manifests/versioning |
| Experiment setup | Guidance only | `galileo-platform-setup` for create/run assets |
| Experiment groups, comparison, ranking, playground runs, and unit-test gates | Guidance or docs-search only | `galileo-platform-setup` for experiment group and CI workflow handoffs |
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

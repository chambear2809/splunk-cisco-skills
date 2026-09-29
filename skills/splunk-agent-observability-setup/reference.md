# Splunk Agent Observability Product Reference

Verified against the official Splunk Agent Observability and Splunk Observability
Cloud documentation on **2026-09-28**. This is a fast-moving product. Confirm
the current docs, release notes, and feature comparison before operational
changes. The feature inventory and row-level automation boundary live in
[`references/product-feature-matrix.json`](references/product-feature-matrix.json).
The managed-object and policy lifecycle inventory lives in
[`references/object-action-matrix.json`](references/object-action-matrix.json).
The audit used Splunk's [complete documentation index](https://agent-observability-docs.splunk.com/llms.txt)
to check product families and API resource groups; source links for each mapped
feature are listed below.
The SKILL.md `compatibility_verified` date records this repository's Splunk
Platform 10.5 compatibility baseline, which is separate from this product-doc
review date.

## Product boundary and routing

Splunk Agent Observability is the product for observing, evaluating, and
applying guardrails to generative AI and agentic applications. Current docs
describe both customer-managed on-premises and SaaS integrated with Splunk
Observability Cloud. The AI Agent Monitoring APM experience is a separate
legacy experience scheduled for deprecation; the current docs direct users to
Splunk Agent Observability but do not state an end-of-life date.

The on-premises product was announced on 2026-08-07; the SaaS deployment
integrated with Splunk Observability Cloud was announced as available on
2026-09-15. These are distinct deployment contracts under the same product
name.

Use the requested tenant and release as the source of truth:

| Target | Owner and routing |
|---|---|
| New Splunk Agent Observability SaaS | This skill. Confirm Free Edition or paid subscription/entitlement, organization and realm, current feature availability, role, and API key scope. |
| Splunk Agent Observability on-premises | This skill for app integration, SDK/API usage, and product readiness. Current public docs announce the deployment but do not expose a complete installation/upgrade procedure; installation is a support/customer-managed handoff until a release-specific official runbook is available. |
| Legacy Galileo tenant or explicitly identified pre-rebrand API contract | `galileo-platform-setup`; confirm the actual product and tenant-linked contract with the customer or Splunk. The 2026-08-07 date is the on-premises announcement date, not an established Galileo migration cutoff. |
| Splunk AI Agent Monitoring in APM | `splunk-observability-ai-agent-monitoring-setup`; use only for the legacy APM pages, migration assessment, and its supported OTel/Python workflow. |
| AI Infrastructure Monitoring in Observability Cloud | `splunk-observability-ai-agent-monitoring-setup` for product readiness and `splunk-observability-otel-collector-setup` for collector deployment. This is a separate infrastructure telemetry workflow. |
| Standalone legacy Galileo Agent Control | `galileo-agent-control-setup`; do not apply its legacy endpoints to new Splunk Agent Observability. |

The new SaaS product is reachable from the Splunk Observability Cloud menu when
enabled. Current access docs say to contact a Splunk team for SaaS product
access. Splunk Observability Cloud Free Edition documentation separately states
Agent Observability is available without a fixed trial period, supports up to
15 hosts, and has a Free Edition onboarding path. Check which access path the
user's actual tenant supports instead of assuming paid entitlement or free
enablement.

Do not infer SSO eligibility from Free Edition status alone. The SSO guide has
deployment-specific instructions; verify current tenant entitlement and the
selected deployment before planning identity changes. SaaS role assignment is
not available to organizations using Unified Identity with centralized RBAC,
so inspect that identity model before proposing product-level role changes.

## Deployment and feature differences

The SaaS and on-premises feature sets are mostly shared, with documented
exceptions that materially affect recommendations:

| Feature | On-premises | SaaS |
|---|---:|---:|
| Preset Luna evaluators | Yes | Limited: Prompt Injection, Toxicity, Sexism, PII |
| Fine-tune Luna models | Yes | No |
| Custom code evaluators | Yes | No |
| AI Assistant | Yes | No |
| Agent Observability inputs/outputs in APM pages | Verify current release | No |
| Results in Observability Cloud global search | Verify current release | No |

Public on-premises announcement/release notes are not a full install guide. Do
not invent package names, cluster topologies, ports, resource sizing, upgrade
steps, or appliance operations. For installation, upgrade, backup, disaster
recovery, or air-gapped design, obtain the applicable entitled product
documentation and support/customer procedure first.

## Product areas and practical workflow

### Access and first-run readiness

Confirm account/tenant, deployment, realm or API base URL, product role,
resource-level collaborator role, organization/project, and credentials. SaaS
authorization checks both API-token capabilities and project/resource
collaborator permissions. The product also has organization-wide, shared-resource,
and global evaluator capability classes. API keys and provider credentials are
secrets: create/rotate them only through the product-supported secure flow and
never echo them in logs or reports.

### Instrumentation and telemetry

The `splunk-ao` Python SDK documents direct logging APIs, provider wrappers,
sessions, Agent Streams, trace/span logging, context, tags/metadata,
multimodal logging, and distributed tracing. Current integrations documentation
lists supported framework/provider paths; follow the page for that exact SDK
and release. Current examples cover OpenAI, Anthropic, Gemini Enterprise, Azure
OpenAI, AWS Bedrock, and NVIDIA NIM. Current framework pages include A2A, CrewAI, Google ADK,
LangChain/LangGraph, Microsoft Agent Framework, OpenAI SDK, OpenAI Agents SDK,
Pydantic AI, and Strands Agents. The exact integrations and auto-instrumentation
mode differ; do not generalize support from one wrapper to another.

Keep application code changes scoped to the user's repository and runtime.
Start with a development/staging app, ensure test inputs contain no real
secrets/PII, install packages in the existing environment, and validate the
trace in the correct Agent Stream. Do not assume an SDK initialization call is
read-only: the official quickstart says it can create a project and Agent Stream
when missing. Reuse existing names/IDs where specified, and report any
auto-created resource.

SaaS quickstarts use `SPLUNK_AO_REALM` plus a Splunk Observability Cloud access
token; on-premises quickstarts use the instance console URL plus an Agent
Observability API key. Keep these deployment contracts separate. For SaaS,
`SPLUNK_AO_O11Y_TOKEN` is the OTLP ingest token. It can also perform CRUD only
when it has the required API permissions and no dedicated API token is set.
`SPLUNK_AO_O11Y_API_TOKEN` is the optional, dedicated CRUD token; when both are
set, the SDK uses it for CRUD and the ingest token for telemetry. CRUD-only
work can use the API token without an ingest token. The current AO key guide
instructs an Observability Cloud admin to select both INGEST and API-token-with-
roles, then assign `agent_observability_admin` when creating a combined token.
The API-role picker alone does not prove that the separate INGEST scope was
selected. Do not infer token scopes or AO capabilities from the signed-in UI
user's role or from a generic Observability Cloud role such as `power`. A 401
must be treated as an authentication/scope/realm failure until a read-only API
request succeeds; a role screenshot is not proof of token validity.

SaaS authorization has three distinct layers: the token's AO capability claims,
the user's Agent Observability system role, and the collaborator role on the
specific project/resource. Both token capability and resource collaborator
role must allow the action. `agent_observability_user` can create, update,
share, and delete projects/resources within projects; project Owner or Editor
is required for project-scoped logging, control binding, and runtime use. The
documented capability names include `o11y_create_project`,
`o11y_log_data_project_shared`, `o11y_create_control`,
`o11y_update_control_bindings_project_shared`,
`o11y_use_control_runtime_project_shared`, and `o11y_delete_control`;
deleting an owned test project requires `o11y_delete_project_shared`. Check
the capability page for each additional operation before trying to cover it.
The docs do not list a separate Agent Stream creation capability even though
the SDK quickstart says initialization creates a missing stream; record this
as a least-privilege documentation gap rather than inventing a permission.

For on-premises, use `SPLUNK_AO_API_KEY` with `SPLUNK_AO_CONSOLE_URL` (and set
`SPLUNK_AO_API_URL` only when a custom API endpoint is required). Check the
installed SDK's configuration contract before staging code. Load secrets at
runtime from a protected file or secret manager; never paste token values into
a source file, shell command, issue, generated artifact, or tool transcript.
For SaaS with `splunk-ao==0.4.0`, set the realm and `SPLUNK_AO_O11Y_*` tokens;
do not combine them with `SPLUNK_AO_API_KEY` or `SPLUNK_AO_API_URL`, which the
SDK treats as a conflicting standalone deployment. Agent Control's separate
`AGENT_CONTROL_API_KEY` can use the protected SaaS token.

### Evaluation and improvement

The evaluator system covers out-of-the-box evaluators, custom LLM-as-a-judge,
and custom code evaluators where supported. The official evaluator documentation
groups built-ins into categories including agentic performance, expression and
readability, multimodal quality, response quality, RAG, safety/compliance, and
text-to-SQL. Use the
current comparison page for the exact evaluator names, node types, deployment
availability, and required model integration. LLM-backed evaluators need a
configured provider integration or Luna where available; their use can incur
usage charges. Review sampling and the quality objective before enabling them.
Autotune can use human feedback to refine evaluator behavior; treat that as a
configuration/data lifecycle operation and preserve a before/after record.

Luna Studio is a separate Enterprise-tier UI/SDK environment for generating
training data, fine-tuning custom Luna evaluators, evaluating outputs, and
registering evaluators. Its infrastructure is deployed by Splunk into the
customer's own cluster or cloud. Check entitlement and deployment prerequisites
first; once an instance is available, execute a bounded training/evaluation
run through the documented UI or SDK when requested. The current UI quickstart
calls for a labeled CSV test set of at least 300 rows and 100 per class; verify
the selected release and data shape before launch. Preset Luna evaluators in
SaaS have limited support, and SaaS fine-tuning is unavailable.

Experiments provide systematic prompt/model/application comparison using
datasets, prompt templates, evaluators, and experiment runs. Docs cover code,
playground, unit-test and experiment-group paths. For regression use, select a
small representative dataset, establish a baseline, run the same evaluation
configuration, inspect per-case failures, and only then integrate a repeatable
check into CI. Dataset generation and evaluation can send sensitive data to
configured providers and incur cost. Keep data retention and access in scope.

### Runtime operations

- **Agent Streams and traces:** check ingestion, latency/errors, sessions,
  messages, nested tool/model spans, tags, and project/stream boundaries.
- **Signals:** investigate grouped failure patterns and inspect the linked
  trace context. A suggested fix from an assistant is a recommendation; do not
  apply source or production changes without the requested scope and review.
- **AI Assistant:** only on-premises, standalone, and custom deployments. It
  reads and cites traces/sessions but is currently read-only, has no memory
  between conversations, and does not execute recommended fixes. Verify its
  cited evidence before using a separate workflow to apply a fix.
- **Tokenomics:** administer integrations for Claude Code, Codex, Cursor,
  GitHub Copilot, and Windsurf; configure the fiscal calendar; and upload the
  Workday organization hierarchy when requested. This reports AI coding-tool
  adoption/cost, not general application LLM token accounting. Data refreshes
  daily and is not backfilled; costs/activity are vendor-reported or estimated,
  not independently audited by Splunk. Review data visibility and work-email
  joins before uploading a hierarchy or presenting costs as finance-grade.
- **Alerts and rankings:** inspect the current capability matrix and tenant
  permissions for supported alert/ranking operations, then use the product UI
  or documented API path and verify saved state. Do not infer alert CRUD from
  capability names alone.
- **Agent Control:** its overview describes centralized input/output guardrails
  for harmful content, prompt injection, PII leakage, and related risk. Current
  setup requires the `splunk-ao` OpenAI extra plus Agent Control SDK/evaluator
  packages and runtime initialization. The documented dependency set is
  `splunk-ao[openai]>=0.2.1`, `agent-control-sdk>=8.5.0`,
  `agent-control-evaluators>=8.5.0`, and
  `agent-control-evaluator-galileo>=8.5.0`; a deterministic built-in list or
  regex test does not need an external model or Galileo evaluator call. Controls
  must be attached to an Agent Stream; attachment creates a clone, so later edits
  to the global control do not change existing stream-bound copies. Record a
  clone ID only if the UI/API exposes one. The generic Agent Control
  [server reference](https://docs.agentcontrol.dev/core/reference) documents
  control CRUD and agent attach/detach routes. Verify those routes and clone
  identity in the target AO deployment before using them for cleanup; the AO
  UI guide documents attachment but not a clone deletion procedure. A control
  is the guardrail policy: scope, selector/evaluator condition, and action.
  The generic engine documents `deny`, `steer`, and `observe`, plus composite
  conditions. The AO UI guide explicitly describes `Deny`, so verify advanced
  choices against the target release before applying them.

  SaaS runtime setup uses the realm Agent Control URL, `X-SF-Token` API-key
  header, JWT runtime mode, and a configured runtime-token header; the documented
  SDK minimum is 8.5.0. The Splunk setup page does not document how a tenant
  obtains the runtime JWT. Follow its current initialization sample; if it does
  not initialize runtime auth for the target tenant, record the docs/access gap
  rather than inventing a credential exchange. The AO control UI documents
  evaluator type, stages, selector, action, execution environment, and evaluator
  config; do not assume it exposes a step-type field. In the Agent Control SDK,
  `@control()` defaults to an `llm` step; set `.name` or `.tool_name` metadata
  before decorating when testing a `tool` step. Require the token capabilities
  and project Owner/Editor access for binding and runtime. Validate an expected
  allow case and blocked test case in staging. Match the actual tool payload:
  the validation SDK wrapped a string argument, so selector `input` with
  `contains` matched where selector `*` with `exact` did not. A control inventory, SDK install,
  or UI view by itself does not prove enforcement in the application path.
- **AI Assistant:** documented for on-premises investigation. The SaaS feature
  comparison excludes it; check its cited traces before acting on suggestions.
- **Model pricing and integration costs:** an organization admin can edit model
  prices used for app/evaluator cost calculations; edits affect new logs and
  experiments, not history. Integration Costs is a read-only view of provider
  spend for LLM-as-a-judge evaluators. This differs from Tokenomics coding-tool
  adoption and from SaaS billable span/Luna usage.
- **Billing and limits:** SaaS usage documentation measures agentic spans and
  Luna tokens, and warns that spans are dropped after configured per-minute
  limits. Check the current subscription and limit pages before load tests or
  production rollout.

### MCP and management interfaces

Splunk documents an Agent Observability MCP server for AI-enabled IDEs. Its
current setup page explicitly labels the server under construction. The page
describes dataset creation/status, prompt templates, experiment guidance/actions,
Signals, integrations, and documentation search; it does not establish support
for all resource administration or destructive operations. When the server is
configured, inspect actual tools and schemas and verify whether each action is
read-only or mutating. Use only tools exposed by the live server and never put
the API key in committed config. If unavailable or missing a needed operation,
use the documented product SDK/API/UI path; do not claim an action was completed
by MCP based only on an answer.

For a requested MCP client setup, configure the user's supported IDE with the
tenant-specific MCP URL and an approved local secret reference, then reconnect
and inspect the live tool list. The current guide includes an inline API key in
its sample config; do not commit that sample with a real key. Keep the MCP
client integration distinct from instrumenting an application that calls MCP
tools, which requires tool spans in application traces.

The product has a public REST API and SDK. For on-premises, standalone, and
custom deployments, derive the API base by replacing `console` with `api` in the
console URL; the current API guide uses `GET /v2/healthcheck` to verify it. The
documented SaaS base form is
`https://app.{realm}.observability.splunkcloud.com/ao/api/`; SaaS API auth follows
the Splunk Observability Cloud developer guide, while self-managed API auth
differs by API key, HTTP Basic, or JWT flow. Use the current API reference for
exact headers, scopes, methods, and retry behavior. SaaS realm endpoints and
on-premises instance URLs are not interchangeable. Some current API reference
pages embed `api.galileo.ai` in their OpenAPI examples; substitute the verified
API base for the *actual target tenant* and check that the operation exists on
its release before calling it. The public API FAQ asks API clients to implement
retry/backoff. Do not guess REST routes based on legacy Galileo APIs.

The official documentation index currently exposes 22 REST resource groups.
The matrix covers their operating families as follows; an indexed endpoint
still needs a release- and tenant-specific availability check before use.

| REST groups in the current index | Feature family to inspect |
|---|---|
| `health`, `auth`, `system_users`, `users`, `groups`, `api_keys` | Deployment readiness, identity, user/group administration, and key lifecycle |
| `projects`, `log_stream`, `datasets`, `experiment`, `data` | Project/Agent Stream lifecycle, datasets/versions, prompts, experiments, and evaluators |
| `trace`, `logstream-insights`, `run_insights_settings` | Telemetry search/export/deletion, stream usage, and Run Insights |
| `annotation`, `annotation_queue`, `annotation_queue_records`, `feedback` | Human feedback, templates, queues, and export |
| `integrations`, `trends_dashboard` | Provider integrations/cost and Trends dashboards |
| `organization-jobs`, `protect` | Organization data jobs and Protect compatibility check |

## Object and policy action contract

The [object-action matrix](references/object-action-matrix.json) lists the
managed resources, policies, settings, and read-only outputs in the official
documentation. Each row states create, update, delete, and read-back paths or
an explicit documentation gap. Use
`bash scripts/setup.sh --plan --object ID --operation create` (or `update`,
`delete`, `verify`) to select an operation. Then open the current linked schema
or UI, inspect existing tenant state, perform the requested action, and read it
back. A feature row or a role capability alone does not prove working CRUD.

The official [documentation index](https://agent-observability-docs.splunk.com/llms.txt)
lists 22 REST reference groups, all mapped in the object matrix, including
read-only and authentication groups. Its [OpenAPI
specification](https://api.galileo.ai/public/v2/openapi.json) advertises a
Galileo server and `/v2` routes; it is a route/schema reference, not proof that
every route is enabled in AO SaaS or on-premises. The SDK documents prompt
and annotation queue actions absent from the public REST group list. The REST
index has no dashboard-create or Tokenomics provider-management CRUD route.
Use the documented UI or SDK where available and record the machine-interface
gap. SaaS Splunk Observability Cloud access tokens are distinct from on-prem AO
API keys: create a scoped token in Observability Cloud, rotate its secret as
needed, and deactivate the validation token after use. The [organization token
guide](https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/org-access-tokens)
states that organization access tokens cannot be deleted. For AO Agent Control,
the global control and stream clone are separate
objects; confirm the target's supported `deny`, `steer`, or `observe` action,
`list`/`regex`/`json`/`sql` or custom evaluator, and any composite condition
before creating it. A saved policy needs stream binding and a real runtime
result to count as enforced.

## Action paths that require distinct evidence

| Request | Execute through the documented surface | Completion evidence |
|---|---|---|
| Agent Stream evaluator setup | Inspect existing assignments, choose the supported trace/span/session node and sampling rate, then configure the requested evaluator in the stream. Test custom evaluators against manual input, existing logs, or a labeled dataset before broad sampling. Composite evaluators need their required metrics available first. | Saved assignment and sample rate; approved trace with a score and expected evaluator version. |
| Agent Stream and dataset lifecycle | Inventory project/stream and dataset/version before creation. Apply exact stream metric settings or dataset content updates through the target-supported UI/API/SDK. Treat synthetic dataset extension as a cost and privacy decision; preview any bulk delete. | Stream and dataset/version IDs, schema/settings, operation status, and sampled resulting state. |
| Luna Studio training | After Enterprise deployment readiness, prepare the labeled test/training data, choose UI or SDK, run a bounded fine-tune, evaluate held-out results, and register the approved evaluator. | Training run ID/status, dataset shape, quality result, usage, registered evaluator ID, and safe Agent Stream result. |
| Alerts and notifications | In the Agent Stream **Alerts** tab, choose an evaluator, aggregation, threshold, and time window. Add requested email, Slack, or generic webhook destinations through secure UI entry. Webhook credentials are write-only after save. Use **Send test event** for a safe staging destination. | Alert settings, destination owner, test delivery result, and Active/Failed state. |
| Views and Trends dashboards | Save Agent Stream or experiment columns/filters as a view, recording private versus project visibility. For Trends widgets/sections/dashboards, inspect the exact deployment's UI or documented API schema before editing. | Saved view/dashboard identity and populated result after reload. |
| Trace search, export, recompute, and deletion | Use the documented project-scoped query/export/recompute endpoints or SDK. Bound time/filter and count matches first. For a delete, confirm exact filters and scope; organization-wide metadata deletion has a separate job API. | Before/after counts, destination or job ID, sanitized sample, and explicit deletion authorization when applicable. |
| Model pricing and cost investigation | Inspect **Model Pricing** and **Integration Costs** separately from Tokenomics and SaaS Billing and Usage. An admin may set/revert a model price after reviewing future impact. | Before/after price, affected model, future-only effect, and read-only integration cost range. |
| Users, groups, keys, and SSO | Check the target identity model, resource collaborator role, and capability. Invite or assign only requested users/groups. Create and rotate API keys with protected local storage; revoke the old key after dependent clients succeed. Use the deployment-specific SSO procedure. | Role/group/key IDs without secret values, effective access, propagation, and dependent-client health. |
| Agent Control | Create the control, initialize its supported runtime SDK in the application, then monitor the Control View and trace. Validate a permitted input and a safe blocked input in staging. | Control ID, runtime configuration, and distinct allow/block evidence. |
| Tokenomics | In Tokenomics Settings, connect only supported coding tools, configure fiscal calendar, and upload the approved Workday hierarchy when requested. Wait for the daily refresh. | Provider integration state, calendar, hierarchy join/visibility check, Data as of timestamp, and no-backfill caveat. |

## Official source index

| Topic | Official documentation |
|---|---|
| Product overview, deployment options | [What Is Splunk Agent Observability?](https://agent-observability-docs.splunk.com/what-is-splunk-agent-observability) |
| SaaS, access, feature comparison | [Splunk Agent Observability (SaaS)](https://agent-observability-docs.splunk.com/saas/overview) |
| SaaS Free Edition and onboarding | [Splunk Observability Cloud Free Edition](https://help.splunk.com/en/splunk-observability-cloud/get-started/free-edition/splunk-observability-cloud-free-edition) |
| SaaS usage and limits | [Billing and Usage](https://agent-observability-docs.splunk.com/saas/billing-and-usage) |
| First trace and SDK configuration | [Log Your First Trace](https://agent-observability-docs.splunk.com/getting-started/quickstart) |
| SDK/API logging | [Instrumentation](https://agent-observability-docs.splunk.com/sdk-api/logging/logging-basics), [Logger](https://agent-observability-docs.splunk.com/sdk-api/logging/splunk-ao-logger) |
| Sessions, multimodal, context | [Sessions](https://agent-observability-docs.splunk.com/concepts/logging/sessions/sessions-overview), [Multimodal](https://agent-observability-docs.splunk.com/concepts/logging/multimodal-observability), [Distributed Tracing with OTel](https://agent-observability-docs.splunk.com/sdk-api/logging/distributed-tracing-otel) |
| Framework/provider integrations | [Integrations Overview](https://agent-observability-docs.splunk.com/sdk-api/third-party-integrations/overview) |
| Evaluators and comparison | [Evaluator Overview](https://agent-observability-docs.splunk.com/concepts/evaluators/overview), [Evaluator Comparison](https://agent-observability-docs.splunk.com/concepts/evaluators/evaluator-comparison) |
| Experiments, datasets | [Experiments](https://agent-observability-docs.splunk.com/sdk-api/experiments/experiments), [Datasets](https://agent-observability-docs.splunk.com/sdk-api/experiments/datasets) |
| Agent Control | [Agent Control Overview](https://agent-observability-docs.splunk.com/concepts/agent-control/overview), [Create a control](https://agent-observability-docs.splunk.com/how-to-guides/agent-control/create-a-control), [Initialize and configure Agent Control](https://agent-observability-docs.splunk.com/how-to-guides/agent-control/initialize-and-configure-agent-control), [Built-in evaluators](https://docs.agentcontrol.dev/concepts/evaluators/built-in-evaluators), [Decorate LLM and tool calls](https://docs.agentcontrol.dev/how-to/decorate-llm-tool-calls) |
| Annotations and Annotation Queues | [Annotations Overview](https://agent-observability-docs.splunk.com/concepts/annotations/overview) |
| Luna Studio | [Luna Studio](https://agent-observability-docs.splunk.com/luna-studio) |
| Luna Studio execution | [SDK overview](https://agent-observability-docs.splunk.com/luna-studio/sdk/overview), [UI quickstart](https://agent-observability-docs.splunk.com/luna-studio/ui/quickstart) |
| Signals and Tokenomics | [Signals](https://agent-observability-docs.splunk.com/concepts/signals), [Tokenomics](https://agent-observability-docs.splunk.com/concepts/tokenomics/tokenomics) |
| Tokenomics scope, metrics, refresh and cost provenance | [Tokenomics concepts and metrics](https://agent-observability-docs.splunk.com/concepts/tokenomics/tokenomics-concepts) |
| Access control and projects | [Capabilities](https://agent-observability-docs.splunk.com/saas/capabilities), [Access Control](https://agent-observability-docs.splunk.com/concepts/access-control), [Projects](https://agent-observability-docs.splunk.com/concepts/projects), [SSO](https://agent-observability-docs.splunk.com/security/sso) |
| SaaS credentials and token variables | [Find Your Organization Keys](https://agent-observability-docs.splunk.com/references/faqs/find-keys), [Capabilities](https://agent-observability-docs.splunk.com/saas/capabilities) |
| MCP maturity and supported use | [Splunk Agent Observability MCP Server](https://agent-observability-docs.splunk.com/getting-started/mcp/setup-splunk-ao-mcp) |
| REST API URL and authentication | [API Overview](https://agent-observability-docs.splunk.com/api/getting-started) |
| Cisco Cloud Control integration | [Agent Observability in Cisco Cloud Control](https://agent-observability-docs.splunk.com/concepts/cisco-cloud-control) |
| Release notes | [On-premises](https://agent-observability-docs.splunk.com/release-notes), [SaaS](https://agent-observability-docs.splunk.com/release-notes-saas) |
| Troubleshooting and errors | [Troubleshooting](https://agent-observability-docs.splunk.com/references/faqs/troubleshooting), [Common Errors](https://agent-observability-docs.splunk.com/references/faqs/errors), [FAQ](https://agent-observability-docs.splunk.com/references/faqs/faqs) |
| Legacy product boundary | [Splunk AI Agent Monitoring](https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring) |
| Adjacent AI infrastructure telemetry | [Splunk AI Infrastructure Monitoring](https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-infrastructure-monitoring) |
| First-run sample projects | [Sample Projects](https://agent-observability-docs.splunk.com/getting-started/sample-projects/sample-projects) |
| Agent Stream evaluators and custom validation | [Configure Evaluators](https://agent-observability-docs.splunk.com/concepts/logging/configure-evaluators/configure-evaluators), [Composite Evaluators](https://agent-observability-docs.splunk.com/concepts/evaluators/custom-evaluators/composite-evaluators), [Test Custom Evaluators](https://agent-observability-docs.splunk.com/concepts/evaluators/custom-evaluators/test-evaluators), [Local Evaluator](https://agent-observability-docs.splunk.com/how-to-guides/evaluators/create-local-evaluator/create-local-evaluator) |
| First experiment and application MCP calls | [Run an Experiment](https://agent-observability-docs.splunk.com/getting-started/experiments), [Log MCP Server Tool Calls](https://agent-observability-docs.splunk.com/how-to-guides/basics/log-mcp-server-calls/log-mcp-server-calls) |
| Alerts, saved views, and Trends dashboards | [Set Up Alerts on Logs](https://agent-observability-docs.splunk.com/how-to-guides/basics/set-up-alerts-on-logs), [Create and Manage Views](https://agent-observability-docs.splunk.com/how-to-guides/basics/create-views), [List Dashboards](https://agent-observability-docs.splunk.com/api-reference/trends_dashboard/list-dashboards), [Create Widget](https://agent-observability-docs.splunk.com/api-reference/trends_dashboard/create-widget) |
| Trace records and maintenance | [Query Traces](https://agent-observability-docs.splunk.com/api-reference/trace/query-traces), [Export Records](https://agent-observability-docs.splunk.com/api-reference/trace/export-records), [Recompute Metrics](https://agent-observability-docs.splunk.com/api-reference/trace/recompute-metrics), [Delete Traces](https://agent-observability-docs.splunk.com/api-reference/trace/delete-traces), [Delete by Metadata](https://agent-observability-docs.splunk.com/api-reference/organization-jobs/delete-by-metadata) |
| Agent Stream lifecycle and Insights | [Create Agent Stream](https://agent-observability-docs.splunk.com/api-reference/log_stream/create-log-stream), [Update Metric Settings](https://agent-observability-docs.splunk.com/api-reference/log_stream/update-metric-settings), [Delete Agent Stream](https://agent-observability-docs.splunk.com/api-reference/log_stream/delete-log-stream), [Get Insights Token Usage](https://agent-observability-docs.splunk.com/api-reference/logstream-insights/get-logstream-insights-token-usages) |
| Dataset versions, extension, and bulk maintenance | [Query Dataset Versions](https://agent-observability-docs.splunk.com/api-reference/datasets/query-dataset-versions), [Get Synthetic Extend Status](https://agent-observability-docs.splunk.com/api-reference/datasets/get-dataset-synthetic-extend-status), [Bulk Delete Datasets](https://agent-observability-docs.splunk.com/api-reference/datasets/bulk-delete-datasets) |
| Model pricing and provider evaluator costs | [Model Pricing Settings](https://agent-observability-docs.splunk.com/concepts/costs/model-pricing-settings), [Integration Costs](https://agent-observability-docs.splunk.com/concepts/costs/integration-costs) |
| Users, groups, and API keys | [Add Users and Assign Roles](https://agent-observability-docs.splunk.com/getting-started/add-users-and-assign-roles), [Add User to Group](https://agent-observability-docs.splunk.com/api-reference/groups/add-user-to-group), [Create API Key](https://agent-observability-docs.splunk.com/api-reference/api_keys/create-api-key), [Delete API Key](https://agent-observability-docs.splunk.com/api-reference/api_keys/delete-api-key) |
| Run Insights settings | [Get Settings](https://agent-observability-docs.splunk.com/api-reference/run_insights_settings/get-settings), [Upsert Insights Config](https://agent-observability-docs.splunk.com/api-reference/run_insights_settings/upsert-insights-config) |
| Agent Control and Protect compatibility | [Protect Invoke API](https://agent-observability-docs.splunk.com/api-reference/protect/invoke) |
| On-premises AI Assistant | [AI Assistant](https://agent-observability-docs.splunk.com/concepts/ai-assistant) |
| NVIDIA NIM application model integration | [Integrate NVIDIA NIM](https://agent-observability-docs.splunk.com/how-to-guides/third-party-integrations/nvidia-nim-models) |

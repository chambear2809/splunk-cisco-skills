---
name: splunk-agent-observability-setup
description: "Use when onboarding, instrumenting, evaluating, securing, or operating Splunk Agent Observability for agentic and generative AI applications across SaaS and on-premises deployments. Work through the product's MCP server when available, otherwise use documented SDK/API/UI paths; cover traces, sessions, Agent Streams, evaluators, experiments, datasets, prompts, Agent Control, Signals, Tokenomics, access, integrations, and troubleshooting."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_enterprise_10_6: "not-applicable"
  enterprise_compatibility_verified: "2026-10-05"
  runtime_requirements: "Offline helpers require Bash and Python 3. Live work requires an authorized Splunk Agent Observability interface and access to current product documentation."
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
  platform_compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
---

# Splunk Agent Observability Setup

## Purpose and routing

Use this skill for the post-rebrand Splunk Agent Observability product: an
observability, evaluation, and guardrail platform for generative AI and agentic
applications. It has separate SaaS and customer-managed on-premises deployment
contracts. It is a distinct product workflow from:

- **Splunk AI Agent Monitoring** in Splunk Observability Cloud APM, which the
  current product docs mark for deprecation. Use
  `splunk-observability-ai-agent-monitoring-setup` only when the user explicitly
  needs that legacy experience or its migration path.
- **Legacy Galileo tenants**. Route an existing Galileo application lifecycle
  or explicitly identified pre-rebrand API contract to `galileo-platform-setup`.
  Confirm the actual tenant/product contract with the customer or Splunk; do not
  treat the August 7, 2026 on-premises announcement date as a tenant migration
  or contract cutoff.
- **Galileo on-premises deployment** or legacy packaged components. Route to the
  applicable `galileo-on-prem-*` deployment skill only when the target is the
  legacy product, not Splunk Agent Observability on-premises.
- **Splunk Observability Cloud AI telemetry/APM** collection or AI infrastructure
  monitoring. Delegate those components to
  `splunk-observability-ai-agent-monitoring-setup` or the named collector,
  dashboard, detector, and Cisco integration child skills; do not confuse those
  APM destinations with the Agent Observability application itself.

When the requested product epoch is unclear, establish whether the tenant is
legacy Galileo, Splunk Agent Observability SaaS, or Splunk Agent Observability
on-premises from the tenant URL and product UI. Do not infer the tenant's
onboarding date from the current date. Route unknown or boundary cases to a
read-only compatibility review until the customer confirms the product and
deployment.

## When to Activate

Use this skill when the request names Splunk Agent Observability or asks to
instrument, evaluate, secure, investigate, or administer its SaaS or
on-premises application. Use the routing rules above for adjacent products.

## Prerequisites

Identify the target deployment and project/Agent Stream, obtain authorized
product access, and inspect the user's application repository if code changes
are requested. Credentials must be available through protected local files,
a secret manager, or an approved product credential flow; request paths and
non-secret configuration values only.

## Workflow Overview

```text
┌──────────┐   ┌──────────────┐   ┌────────────────┐   ┌──────────┐
│ Discover │ → │ Plan & stage │ → │ Apply requested│ → │ Validate │
│ product  │   │ exact scope  │   │ action         │   │ evidence │
└──────────┘   └──────────────┘   └────────────────┘   └──────────┘
```

The bundled `setup.sh` is an offline task planner and `validate.sh` checks the
local coverage contract. `references/product-feature-matrix.json` tracks product
topics; `references/object-action-matrix.json` tracks distinct managed
objects, policies, settings, or read-only outputs and their create/update/delete
paths. Matrix `direct_apply` means the agent carries out a documented code, MCP,
API, or UI action when that surface and authorization are available; it does not
mean `setup.sh` changes a tenant. A public API reference is not proof that the
route is enabled in a particular SaaS or on-premises tenant.

## Operating contract

This is an action-oriented workflow. Inspect the user's repository, deployment,
connected MCP tools, and target entitlement; perform the requested setup or
configuration using the strongest documented interface available; and validate
the result. Do not stop after giving generic instructions when a supported MCP,
SDK, API, local file, or child-skill action is available.

1. **Discover before acting.** Read `reference.md`,
   `references/product-feature-matrix.json`, and
   `references/object-action-matrix.json`. Inspect the current official docs
   and release notes for the requested feature. For this fast-moving product,
   verify version and deployment-specific availability instead of reusing old
   Galileo or AI Agent Monitoring instructions.
2. **Identify the deployment.** Record SaaS versus on-premises, exact console/API
   base URL or Observability Cloud realm, product/release entitlement, and
   target project/Agent Stream. For SaaS, distinguish Free Edition from a
   separately entitled subscription. Free Edition is documented as available
   without a fixed trial and supports up to 15 hosts; paid access/entitlement
   steps can require the Splunk account team. Do not assume every SaaS feature is
   enabled for every organization. The on-premises release is announced, but
   the public docs do not provide a complete install/upgrade runbook; use a
   support-assisted deployment handoff unless current official release-specific
   instructions and an approved customer procedure are available.
3. **Inspect available tools and permissions.** Prefer an already connected,
   organization-approved Splunk Agent Observability MCP server for supported
   account actions. Treat its documented server as under construction until its
   current docs declare general availability. Inspect its actual tool list and
   schemas before acting; do not infer tool names, API routes, or CRUD support.
   Use the official `splunk-ao` SDK for application instrumentation and
   documented APIs for management operations. Use UI runbooks only where no
   documented machine interface exists.
4. **Plan and stage.** Inventory what exists first. Reuse the requested project,
   Agent Stream, evaluators, and integrations when possible. Stage application
   code/configuration changes for review. List each live create/update/delete,
   data export, integration credential, evaluator cost, and privacy consequence.
   For each requested object or policy, select its `--object` plan, read the
   linked source and live schema/UI, and record exact create, update, bind,
   verify, and cleanup operations. A `not-documented` entry is a gap to resolve
   from the actual tenant interface, not permission to invent an endpoint.
5. **Apply the requested scope.** Carry out read-only checks and specifically
   requested, reversible setup actions. A `render_runbook` matrix status means
   the interface must be checked first; when the documented interface is
   available and the task is authorized, perform the action and validate it.
   Before deleting data/resources, sharing access, changing production controls,
   enabling broad content capture, or generating material billable evaluation
   traffic, show the exact target and effect when those actions are not already
   authorized in the user's request. Do not use approval for one operation to
   authorize unrelated changes.
6. **Validate with evidence.** Send a small synthetic or approved test trace
   without real customer secrets or personal data; confirm it appears in the
   intended project and Agent Stream; check expected span/session/message
   relationships, metadata, evaluator results, experiment state, and controls
   according to the requested scope. Capture status, identifiers, links, and
   sanitized errors; never copy prompt/response bodies or credentials into the
   report unless explicitly requested and approved.
   For explicitly requested live end-to-end validation of SaaS telemetry and
   Agent Control in Kubernetes, follow
   `references/live-validation-runbook.md`; it covers secret staging, the
   deterministic allow/block proof, and exact-scope cleanup.
7. **Close the loop.** Report completed actions, created/changed identifiers,
   validation evidence, costs/limits relevant to the run, and remaining UI,
   account-team, or deployment-owner handoffs. Mark incomplete features as gaps.

## Secret and data handling

- Never ask for or display API keys, ingest tokens, LLM provider keys, SSO
  secrets, passwords, or client secrets in conversation.
- Never put a literal secret in a command argument, shell history, generated
  example, source control, or shell command's environment-variable prefix.
  The SDK does require runtime token variables; load them from a protected,
  gitignored `.env` file or secret manager without printing values, and verify
  the exact variable name against the installed SDK and current deployment
  guide. Use approved secret files or the product's secure credential entry.
  Keep key material out of MCP server configuration files committed to a
  repository; prefer the IDE's secret/input facility or its documented
  environment-variable reference.
- Treat user prompts, system prompts, tool inputs/outputs, traces, evaluation
  data, datasets, and multimodal content as potentially sensitive. Collect the
  minimum fields needed. Mask, anonymize, or exclude PII before logging as the
  official FAQ directs. Confirm before enabling content capture or exporting
  data. Explain retention, access, sampling, and any destination change from
  current documentation; do not claim redaction unless the selected component
  documents and validates it.
- Do not send synthetic test traces to a production project without the user's
  direction. Do not call paid LLMs/evaluators or create large datasets without
  including expected usage in the plan.

## Supported task families

Use the matrix in `references/product-feature-matrix.json` as the source of
truth for topic coverage and `references/object-action-matrix.json` for object
actions and documented gaps. It includes, at minimum:

- entitlement, edition, SaaS/on-prem deployment, release, console/API URL, and
  first-run readiness;
- API key/ingest authentication, user/role/capability and project-sharing
  readiness, SSO handoffs, and organization/project boundaries;
- Python SDK instrumentation, supported framework/model integrations (including
  NVIDIA NIM), custom logging, MCP tool-call spans, Agent Streams, sessions,
  traces/spans, metadata/tags, multimodal content, distributed tracing,
  saved views, search/export, and data maintenance;
- built-in, LLM-as-a-judge, Luna, custom code, composite, and local experiment
  evaluators; assignment, sampling/feedback/autotune behavior, test cases,
  Luna Studio training/deployment, and evaluation-cost review;
- projects, datasets, prompts, runs, experiment groups/comparison, and code,
  playground, or unit-test experiment paths;
- Agent Control policy/runtime setup and monitoring, annotations and queues,
  Signals, on-premises AI Assistant, Tokenomics, model pricing, integration
  costs, alerts, rankings, Trends dashboards, and Run Insights where documented;
- MCP server setup and current maturity, supported API/SDK surfaces, SaaS
  billing and limits, Cisco Cloud Control entry points, release notes, and
  troubleshooting/error catalog.

Deployment-specific boundaries include the current SaaS feature differences:
SaaS has limited preset Luna evaluator support (Prompt Injection, Toxicity,
Sexism, and PII only), does not offer Luna fine-tuning, custom code evaluators,
or AI Assistant, and does not surface Agent Observability inputs/outputs in APM
pages or Observability Cloud global search. Recheck the official comparison
before each plan because this product is changing quickly.

Use the first-party Splunk Agent Observability MCP server for its documented
capabilities when present: dataset creation/status, prompt templates, experiment
guidance/actions, Signals, integrations, and documentation lookup. This server
is currently documented as under construction. Check its live tools and current
documentation before invoking it; use feature-specific SDK/API or UI paths for
unsupported operations. Its presence does not mean it can administer every
product feature.

Agent Control's managed guardrail object is a **control**. Its policy consists of
scope (step type/name and Pre/Post stage), a selector and evaluator condition
(including `and`/`or`/`not` combinations where supported), and a `deny`, `steer`,
or `observe` action. Inventory the exact policy type and action exposed by the
tenant before creation. Create the global control, bind it to the intended Agent
Stream, and test both a safe allowed case and the expected policy action.
Binding creates an independent stream clone; later global edits do not update
it. The generic Agent Control server reference documents create, update, delete,
attach, and detach endpoints, but its default local-server routes and auth are
not automatically the AO SaaS contract. Verify the AO deployment's live route
and clone behavior before using those endpoints for update or cleanup. AO SaaS
capabilities name separate control CRUD, binding, and runtime permissions.
The runtime SDK can register an Agent Control agent name. For disposable work,
check whether the target tenant offers a supported delete-agent action before
registering a new name; deleting an AO project alone may leave that agent
record behind.

## Quick start

Resolve paths from this skill's directory. For a scoped local plan, run
`bash scripts/setup.sh --plan --feature first-trace-python-sdk --deployment saas`
from that directory
and select the relevant feature ID for the actual request. The plan lists the
official source and validation evidence; the agent must then carry out the
requested action through the available product or application interface.
For an exact resource action, run for example
`bash scripts/setup.sh --plan --object agent-control-global-policy --operation create --deployment saas`.
If an operation is marked `not-documented`, check the live tenant and report the
gap if no supported action exists; do not claim complete CRUD from topic count.

Check whether the product MCP server is already configured and inspect its
available tools without exposing credentials. If the application is in this
workspace, inspect its dependency manager, framework, and tests before editing.
Follow the official [first-trace quickstart](https://agent-observability-docs.splunk.com/getting-started/quickstart)
for the exact current SDK calls and environment names. Do not copy sample
secrets into the repository; use file-backed local settings and `.gitignore`.

## Delegation

Keep this skill as the owner of Splunk Agent Observability product orchestration
and final validation. Delegate only a clearly bounded component when needed:

| Work | Canonical skill |
|---|---|
| Legacy Splunk AI Agent Monitoring or OTel AI telemetry | `splunk-observability-ai-agent-monitoring-setup` |
| Splunk Observability Cloud AI Infrastructure Monitoring | `splunk-observability-ai-agent-monitoring-setup` and `splunk-observability-otel-collector-setup` |
| Splunk OTel Collector installation/configuration | `splunk-observability-otel-collector-setup` |
| Splunk Observability dashboards | `splunk-observability-dashboard-builder` |
| Observability Cloud detectors, native alerts, or operations | `splunk-observability-native-ops` |
| Cisco AI Defense integration | `cisco-security-cloud-setup` or the specific current Cisco AI Defense skill in the catalog |
| Legacy Galileo tenant lifecycle | `galileo-platform-setup` |
| Legacy Galileo Agent Control only | `galileo-agent-control-setup` |

Do not delegate new Splunk Agent Observability objects to a legacy Galileo
script or use a legacy Galileo token/API endpoint against the new product.

## Examples

- “Instrument this Python agent with Splunk Agent Observability and verify one
  safe trace in the staging Agent Stream.”
- “Create a test dataset, run the evaluator experiment against this prompt, and
  summarize failures without exposing the trace content.”
- “Audit which evaluators are enabled on this Agent Stream and recommend safe
  production thresholds.”
- “Review Signals and Tokenomics for this team; don't change any live controls.”
- “Help me enable Agent Control for prompt injection and PII, then validate its
  behavior in staging before we consider production.”

## Troubleshooting

Use `bash scripts/validate.sh --help` from this skill's directory
for local, offline repository validation. For a live deployment, validate the
application behavior and target state with the actual approved interface and
sanitized test data. A valid repository matrix does not prove tenant entitlement
or live data ingest.

| Symptom | Check |
|---|---|
| Access denied or missing product menu | Verify edition/entitlement, organization, user role, resource collaborator role, API key capabilities, and SaaS role-assignment propagation. |
| No traces or wrong project | Verify deployment-specific SDK configuration, console URL or SaaS realm/token, project and Agent Stream selection, network access, and SDK error output. |
| Trace appears but evaluators are empty | Verify evaluator assignment/enabled state, supported node types, provider integration, access, and that the input data needed by the evaluator is present. |
| Evaluator results vary or cost unexpectedly | Check model/provider, evaluator type, sampling, run size, Luna availability, and current billing docs before rerunning. |
| On-premises feature or endpoint mismatch | Verify exact product release and deployment docs; do not copy SaaS realms/endpoints into self-managed API calls. |
| MCP setup or action fails | Reinspect current MCP docs, server maturity, endpoint and API key scope; use the supported SDK/API/UI fallback and record the unsupported action. |

## References

`reference.md` links the current official documentation by task family and
records product-routing and feature-availability boundaries. The feature matrix
is the tracked topic coverage contract and feeds the repository product-feature
coverage audit. The object matrix is the action contract. Review both whenever
a Splunk release or Agent Observability doc changes.

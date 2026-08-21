# Splunk AI/ML Toolkit Setup Reference

## Product Catalog

Current first-class installable coverage:

| Product | Splunkbase | Package ID | Latest audited release | Placement |
| --- | --- | --- | --- | --- |
| Splunk AI Toolkit / MLTK | `2890` | `Splunk_ML_Toolkit` | `6.0.2`, August 10, 2026 | Search tier |
| PSC Linux 64-bit | `2882` | `Splunk_SA_Scientific_Python_linux_x86_64` | `4.3.4`, July 22, 2026 | Search tier |
| PSC Windows 64-bit | `2883` | `Splunk_SA_Scientific_Python_windows_x86_64` | `4.3.4`, July 22, 2026 | Search tier |
| PSC Mac Intel | `2881` | `Splunk_SA_Scientific_Python_darwin_x86_64` | `4.3.4`, July 22, 2026 | Search tier |
| PSC Mac Apple Silicon | `6785` | `Splunk_SA_Scientific_Python_darwin_arm64` | `4.3.4`, July 22, 2026 | Search tier |
| DSDL | `4607` | `mltk-container` | `5.2.4`, May 22, 2026 | Search tier plus external runtime |

Legacy/migration-only coverage:

| Product | Splunkbase | Package ID | Status |
| --- | --- | --- | --- |
| PSC Linux 32-bit | `2884` | `Splunk_SA_Scientific_Python_linux_x86` | Legacy/migration only; no new Splunk 10.5 install |
| Splunk App for Anomaly Detection | `6843` | unknown public manifest | EOL/migration-only; no new Splunk 10.5 install |
| Smart Alerts Assistant for Splunk (beta) | `6415` | `Smart_Alerts_Assistant` | Legacy beta/migration-only; no new Splunk 10.5 install |

The registry retains these IDs for discovery and migration evidence. None of
the three listings advertises Splunk 10.5 compatibility, and this skill must
never emit an install command for them on a 10.5 target.

## AI Toolkit Feature Coverage

The coverage report must include these surfaces:

- package install and version compatibility
- PSC dependency selection and install order
- the documented `6.0.2` ML-SPL command surface: `ai`, `aiagent`, `apply`,
  `deletemodel`, `fit`, `listmodels`, `sample`, `score`, `summary`
- the package-only commands `agentstatus`, `externalendpointinventory`,
  `kvstorelookup`, `logexperiment`, and `mltkmanage`, which ship in
  `default/commands.conf` but are absent from the documented command table
- AI Toolkit `6.0.2` compatibility with PSC `4.3.4`, the Python `3.13` PSC
  runtime, and Splunk Enterprise `9.3.x`-`10.5.x` or Splunk Cloud Platform
- ML command permissions, algorithm access, search safeguards, and performance
  cost settings, including the `is_risky` commands that trip SPL safeguards
- Smart Assistants and Experiment Management for prediction, clustering,
  outlier detection, forecasting, and anomaly workflows
- Cisco Deep Time Series Model forecasting, anomaly detection, predictive
  alerting, hosted Cloud, and self-hosted Enterprise readiness, recorded as
  `ga` since AI Toolkit `6.0.0`
- Cisco Time Series Model 1.0 open-weight model readiness, explicitly retained
  as a separate `available` Apache-2.0 release rather than an AI Toolkit
  package or hosted-LLM connection
- Hosted LLM readiness for Foundation-Sec and GPT-OSS where available inside
  the Splunk Platform boundary
- AI Toolkit Agent Launchpad readiness, recorded as `ga` since `6.0.0` and
  distinct from Cloud Control Studio Agent Builder
- Agent Launchpad supported LLM providers, MCP providers, Agent Skills, and the
  `edit_agent_connections` / `run_agents` permission boundary
- `aiagent` invocation with `agent_name` and optional `prompt`, agent
  `Available`/enabled state, and the in-product run-history surface
- Connections tab readiness for LLM providers and container endpoints
- Container Management tab readiness for DSDL-backed workflows
- model object inventory, lookup permissions, and retraining risk after the
  MLTK `5.3.0` model compatibility break
- ONNX upload/apply readiness
- external LLM/provider handoffs for OpenAI-compatible endpoints, AWS Bedrock,
  AWS SageMaker inference, GCP Vertex AI, and local/private model endpoints
- alerting handoffs for searches that use trained models or anomaly outputs,
  including the `Run AI Agent` alert trigger action

### Package-derived `6.0.2` command surface

`default/commands.conf` in the inspected `6.0.2` package is the authority for
what the install actually exposes:

| Command | Documented in `6.0.2` | `is_risky` | Notes |
| --- | --- | --- | --- |
| `fit` | Yes | Yes | Core model training |
| `apply` | Yes | Yes | Also the CDTSM entry point via `apply CDTSM` |
| `summary` | Yes | No | |
| `score` | Yes | No | |
| `listmodels` | Yes | No | |
| `deletemodel` | Yes | Yes | |
| `sample` | Yes | No | |
| `ai` | Yes | Yes | LLM passthrough, added in `5.6.0` |
| `aiagent` | Yes | Yes | GA in `6.0.0`; `maxwait = 1500`, `run_in_preview = false` |
| `agentstatus` | No | Yes | Backs Agent Launchpad create/delete |
| `externalendpointinventory` | No | No | Feeds the external-models inventory search |
| `kvstorelookup` | No | No | App internal |
| `logexperiment` | No | No | App internal, `local = true` |
| `mltkmanage` | No | Yes | Maintenance, e.g. `mltkmanage cleanupPyCache` |

All commands declare `python.required = 3.13`, which matches the PSC `4.3.4`
runtime requirement.

`agentstatus` requires `agent_name`, `action` (`create` or `delete`), and
`user_name`; its `searchbnf.conf` example shows only the first two. `aiagent`
requires `agent_name` and additionally accepts `prompt`, `session_id`,
`trigger`, `source`, and `conversation_tool`, defaulting `trigger` to
`adhoc_search` and `source` to `SPL`. Only `agent_name` and `prompt` are
documented, so treat the remaining parameters as internal.

## Product Lifecycle Matrix

Product lifecycle is independent from repository automation status. For
example, an upstream GA package can remain a manual handoff in this skill, and
an Alpha feature must not be called GA because the renderer covers it.

| Surface | Product stage as of 2026-08-20 | Platform boundary | Repository behavior |
| --- | --- | --- | --- |
| Splunk AI Toolkit `6.0.2` | GA package | Splunk Enterprise `9.3.x`-`10.5.x` and Splunk Cloud per the version matrix | Install/update delegation plus validation |
| AI Toolkit Agent Launchpad | GA since `6.0.0` | Splunk Cloud in a supported AWS region; Splunk Enterprise through Splunk Cloud Connect | Manual handoff on both platforms; no agent mutation |
| Agent Launchpad connections and Agent Skills | GA since `6.0.0` | Requires a supported LLM provider and `edit_agent_connections` | UI/secret-store handoff only |
| `aiagent` command and agent run history | GA since `6.0.0` | Ships in the public package; invocation requires `run_agents` | Validation handoff only; no agent or index creation |
| Cisco Time Series Model 1.0 | Available open-weight release | Hugging Face/GitHub/PyPI or reviewed DSDL/self-hosted runtime | Runtime and provenance handoff |
| Cisco Deep Time Series Model integration | GA since `6.0.0` | Splunk-hosted for Cloud in a supported region; self-hosted model service for Enterprise | Readiness and model-service handoff only |
| Splunk-hosted Foundation-Sec and GPT-OSS LLMs | GA hosted-model capability, tenant/model dependent | Eligible Splunk Cloud | Connections and data-governance review |

### AI Toolkit Agent Launchpad boundary

Agent Launchpad is the Splunk feature that builds, runs, reviews, and manages
operational agents around Splunk searches and alerts, approved knowledge
sources, MCP tools, and an LLM. It is not the Agent Builder described for Cisco
Cloud Control Studio. Cloud Control Studio implementation, marketplace, Cisco
product connectors, and Cloud Control agent deployment route to
`cisco-cloud-control-setup`.

AI Toolkit `6.0.0` released Agent Launchpad as the generally available
successor to the earlier Agent Builder feature preview, and the `6.0.2`
documentation set is the source for these surfaces:

- installing the public Splunkbase AI Toolkit package ships the Agent Launchpad
  views (`agents`, `agent_edit`, `agent_skills`, `agent_run_history`,
  `agent_conversation`, `agentconnections`) and the `aiagent` command. There is
  no private-preview enrollment step.
- Splunk Cloud Platform must be in a documented supported AWS region, and that
  region's Agent Launchpad egress IP must be added to the stack spec
  `accessRules.apiAllowlistIP`
- Splunk Enterprise reaches Agent Launchpad through the Splunk Cloud Connect
  app, so an on-premises estate is a documented handoff rather than an
  unavailable surface
- `edit_agent_connections` controls creation of knowledge-base and MCP
  connections; `run_agents` controls agent creation and invocation. The package
  `authorize.conf` grants both to `mltk_admin`, `sc_admin`, and
  `mltk_model_admin`.
- at least one supported LLM connection is required before creating an agent:
  OpenAI, Anthropic, Azure OpenAI, Amazon Bedrock, or a Splunk-hosted model.
  Custom LLM and Ollama connections are explicitly unsupported for Agent
  Launchpad even though the Connections tab can hold them.
- supported MCP providers are Splunk, Atlassian, Slack, PagerDuty, GitHub, and
  GitLab, plus custom MCP with Basic Auth, API key, Bearer Token, or OAuth 2.0.
  A single agent can use multiple connections of the same provider type.
- agents are private by default. Creation takes an alphanumeric name, an
  optional description of 500 characters or less, an LLM connection, a
  temperature defaulting to `0.7`, a max-tokens value defaulting to `5000`, and
  a reasoning effort of `None`, `Low`, `Medium`, or `High`.
- Agent Skills are reusable named instruction sets attached to an agent
- the invocation command is `aiagent`, with `agent_name` and an optional
  `prompt`. It ships in the public package, so its presence is expected on
  `6.0.2` rather than something to disclaim.
- an agent must reach the `Available` state and stay enabled before `aiagent`
  can invoke it
- run history is an in-product page filtered by time range, agent name, and
  owner, visible only to the owner or a shared role. The package writes it
  through `mlspl.conf` `[ai:AgentIntegrations] agent_run_index`, shipped as
  `_audit`, so no customer-created run-history index is a prerequisite.
- agent egress is constrained by `mlspl.conf` `[ai:AllowedDomains]`
  `allowed_domains` with `enforce_domain_validation`, which the package ships
  as `*` with validation enforced
- agents can be attached to alerts through the `Run AI Agent` trigger action,
  which automatically passes alert name, time, results, and search to the agent

Confirm the PSC pairing before reporting readiness: `6.0.2` requires PSC
`4.3.4` on Python `3.13`, while `6.0.0` accepted only `4.3.2` or `4.3.3`.

### Cisco time-series model boundary

The names refer to related but independently governed surfaces:

- **Cisco Time Series Model 1.0 (CTSM)** is the available, 250-million-
  parameter, univariate zero-shot forecasting model published under Apache
  2.0 as `cisco-ai/cisco-time-series-model-1.0`. The open model has model
  weights, GitHub/PyPI code, notebooks, and a self-hosting path. Splunk Lantern
  documents a DSDL `5.2.3` integration example; validate the command and image
  against the installed DSDL version.
- **Cisco Deep Time Series Model (CDTSM)** is the AI Toolkit-integrated
  forecasting, anomaly-detection, and predictive-alerting experience. `6.0.0`
  took it out of feature preview, so the `6.0.2` documentation records it as
  generally available. Cloud uses the Splunk-hosted model on dedicated GPU
  capacity in a supported region. Enterprise requires a separately hosted open
  Cisco Time Series Model service, an endpoint in `mlspl.conf`, and a matching
  bearer token in Splunk encrypted storage.

CDTSM is invoked as `apply CDTSM <fields_to_forecast>`. Wildcard forecast
fields are supported from `6.0.0`; the `by` and `fill_null` parameters arrived
in `5.7.4`. Usage is rate limited to 50 model requests per minute, managed by
the AI Toolkit, and the package exposes an opt-out through `mlspl.conf`
`[CTSM] ctsm_opt_out` guarded by the `aitk_ctsm_opt_out` capability.

The hosted LLM list in the `6.0.2` Connections documentation includes
Foundation-Sec and GPT-OSS options, not CDTSM. Never represent CDTSM as an LLM
connection, and keep the open model release, the model service, and the
integrated AI Toolkit experience as separately validated layers even now that
both the open model and the integration are available.

## DSDL Feature Coverage

The coverage report must include these surfaces:

- DSDL app install and setup page readiness
- DSDL API endpoint, runtime health, and container logs/readiness checks
- container environment selection: Docker, Kubernetes, OpenShift, HPC, GPU,
  air-gapped image registry, or generic handoff
- DSDL API endpoint and container health handoff
- JupyterLab notebook development and model export flow
- TensorFlow, PyTorch, NLP, graph analytics, forecasting, RAG/LLM, and custom
  algorithm examples as operator coverage, not pre-created app state
- image provenance, registry mirror, TLS, RBAC, storage, resource quota, and
  notebook/model governance checks
- HEC and Splunk Observability handoff for runtime telemetry and inference
  output where applicable
- one-to-one DSDL app to container environment warning for older DLTK/DSDL sync
  collision behavior

## Generated Artifact Contract

`scripts/render_assets.py` writes:

- `coverage-report.json` and `coverage-report.md`
- `apply-plan.json`
- `doctor-report.md`
- `dsdl-runtime-handoff.md`
- `agent-launchpad-handoff.md`
- `time-series-model-handoff.md`
- `legacy-anomaly-migration.md`

Every coverage entry has:

- `key`
- `title`
- `status`
- `product_stage`
- `source_url`
- `summary`
- `owner`

Allowed statuses:

- `planned`
- `validated`
- `delegated`
- `manual_handoff`
- `eol_migration`
- `blocked`
- `not_applicable`

Allowed upstream product stages:

- `ga`
- `available`
- `feature_preview`
- `alpha`
- `deprecated`

The renderer and validator must never emit `unknown`.

## Compatibility Defaults

- Default PSC target for render-only plans is `linux64`; override with
  `--psc-target windows64`, `mac-intel`, or `mac-arm` when the search head OS
  is known.
- Splunk Cloud search heads use Linux PSC.
- Live Enterprise installs should prefer explicit `--psc-target` unless the
  operator has separately confirmed the search head OS.
- AI Toolkit `6.0.2` and PSC `4.3.4` are the current audited pair, derived from
  the inspected packages and the `6.0.2` version-dependency matrix. `6.0.0`
  accepted PSC `4.3.2` or `4.3.3`; `5.7.4` accepted only `4.3.2`. Never pair
  `6.0.2` with a PSC release below `4.3.4`.
- PSC upgrades require removing the previous PSC version and performing a clean
  install, and any custom algorithm that links PSC libraries must be refit.
- Live install commands intentionally omit `--app-version` so
  `splunk-app-install` pulls the latest compatible Splunkbase release; the
  audited version values in this reference are validation metadata, not pins.
- DSDL `5.2.4` supports Splunk Enterprise and Splunk Cloud package delivery,
  but external runtime setup remains a handoff.

## Source Links

- Splunk AI Toolkit Splunkbase: https://splunkbase.splunk.com/app/2890
- Splunk AI Toolkit 6.0.2 install: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/install-and-upgrade-the-ai-toolkit/install-the-ai-toolkit
- Splunk AI Toolkit 6.0.2 version dependencies: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/install-and-upgrade-the-ai-toolkit/splunk-ai-toolkit-version-dependencies
- Splunk AI Toolkit 6.0.2 release notes: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/release-notes/whats-new-in-the-ai-toolkit
- Search commands for machine learning: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-commands-macros-and-visualizations/search-commands-for-machine-learning
- ML command permissions: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-commands-macros-and-visualizations/permissions-for-machine-learning-commands
- ML command safeguards: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-commands-macros-and-visualizations/search-commands-for-machine-learning-safeguards
- About the ai command: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-commands-macros-and-visualizations/about-the-ai-command
- Cisco Deep Time Series Model: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-models/cisco-deep-time-series-model
- Cisco Deep Time Series Model Enterprise self-hosting: https://help.splunk.com/en/splunk-enterprise/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-models/cisco-deep-time-series-model-on--premises-installation
- Cisco Time Series Model 1.0 model card: https://huggingface.co/cisco-ai/cisco-time-series-model-1.0
- Cisco Time Series Model source and self-hosting: https://github.com/splunk/cisco-time-series-model
- Cisco Time Series Model 1.0 with DSDL: https://lantern.splunk.com/Platform_Data_Management/Analysis_with_AI/Using_the_Cisco_Time_Series_Model_1.0_on_DSDL_5.2.3
- AI Toolkit Agent Launchpad: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-connections-containers-and-agents/ai-toolkit-agent-launchpad
- Agent Launchpad for on-premises users: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-connections-containers-and-agents/agent-launchpad-for-on-premises-users
- AI Toolkit connections and hosted LLMs: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-connections-containers-and-agents/connections-in-the-ai-toolkit
- AI Toolkit container management: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-connections-containers-and-agents/container-management-in-the-ai-toolkit
- ONNX model upload and inference: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-models/upload-and-inference-pre-trained-onnx-models-in-the-ai-toolkit
- AI Toolkit model permissions: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-models/model-permissions-in-the-ai-toolkit
- Smart Assistants overview: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-guided-workflows/smart-assistants-overview
- Experiment Assistants overview (Experiment Management Framework): https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-guided-workflows/experiment-assistants-overview
- Cisco Cloud Control Studio boundary: https://www.cisco.com/site/us/en/solutions/artificial-intelligence/agentic-ops/cloud-control-studio/index.html
- Splunk AI Toolkit product page: https://www.splunk.com/en_us/products/ai-toolkit.html
- PSC Linux 64-bit Splunkbase: https://splunkbase.splunk.com/app/2882
- PSC Windows 64-bit Splunkbase: https://splunkbase.splunk.com/app/2883
- PSC Mac Intel Splunkbase: https://splunkbase.splunk.com/app/2881
- PSC Mac Apple Silicon Splunkbase: https://splunkbase.splunk.com/app/6785
- DSDL Splunkbase: https://splunkbase.splunk.com/app/4607
- DSDL components: https://help.splunk.com/en/splunk-enterprise/apply-machine-learning/use-splunk-app-for-data-science-and-deep-learning/5.2.0/about-the-splunk-app-for-data-science-and-deep-learning/splunk-app-for-data-science-and-deep-learning-components
- Legacy Splunk App for Anomaly Detection: https://splunkbase.splunk.com/app/6843
- Smart Alerts Assistant beta: https://splunkbase.splunk.com/app/6415

# Splunk AI/ML Toolkit Setup Reference

## Product Catalog

Current first-class installable coverage:

| Product | Splunkbase | Package ID | Latest audited release | Placement |
| --- | --- | --- | --- | --- |
| Splunk AI Toolkit / MLTK | `2890` | `Splunk_ML_Toolkit` | `5.7.4`, May 20, 2026 | Search tier |
| PSC Linux 64-bit | `2882` | `Splunk_SA_Scientific_Python_linux_x86_64` | `4.3.2`, May 20, 2026 | Search tier |
| PSC Windows 64-bit | `2883` | `Splunk_SA_Scientific_Python_windows_x86_64` | `4.3.2`, May 20, 2026 | Search tier |
| PSC Mac Intel | `2881` | `Splunk_SA_Scientific_Python_darwin_x86_64` | `4.3.2`, May 20, 2026 | Search tier |
| PSC Mac Apple Silicon | `6785` | `Splunk_SA_Scientific_Python_darwin_arm64` | `4.3.2`, May 20, 2026 | Search tier |
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
- ML-SPL commands: `fit`, `apply`, `summary`, `score`, `listmodels`,
  `deletemodel`, and the AI Toolkit `ai` command
- AI Toolkit 5.7.4 compatibility with PSC 4.3.2, Python 3.13 PSC runtime,
  and the current supported Splunk platform matrix
- ML command permissions, algorithm access, search safeguards, and performance
  cost settings
- Smart Assistants and Experiment Management for prediction, clustering,
  outlier detection, forecasting, and anomaly workflows
- Cisco Deep Time Series Model forecasting, anomaly detection, predictive
  alerting, hosted Cloud, and self-hosted Enterprise readiness in AI Toolkit
  `5.7.4`, explicitly retained as `feature_preview`
- Cisco Time Series Model 1.0 open-weight model readiness, explicitly retained
  as a separate `available` Apache-2.0 release rather than an AI Toolkit
  package or hosted-LLM connection
- Hosted LLM readiness for Foundation-Sec and GPT-OSS where available inside
  the Splunk Platform boundary
- AI Toolkit Agent Builder Alpha/private-preview readiness, distinct from
  Cloud Control Studio Agent Builder
- Agent Builder knowledge-base and MCP connection prerequisites and the
  `edit_agent_connections` / `run_agents` permission boundary
- preview `aiagent` invocation, per-row limits and timeouts, and run-history
  readiness for `ai_agent_run_history_index`
- Connections tab readiness for LLM providers and container endpoints
- Container Management tab readiness for DSDL-backed workflows
- model object inventory, lookup permissions, and retraining risk after the
  MLTK `5.3.0` model compatibility break
- ONNX upload/apply readiness
- external LLM/provider handoffs for OpenAI-compatible endpoints, AWS Bedrock,
  AWS SageMaker inference, and local/private model endpoints
- alerting handoffs for searches that use trained models or anomaly outputs

## Product Lifecycle Matrix

Product lifecycle is independent from repository automation status. For
example, an upstream GA package can remain a manual handoff in this skill, and
an Alpha feature must not be called GA because the renderer covers it.

| Surface | Product stage as of 2026-07-03 | Platform boundary | Repository behavior |
| --- | --- | --- | --- |
| Splunk AI Toolkit `5.7.4` | GA package | Splunk Enterprise and Splunk Cloud per the version matrix | Install/update delegation plus validation |
| AI Toolkit Agent Builder | Alpha/private preview; public GA target Fall 2026 | Documented preview is Splunk Cloud only | Cloud manual handoff; Enterprise not applicable; no private API mutation |
| Agent Builder knowledge-base and MCP connections | Alpha/private preview | Requires preview enrollment and `edit_agent_connections` | UI/secret-store handoff only |
| `aiagent` command and agent run history | Alpha/private preview | Requires preview build and `run_agents`; history requires an index | Validation handoff only; no agent or index creation |
| Cisco Time Series Model 1.0 | Available open-weight release | Hugging Face/GitHub/PyPI or reviewed DSDL/self-hosted runtime | Runtime and provenance handoff |
| Cisco Deep Time Series Model integration | Feature preview | Hosted Splunk Cloud where enabled; self-hosted model service for Enterprise | Readiness and model-service handoff only |
| Splunk-hosted Foundation-Sec and GPT-OSS LLMs | GA hosted-model capability, tenant/model dependent | Eligible Splunk Cloud | Connections and data-governance review |

### AI Toolkit Agent Builder boundary

AI Toolkit Agent Builder is the no-code Splunk feature that defines agents
around Splunk searches and alerts, approved knowledge sources, MCP tools, and
an LLM. It is not the Agent Builder described for Cisco Cloud Control Studio.
Cloud Control Studio implementation, marketplace, Cisco product connectors,
and Cloud Control agent deployment route to `cisco-cloud-control-setup`.

The latest public lifecycle statement says AI Toolkit Agent Builder is in the
Alpha program and targets general availability on Splunk Cloud Platform in
Fall 2026. The detailed preview documentation remains the source for these
surfaces:

- the documented preview requires Splunk Cloud Platform private enrollment;
  a public Splunkbase AI Toolkit install is insufficient
- `edit_agent_connections` controls creation of knowledge-base and MCP
  connections; `run_agents` controls agent creation and invocation; preview
  documentation assigns both to `mltk_admin`
- at least one knowledge-base connection and one MCP server connection are
  required before creating an agent
- agents are private by default and can select approved MCP servers,
  knowledge bases, an LLM, a system prompt, timeout, and at most 25 invocations
  per row in the documented preview
- the preview invocation command is `aiagent`, with `agent_name` and an
  optional `prompt`; do not infer its presence on public AI Toolkit `5.7.4`
- the run-history page requires `ai_agent_run_history_index`; the preview docs
  give 100 MB maximum raw size and 30 days searchable retention as starting
  settings, which still require customer capacity, retention, ACL, and data
  sensitivity review

The preview page predates the public `5.7.4` / PSC `4.3.2` compatibility pair.
Confirm the private build and matching PSC dependency with Splunk onboarding;
do not downgrade the public pair based on the older preview prerequisites.

### Cisco time-series model boundary

The names refer to related but independently governed surfaces:

- **Cisco Time Series Model 1.0 (CTSM)** is the available, 250-million-
  parameter, univariate zero-shot forecasting model published under Apache
  2.0 as `cisco-ai/cisco-time-series-model-1.0`. The open model has model
  weights, GitHub/PyPI code, notebooks, and a self-hosting path. Splunk Lantern
  documents a DSDL `5.2.3` integration example; validate the command and image
  against the installed DSDL version.
- **Cisco Deep Time Series Model (CDTSM)** is the AI Toolkit-integrated
  forecasting, anomaly-detection, and predictive-alerting experience. The
  `5.7.4` product documentation labels it a feature preview. Cloud uses the
  hosted integration where enabled. Enterprise requires a separately hosted
  model service, an endpoint in `mlspl.conf`, and a matching bearer token in
  Splunk encrypted storage.

The hosted LLM list in the `5.7.4` Connections documentation includes
Foundation-Sec and GPT-OSS options, not CDTSM. Never represent CDTSM as an LLM
connection, or treat open model availability as proof that the integrated
experience is generally available.

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
- `agent-builder-handoff.md`
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
- AI Toolkit `5.7.4` and PSC `4.3.2` are the current audited pair.
- Live install commands intentionally omit `--app-version` so
  `splunk-app-install` pulls the latest compatible Splunkbase release; the
  audited version values in this reference are validation metadata, not pins.
- DSDL `5.2.4` supports Splunk Enterprise and Splunk Cloud package delivery,
  but external runtime setup remains a handoff.

## Source Links

- Splunk AI Toolkit Splunkbase: https://splunkbase.splunk.com/app/2890
- Splunk AI Toolkit 5.7.4 install and version dependencies: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.4/install-and-upgrade-the-ai-toolkit/install-the-ai-toolkit
- Splunk AI Toolkit 5.7.4 release notes: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.4/release-notes/whats-new-in-the-ai-toolkit
- Cisco Deep Time Series Model preview: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.4/ai-toolkit-models/feature-preview-cisco-deep-time-series-model
- Cisco Deep Time Series Model Enterprise self-hosting: https://help.splunk.com/en/splunk-enterprise/apply-machine-learning/use-ai-toolkit/5.7.4/ai-toolkit-models/cisco-deep-time-series-model-on--premises-installation
- Cisco Time Series Model 1.0 model card: https://huggingface.co/cisco-ai/cisco-time-series-model-1.0
- Cisco Time Series Model source and self-hosting: https://github.com/splunk/cisco-time-series-model
- Cisco Time Series Model 1.0 with DSDL: https://lantern.splunk.com/Platform_Data_Management/Analysis_with_AI/Using_the_Cisco_Time_Series_Model_1.0_on_DSDL_5.2.3
- AI Toolkit Agent Builder current lifecycle statement: https://www.splunk.com/en_us/blog/platform/new-splunk-platform-innovations-cisco-live-2026.html
- AI Toolkit Agent Builder detailed preview workflow: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.6.4/ai-toolkit-commands-macros-and-visualizations/feature-preview-ai-toolkit-agent-builder
- AI Toolkit connections and hosted LLMs: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.4/ai-toolkit-commands-macros-and-visualizations/connections-in-the-ai-toolkit
- Cisco Cloud Control Studio boundary: https://www.cisco.com/site/us/en/solutions/artificial-intelligence/agentic-ops/cloud-control-studio/index.html
- Splunk AI Toolkit product page: https://www.splunk.com/en_us/products/ai-toolkit.html
- PSC Linux 64-bit Splunkbase: https://splunkbase.splunk.com/app/2882
- PSC Windows 64-bit Splunkbase: https://splunkbase.splunk.com/app/2883
- PSC Mac Intel Splunkbase: https://splunkbase.splunk.com/app/2881
- PSC Mac Apple Silicon Splunkbase: https://splunkbase.splunk.com/app/6785
- DSDL Splunkbase: https://splunkbase.splunk.com/app/4607
- DSDL components: https://help.splunk.com/en/splunk-enterprise/apply-machine-learning/use-splunk-app-for-data-science-and-deep-learning/5.2/about-the-splunk-app-for-data-science-and-deep-learning/splunk-app-for-data-science-and-deep-learning-components
- Legacy Splunk App for Anomaly Detection: https://splunkbase.splunk.com/app/6843
- Smart Alerts Assistant beta: https://splunkbase.splunk.com/app/6415

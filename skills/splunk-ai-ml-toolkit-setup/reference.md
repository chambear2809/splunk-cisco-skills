# Splunk AI/ML Toolkit Setup Reference

## Product Catalog

Current first-class installable coverage:

| Product | Splunkbase | Package ID | Latest audited release | Placement |
| --- | --- | --- | --- | --- |
| Splunk AI Toolkit / MLTK | `2890` | `Splunk_ML_Toolkit` | `5.7.3`, April 19, 2026 | Search tier |
| PSC Linux 64-bit | `2882` | `Splunk_SA_Scientific_Python_linux_x86_64` | `4.3.1`, February 27, 2026 | Search tier |
| PSC Windows 64-bit | `2883` | `Splunk_SA_Scientific_Python_windows_x86_64` | `4.3.1`, February 27, 2026 | Search tier |
| PSC Mac Intel | `2881` | `Splunk_SA_Scientific_Python_darwin_x86_64` | `4.3.1`, February 27, 2026 | Search tier |
| PSC Mac Apple Silicon | `6785` | `Splunk_SA_Scientific_Python_darwin_arm64` | `4.3.1`, February 27, 2026 | Search tier |
| DSDL | `4607` | `mltk-container` | `5.2.3`, February 5, 2026 | Search tier plus external runtime |

Legacy/migration-only coverage:

| Product | Splunkbase | Package ID | Status |
| --- | --- | --- | --- |
| PSC Linux 32-bit | `2884` | `Splunk_SA_Scientific_Python_linux_x86` | Legacy only; not a modern install target |
| Splunk App for Anomaly Detection | `6843` | unknown public manifest | EOL/migration-only |
| Smart Alerts Assistant for Splunk (beta) | `6415` | `Smart_Alerts_Assistant` | Legacy beta/migration-only |

## AI Toolkit Feature Coverage

The coverage report must include these surfaces:

- package install and version compatibility
- PSC dependency selection and install order
- ML-SPL commands: `fit`, `apply`, `summary`, `score`, `listmodels`,
  `deletemodel`, and the AI Toolkit `ai` command
- AI Toolkit 5.7.3 compatibility with PSC 4.3.1, Python 3.13 PSC runtime,
  and the current supported Splunk platform matrix
- ML command permissions, algorithm access, search safeguards, and performance
  cost settings
- Smart Assistants and Experiment Management for prediction, clustering,
  outlier detection, forecasting, and anomaly workflows
- Cisco Deep Time Series anomaly detection readiness in AI Toolkit `5.7.3`
- Connections tab readiness for LLM providers and container endpoints
- Container Management tab readiness for DSDL-backed workflows
- model object inventory, lookup permissions, and retraining risk after the
  MLTK `5.3.0` model compatibility break
- ONNX upload/apply readiness
- external LLM/provider handoffs for OpenAI-compatible endpoints, AWS Bedrock,
  AWS SageMaker inference, and local/private model endpoints
- alerting handoffs for searches that use trained models or anomaly outputs

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
- `legacy-anomaly-migration.md`

Every coverage entry has:

- `key`
- `title`
- `status`
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

The renderer and validator must never emit `unknown`.

## Compatibility Defaults

- Default PSC target for render-only plans is `linux64`; override with
  `--psc-target windows64`, `mac-intel`, or `mac-arm` when the search head OS
  is known.
- Splunk Cloud search heads use Linux PSC.
- Live Enterprise installs should prefer explicit `--psc-target` unless the
  operator has separately confirmed the search head OS.
- AI Toolkit `5.7.3` and PSC `4.3.1` are the current audited pair.
- Live install commands intentionally omit `--app-version` so
  `splunk-app-install` pulls the latest compatible Splunkbase release; the
  audited version values in this reference are validation metadata, not pins.
- DSDL `5.2.3` supports Splunk Enterprise and Splunk Cloud package delivery,
  but external runtime setup remains a handoff.

## Source Links

- Splunk AI Toolkit Splunkbase: https://splunkbase.splunk.com/app/2890
- Splunk AI Toolkit 5.7.3 install and version dependencies: https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.3/install-and-upgrade-the-ai-toolkit/install-the-ai-toolkit
- PSC Linux 64-bit Splunkbase: https://splunkbase.splunk.com/app/2882
- PSC Windows 64-bit Splunkbase: https://splunkbase.splunk.com/app/2883
- PSC Mac Intel Splunkbase: https://splunkbase.splunk.com/app/2881
- PSC Mac Apple Silicon Splunkbase: https://splunkbase.splunk.com/app/6785
- DSDL Splunkbase: https://splunkbase.splunk.com/app/4607
- DSDL components: https://help.splunk.com/en/splunk-enterprise/apply-machine-learning/use-splunk-app-for-data-science-and-deep-learning/5.2/about-the-splunk-app-for-data-science-and-deep-learning/splunk-app-for-data-science-and-deep-learning-components
- Legacy Splunk App for Anomaly Detection: https://splunkbase.splunk.com/app/6843
- Smart Alerts Assistant beta: https://splunkbase.splunk.com/app/6415

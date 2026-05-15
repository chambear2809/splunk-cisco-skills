---
name: splunk-ai-ml-toolkit-setup
description: >-
  Install, render, validate, and audit Splunk-owned AI and machine-learning
  workflows beyond Splunk AI Assistant: Splunk AI Toolkit / MLTK
  (`Splunk_ML_Toolkit`), Python for Scientific Computing (PSC), Splunk App for
  Data Science and Deep Learning (DSDL), MLTK anomaly workflows, LLM/`ai`
  command readiness, external model runtimes, and legacy anomaly app migration.
  Use when the user asks about MLTK, Splunk AI Toolkit, Machine Learning
  Toolkit, PSC, Python for Scientific Computing, DSDL, Deep Learning Toolkit,
  Splunk anomaly detection assistants, Smart Alerts Assistant, or AI/ML product
  coverage outside Splunk AI Assistant.
---

# Splunk AI/ML Toolkit Setup

Use this skill for Splunk-owned AI and machine-learning platform workflows
that are not Splunk AI Assistant. It owns coverage reporting, install
orchestration, compatibility validation, DSDL runtime handoffs, and migration
guidance for legacy anomaly apps.

## Coverage Boundary

This skill covers Splunk-owned and Splunk-supported AI/ML products:

- Splunk AI Toolkit / MLTK (`Splunk_ML_Toolkit`, Splunkbase `2890`)
- Python for Scientific Computing (PSC) add-ons:
  - Linux 64-bit (`2882`, `Splunk_SA_Scientific_Python_linux_x86_64`)
  - Windows 64-bit (`2883`, `Splunk_SA_Scientific_Python_windows_x86_64`)
  - Mac Intel (`2881`, `Splunk_SA_Scientific_Python_darwin_x86_64`)
  - Mac Apple Silicon (`6785`, `Splunk_SA_Scientific_Python_darwin_arm64`)
  - Linux 32-bit (`2884`) as legacy migration/blocking coverage only
- Splunk App for Data Science and Deep Learning / DSDL (`4607`,
  package id `mltk-container`)
- AI Toolkit Smart Assistants, ML-SPL commands, model management, ONNX apply,
  LLM `ai` command readiness, Connections tab, Container Management tab,
  external LLM/provider connection handoffs, ML alerting, and Cisco Deep Time
  Series anomaly detection readiness
- Legacy Splunk App for Anomaly Detection (`6843`) and Smart Alerts Assistant
  beta (`6415`) as audit and migration-only coverage

Third-party AI-tagged Splunkbase apps are out of scope unless another skill
explicitly routes them.

## Safety Rules

- Never ask for Splunk passwords, Splunkbase passwords, HEC tokens, LLM API
  keys, cloud provider secrets, DSDL container credentials, or model registry
  tokens in chat.
- Never pass secrets on the command line or as environment-variable prefixes.
- LLM provider credentials, HEC tokens, Splunk access tokens, Docker registry
  secrets, Kubernetes kubeconfigs, and TLS key material must be file-backed or
  delegated to the owning setup skill.
- Do not install legacy EOL/beta anomaly apps by default. Audit and migrate
  them to current AI Toolkit workflows.
- Do not claim DSDL runtime automation for Docker, Kubernetes, OpenShift, HPC,
  GPU, air-gapped images, Jupyter notebooks, or model governance unless the
  workflow is rendered as a handoff or an owning runtime skill applies it.

## Primary Workflow

Render and validate a complete coverage plan:

```bash
bash skills/splunk-ai-ml-toolkit-setup/scripts/setup.sh \
  --render --validate \
  --spec skills/splunk-ai-ml-toolkit-setup/template.example \
  --output-dir splunk-ai-ml-toolkit-rendered
```

Install or update AI Toolkit with the right PSC add-on:

```bash
bash skills/splunk-ai-ml-toolkit-setup/scripts/setup.sh \
  --install \
  --psc-target linux64
```

Include DSDL package delivery and runtime handoff artifacts:

```bash
bash skills/splunk-ai-ml-toolkit-setup/scripts/setup.sh \
  --render --validate \
  --include-dsdl \
  --dsdl-runtime kubernetes \
  --output-dir splunk-ai-ml-toolkit-rendered
```

Audit legacy anomaly apps without installing them:

```bash
bash skills/splunk-ai-ml-toolkit-setup/scripts/setup.sh \
  --doctor \
  --legacy-anomaly-audit
```

## Apply Model

- Package delivery delegates to `splunk-app-install`.
- Package delivery intentionally omits `--app-version` so Splunkbase/ACS pulls
  the latest compatible release; audited version metadata is used for reports
  and regression checks, not as a live install pin.
- AI Toolkit and PSC belong on the search tier/search head cluster only.
- Install order is PSC first, AI Toolkit second, optional DSDL third.
- DSDL external runtimes are rendered handoffs by default:
  `docker`, `kubernetes`, `openshift`, `hpc`, `gpu`, `airgap`, or `handoff`.
- Legacy Anomaly Detection and Smart Alerts beta are never part of the default
  install plan; the skill emits migration reports instead.

## Validation Rules

Validation must fail for:

- Unknown coverage statuses in `coverage-report.json`
- AI Toolkit install plans without a selected compatible PSC target
- PSC Linux 32-bit as a new install target unless explicitly audited as legacy
- DSDL requested without AI Toolkit and PSC coverage in the same plan
- Direct-secret flags such as `--token`, `--api-token`, `--password`,
  `--client-secret`, or `--llm-api-key`

Validation must warn for:

- DSDL Docker runtime in production because TLS, image provenance, and network
  isolation must be handled by the operator
- AI Toolkit/PSC versions lower than the latest audited compatibility pair
- Legacy Anomaly Detection or Smart Alerts Assistant beta installs
- MLTK model objects created before the MLTK 5.3 compatibility break, which
  may need retraining

## References

- Read `reference.md` before changing product coverage, compatibility rules,
  generated artifacts, or live install behavior.
- Use `scripts/render_assets.py --discover` to print the built-in product
  catalog and coverage surface.

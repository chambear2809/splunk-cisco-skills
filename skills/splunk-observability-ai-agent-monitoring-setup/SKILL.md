---
name: splunk-observability-ai-agent-monitoring-setup
description: Render, validate, diagnose, and safely apply Splunk Observability Cloud AI Agent Monitoring setup plans, including GenAI Python instrumentation, instrumentation-side evaluations, Log Observer Connect handoffs, histogram collector readiness, and AI Infrastructure Monitoring coverage. Use when setting up or auditing Splunk AI Agent Monitoring, GenAI telemetry packages, AI agent evaluation telemetry, or adjacent AI infrastructure observability.
---

# Splunk Observability AI Agent Monitoring Setup

## Overview

Use this skill to build a render-first setup plan for Splunk AI Agent Monitoring and adjacent AI Infrastructure Monitoring. The skill owns orchestration, validation, coverage reporting, and safe delegation; it does not mark UI-only workflows as API-applied.

The renderer always emits a coverage report. Treat `coverage-report.json` as the source of truth for what is `delegated_apply`, `render`, `deeplink`, `handoff`, or `not_applicable`.

## Safety Rules

- Never ask for Splunk Observability tokens, Splunk Platform passwords, HEC tokens, LLM API keys, or client secrets in conversation.
- Never pass secrets directly on the command line or as environment-variable prefixes.
- Use file-based secrets only, such as `SPLUNK_O11Y_TOKEN_FILE`, `--o11y-token-file`, `--platform-hec-token-file`, or the delegated skill's file flags.
- Default prompt and response content capture to off.
- Require explicit accept flags before rendering content capture or LLM-as-judge evaluation env vars.
- Do not promise PII redaction, hashing, or truncation. The upstream GenAI utility marks those helpers as not implemented.

## Primary Workflow

1. Start from `template.example`, or create a small JSON/YAML spec with the target realm, collector mode, agent frameworks, and AI infrastructure products.
   For Kubernetes runtime handoffs, set `deployment.workload_kind`, `deployment.workload_namespace`, `deployment.workload_name`, and `deployment.container_name` to the exact application workload and container that should receive the environment variables.
2. Render and validate:

   ```bash
   bash skills/splunk-observability-ai-agent-monitoring-setup/scripts/setup.sh \
     --render \
     --validate \
     --spec skills/splunk-observability-ai-agent-monitoring-setup/template.example \
     --output-dir splunk-observability-ai-agent-monitoring-rendered
   ```

3. Review the generated files:
   - `coverage-report.json` and `coverage-report.md`
   - `apply-plan.json`
   - `runtime/python.env` and `runtime/requirements.txt`
   - `collector/values-ai-agent-monitoring.yaml`
   - `handoff.md` and `doctor-report.md`

4. Apply only when explicitly requested:

   ```bash
   bash skills/splunk-observability-ai-agent-monitoring-setup/scripts/setup.sh \
     --apply collector,hec,loc \
     --spec my-ai-agent-monitoring.json \
     --o11y-token-file /tmp/splunk_o11y_token
   ```

## Apply Model

Supported `--apply` sections are:

- `collector` delegates to `splunk-observability-otel-collector-setup` using `--apply-k8s` or `--apply-linux`.
- `hec` delegates to `splunk-hec-service-setup --phase apply`.
- `loc` delegates to `splunk-observability-cloud-integration-setup --apply log_observer_connect`; the Observability UI connection wizard remains `deeplink`.
- `python-runtime` and `kubernetes-runtime` render deterministic application changes and print operator handoffs because the skill does not own the user's application repository or cluster workloads.
- `ai-infra-collector` delegates to existing product skills when available, such as Cisco AI PODs and NVIDIA GPU, otherwise renders collector overlay handoffs.
- `dashboards` delegates to `splunk-observability-dashboard-builder`.
- `detectors` delegates to `splunk-observability-native-ops`.

## Validation Rules

Validation must fail for:

- `send_otlp_histograms: false`, because the Agents page requires histogram metrics.
- Prompt/response content capture without `--accept-content-capture` or `accept_content_capture: true`.
- Instrumentation-side evaluations without `--accept-evaluation-cost` or `accept_evaluation_cost: true`.
- OpenAI evaluations without `OTEL_INSTRUMENTATION_GENAI_EVALS_SEPARATE_PROCESS=true`.
- Unsupported package names such as `splunk-otel-instrumentation-openai-v2` or `splunk-otel-instrumentation-vertexai`.
- Selected packages whose Python requirement exceeds the declared runtime version.

## References

- Read `reference.md` for the CLI and generated artifact contract.
- Read `references/coverage.md` when changing coverage status or adding product support.
- Read `references/package-catalog.md` before changing package names, Python floors, or framework mappings.
- Read `references/apply-and-safety.md` before changing live apply behavior.
- Read `references/troubleshooting.md` when updating doctor output.

---
name: splunk-appdynamics-machine-agent-otel-collector-setup
description: "Use when the user asks for Machine Agent bundled OTel Collector, combined agent for infrastructure
  visibility, AppDynamics collector YAML, local OTLP 4317/4318 listeners, or Splunk Observability plus
  AppDynamics OTel export from Linux, Docker, or Windows Machine Agent installs. Render, validate,
  preflight, apply, and rollback the bundled OpenTelemetry Collector that runs with AppDynamics Machine
  Agent combined mode."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Splunk AppDynamics Machine Agent OTel Collector Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- The user asks for Machine Agent bundled OTel Collector, combined agent for infrastructure visibility, AppDynamics
  collector YAML, local OTLP 4317/4318 listeners, or Splunk Observability plus AppDynamics OTel export from Linux,
  Docker, or.
- Preview and review the splunk appdynamics machine agent otel collector setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-appdynamics-machine-agent-otel-collector-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-appdynamics-machine-agent-otel-collector-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

Owns the AppDynamics Machine Agent bundled OTel Collector configuration. The
default is loopback-only OTLP reception, traces to Splunk Observability Cloud
and AppDynamics OTel, metrics to Splunk Observability Cloud, and logs disabled
unless a log destination is explicitly declared.

```bash
bash skills/splunk-appdynamics-machine-agent-otel-collector-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-machine-agent-otel-collector-setup/scripts/setup.sh --apply preflight --spec collector.yaml
bash skills/splunk-appdynamics-machine-agent-otel-collector-setup/scripts/setup.sh --apply collector --spec collector.yaml --accept-host-mutation
bash skills/splunk-appdynamics-machine-agent-otel-collector-setup/scripts/validate.sh --output-dir splunk-appdynamics-machine-agent-otel-collector-setup-rendered
```

## What This Skill Covers

- Machine Agent combined mode for Linux RPM, Linux ZIP, Docker, and Windows ZIP
  layouts.
- Bundled collector config rendering with OTLP gRPC on `127.0.0.1:4317` and
  OTLP HTTP on `127.0.0.1:4318` by default.
- Splunk Observability token-file and AppDynamics API key-file placeholders.
- A chmod-600 runtime environment file generated on the target from those
  secret files, plus a systemd drop-in for Linux service installs.
- Collector service/container restart, OTLP port checks, exporter health probes,
  backup manifests, and rollback.

## Guardrails

- `--accept-host-mutation` is required before writing files or restarting the
  collector.
- `--accept-remote-execution` is required for SSH targets.
- Direct token, access-token, and API key flags are refused; use file-backed
  fields in the spec.
- Referenced secret files must be non-empty and mode 600. Docker and Windows
  targets require an explicit `collector_credentials_ready_command`; a plain
  container/service restart cannot attach new credentials.
- Mutation is refused when the expected bundled collector path or service or
  container name cannot be confirmed from the spec and preflight.

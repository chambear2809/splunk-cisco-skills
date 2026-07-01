---
name: splunk-appdynamics-machine-agent-otel-collector-setup
description: >-
  Render, validate, preflight, apply, and rollback the bundled OpenTelemetry
  Collector that runs with AppDynamics Machine Agent combined mode. Use when the
  user asks for Machine Agent bundled OTel Collector, combined agent for
  infrastructure visibility, AppDynamics collector YAML, local OTLP 4317/4318
  listeners, or Splunk Observability plus AppDynamics OTel export from Linux,
  Docker, or Windows Machine Agent installs.
---

# Splunk AppDynamics Machine Agent OTel Collector Setup

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

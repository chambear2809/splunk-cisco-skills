---
name: splunk-appdynamics-dual-agent-setup
description: >-
  Render, validate, preflight, apply, and rollback production Java Dual Signal
  AppDynamics agent configuration. Use when the user asks for AppDynamics Java
  dual-agent, Java Dual Signal mode, AGENT_DEPLOYMENT_MODE=dual,
  -Dagent.deployment.mode=dual, Java OTLP export to a local collector, or
  coordinated collector-first then Java restart rollout on local or SSH hosts.
---

# Splunk AppDynamics Dual Agent Setup

Owns production Java Dual Signal host configuration. The supported apply order
is collector first, Java second: configure and validate the local collector, then
write persistent Java startup settings and restart only approved app services.

```bash
bash skills/splunk-appdynamics-dual-agent-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-dual-agent-setup/scripts/setup.sh --apply preflight --spec dual-agent.yaml
bash skills/splunk-appdynamics-dual-agent-setup/scripts/setup.sh --apply all --spec dual-agent.yaml --accept-host-mutation --accept-app-restart
bash skills/splunk-appdynamics-dual-agent-setup/scripts/validate.sh --output-dir splunk-appdynamics-dual-agent-setup-rendered
```

## What This Skill Covers

- Java Dual Signal startup configuration using `AGENT_DEPLOYMENT_MODE=dual`
  or equivalent system properties.
- OTLP trace export to a local collector, defaulting to
  `http://127.0.0.1:4318` and `http/protobuf`.
- Resource attributes for application, tier, node, and deployment environment.
- Linux systemd drop-ins, process env files or wrappers, Docker env files, and
  Windows service environment guidance.
- Gated apply and rollback for local or SSH targets with backup manifests,
  checksum verification, redacted reports, and generated rollback plans.

## Guardrails

- `--accept-host-mutation` is required before writing files or restarting
  services.
- `--accept-remote-execution` is required for SSH targets.
- `--accept-app-restart` is required for Java service or container restarts.
- `--accept-full-restart` is required when `restart_strategy: full`.
- Direct token, access-token, and API key flags are refused; use file-backed
  fields in the spec.

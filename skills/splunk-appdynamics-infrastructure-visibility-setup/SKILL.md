---
name: splunk-appdynamics-infrastructure-visibility-setup
description: >-
  Render and validate Splunk AppDynamics Infrastructure
  Visibility workflows, including Machine Agent, Server Visibility, Network
  Visibility, Docker and container visibility, service availability, server
  tags, GPU Monitoring, Prometheus extension coverage, and infrastructure health rules. Use when the user asks for
  AppDynamics Machine Agent, Server Visibility, Network Visibility, Docker or
  container visibility, service availability, server tags, host metrics, or
  infrastructure health rules, NVIDIA GPU monitoring, DCGM, NVIDIA-SMI, or
  Prometheus exporter monitoring through Machine Agent.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk AppDynamics Infrastructure Visibility Setup

Owns Machine Agent and infrastructure visibility plans. Privileged host or
network-agent changes are rendered for review.
The generated command plan is non-mutating and `--apply` fails closed; operators
must execute the reviewed host/API runbook or delegate collector configuration
to `splunk-appdynamics-machine-agent-otel-collector-setup`.

```bash
bash skills/splunk-appdynamics-infrastructure-visibility-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-infrastructure-visibility-setup/scripts/validate.sh
```

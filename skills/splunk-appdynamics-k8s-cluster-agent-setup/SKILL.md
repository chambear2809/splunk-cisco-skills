---
name: splunk-appdynamics-k8s-cluster-agent-setup
description: >-
  Render, validate, and gate Splunk AppDynamics Kubernetes Cluster Agent,
  Kubernetes auto-instrumentation, and Splunk OpenTelemetry Collector setup
  through the Cluster Agent, including Java, .NET Core Linux, and Node.js
  workload instrumentation. Use when the user asks for AppDynamics Cluster
  Agent, Kubernetes monitoring, AppDynamics Kubernetes auto-instrumentation,
  Splunk OTel Collector through Cluster Agent, or Java, .NET Core Linux, and
  Node.js workload rollout validation.
---

# Splunk AppDynamics Kubernetes Cluster Agent Setup

Kubernetes mutations require `--accept-k8s-rollout`. Render mode writes Helm
values and validation runbooks without touching the active cluster.

```bash
bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-k8s-cluster-agent-setup/scripts/validate.sh
```

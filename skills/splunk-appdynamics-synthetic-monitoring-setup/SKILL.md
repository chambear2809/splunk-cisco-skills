---
name: splunk-appdynamics-synthetic-monitoring-setup
description: >-
  Render, validate, and optionally apply Splunk AppDynamics Synthetic Monitoring
  workflows, including Browser Synthetic jobs, Synthetic API Monitoring, hosted
  locations, Private Synthetic Agents, Docker, Kubernetes, Minikube PSA assets,
  Shepherd URLs, screenshots, waterfalls, and run validation. Use when the user
  asks for AppDynamics Synthetic Monitoring, browser synthetic jobs, Synthetic
  API Monitoring, hosted synthetic locations, Private Synthetic Agent, PSA,
  Shepherd URL validation, synthetic waterfalls, or synthetic run checks.
---

# Splunk AppDynamics Synthetic Monitoring Setup

Renders Synthetic API monitor payloads and Private Synthetic Agent values. The
operator reviews and applies private agent rollout assets.

```bash
bash skills/splunk-appdynamics-synthetic-monitoring-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-synthetic-monitoring-setup/scripts/validate.sh
```

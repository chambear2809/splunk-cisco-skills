---
name: splunk-appdynamics-synthetic-monitoring-setup
description: >-
  Render and validate Splunk AppDynamics Synthetic Monitoring
  workflows, including Browser Synthetic jobs, Synthetic API Monitoring, hosted
  locations, Private Synthetic Agents, Docker, Kubernetes, Minikube PSA assets,
  Shepherd URLs, screenshots, waterfalls, and run validation. Use when the user
  asks for AppDynamics Synthetic Monitoring, browser synthetic jobs, Synthetic
  API Monitoring, hosted synthetic locations, Private Synthetic Agent, PSA,
  Shepherd URL validation, synthetic waterfalls, or synthetic run checks.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk AppDynamics Synthetic Monitoring Setup

Renders Synthetic API monitor payloads and Private Synthetic Agent values. The
operator reviews and applies private agent rollout assets.
The wrapper does not submit jobs or run the container/Kubernetes rollout;
`--apply` fails closed and the rendered packet is an operator handoff.

```bash
bash skills/splunk-appdynamics-synthetic-monitoring-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-synthetic-monitoring-setup/scripts/validate.sh
```

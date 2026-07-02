---
name: splunk-appdynamics-apm-setup
description: >-
  Render and validate Splunk AppDynamics APM
  workflows for business applications, tiers, nodes, business transactions,
  service endpoints, remote services, information points, snapshots, metrics,
  serverless APM, Development Level Monitoring, Splunk AppDynamics for
  OpenTelemetry, OTel collector/access-key validation, and app-server agent snippets.
  Use when the user asks for AppDynamics APM, business applications, tiers,
  nodes, business transactions, snapshots, service endpoints, remote services,
  information points, metrics, AWS Lambda/serverless APM, development
  monitoring, OpenTelemetry ingestion, OTel collector setup, or application
  server agent instrumentation snippets.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk AppDynamics APM Setup

Owns the AppDynamics APM model and application server instrumentation runbooks.
Runtime installs delegate to Agent Management or Kubernetes Cluster Agent skills.
The current wrapper does not submit Controller model changes; `--apply` fails
closed and the rendered API/UI runbook is an explicit operator handoff.

```bash
bash skills/splunk-appdynamics-apm-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-apm-setup/scripts/validate.sh
```

---
name: splunk-appdynamics-security-ai-setup
description: >-
  Render, validate, and delegate Splunk AppDynamics security and AI workflows,
  including Application Security Monitoring, Secure Application, Secure
  Application runtime policies, Secure Application `policyConfigs`, Secure Application APIs, Secure Application for OpenTelemetry Java,
  Observability for AI, OpenAI, LangChain, Bedrock, GPU readiness, and Cisco AI
  Pod handoffs. Use when the user asks for AppDynamics Secure Application,
  application security monitoring, Secure Application policies, Secure
  Application APIs, Secure Application `policyConfigs`, Secure Application for OTel Java,
  Observability for AI, OpenAI or LangChain monitoring, Bedrock checks, GPU
  telemetry, or Cisco AI Pod AppDynamics handoffs.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk AppDynamics Security AI Setup

Security and AI enablement is validate/runbook-first. GPU and Cisco AI Pod work
delegates to the existing Observability and Cisco AI Pod skills.

```bash
bash skills/splunk-appdynamics-security-ai-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-security-ai-setup/scripts/validate.sh
```

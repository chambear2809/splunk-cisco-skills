---
name: splunk-appdynamics-sap-agent-setup
description: >-
  Render, validate, and hand off Splunk AppDynamics SAP Agent workflows,
  including SAP Agent, ABAP Agent, HTTP SDK, SNP CrystalBridge Monitoring, BiQ
  Collector, local and gateway HTTP SDK deployment, SAP NetWeaver transports, SAP authorization checks, Controller
  node registration, SAP Agent release notes, and SAP metric validation. Use when the user asks for
  AppDynamics SAP Agent, ABAP Agent, HTTP SDK, SNP CrystalBridge Monitoring,
  BiQ Collector, SAP NetWeaver transports, SAP authorization runbooks, local or gateway HTTP SDK deployment, or SAP
  release or metric validation.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk AppDynamics SAP Agent Setup

SAP transports and authorization changes are runbook-only. Agent command
snippets are rendered for SAP Basis/application teams to execute.

```bash
bash skills/splunk-appdynamics-sap-agent-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-sap-agent-setup/scripts/validate.sh
```

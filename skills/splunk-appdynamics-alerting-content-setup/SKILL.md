---
name: splunk-appdynamics-alerting-content-setup
description: >-
  Render, validate, and optionally apply Splunk AppDynamics alerting content,
  including health rules, schedules, policies, actions, email digests, action
  suppression, anomaly detection, automated root cause analysis, import, export,
  rollback, AIML dynamic baselines, automated transaction diagnostics, and post-apply readback validation.
  Use when the user asks for AppDynamics health rules, alert policies, actions,
  schedules, email digests, action suppression, anomaly detection, automated
  RCA, dynamic baseline behavior, automated transaction diagnostics, alerting
  content import/export, rollback, or alert validation.
---

# Splunk AppDynamics Alerting Content Setup

Renders alert content plans and rollback snapshots. API-backed objects can be
applied where documented; unsupported UI-only content stays as runbooks.

```bash
bash skills/splunk-appdynamics-alerting-content-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-alerting-content-setup/scripts/validate.sh
```

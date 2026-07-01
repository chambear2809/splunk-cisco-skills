---
name: splunk-appdynamics-alerting-content-setup
description: >-
  Render and validate Splunk AppDynamics alerting content,
  including health rules, schedules, policies, actions, email digests, action
  suppression, anomaly detection, automated root cause analysis, import, export,
  rollback, AIML dynamic baselines, automated transaction diagnostics, and post-apply readback validation.
  Use when the user asks for AppDynamics health rules, alert policies, actions,
  schedules, email digests, action suppression, anomaly detection, automated
  RCA, dynamic baseline behavior, automated transaction diagnostics, alerting
  content import/export, rollback, or alert validation.
---

# Splunk AppDynamics Alerting Content Setup

Renders alert content plans and rollback instructions. It does not create a
snapshot or submit Controller changes; `--apply` and generic `--rollback` fail
closed. Export, mutation, readback, and restore remain explicit operator steps.

```bash
bash skills/splunk-appdynamics-alerting-content-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-alerting-content-setup/scripts/validate.sh
```

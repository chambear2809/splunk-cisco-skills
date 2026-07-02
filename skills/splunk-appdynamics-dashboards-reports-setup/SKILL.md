---
name: splunk-appdynamics-dashboards-reports-setup
description: >-
  Render and validate Splunk AppDynamics dashboard and report
  workflows, including custom dashboards, Dash Studio handoffs, reports,
  scheduled reports, War Rooms, ThousandEyes dashboard handoff, dashboard inventory, report delivery checks, and
  validation runbooks. Use when the user asks for AppDynamics dashboards,
  custom dashboard migration, Dash Studio handoffs, reports, scheduled reports,
  report delivery, War Rooms, or dashboard and report validation.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk AppDynamics Dashboards Reports Setup

Owns dashboard, report, and War Room planning. Dashboard payloads and UI-only
report/War Room operations stay operator runbooks; `--apply` fails closed.

```bash
bash skills/splunk-appdynamics-dashboards-reports-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-dashboards-reports-setup/scripts/validate.sh
```

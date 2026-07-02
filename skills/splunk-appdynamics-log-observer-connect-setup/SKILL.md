---
name: splunk-appdynamics-log-observer-connect-setup
description: >-
  Render, validate, and delegate Splunk Log Observer Connect for Splunk
  AppDynamics workflows, including new LOC setup, old Splunk integration
  detection and disablement, Splunk Cloud or Enterprise service-account
  handoffs, allow-list checks, and deep-link validation. Use when the user asks
  for AppDynamics Log Observer Connect, AppDynamics logs in Splunk Platform,
  legacy Splunk integration disablement, service-account handoffs, or AppD to
  Splunk log deep links.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk AppDynamics Log Observer Connect Setup

Splunk-side work delegates to Splunk Platform skills. This skill renders AppD
LOC validation and handoff assets.

```bash
bash skills/splunk-appdynamics-log-observer-connect-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-log-observer-connect-setup/scripts/validate.sh
```

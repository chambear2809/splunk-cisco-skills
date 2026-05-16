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
---

# Splunk AppDynamics Log Observer Connect Setup

Splunk-side work delegates to Splunk Platform skills. This skill renders AppD
LOC validation and handoff assets.

```bash
bash skills/splunk-appdynamics-log-observer-connect-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-log-observer-connect-setup/scripts/validate.sh
```

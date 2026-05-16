---
name: splunk-appdynamics-analytics-setup
description: >-
  Render, validate, and gate Splunk AppDynamics Analytics workflows for
  Transaction Analytics, Log Analytics, Browser Analytics, Mobile Analytics,
  Synthetic Analytics, IoT Analytics, Connected Devices Analytics, Business Journeys,
  Experience Level Management (XLM), ADQL, Analytics Events API schemas, event
  publishing, and query validation. Use when the user asks for AppDynamics
  Analytics, ADQL, Analytics Events API, custom event publishing, analytics
  schemas, transaction analytics, log analytics, browser or mobile analytics,
  synthetic analytics, IoT analytics, connected device analytics, Business Journeys, XLM, SLA,
  or experience-level reporting.
---

# Splunk AppDynamics Analytics Setup

Custom event publishing is gated by `--accept-analytics-event-publish` and uses
an Events API key file. Render mode writes redacted headers and ADQL runbooks.

```bash
bash skills/splunk-appdynamics-analytics-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-analytics-setup/scripts/validate.sh
```

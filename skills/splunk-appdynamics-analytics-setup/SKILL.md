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
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk AppDynamics Analytics Setup

Custom event publishing is the executable action path. It is gated by
`--accept-analytics-event-publish`, uses a chmod-600 Events API key file, rejects
empty event arrays, and fails on HTTP errors. Other Analytics assets remain
operator runbooks.

```bash
bash skills/splunk-appdynamics-analytics-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-analytics-setup/scripts/validate.sh
bash skills/splunk-appdynamics-analytics-setup/scripts/setup.sh \
  --apply events --accept-analytics-event-publish --spec path/to/analytics.yaml
```

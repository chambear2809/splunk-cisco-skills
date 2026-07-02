---
name: splunk-appdynamics-database-visibility-setup
description: >-
  Render and validate Splunk AppDynamics Database Visibility
  workflows, including Database Agent readiness, Database Visibility API
  collector CRUD, file-backed database secrets, DB server, node, metric, and
  event validation. Use when the user asks for AppDynamics Database Visibility,
  Database Agent, database collector creation or updates, Database Visibility
  API payloads, DB credential redaction, DB server validation, DB node
  validation, or database event checks.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk AppDynamics Database Visibility Setup

Database collector payloads are always rendered with redacted credentials and
file-backed secret references.
The payloads are operator handoffs, not executable requests; `--apply` fails
closed until collector CRUD has a documented, read-back-validated executor.

```bash
bash skills/splunk-appdynamics-database-visibility-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-database-visibility-setup/scripts/validate.sh
```

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

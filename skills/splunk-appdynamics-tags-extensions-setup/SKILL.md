---
name: splunk-appdynamics-tags-extensions-setup
description: >-
  Render, validate, and optionally apply Splunk AppDynamics tags, extensions,
  and integration-module workflows, including Custom Tag APIs, tag enablement,
  Machine Agent custom metrics, Integration Modules, extensions, ServiceNow,
  Jira, Scalyr, Agent Command Center, and Log Auto-Discovery runbooks. Use when
  the user asks for AppDynamics custom tags, tag APIs, extensions, Machine Agent
  custom metrics, Integration Modules, ServiceNow, Jira, Scalyr, Agent Command
  Center, or Log Auto-Discovery.
---

# Splunk AppDynamics Tags Extensions Setup

Tag APIs are API-backed where documented. Extensions and third-party systems
render runbooks unless the owning system has an explicit apply path.

```bash
bash skills/splunk-appdynamics-tags-extensions-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-tags-extensions-setup/scripts/validate.sh
```

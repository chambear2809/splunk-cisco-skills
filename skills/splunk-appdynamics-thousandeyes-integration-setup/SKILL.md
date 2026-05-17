---
name: splunk-appdynamics-thousandeyes-integration-setup
description: >-
  Render, validate, and safely gate the AppDynamics-ThousandEyes integration
  across AppDynamics SaaS, On-Premises, and Virtual Appliance. Use when Codex
  needs to configure AppDynamics ThousandEyes token readiness, Dash Studio
  ThousandEyes widgets, Browser/Mobile RUM ThousandEyes network metrics,
  ThousandEyes native AppDynamics integration runbooks for test recommendations
  and alert notifications, ThousandEyes API-backed tests/labels/tags/alert
  rules/dashboards/templates, or a custom webhook fallback that posts
  ThousandEyes alerts into AppDynamics custom events.
---

# Splunk AppDynamics ThousandEyes Integration Setup

Own the AppDynamics-ThousandEyes integration end to end. The skill renders
reviewable artifacts first and keeps live product mutation behind explicit gates.

## Safe Workflow

```bash
bash skills/splunk-appdynamics-thousandeyes-integration-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-thousandeyes-integration-setup/scripts/validate.sh
```

Use a local spec derived from `template.example` for customer work. Never put
ThousandEyes tokens, AppDynamics passwords, OAuth client secrets, or API keys in
the spec, shell history, rendered files, or chat. Use chmod-600 secret files.

## What This Skill Covers

- AppDynamics `Administration > Integrations > ThousandEyes` token enablement,
  rotation, disablement, and Dash Studio query readiness.
- Dash Studio ThousandEyes widget constraints: Time Series, Metric Number, and
  Gauge only; one TE query per widget; group-by only for Time Series; disabled
  tests excluded; max time range 90 days; no time range comparison.
- Browser/Mobile RUM ThousandEyes network metrics. Treat this as SaaS-supported
  unless an on-premises or Virtual Appliance Controller exposes the documented
  UI.
- ThousandEyes native AppDynamics integration runbook. Test recommendations are
  cSaaS-only; alert notifications need a reachable Controller URL and Create
  Events permission.
- ThousandEyes API-backed assets through the existing
  `splunk-observability-thousandeyes-integration` skill: tests, alert rules,
  labels, tags, dashboards, and templates.
- ThousandEyes Integrations API custom webhook fallback: generic connector,
  webhook operation, connector assignment, alert-rule notification fragments,
  and AppDynamics custom event probe.

## Boundaries

- Do not claim a public ThousandEyes API can create the native AppDynamics
  integration unless Cisco documents that endpoint. Render the UI runbook and
  accept an existing native integration ID for alert rules.
- Do not use ThousandEyes Webhook Operations APIs for ThousandEyes for
  Government instances.
- Do not mutate ThousandEyes assets without `--accept-appd-te-mutation` and the
  downstream `--i-accept-te-mutations` gate.

## Rendered Outputs

Primary outputs include:

- `appd-te-readiness.yaml`
- `thousandeyes-token-runbook.md`
- `dash-studio-query-runbook.md`
- `eum-network-metrics-runbook.md`
- `te-assets-spec.yaml`
- `handoff-thousandeyes-assets.sh`
- `te-native-appd-integration-runbook.md`
- `te-appd-webhook-payloads/connector.json`
- `te-appd-webhook-payloads/operation.json`
- `te-alert-notification-fragments.json`
- `te-api-apply-plan.sh`
- `appd-events-api-probe.sh`
- `te-appd-admin-checklist.md`

Read `reference.md` before applying or adapting the rendered API payloads.

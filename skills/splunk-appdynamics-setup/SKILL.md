---
name: splunk-appdynamics-setup
description: >-
  Coverage-first parent router for the Splunk AppDynamics skill suite. Resolves
  AppDynamics SaaS, On-Premises, Virtual Appliance, SAP Agent, APM, agents,
  Smart Agent, Cluster Agent, Infrastructure Visibility, Database Visibility,
  Analytics, EUM, Synthetic Monitoring, Log Observer Connect, Controller/admin,
  alerting, dashboards/reports, ThousandEyes integration, tags, extensions,
  Sensitive Data Collection and Security, release notes and references, product
  announcements, AIML, GPU Monitoring, Splunk AppDynamics for OpenTelemetry,
  Secure Application, Observability for AI, and Splunk Platform integration
  requests to the owning child skill, then emits a machine-readable coverage
  report from the checked-in taxonomy. Use when the user asks for AppDynamics
  setup, AppDynamics coverage, AppDynamics product routing, or a full
  AppDynamics doctor/gap report.
---

# Splunk AppDynamics Setup

This is the parent router for the AppDynamics suite. It does not mutate a
Controller, Kubernetes cluster, host, SAP system, or Splunk deployment directly.
It reads the taxonomy in `references/appdynamics-taxonomy.yaml`, routes each
feature family to its owner, and renders a coverage report with explicit source
URLs, validation methods, and apply boundaries.

`cisco-appdynamics-setup` remains the owner for `Splunk_TA_AppDynamics` on
Splunk Platform. This parent delegates that path instead of duplicating TA
automation.

## Safe Workflow

```bash
bash skills/splunk-appdynamics-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-setup/scripts/validate.sh
python3 skills/splunk-appdynamics-setup/scripts/check_coverage.py
```

Render output defaults to `splunk-appdynamics-setup-rendered/` and includes:

- `coverage-report.json`
- `child-orchestration-plan.md`
- `doctor-summary.md`
- `apply-plan.sh`
- `redacted-spec.json`

## Modes

- `--render`: render coverage, child routing, and runbooks.
- `--apply [sections]`: parent renders delegated apply plans only.
- `--validate [--live]`: validate rendered coverage; live checks are delegated.
- `--doctor`: summarize coverage and routing health.
- `--quickstart`: render and print the validation command.
- `--rollback [sections]`: render rollback handoff plan.
- `--json`: emit machine-readable result.

## Coverage Contract

A feature is covered only when taxonomy rows include:

- owner skill
- official source URL
- allowed coverage status
- validation method
- explicit apply boundary

Allowed statuses are `api_apply`, `cli_apply`, `k8s_apply`, `delegated_apply`,
`render_runbook`, `validate_only`, and `not_applicable`.

## Secret Handling

Never ask for, paste, or render AppDynamics passwords, OAuth client secrets,
Events API keys, Database Visibility credentials, SAP passwords, or Splunk
tokens. Use chmod-600 files and the `*-file` flags exposed by child workflows.

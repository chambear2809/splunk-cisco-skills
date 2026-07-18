---
name: splunk-appdynamics-setup
description: "Use when the user asks for AppDynamics setup, AppDynamics coverage, AppDynamics product routing, or a
  full AppDynamics doctor/gap report. Coverage-first parent router for the Splunk AppDynamics skill suite.
  Resolves AppDynamics SaaS, On-Premises, Virtual Appliance, SAP Agent, APM, agents, Smart Agent, Cluster
  Agent, Infrastructure Visibility, Database Visibility, Analytics, EUM, Synthetic Monitoring, Log
  Observer Connect, Controller/admin, alerting, dashboards/reports, ThousandEyes integration, tags,
  extensions, Sensitive Data Collection and Security, release notes and references, product announcements,
  AIML, GPU Monitoring, Splunk AppDynamics for OpenTelemetry, Secure Application, Observability for AI,
  and Splunk Platform integration requests to the owning child skill, then emits a machine-readable
  coverage report from the checked-in taxonomy."
compatibility: "Splunk Cloud Platform 10.5.2605: delegated. Compatibility is determined by the selected child skill; this router does not install a runtime or package itself."
metadata:
  splunk_cloud_10_5: "delegated"
  compatibility_verified: "2026-07-02"
---

# Splunk AppDynamics Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- The user asks for AppDynamics setup, AppDynamics coverage, AppDynamics product routing, or a full AppDynamics
  doctor/gap report.
- Preview and review the splunk appdynamics setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-appdynamics-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-appdynamics-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

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
- `--apply`: rejected at the parent. Invoke the routed child skill so its real
  mutation gate, spec schema, and validation contract are enforced.
- `--validate`: validate rendered coverage and artifact contracts. `--live`
  executes only implemented read-only child probes (currently platform,
  Controller licensing, and Kubernetes/O11y) and fails closed for workflows
  whose only probe would mutate state or is not implemented.
- `--doctor`: check taxonomy fields, ownership, wrapper files, and consistency
  between actionable coverage claims and executable apply paths.
- `--quickstart`: render and print the validation command.
- `--rollback`: rejected at the parent; rollback belongs to the child that
  created the mutation and evidence.
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

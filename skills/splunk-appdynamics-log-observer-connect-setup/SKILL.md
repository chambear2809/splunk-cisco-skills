---
name: splunk-appdynamics-log-observer-connect-setup
description: "Use when the user asks for AppDynamics Log Observer Connect, AppDynamics logs in Splunk Platform, legacy
  Splunk integration disablement, service-account handoffs, or AppD to Splunk log deep links. Render,
  validate, and delegate Splunk Log Observer Connect for Splunk AppDynamics workflows, including new LOC
  setup, old Splunk integration detection and disablement, Splunk Cloud or Enterprise service-account
  handoffs, allow-list checks, and deep-link validation."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk AppDynamics Log Observer Connect Setup

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

- The user asks for AppDynamics Log Observer Connect, AppDynamics logs in Splunk Platform, legacy Splunk integration
  disablement, service-account handoffs, or AppD to Splunk log deep links.
- Preview and review the splunk appdynamics log observer connect setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-appdynamics-log-observer-connect-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-appdynamics-log-observer-connect-setup/scripts/validate.sh --help
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

Splunk-side work delegates to Splunk Platform skills. This skill renders AppD
LOC validation and handoff assets.

```bash
bash skills/splunk-appdynamics-log-observer-connect-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-log-observer-connect-setup/scripts/validate.sh
```

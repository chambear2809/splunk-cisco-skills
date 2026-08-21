---
name: splunk-infosec-app-setup
description: "Use when the user asks to install, configure, prepare, or validate the InfoSec app. Render, install, and
  validate InfoSec App for Splunk readiness, including package delivery, prerequisite security data-source
  checklist, dashboard and macro checks, CIM/data-model prerequisites, Cloud IDM support-request notes,
  Lookup Editor dependency, and validation SPL."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Splunk InfoSec App Setup

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

- Install, configure, prepare, or validate the InfoSec app.
- Preview and review the splunk infosec app setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-infosec-app-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-infosec-app-setup/scripts/validate.sh --help
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

## Shared add-on completion gate

Whenever this workflow installs, configures, or hands off the InfoSec app or
one of its add-on dependencies, follow the
[shared completion gate](../shared/ta_completion_gate.md). Package delivery
alone is not success; validate prerequisite ingest, macros, and shipped
dashboards against data.

Render-first workflow for the InfoSec App for Splunk. It emits install
readiness, prerequisite source checklists, dashboard and macro validation SPL,
Cloud IDM support notes, and handoffs to knowledge-object, CIM, and Lookup
Editor workflows. Its explicit `--install` and `--all` modes install the app;
it does not change dashboards, macros, lookups, or data-source configuration.

## Package Verification Boundary

The reviewed InfoSec App baseline is `1.7.2`, the current public release, which
advertises Splunk 10.5. The package was downloaded, unpacked, and inspected
here, so the shared installer's default pin needs no review override. Still
inventory the shipped dashboards, macros, lookups, and prerequisites against
your own data before declaring the app ready — package verification does not
prove the dashboards return results in your environment.

## Workflow

```bash
bash skills/splunk-infosec-app-setup/scripts/setup.sh --render \
  --platform auto --security-indexes security,endpoint,network
```

## Execute

Preview package install and validation:

```bash
bash skills/splunk-infosec-app-setup/scripts/setup.sh --all --dry-run --json
```

Install and validate:

```bash
bash skills/splunk-infosec-app-setup/scripts/setup.sh --all --live
```

Data-source onboarding, CIM readiness, macros, and lookup governance remain
delegated to the owning setup skills.

```bash
bash skills/splunk-infosec-app-setup/scripts/validate.sh \
  --rendered-dir splunk-infosec-app-rendered --live
```

See `reference.md` for prerequisites and Cloud IDM notes.

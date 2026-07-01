---
name: splunk-infosec-app-setup
description: >-
  Render, install, and validate InfoSec App for Splunk readiness, including
  package delivery, prerequisite security data-source checklist, dashboard and macro
  checks, CIM/data-model prerequisites, Cloud IDM support-request notes, Lookup
  Editor dependency, and validation SPL. Use when the user asks to install,
  configure, prepare, or validate the InfoSec app.
---

# Splunk InfoSec App Setup

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

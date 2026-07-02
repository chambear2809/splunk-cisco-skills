---
name: splunk-infosec-app-setup
description: >-
  Render, install, and validate InfoSec App for Splunk readiness, including
  package delivery, prerequisite security data-source checklist, dashboard and macro
  checks, CIM/data-model prerequisites, Cloud IDM support-request notes, Lookup
  Editor dependency, and validation SPL. Use when the user asks to install,
  configure, prepare, or validate the InfoSec app.
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
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

## Package Verification Boundary

The repository's reviewed InfoSec App baseline is `1.7.1`. The current public
release is `1.7.2` and advertises Splunk 10.5 support, but this repository has
not inspected that package. The shared installer defaults to verified `1.7.1`;
only `--accept-unverified-release` follows public `1.7.2`. After that explicit
override, inventory its dashboards, macros, lookups, and prerequisites before
declaring the app ready.

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

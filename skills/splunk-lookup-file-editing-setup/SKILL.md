---
name: splunk-lookup-file-editing-setup
description: >-
  Render and validate Splunk App for Lookup File Editing readiness, including
  install planning, CSV and KV Store lookup inventory checks, SHC allowRestReplay
  backup-replication runbook, app health checks, lookup ownership guidance, and
  handoffs to knowledge-object and KV Store skills. Use when the user asks to
  install, configure, operate, or validate Lookup File Editing.
---

# Splunk Lookup File Editing Setup

## Shared add-on completion gate

Whenever this workflow installs, configures, or hands off the Lookup File
Editing app or a dependency, follow the
[shared completion gate](../shared/ta_completion_gate.md). Package delivery
alone is not success; validate applicable lookup operations and shipped views,
or record explicit evidence that no dashboards ship.

Render-first workflow for the Splunk App for Lookup File Editing. It emits
install readiness, CSV/KV Store lookup inventory SPL, SHC backup-replication
notes, app health checks, and handoffs to knowledge-object and KV Store skills.
It does not edit lookup files or app configuration.

## Workflow

```bash
bash skills/splunk-lookup-file-editing-setup/scripts/setup.sh --render \
  --platform auto --lookup-scope both --shc-mode true
```

## Execute

Preview package install and validation:

```bash
bash skills/splunk-lookup-file-editing-setup/scripts/setup.sh --all \
  --dry-run --json
```

Install and validate:

```bash
bash skills/splunk-lookup-file-editing-setup/scripts/setup.sh --all --live
```

Lookup contents, ACL updates, SHC app config, and KV Store operations remain
delegated to knowledge-object and KV Store workflows.

```bash
bash skills/splunk-lookup-file-editing-setup/scripts/validate.sh \
  --rendered-dir splunk-lookup-file-editing-rendered --live
```

See `reference.md` for SHC and lookup-governance guardrails.

---
name: splunk-knowledge-objects
description: "Deprecated help-only compatibility alias for splunk-knowledge-objects-setup. Use when an existing caller supplies the exact legacy skill name and needs an actionable canonical handoff; every operational invocation fails closed before rendering, validation, live access, or mutation."
compatibility: "Splunk Cloud Platform 10.5.2605: delegated. Compatibility is determined by the canonical replacement or selected child skill; this compatibility alias or router does not own a runtime or package."
metadata:
  splunk_cloud_10_5: "delegated"
  compatibility_verified: "2026-08-20"
  deprecated: "true"
  replaced_by: "splunk-knowledge-objects-setup"
---

# Splunk Knowledge-Object Governance (Deprecated Compatibility Alias)

> [!WARNING]
> `splunk-knowledge-objects` is deprecated and replaced by
> [`splunk-knowledge-objects-setup`](../splunk-knowledge-objects-setup/SKILL.md). Use the canonical skill for all work.

## Prerequisites

| Requirement | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Display the help-only compatibility handoff | `bash --version && python3 --version` |
| Canonical replacement | Perform supported knowledge-object work | `test -f skills/splunk-knowledge-objects-setup/SKILL.md` |

## When to Activate

- An existing caller supplies the exact legacy name `splunk-knowledge-objects`.
- The caller needs the canonical replacement name before taking any action.

Do not activate this alias for setup, rendering, validation, or live operations.

## Workflow Overview

```text
┌──────────────────────────┐
│ Compatibility invocation │
└────────────┬─────────────┘
             │
     ┌───────┴────────┐
     ▼                ▼
┌────────────────┐  ┌────────────────────┐
│ Exactly one    │  │ Anything else,     │
│ --help or -h   │  │ including no args  │
└───────┬────────┘  └─────────┬──────────┘
        ▼                     ▼
┌────────────────────┐  ┌────────────────────┐
│ Show deprecation   │  │ Exit 2 before      │
│ and canonical      │  │ rendering, network │
│ handoff            │  │ access, or mutation│
└────────────────────┘  └────────────────────┘
```

## Fail-Closed Compatibility Contract

This directory preserves only exact-name discovery and an actionable handoff. No legacy
operational interface is demonstrably compatible with the canonical safety gates, so
nothing is forwarded. The setup, validation, and renderer entrypoints accept only an
exact `--help` or `-h` request. Every other invocation exits with status 2 before
rendering files, opening network connections, launching product commands, or changing
state, and names `splunk-knowledge-objects-setup` as `replaced_by`.

Legacy reference and intake-template copies were removed so this alias cannot be mistaken
for an independently maintained workflow. Do not reconstruct or execute an old rendered
bundle. Read the canonical skill and collect inputs using its current contract.

## Commands

```bash
bash skills/splunk-knowledge-objects/scripts/setup.sh --help
bash skills/splunk-knowledge-objects/scripts/validate.sh --help
python3 skills/splunk-knowledge-objects/scripts/render_assets.py --help
```

For supported behavior, begin here:

```bash
bash skills/splunk-knowledge-objects-setup/scripts/setup.sh --help
bash skills/splunk-knowledge-objects-setup/scripts/validate.sh --help
```

Any existing automation that supplies operational legacy flags must stop and be migrated
to the canonical interface after reviewing its apply and acceptance gates. Do not infer a
flag translation.

## Troubleshooting

| Failure | Meaning | Resolution |
|---|---|---|
| Exit status 2 | An operational legacy argument was refused | Read `splunk-knowledge-objects-setup` and migrate explicitly |
| Canonical skill missing | The checkout is incomplete or stale | Refresh the canonical skill source before continuing |

---
name: splunk-knowledge-objects
description: "Use when the user asks to govern or audit saved searches and scheduled searches, manage lookups and
  lookup definitions, standardize macros, eventtypes, and tags, fix knowledge-object permissions and
  sharing, find orphaned or private knowledge objects, reassign ownership, or stage governed knowledge
  objects and metadata into an app. Render, preflight, and validate Splunk knowledge-object governance
  assets for saved searches, reports, alerts, macros, lookups, lookup definitions, eventtypes, tags, and
  field extractions, plus sharing/permission metadata and ownership reassignment."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Knowledge-Object Governance

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

- Govern or audit saved searches and scheduled searches, manage lookups and lookup definitions, standardize macros,
  eventtypes, and tags, fix knowledge-object permissions and sharing, find orphaned or private knowledge objects,
  reassign.
- Preview and review the splunk knowledge objects workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-knowledge-objects/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-knowledge-objects/scripts/validate.sh --help
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

This skill renders knowledge-object (KO) governance assets and a live audit
toolkit for Splunk Platform: saved searches, reports, alerts, macros, lookups
and lookup definitions, eventtypes, tags, field extractions, and the
sharing/ownership metadata (`local.meta`) that controls who can see and edit
them. It is render-first because changing sharing, ownership, or scheduled
search definitions affects every user and app that depends on them.

## Agent Behavior

This skill does not handle secrets. Knowledge objects live in app
`default/` and `local/` conf plus `metadata/` (`default.meta`, `local.meta`).
Always stage governed objects and metadata into a dedicated app `local/`; never
edit shipped `default/` files.

Use `template.example` for non-secret values: target app context, object types
to audit, governance app name, and the owner to reassign to.

## Quick Start

Audit all knowledge objects across apps (read-only):

```bash
bash skills/splunk-knowledge-objects/scripts/setup.sh --phase render
bash skills/splunk-knowledge-objects/scripts/validate.sh --live
```

Render governed conf + sharing metadata into an app:

```bash
bash skills/splunk-knowledge-objects/scripts/setup.sh \
  --app-name ZZZ_governance \
  --app-context search \
  --object-types savedsearches,macros,lookups,eventtypes,tags
```

## What It Renders

- `inventory.sh` — full KO inventory via REST (app, owner, sharing, disabled)
- `audit.sh` — governance findings: orphaned owners, private scheduled searches,
  lookups without definitions, world-writable sharing, disabled objects
- `local.meta` — sharing/ownership metadata template for governed objects
- `savedsearches.conf`, `macros.conf`, `transforms.conf` — governed object and
  lookup-definition templates (commented, review before use)
- `apply.sh` — stage conf and `local.meta` into `etc/apps/<app>/{local,metadata}`
- `reassign.sh` — reassign object ownership via the ACL REST endpoint (gated)
- `README.md` / `metadata.json` — review context

## Operating Notes

- Prefer app-level (`global`/`app`) sharing for shared content; reserve `user`
  (private) sharing for personal work.
- Orphaned objects (owned by a removed user) keep running scheduled jobs but
  cannot be edited in the UI; reassign them to a service account or app context.
- Lookups need both a lookup-table file and a lookup definition (`transforms.conf`
  `[<name>]` with `filename` or `external_cmd`); automatic lookups go in
  `props.conf`.
- On a search head cluster, apply through the SHC deployer.

Read `reference.md` before reassigning ownership or changing sharing in bulk.

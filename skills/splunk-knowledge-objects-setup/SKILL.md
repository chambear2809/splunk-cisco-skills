---
name: splunk-knowledge-objects-setup
description: "Use when the user asks to create or govern saved searches, scheduled searches, alerts, macros, lookups,
  eventtypes, tags, or to set knowledge-object permissions, ownership, or app sharing. Not for Enterprise
  Security detections, which live in splunk-enterprise-security-config. Render, validate, and apply
  governance for Splunk knowledge objects: saved searches and alerts, search macros, CSV and KV Store
  lookups (with automatic lookup binding), eventtypes, tags, and field knowledge, plus sharing and
  ownership (ACL) governance across user, app, and global scopes."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Knowledge Objects Setup

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

- Create or govern saved searches, scheduled searches, alerts, macros, lookups, eventtypes, tags, or to set
  knowledge-object permissions, ownership, or app sharing. Not for Enterprise Security detections, which live in.
- Preview and review the splunk knowledge objects setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-knowledge-objects-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-knowledge-objects-setup/scripts/validate.sh --help
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

This skill renders and applies common Splunk knowledge objects and their
permissions. It is render-first so you can review the exact conf stanzas and
ACL plan before writing them live.

## Agent Behavior

Never ask for the Splunk admin password; apply reads the project `credentials`
file via the shared helper. Setting `sharing=global` is broad and refuses to
apply without `--accept-global-sharing`. App/global objects must use owner
`nobody`; private (`user`) objects must name a user owner. Owner names must
match the strict Splunk username allowlist, and every REST namespace segment is
URL-encoded before use.

## Quick Start

Render a search macro:

```bash
bash skills/splunk-knowledge-objects-setup/scripts/setup.sh --object-kind macro --name net_idx --definition 'index IN ("a","b")'
```

Apply a scheduled saved search live:

```bash
bash skills/splunk-knowledge-objects-setup/scripts/setup.sh --phase apply \
  --object-kind savedsearch --name "Daily Count" --app-name search \
  --search 'index=main | stats count' --is-scheduled true --cron-schedule '0 6 * * *'
```

Apply a KV Store lookup definition shared at app scope:

```bash
bash skills/splunk-knowledge-objects-setup/scripts/setup.sh --phase apply \
  --object-kind lookup --name asset_lookup --lookup-type kvstore --collection asset_inventory \
  --fields-list "_key,ip,risk" --sharing app --owner nobody --read-roles "*"
```

Query the real object, ACL, and optional automatic-lookup binding and fail on
drift:

```bash
bash skills/splunk-knowledge-objects-setup/scripts/setup.sh --phase status \
  --object-kind macro --name net_idx --definition 'index IN ("a","b")'
```

## What It Renders

- `savedsearches.conf`, `macros.conf`, `transforms.conf`, `props.conf`,
  `eventtypes.conf`, `tags.conf` (whichever the object kind needs)
- `lookup-stub.csv` for CSV lookups
- `acl-plan.json` describing sharing/ownership applied to the object `/acl`

## Apply And ACL

`preflight` is a live, read-only phase: it authenticates, proves the target app
and conf collection are readable, and snapshots the existing object, ACL, and
optional automatic-lookup stanza. `status` also performs live REST reads and
writes a mode-600 `knowledge-objects/state/live-status.json`; it is not an
alias for rendered intent.

Apply uses the REST `configs/conf-*` endpoints, sets the object's `/acl`, reads
the result back, and fails if content or governance differs from the request.
If any step fails after mutation, it performs GET-only reconciliation. A
pre-existing or newly created object, ACL, or automatic-lookup stanza is never
restored, overwritten, or deleted automatically: Splunk exposes no verified
conditional `If-Match` write/delete contract, so another actor can edit state
after any guard GET. Failed state is retained with mode-600 before/current
snapshots under a mode-700 `knowledge-objects/state/manual-cleanup-*`
directory, explicit reviewed recovery guidance, and
`rollback=partial`/`manual_cleanup_required=true` in mode-600
`apply-evidence.json`. If every queried target already matches its exact
pre-transaction state, reconciliation records that no failed mutation remains.

Transactional REST apply fails closed for SHC deployer-bundle delivery because
a member REST ACL update cannot be atomic with a deployer file write. For that
topology, use `splunk-knowledge-objects` to render content plus `local.meta` and
push one reviewed deployer bundle. CSV lookup content remains a separate file:
place it in the app `lookups/` directory or upload it through the lookup editor.

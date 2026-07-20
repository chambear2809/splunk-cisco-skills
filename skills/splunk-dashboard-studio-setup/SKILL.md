---
name: splunk-dashboard-studio-setup
description: "Use when the user asks to create a Splunk Dashboard Studio dashboard, build a platform dashboard as
  code, push a dashboard JSON to data/ui/views, or replicate a dashboard between Splunk environments. Not
  for Splunk Observability Cloud dashboards, which use splunk-observability-dashboard-builder. Render,
  validate, and apply Splunk Platform Dashboard Studio dashboards: build a version 2 JSON definition
  (dataSources, visualizations, inputs, layout, defaults), wrap it in the data/ui/views eai:data XML, and
  create or update the view via REST with ACL governance."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Dashboard Studio Setup

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

- Create a Splunk Dashboard Studio dashboard, build a platform dashboard as code, push a dashboard JSON to
  data/ui/views, or replicate a dashboard between Splunk environments. Not for Splunk Observability Cloud
  dashboards, which use.
- Preview and review the splunk dashboard studio setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-dashboard-studio-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-dashboard-studio-setup/scripts/validate.sh --help
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

This skill renders and applies Splunk Platform Dashboard Studio dashboards. It
is render-first so you can review the JSON definition and the `data/ui/views`
XML wrapper before writing the view live.

## Agent Behavior

Never ask for the Splunk admin password; apply reads the project `credentials`
file via the shared helper. Updating an existing dashboard requires
`--accept-overwrite`.

`preflight`, `status`, `apply`, and `all` are live phases. Preflight fails
closed unless the target app, authenticated context, views collection, exact
view, and (when present) exact ACL are readable. Status compares the rendered
`eai:data` byte-for-byte with the exact live view and also validates owner,
sharing, and exact normalized `perms.read` / `perms.write` role sets; it exits
nonzero on drift. Defaults are `--read-roles '*' --write-roles ''`.

Apply snapshots an existing view and ACL into a private temporary directory,
writes content and ACL, then reads both back. An ACL, readback, signal, or local
failure starts read-only reconciliation. If the exact pre-transaction state is
not already present, both existing and newly created views are retained: the
endpoint has no verified conditional `If-Match` restore or delete contract, so
a guard GET followed by an unconditional POST/DELETE could overwrite a
concurrent edit. Apply writes mode-600 before/current snapshots under a
mode-700 `dashboard-studio/state/manual-cleanup-*` directory and marks the
rollback partial/manual-recovery-required. Redacted status/apply evidence
contains hashes, HTTP outcomes, role sets, and reviewed recovery guidance.

This is Splunk Platform Dashboard Studio. For Splunk Observability Cloud
dashboards, use `splunk-observability-dashboard-builder`.

## Quick Start

Build a dashboard from a search:

```bash
bash skills/splunk-dashboard-studio-setup/scripts/setup.sh --dashboard-name net_overview \
  --title "Network Overview" --search 'index=netfw | stats count by action' --viz-type splunk.column
```

Apply it live:

```bash
bash skills/splunk-dashboard-studio-setup/scripts/setup.sh --phase apply \
  --dashboard-name net_overview --app-name search \
  --search 'index=netfw | stats count by action' --viz-type splunk.column --accept-overwrite
```

Apply a full hand-authored definition:

```bash
bash skills/splunk-dashboard-studio-setup/scripts/setup.sh --phase apply \
  --dashboard-name complex_dash --definition-file ./my_dashboard.json --accept-overwrite
```

Check exact live content and governance drift without mutation:

```bash
bash skills/splunk-dashboard-studio-setup/scripts/setup.sh --phase status \
  --dashboard-name complex_dash --definition-file ./my_dashboard.json \
  --owner nobody --sharing app --read-roles '*' --write-roles admin
```

## What It Renders

- `dashboard.json` - the Dashboard Studio version 2 JSON definition
- `view.xml` - the `<dashboard version="2">...<definition><![CDATA[...]]></definition></dashboard>` wrapper

Apply posts `name` + `eai:data` to `/servicesNS/<owner>/<app>/data/ui/views`
(create) or `.../data/ui/views/<name>` (update), then sets sharing/ownership on
the view's `/acl` endpoint, including exact read/write role sets, and reads both
exact endpoints back. Preflight snapshots existing content and ACL before
overwrite. Failure handling performs GET-only reconciliation and never issues
an automatic restore POST or DELETE. The REST endpoint can also read, update,
and delete dashboards and is the supported way to replicate dashboards across
environments.

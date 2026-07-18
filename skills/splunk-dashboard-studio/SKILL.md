---
name: splunk-dashboard-studio
description: "Use when the user asks to build or convert a Splunk Platform Dashboard Studio dashboard, author a
  version 2 dashboard definition, create dashboards as code for Splunk Enterprise or Splunk Cloud,
  generate dashboard JSON/XML from SPL panels, or apply a dashboard via the data/ui/views REST endpoint.
  This is Splunk Platform Dashboard Studio, NOT the Splunk Observability Cloud dashboard builder. Render,
  preflight, and validate Splunk Platform Dashboard Studio dashboards: the version=2 JSON dashboard
  definition, the data/ui/views source XML wrapper, panels for table/single-
  value/line/area/column/bar/pie/markdown visualizations, data source searches, layout (grid or absolute),
  and a REST apply helper."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Platform Dashboard Studio

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

- Build or convert a Splunk Platform Dashboard Studio dashboard, author a version 2 dashboard definition, create
  dashboards as code for Splunk Enterprise or Splunk Cloud, generate dashboard JSON/XML from SPL panels, or apply a
  dashboard via.
- Preview and review the splunk dashboard studio workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-dashboard-studio/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-dashboard-studio/scripts/validate.sh --help
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

This skill renders Splunk Platform **Dashboard Studio** dashboards (the modern
`version="2"` JSON framework) from a simple panel spec: the JSON dashboard
definition, the `data/ui/views` source XML wrapper, and a REST apply helper. It
is render-first so you review the generated definition before publishing a view.

This is Splunk **Platform** Dashboard Studio. For Splunk Observability Cloud
dashboards, use `splunk-observability-dashboard-builder`.

## Agent Behavior

This skill does not handle secrets. Dashboards are stored as views under an app;
the rendered apply helper publishes through the `data/ui/views` REST endpoint and
authenticates against splunkd (interactively or via an existing session) — never
via secrets in argv. Use `template.example` for non-secret values: title, app,
owner, theme, layout, and panels.

## Quick Start

Render a two-panel dashboard from inline panel specs:

```bash
bash skills/splunk-dashboard-studio/scripts/setup.sh \
  --title "Cisco ASA Overview" --app search --theme dark --layout grid \
  --panel "Event volume::column::index=cisco_asa | timechart count" \
  --panel "Top sources::table::index=cisco_asa | top src_ip"
```

Render from a panel spec file and validate:

```bash
bash skills/splunk-dashboard-studio/scripts/setup.sh --title "My DB" --panels-file panels.json
bash skills/splunk-dashboard-studio/scripts/validate.sh
```

Publish the rendered view (review first):

```bash
bash skills/splunk-dashboard-studio/scripts/setup.sh --phase apply --title "My DB" --app search
```

## What It Renders

- `dashboard.json` — the Dashboard Studio `version=2` definition
  (`dataSources`, `visualizations`, `inputs`, `defaults`, `layout`)
- `dashboard.xml` — the `data/ui/views` source XML wrapper with the definition in
  a CDATA `<definition>` block
- `apply.sh` — create or update the view via `data/ui/views` REST (gated)
- `status.sh` — list version=2 views in the target app
- `README.md` / `metadata.json` — review context

## Panel Spec

Inline: `--panel "Title::type::SPL or markdown text"`, repeatable. Types:
`table`, `single`, `line`, `area`, `column`, `bar`, `pie`, `markdown`. For
`markdown`, the third field is the markdown text instead of SPL.

File: `--panels-file panels.json` with a JSON list of objects
(`{"title","type","query"}`, or `{"title","type":"markdown","markdown"}`).

## Operating Notes

- A dashboard is one view per app namespace; the view name (id) is derived from
  the title unless `--dashboard-id` is set.
- Time range comes from a global time-range input and `defaults`; adjust the
  rendered `defaults` block as needed.
- On Splunk Cloud, publishing uses the search-tier REST API; ensure the
  `search-api` allow list permits your IP.
- Authenticated publishing requires a credential-free HTTPS management origin,
  never follows redirects, ignores user curl configuration, and disables URL
  globbing. Plaintext HTTP requires the explicit lab-only
  `SPLUNK_ALLOW_INSECURE_HTTP=true` opt-in.

Read `reference.md` for the schema sections and conversion guidance.

---
name: splunk-dashboard-studio-setup
description: >-
  Render, validate, and apply Splunk Platform Dashboard Studio dashboards: build
  a version 2 JSON definition (dataSources, visualizations, inputs, layout,
  defaults), wrap it in the data/ui/views eai:data XML, and create or update the
  view via REST with ACL governance. Use when the user asks to create a Splunk
  Dashboard Studio dashboard, build a platform dashboard as code, push a
  dashboard JSON to data/ui/views, or replicate a dashboard between Splunk
  environments. Not for Splunk Observability Cloud dashboards, which use
  splunk-observability-dashboard-builder.
---

# Splunk Dashboard Studio Setup

This skill renders and applies Splunk Platform Dashboard Studio dashboards. It
is render-first so you can review the JSON definition and the `data/ui/views`
XML wrapper before writing the view live.

## Agent Behavior

Never ask for the Splunk admin password; apply reads the project `credentials`
file via the shared helper. Updating an existing dashboard requires
`--accept-overwrite`.

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

## What It Renders

- `dashboard.json` - the Dashboard Studio version 2 JSON definition
- `view.xml` - the `<dashboard version="2">...<definition><![CDATA[...]]></definition></dashboard>` wrapper

Apply posts `name` + `eai:data` to `/servicesNS/<owner>/<app>/data/ui/views`
(create) or `.../data/ui/views/<name>` (update), then sets sharing/ownership on
the view's `/acl` endpoint. The REST endpoint can also read, update, and delete
dashboards and is the supported way to replicate dashboards across environments.

# Splunk Dashboard Studio Reference

## Research Basis

Based on current Splunk Dashboard Studio REST documentation (verified 2026):

- Dashboard Studio dashboards are created with the `data/ui/views` REST endpoint
  (`/servicesNS/<user>/<app>/data/ui/views`). The endpoint can also read,
  update, and delete dashboards and is the supported way to replicate a
  dashboard from one environment to another.
- The request is a POST with `Content-Type: application/x-www-form-urlencoded`,
  the dashboard id as `name`, and the full dashboard as `eai:data`.
- `eai:data` is an XML wrapper whose `<dashboard>` element sets `version="2"`
  (and an optional `theme`), contains `<label>` and `<description>`, and embeds
  the JSON definition inside `<definition><![CDATA[ ... ]]></definition>`.
- The JSON definition contains `visualizations`, `dataSources`, `inputs`,
  `layout` (with `layoutDefinitions` of type `absolute`, `grid`, or `freeform`,
  and `tabs`), `defaults`, `title`, and `description`. Data sources use types
  such as `ds.search` (with `options.query`), `ds.chain`, and `ds.savedSearch`.

## Apply Transport

This skill renders `dashboard.json` and the `view.xml` wrapper, then applies via
REST: it POSTs `name` + `eai:data` to `data/ui/views` to create, or to
`data/ui/views/<name>` to update an existing view (gated by `--accept-overwrite`
after an existence check). It then sets sharing/ownership on the view's `/acl`
endpoint. The definition is validated as JSON and checked for the CDATA
terminator before being embedded.

## Building vs Bring-Your-Own Definition

- Provide `--search` (plus `--viz-type`, `--layout`) to generate a minimal
  single-visualization dashboard.
- Provide `--definition-file` with a complete Dashboard Studio JSON definition
  (for example exported from the Source editor) to apply a complex dashboard
  verbatim.

## Boundaries

Splunk Platform Dashboard Studio only. Splunk Observability Cloud dashboards are
handled by `splunk-observability-dashboard-builder`; Simple XML dashboards are
out of scope.

## Validation

Static validation confirms the rendered assets exist and that `view.xml`
declares `version="2"`. Confirm the live view in Splunk Web or via a GET to the
`data/ui/views/<name>` endpoint after applying.

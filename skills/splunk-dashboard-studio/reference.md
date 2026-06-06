# Splunk Platform Dashboard Studio Reference

Dashboard Studio is the modern Splunk Platform dashboarding framework
(introduced in 8.2), using a JSON `version="2"` definition instead of the classic
Simple XML. This skill renders that definition plus the `data/ui/views` source
XML wrapper and a REST apply helper so you can build dashboards as code.

This is Splunk **Platform** Dashboard Studio. For Splunk Observability Cloud
dashboards (SignalFlow charts), use `splunk-observability-dashboard-builder`.

## Source Format

A Dashboard Studio view is stored like any view, but the `eai:data` is a v2
wrapper:

```xml
<dashboard version="2" theme="dark">
  <label>Title</label>
  <description>Description</description>
  <definition><![CDATA[
  { ...JSON definition... }
  ]]></definition>
  <meta type="hiddenElements"><![CDATA[
  { "hideEdit": false, "hideOpenInSearch": false, "hideExport": false }
  ]]></meta>
</dashboard>
```

The JSON definition cannot contain the literal `]]>` (it would close the CDATA
block); the renderer rejects panel content containing it.

## JSON Definition Sections

- `dataSources` — search stanzas (`ds.search`) with `options.query` and `name`.
- `visualizations` — viz stanzas keyed by id, with `type` (for example
  `splunk.table`, `splunk.line`), `title`, and `dataSources.primary` pointing at
  a data source id. Markdown panels (`splunk.markdown`) use
  `options.markdown` and have no data source.
- `inputs` — input stanzas, for example a global time range
  (`input.timerange`) with `options.token`.
- `defaults` — global defaults applied to all data sources/visualizations. This
  skill wires every search to the global time token via
  `defaults.dataSources["ds.search"].options.queryParameters`.
- `layout` — `globalInputs`, `layoutDefinitions.layout_1` (`type` `grid` or
  `absolute`, `options.width/height`, and a `structure` array of blocks with
  `position` `{x,y,w,h}`), and `tabs.items`.
- Optional: `expressions`, `applicationProperties`.

## Visualization Types

This skill maps friendly names to Dashboard Studio types:

| Friendly | Dashboard Studio type |
| --- | --- |
| `table` | `splunk.table` |
| `single` | `splunk.singlevalue` |
| `line` | `splunk.line` |
| `area` | `splunk.area` |
| `column` | `splunk.column` |
| `bar` | `splunk.bar` |
| `pie` | `splunk.pie` |
| `markdown` | `splunk.markdown` |

For richer visualizations (choropleth, single-value icons, trellis, color/format
options), edit the rendered `dashboard.json` directly before applying.

## Layout

- `grid` — Splunk reflows blocks; positions act as ordering/sizing hints.
- `absolute` — exact `x/y/w/h` placement, supports layering.

The renderer arranges panels in a two-column grid (600x316 blocks). Adjust the
`structure` positions for custom layouts.

## Publishing (data/ui/views)

Dashboards are created, read, updated, and deleted through the `data/ui/views`
REST endpoint:

- Create: `POST /servicesNS/<owner>/<app>/data/ui/views` with `name=<id>` and
  `eai:data=<v2 xml>`.
- Update: `POST /servicesNS/<owner>/<app>/data/ui/views/<id>` with `eai:data`.

The rendered `apply.sh` uses the local `splunk` CLI `_internal call` (which uses
your authenticated CLI session — no secrets in argv), checks whether the view
exists, and creates or updates accordingly. It is gated behind a typed `APPLY`
confirmation. On Splunk Cloud, the underlying REST runs on the search tier;
ensure the `search-api` IP allow list permits your host
(`splunk-cloud-acs-admin-setup`).

Owner `nobody` creates an app-level (shared) view; a username creates it as that
user's private object (manage sharing with `splunk-knowledge-objects`).

## Converting From Classic

Classic Simple XML dashboards can be converted to Dashboard Studio in the UI
(Dashboards > Convert). There is no lossless automatic field-by-field converter
for all panels; third-party visualizations and some Simple XML features are not
supported in Dashboard Studio. Use this skill to author new v2 dashboards or to
template repeatable ones; review conversions in the UI.

## Out Of Scope And Handoffs

- Saved searches / reports / alerts powering panels: `splunk-knowledge-objects`.
- Sharing/permissions of the published view: `splunk-knowledge-objects`.
- Splunk Observability Cloud dashboards: `splunk-observability-dashboard-builder`.
- Mobile delivery of dashboards: `splunk-secure-gateway`.

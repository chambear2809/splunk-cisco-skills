# Classic Observability Dashboard API Reference

## Scope

This skill renders the documented classic Splunk Observability Cloud dashboard APIs:

- `GET/POST/PUT/DELETE /v2/chart`
- `GET/POST/PUT/DELETE /v2/dashboard`
- `GET/POST/PUT/DELETE /v2/dashboardgroup`
- `POST /v2/dashboardgroup/{id}/dashboard` for cloning dashboards to a group

Use `https://api.<realm>.observability.splunkcloud.com/v2` as the REST API base URL.
Use `https://stream.<realm>.observability.splunkcloud.com` only for SignalFlow execution workflows.

## Authentication

Live requests use the `X-SF-Token` header. The token must come from `--token-file`; never put token values in rendered payloads, command arguments, or environment-variable prefixes.

## Metric Discovery

The metric discovery helper calls `GET /v2/metric`. Splunk Observability Cloud
expects fielded search syntax for filtered metric discovery. For ergonomics, the
helper converts simple bare terms such as `latency` to `sf_metric:*latency*`.
Already-fielded queries such as `sf_metric:kube.*` pass through unchanged.

## Supported Chart Types

The renderer accepts common aliases but emits canonical API values:

| User alias | API value |
|------------|-----------|
| `time_series`, `timeseries`, `TimeSeries`, `TimeSeriesChart` | `TimeSeriesChart` |
| `single_value`, `singlevalue`, `SingleValue` | `SingleValue` |
| `list`, `List` | `List` |
| `table`, `table_chart`, `TableChart` | `TableChart` |
| `heatmap`, `Heatmap` | `Heatmap` |
| `text`, `markdown`, `Text` | `Text` |

Plot types for time-series output are `LineChart`, `AreaChart`, `ColumnChart`, and `Histogram`.

Current product docs also list pie/donut and event feed chart types. This
renderer does not apply those through the classic API until a public `/v2/chart`
payload schema is verified. Represent them with `mode: modern-ui-advisory`, a
Text chart, or metric summary charts until support is added.

## Chart Payload Rules

For metric charts:

- `name` is required.
- `programText` is required.
- `programText` must publish at least one stream with `publish()`.
- `options.type` must be one of the supported chart types.
- `options.defaultPlotType` only applies to TimeSeriesChart plots.
- Use `publishLabelOptions` only when labels match SignalFlow `publish(label=...)` values.

For text charts:

- `options.type` is `Text`.
- `options.markdown` contains the rendered note.
- `programText` is omitted.

## Dashboard Payload Rules

Dashboards belong to a dashboard group. Provide either:

- `dashboard_group.id` to attach to an existing group, or
- `dashboard_group.name` to create a custom group before dashboard creation.

The renderer uses placeholders in `dashboard.json` because chart and group IDs do not exist until apply:

- `${dashboard_group_id}`
- `${chart:<local-chart-id>}`

The apply client replaces these placeholders with live API response IDs.

## Update Rules

Chart and dashboard updates use overwrite semantics. To avoid losing fields:

1. GET the existing object.
2. Modify the fetched object.
3. PUT the complete object.

The skill creates new groups, charts, and dashboards by default. Use
`scripts/setup.sh --apply --update-existing` only when the spec includes
`dashboard.id` and a `chart_id` for every chart. The API helper fetches each
existing object and merges the rendered payload before PUT.

## Modern Dashboard Caveat

The new Splunk Observability dashboard experience includes sections, section tabs, service maps, and logs charts. Current public docs describe those as UI workflows. Do not render them through the classic API unless a public API is verified and the renderer is updated with schema validation.

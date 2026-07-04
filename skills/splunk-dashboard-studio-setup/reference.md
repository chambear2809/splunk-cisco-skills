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
after an exact-view preflight). It then sets sharing/ownership on the view's
`/acl` endpoint and reads the exact view and ACL back. The shared Splunk REST
transport enforces its HTTPS, redirect, TLS, and credential protections for
every request. The definition is validated as JSON and checked for the CDATA
terminator before being embedded.

The app and owner are validated as concrete namespace segments (wildcard and
dot-segment values are rejected) and URL-encoded before use in every
`servicesNS` path.

Live preflight requires readable, valid JSON from the target app, authenticated
context, and views collection. An existing exact view is not eligible for
mutation unless both its `eai:data` and ACL can be privately snapshotted first.
The snapshot is transient and mode-restricted.

After a mutation request, ACL/readback failures, ambiguous HTTP responses,
signals, and unexpected local exits trigger read-only reconciliation. The
runner fetches the exact current view and ACL. If they already match the exact
pre-transaction snapshots, it records that no failed mutation remains.
Otherwise it never issues a compensating POST or DELETE: `data/ui/views` has no
verified conditional `If-Match` write/delete contract, and state can change
between a guard GET and an unconditional mutation.

Both failed creates and failed updates are retained for reviewed recovery.
Before/current view and ACL responses (plus available post-content-write
snapshots) are copied as mode-0600 files beneath a mode-0700
`dashboard-studio/state/manual-cleanup-*` directory. The redacted
`apply-evidence.json` records `rollback=partial`, `partial_failure=true`, the
private snapshot path, and explicit guidance to fetch live state again before
manual reconciliation. Session credentials never enter persistent evidence.

ACL intent includes owner, sharing, and exact normalized read/write role sets.
The defaults are read `*` and no write roles. `--read-roles` and
`--write-roles` accept comma-separated sets; apply explicitly sends both fields,
and status/readback fail on any extra, missing, or different role.

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
declares `version="2"`. `--phase status` is a read-only live check against the
exact `data/ui/views/<name>` and `/acl` endpoints. It validates byte-for-byte
`eai:data`, owner, sharing, and normalized `perms.read` / `perms.write` sets,
writes only content hashes/governance fields to
`dashboard-studio/state/live-status.json`, and exits nonzero on drift. Apply
performs this same readback before reporting success.

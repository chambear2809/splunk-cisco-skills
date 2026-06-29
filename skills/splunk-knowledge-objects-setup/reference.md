# Splunk Knowledge Objects Reference

## Research Basis

Based on current Splunk Platform knowledge object and REST documentation:

- Saved searches and alerts live in `savedsearches.conf` and the
  `saved/searches` REST endpoint. Scheduling uses `enableSched = 1` plus
  `cron_schedule`; alerting uses `alert_type`, `alert_condition`, and
  `action.<name> = 1` / `actions = <csv>` for alert actions such as email.
- Search macros live in `macros.conf`. A macro that takes arguments uses a
  stanza name of the form `name(<argcount>)` with `args = a, b` and
  `definition = ...`; `iseval = 1` marks an eval-based macro.
- Lookups: file-based (CSV) lookups use a `transforms.conf` stanza with
  `filename = <file>.csv`; KV Store lookups use `external_type = kvstore` and
  `collection = <collection>`. `fields_list` lists the lookup fields. Automatic
  lookups bind a lookup to a sourcetype in `props.conf` with
  `LOOKUP-<name> = <transform> <input fields> OUTPUT <output fields>`.
- Eventtypes live in `eventtypes.conf` / `saved/eventtypes`; tags live in
  `tags.conf` as `[eventtype=<name>]` with `<tag> = enabled`.
- Permissions and ownership are not stored in the conf file; they are set on the
  object's `/acl` endpoint with `sharing` (`user`, `app`, `global`), `owner`,
  and `perms.read` / `perms.write` role lists. App- and global-scoped objects
  are owned by `nobody`.

## Apply Transport

Apply writes the object via REST `configs/conf-<file>/<stanza>` (the shared
`rest_set_conf` helper is search head cluster deployer-bundle aware) and then
POSTs sharing/ownership to `.../configs/conf-<file>/<stanza>/acl`. For lookups
with `--auto-lookup-sourcetype`, apply also writes the `LOOKUP-<name>` binding to
`props.conf` on that source type (app-scoped), matching the rendered
`props.conf`. Knowledge object changes generally take effect after a
configuration reload; the skill prints platform-appropriate restart/reload
guidance.

## CSV Lookup Content

The lookup definition is written via REST, but the CSV content itself is a file.
Place the rendered `lookup-stub.csv` (renamed to your filename) into the app's
`lookups/` directory on the search tier, or upload it through the lookup editor.
On a search head cluster, distribute lookup files through the deployer.

## Decisions

- Default `--sharing app --owner nobody` for shared content; reserve
  `--sharing global` (gated) for content that must be visible across all apps.
- Use `--read-roles`/`--write-roles` to scope access. With no `--read-roles`, the
  apply step sends no `perms.read`, so Splunk's defaults apply: app- and
  global-scoped objects are readable by all roles (`*`), while `--sharing user`
  objects stay private to the owner.

## Validation

Static validation confirms the rendered conf and ACL-plan assets exist. Confirm
the live object and its permissions in Settings or via the object's REST
endpoint after applying.

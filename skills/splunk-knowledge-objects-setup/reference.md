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

Before mutation, apply reads the target app, authenticated context, conf
collection, object, ACL, and optional `props.conf` stanza. Existing state is
held only in a private temporary transaction directory. Apply then writes the
object via REST `configs/conf-<file>/<stanza>`, POSTs sharing/ownership to
`.../configs/conf-<file>/<stanza>/acl`, writes any requested
`LOOKUP-<name>` binding, and reads all requested state back.

Failures after the first write invoke read-only reconciliation. Immediately after creating
an object, apply captures and validates its complete mutable content and initial
ACL before attempting governance. It does not later DELETE that object: Splunk
does not provide a supported conditional DELETE/If-Match contract, so state can
change between any read-back and an unconditional DELETE. A failed create path
therefore retains the object and writes its before, post-write, current, and ACL
responses under a mode-700 `knowledge-objects/state/manual-cleanup-*`
directory; each snapshot is mode 600. Newly created automatic-lookup stanzas
follow the same retain-and-handoff rule.

Pre-existing objects, ACLs, and automatic-lookup stanzas are also never restored
with a compensating POST. Splunk exposes no verified conditional update
contract, so a guard GET followed by an unconditional restore can overwrite an
edit made in between. The runner reads current state and records `unchanged`
only when touched values or ACL governance still match their prestate;
otherwise it preserves mode-600 before/current snapshots, retains the failed
state, and sets `rollback=partial`, `partial_failure=true`, and
`manual_cleanup_required=true` in `apply-evidence.json`. Recovery guidance
requires a fresh exact live read and ownership review before manual UI/REST
reconciliation.

The SHC deployer bundle path is refused before mutation because file-based
content delivery and a live member `/acl` POST cannot form one transaction.
This skill does not stage `local.meta` or bulk content; use a reviewed,
deployer-owned app bundle through a supported SHC deployment workflow.
Knowledge object changes generally take effect after a
configuration reload; the skill prints platform-appropriate restart/reload
guidance after verified success.

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
- App/global sharing requires owner `nobody`. User sharing requires a named
  user owner and uses that owner's `/servicesNS/<owner>/<app>` namespace.
  Owners must match `[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}`; every namespace and
  app path segment is URL-encoded. Invalid or traversal-like owners fail before
  render and authentication.
- App names must begin with an alphanumeric character. Exact `.`/`..` values
  are refused for object names and automatic-lookup source types because URL
  encoding does not escape unreserved dot path segments.

## Validation

Static validation confirms the rendered conf and ACL-plan assets exist. The
setup wrapper's `--phase status` is the live validation path: it queries the
object and `/acl` endpoints (plus `props.conf` for automatic lookups), compares
them with the requested state, writes a private `live-status.json`, and exits
nonzero for missing content or governance drift.

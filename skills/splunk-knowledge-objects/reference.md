# Splunk Knowledge-Object Governance Reference

Knowledge objects (KOs) are the searchable, reusable artifacts users create on
top of indexed data: saved searches (reports and alerts), macros, lookups and
lookup definitions, eventtypes, tags, field extractions, calculated fields, and
workflow actions. Over time they sprawl across users and apps with inconsistent
sharing and ownership. This skill inventories, audits, and governs them.

## Object Model And Storage

KOs live in three places inside an app:

- `default/` — shipped configuration (never edit).
- `local/` — local overrides and user-created objects (`savedsearches.conf`,
  `macros.conf`, `transforms.conf`, `props.conf`, `eventtypes.conf`, `tags.conf`).
- `metadata/` — `default.meta` and `local.meta` control sharing (`export`),
  read/write access, and `owner`.

Sharing levels:

- `user` (private) — visible only to the owner.
- `app` — visible to everyone in the app (`export = none` scoped to app).
- `global` — visible across all apps (`export = system`).

## Inventory

`inventory.sh` enumerates each object type via REST with app, owner, sharing,
and disabled state. Endpoints used:

- Saved searches: `/servicesNS/-/-/saved/searches`
- Macros: `/servicesNS/-/-/admin/macros`
- Lookup definitions: `/servicesNS/-/-/data/transforms/lookups`
- Lookup table files: `/servicesNS/-/-/data/lookup-table-files`
- Eventtypes: `/servicesNS/-/-/saved/eventtypes`
- Tags: `/servicesNS/-/-/configs/conf-tags`
- Field extractions: `/servicesNS/-/-/data/props/extractions`

The `-/-` namespace returns objects across all users and apps that the running
user can see (requires broad read; `admin_all_objects` for full visibility).

## Governance Findings (audit.sh)

- **Orphaned owners** — private objects whose owner no longer exists. They keep
  running scheduled jobs but cannot be edited in the UI. Reassign to a service
  account or share at app level.
- **Private scheduled searches** — enabled, scheduled, and `sharing=user`. These
  run as an individual and break when that user leaves. Move to app sharing under
  a service owner.
- **Lookup files without definitions** — a CSV exists with no `transforms.conf`
  definition, so it is not usable as a `lookup`. Add the definition.
- **Disabled saved searches** — candidates for cleanup or re-enablement.

Extend the audit with your own checks (for example, world-writable `write : [ * ]`
ACLs, duplicated report names, or expensive `cron_schedule` concentration).

## Lookups

A working lookup needs:

1. A lookup table file (CSV under `lookups/`) or external/KV-store source.
2. A lookup definition in `transforms.conf` (`[name]` with `filename =` or
   `external_cmd =`, or `collection =` for KV Store lookups).
3. Optionally an automatic lookup in `props.conf`
   (`LOOKUP-<class> = <name> <input> OUTPUT <output>`).

KV Store-backed lookups depend on the KV Store; see `splunk-kvstore-admin` for
KV Store backup/restore. CSV lookups are replicated by the bundle/deployer.

## Applying Governed Objects And Metadata

`apply.sh` stages the rendered `savedsearches.conf`, `macros.conf`,
`transforms.conf`, and `local.meta` into `etc/apps/<app>/{local,metadata}` and
reloads. Reloading conf endpoints avoids a full restart for most KO changes;
metadata changes may require a restart or deployer push to take full effect.

On a search head cluster, do not edit member apps directly. Stage governed
content into the deployer's `shcluster/apps/<app>` and push the bundle
(`splunk-search-head-cluster-setup`).

## Reassigning Ownership

`reassign.sh <acl-endpoint>` POSTs to an object's ACL endpoint to change `owner`
and `sharing`. Find the endpoint from `inventory.sh` and append `/acl`, for
example:

```
servicesNS/nobody/search/saved/searches/My%20Report/acl
```

Reassignment requires `admin_all_objects` (or ownership). It is gated behind a
typed `REASSIGN` confirmation. Reassign orphaned and risky private objects to a
managed service account and share at the app level.

## Out Of Scope

- CIM data model acceleration (see `splunk-cim-data-model`).
- Dashboards / views authoring (see `splunk-dashboard-studio`).
- Roles and capabilities (see `splunk-enterprise-security-config` for ES roles,
  `splunk-cloud-acs-admin-setup` for Cloud roles/capabilities).
- Ingest-time field work and routing (see `splunk-ingest-actions`,
  `splunk-spl2-pipeline-kit`).

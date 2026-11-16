# SCAN package review — 2026-11-16

Source: [listing 8566](https://splunkbase.splunk.com/app/8566),
[release API](https://splunkbase.splunk.com/api/v1/app/8566/release/).
Listing default: **1.0.50**, November 9, 2026. Selected repository pin:
**1.0.30**, deliberately unchanged. This is static package inspection, not
live Splunk validation or adoption approval.

The repository's download-only helper obtained
`splunk-cisco-app-navigator-scan_1050.tar.gz`; the safe extractor validated
184 members and package identity `splunk-cisco-app-navigator` / launcher
version `1.0.50`. Binary SHA-256:
`8a1c7c007be05f097950384526393419422ebefbd7adcf32dd0939a79f782022`.
Archive and extraction remain in the ignored `splunk-ta/` cache.

Inspected `default/app.conf`, `commands.conf`, `restmap.conf`,
`savedsearches.conf`, `products.conf`, `transforms.conf`, `distsearch.conf`,
`server.conf`, `metadata/default.meta`, shipped views and the two command
implementations in `bin/`:

- Four views: `ecosystem_intelligence`, `cisco_glass_pane`, `products`,
  `user_guide`; app visibility enabled. There are 42 saved searches and
  94 product stanzas. No `default/inputs.conf` or `default/macros.conf` ships.
  This is a search-tier catalog application, with no event-ingestion account,
  modular input, sourcetype, CIM model, or event index to configure.
- Both `synccatalog` and `synclookup` declare `python.required = 3.13`.
  Listing compatibility is insufficient to prove this runtime exists on a
  particular Enterprise or Cloud search tier. Keep the selected pin until
  runtime availability and command execution are independently qualified.
- The `products` REST endpoint requires `search` to read and
  `admin_all_objects` to write. App metadata allows writes by `admin`,
  `sc_admin`, and `power`; endpoint capability checks remain separate.
  Lookup export is app-local (`export = none`), despite an outdated package
  comment suggesting global export.
- The daily `SCAN - Splunkbase Catalog Sync` search runs at `39 3 * * *`,
  invoking `synccatalog dryrun=false` followed by lookup refresh. Both commands
  fetch public HTTPS content from `is4s.s3.amazonaws.com`; there is no vendor
  API account. `synclookup` overwrites its destination lookup.
- `synccatalog` requires an explicit `dryrun` Boolean, compares catalog
  timestamps and `min_app_version`, backs up the old file, then writes and
  reloads the configuration. A reload failure produces `Partial Success`;
  the repository setup already rejects that status. File update and reload
  are separate operations, so recovery still requires operator review.
- `server.conf` replicates `products` and `splunk_create` configurations;
  the large lookup remains on the replication denylist. Qualify lookup
  availability on each search-head cluster member. Enterprise deployer and
  Cloud ACS delivery/approval remain distinct paths.

The repository's pinned SCAN product fixture and sourcetype reconciliation
were not refreshed from this archive: approving a package does not approve
all product-catalog changes. The new `validate.sh --completion` mode checks
the four views and a nonempty dashboard lookup and makes prerequisite
warnings blocking. Final handoff still requires opening the views and
retaining evidence that their searches return useful catalog results.

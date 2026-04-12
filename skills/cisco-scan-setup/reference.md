# Splunk Cisco App Navigator (SCAN) — Reference

Complete reference for **Splunk Cisco App Navigator** (`splunk-cisco-app-navigator`),
covering catalog structure, sync commands, saved searches, dashboards, and
operational notes.

## App Identity

| Item | Value |
|---|---|
| App name | `splunk-cisco-app-navigator` |
| Splunkbase listing | Not available — install from local package |
| Install source | `splunk-ta/splunk-cisco-app-navigator-scan_*.tar.gz` |
| Cloud install | ACS private app upload |
| Catalog size | 93+ Cisco product entries |
| Saved searches | 42+ catalog analysis and gap detection searches |

## Catalog Structure (`products.conf`)

Each Cisco product is a stanza in `products.conf`:

```ini
[<Product Name>]
product_name = <display name>
product_family = <family>
splunkbase_app_id = <id or empty>
ta_name = <app internal name>
data_collection_method = <REST|syslog|netflow|…>
documentation_url = <url>
min_app_version = <version>
```

Key fields used by SCAN features:

| Field | Description |
|-------|-------------|
| `product_name` | Canonical display name |
| `product_family` | Product family (Catalyst, Security, etc.) |
| `splunkbase_app_id` | Splunkbase ID if a TA/app exists; empty if gap |
| `ta_name` | Internal app name matching the installed app folder |
| `data_collection_method` | How data is collected |
| `min_app_version` | Minimum SCAN version required for this entry |

## Catalog Sync

SCAN fetches updates from a public S3 bucket: `is4s.s3.amazonaws.com`.

### Commands

| Command | Purpose |
|---|---|
| `synccatalog dryrun=false` | Sync `products.conf` from S3 |
| `synccatalog dryrun=true` | Validate sync without writing |
| `synclookup` | Sync `scan_splunkbase_apps.csv.gz` from S3 |

Both commands require outbound HTTPS to `is4s.s3.amazonaws.com`. If the search
head cannot reach S3, the app continues to function using its bundled catalog.

### Sync via Script

```bash
bash skills/cisco-scan-setup/scripts/setup.sh --sync
```

This runs both `synccatalog dryrun=false` and `synclookup` via the Splunk REST
API dispatch endpoint.

### Automated Sync

SCAN includes a scheduled search (`scan_catalog_sync`) that runs daily. Manual
sync is only needed for immediate freshness.

## Saved Searches (42+)

Categories:

| Category | Examples |
|---|---|
| Catalog analysis | `scan_product_count`, `scan_family_breakdown` |
| Gap detection | `scan_gaps_no_ta`, `scan_gaps_no_splunkbase` |
| Compatibility | `scan_compat_cloud`, `scan_compat_uf` |
| Migration | `scan_legacy_apps`, `scan_migration_candidates` |
| Installed app detection | `scan_installed_overlap`, `scan_missing_deployed` |
| Data flow validation | `scan_data_flow_check` |
| Legacy debt | `scan_legacy_debt_audit` |

All saved searches are in `savedsearches.conf` and can be run via Splunk Web
or the REST API.

## Dashboards

| Dashboard | Type | Description |
|---|---|---|
| Ecosystem Intelligence | Dashboard Studio | Analytics and catalog overview; requires data in Splunk |

The Ecosystem Intelligence dashboard is a Dashboard Studio view. It is
included in the app package and appears in Splunk Web automatically after
installation. No macro setup or index wiring is required — SCAN does not
collect data and does not need index configuration.

To view the dashboard, navigate to **Apps → Splunk Cisco App Navigator** in
Splunk Web after installation.

## SHC Replication

`server.conf` includes `products` in the SHC conf replication stanza so
catalog changes propagate across SHC members.

`distsearch.conf` excludes `scan_splunkbase_apps.csv.gz` from search-head
replication because the file is large. Each SHC member should run
`synclookup` independently, or rely on the daily scheduled search.

## Platform Notes

| Platform | Install Method | Post-Install |
|---|---|---|
| Splunk Enterprise | `install_app.sh --source local` | Run `setup.sh`, optionally `--sync` |
| Splunk Cloud | ACS private app upload | Run `setup.sh` for post-install verification |

SCAN does not create indexes, configure data inputs, or require ACS index
management. The ACS step for Cloud is only the app upload.

## REST API Endpoints Used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/services/search/jobs` | Run `synccatalog` and `synclookup` commands |
| GET | `/services/apps/local/splunk-cisco-app-navigator` | Verify app installation |
| GET | `/services/configs/conf-products` | Verify catalog stanza count |
| GET | `/services/saved/searches` | Verify saved search presence |

## Known Limitations

- `synccatalog` requires the `dryrun` argument; omitting it causes a Python error.
- If the installed SCAN version is below `min_app_version` in S3's catalog,
  `synccatalog` skips the update. Upgrade the app first.
- `synclookup` is not atomic: a failure after write but before reload leaves
  the CSV updated on disk without Splunk reloading it. Re-run `synclookup`
  or POST to the app's `_reload` endpoint to recover.

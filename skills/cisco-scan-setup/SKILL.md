---
name: cisco-scan-setup
description: >-
  Automate Splunk Cisco App Navigator (SCAN) setup and validation. Installs
  the splunk-cisco-app-navigator app from a local package, verifies the
  product catalog and Splunkbase lookup, triggers catalog sync from S3,
  and validates the deployment. Use when the user asks about SCAN, Cisco
  App Navigator, product catalog, ecosystem intelligence, or
  splunk-cisco-app-navigator setup in Splunk.
---

# Splunk Cisco App Navigator (SCAN) Setup Automation

Automates the **Splunk Cisco App Navigator** (`splunk-cisco-app-navigator`).

SCAN is a management and catalog app, not a data-ingestion TA. It provides a
unified product catalog UI for 93+ Cisco products, ecosystem intelligence
dashboards, and 42+ saved searches for catalog analysis. It does **not** create
indexes, configure data inputs, or require vendor-specific credentials.

## Package Model

**Splunkbase is the public install source; `splunk-ta/` is the local cache
for offline installs and product-catalog builds.** SCAN is listed on
Splunkbase as app ID `8566`. Use `splunk-app-install` with the Splunkbase ID
when a fresh download or public Cloud install is available:

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source splunkbase --app-id 8566
```

For offline Enterprise installs or private review copies, place the downloaded
package in `splunk-ta/` and run this skill's `setup.sh`; it installs the newest
matching local package. The product repo's `cisco-product-setup` catalog is
also generated from the newest local SCAN tarball, using the embedded
`default/app.conf` app version when cached filenames do not include a dotted
version.

For Splunk Cloud (ACS), prefer the Splunkbase install path. Use private app
upload only for pre-vetted local packages. After installation, use this skill
to verify the catalog, run the initial sync, and validate the deployment.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, API keys, or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials` file
(falls back to `~/.splunk/credentials`). If neither exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

SCAN requires **no vendor-specific secrets**. The S3 bucket used for catalog sync
(`is4s.s3.amazonaws.com`) is publicly readable. The only credentials needed are
for the Splunk management REST API.

## Environment

Setup and validation use the Splunk search-tier REST API and can run from any
host with network access to the Splunk management port (`8089`). Catalog sync
requires outbound HTTPS to `is4s.s3.amazonaws.com`.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs (`SPLUNK_PLATFORM` is only an override for hybrid runs) |
| App name | `splunk-cisco-app-navigator` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-scan-setup/scripts/` (relative to repo root) |

### Remote Splunk Connection

To run against a remote Splunk instance:

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

## Splunk Authentication

Scripts read Splunk credentials from the project-root `credentials` file (falls back to `~/.splunk/credentials`) automatically.
No environment variables or command-line password arguments are needed:

```bash
bash skills/cisco-scan-setup/scripts/validate.sh
```

If credentials are not yet configured, run the setup script first:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

## Setup Workflow

SCAN is a catalog app with no indexes, no data inputs, and no account
configuration. Setup is simpler than typical data-ingestion TAs.

### Step 1: Install App

```bash
bash skills/cisco-scan-setup/scripts/setup.sh
```

Installs the app from `splunk-ta/`, verifies it is visible in Splunk Web,
and confirms the product catalog loads via REST.

For Splunk Cloud, install the package as a private app through ACS first,
then run setup.sh for post-install verification.

### Step 2: Initial Catalog Sync (Optional)

To trigger an immediate sync of products.conf and the Splunkbase lookup
from S3 (requires outbound HTTPS to `is4s.s3.amazonaws.com`):

```bash
bash skills/cisco-scan-setup/scripts/setup.sh --sync
```

This runs `| synccatalog dryrun=false` and `| synclookup` via the Splunk
REST API. Without `--sync`, the app's daily scheduled search handles
this automatically.

### Step 3: Validate

```bash
bash skills/cisco-scan-setup/scripts/validate.sh
```

Checks: app installation, app version, product catalog stanza count,
Splunkbase lookup, S3 sync connectivity, saved searches, and scheduled
sync job status.

## Key Components

| Component | Description |
|-----------|-------------|
| `products.conf` | Product catalog with 93+ Cisco product stanzas |
| `scan_splunkbase_apps.csv.gz` | Synced Splunkbase ecosystem lookup |
| `synccatalog` | Custom search command: syncs products.conf from S3 |
| `synclookup` | Custom search command: syncs Splunkbase CSV from S3 |
| 42+ saved searches | Catalog analysis, gap analysis, compatibility, migration |
| Ecosystem Intelligence | Dashboard Studio analytics dashboard |

## Dashboard

The **Ecosystem Intelligence** dashboard is a Dashboard Studio view included in
the package. It appears in Splunk Web automatically after installation — no
import or manual activation step is needed.

To access it: **Apps → Splunk Cisco App Navigator → Ecosystem Intelligence**

SCAN does not collect data, so the dashboard visualizes catalog metadata
rather than time-series events. It does not require index configuration or
data input enablement.

If the dashboard appears blank after installation, trigger an initial catalog
sync:

```bash
bash skills/cisco-scan-setup/scripts/setup.sh --sync
```

On **Splunk Cloud**, the dashboard is available immediately after the ACS
private app upload completes.

## Key Learnings / Known Issues

1. **No indexes or inputs**: SCAN is a catalog/management app. It does not
   create indexes, configure data inputs, or ingest data. This makes setup
   significantly simpler than other Cisco TAs.
2. **S3 outbound connectivity**: The `synccatalog` and `synclookup` commands
   require HTTPS access to `is4s.s3.amazonaws.com`. If the search head cannot
   reach S3, catalog sync will fail but the app still functions with its
   shipped default catalog.
3. **synccatalog dryrun is required**: Despite `searchbnf.conf` marking
   `dryrun` as optional, the Python command yields an error event and exits
   early if `dryrun` is omitted, producing no useful output.
   Always pass `dryrun=true` or `dryrun=false` explicitly.
4. **min_app_version gating**: The S3 products.conf may include a
   `min_app_version` header. If the installed app version is below this
   threshold, `synccatalog` skips the update. Upgrade the app first.
5. **SHC replication**: `server.conf` includes `products` in SHC conf
   replication so catalog updates propagate across cluster members.
6. **Lookup replication denied**: `distsearch.conf` excludes the large
   `scan_splunkbase_apps.csv.gz` from search-head replication. Each SHC
   member must run `synclookup` independently (or use the scheduled search).
7. **Splunkbase listing available**: SCAN is Splunkbase app ID `8566`. Keep a
   local package in `splunk-ta/` when you need offline Enterprise installs or
   to regenerate the product repo catalog from a reviewed package.
8. **Restart behavior**: SCAN does not create indexes, so a restart is
   typically only needed if Splunk requires one after app installation.
9. **Non-atomic sync**: `synccatalog` writes the file before reloading.
   A failure after write but before reload leaves the file updated on disk
   without Splunk seeing the changes. POST to the `_reload` endpoint
   (`/services/configs/conf-products/_reload`) to force Splunk to pick up
   the already-written file. Run `| synccatalog dryrun=true` separately to
   diagnose version state, not to trigger a reload.
10. **cisco-product-setup dependency**: The `cisco-product-setup` skill
    reads the SCAN tarball at build-time to generate `catalog.json`. At
    runtime, live SCAN features (installed app detection, data flow
    validation, legacy debt auditing) require the app to be installed.

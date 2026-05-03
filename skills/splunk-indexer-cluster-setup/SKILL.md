---
name: splunk-indexer-cluster-setup
description: >-
  Render, preflight, apply, validate, and operate Splunk Enterprise indexer
  clusters end-to-end: single-site multi-host bootstrap, multisite bootstrap
  (per-site explicit factors, site_mappings, search affinity), cluster manager
  redundancy (active/standby with manager_switchover_mode + LB or DNS),
  configuration bundle (validate / status / apply / rollback / skip-validation),
  rolling restart (default 10%, searchable with health checks, searchable
  forced), fast and enforce-counts peer offline, peer removal from manager
  list, maintenance mode, single-site to multisite migration, decommission a
  site, move a peer to a new site, migrate a non-clustered indexer into the
  cluster, pass4SymmKey rotation, manager DR backup, and forwarder
  indexer-discovery output snippets. Use when the user asks to bootstrap an
  indexer cluster, multisite cluster, configure site_replication_factor /
  site_search_factor, apply or rollback a cluster bundle, perform a rolling
  restart, take a peer offline, migrate single-site to multisite, or run
  cluster manager redundancy.
---

# Splunk Indexer Cluster Setup

This skill sits **above**
[`skills/splunk-enterprise-host-setup`](../../skills/splunk-enterprise-host-setup/SKILL.md),
which still owns per-host install/upgrade. It owns multi-host orchestration of
the cluster control plane and every documented cluster operation.

## Architecture First

- The host-setup skill installs Splunk Enterprise per host. This skill
  configures those installed hosts as a coordinated cluster (single-site or
  multisite).
- Cluster manager redundancy uses two or more managers in active/standby; the
  skill renders the LB + DNS recipes per Splunk's documented patterns.
- Multisite migration keeps both legacy `replication_factor`/`search_factor`
  AND the new `site_*` factors so existing buckets remain valid.

## Agent Behavior — Credentials

Never paste secrets into chat.

- Use `template.example` for the non-secret intake worksheet (manager URI,
  peer/SH lists, factors, sites).
- Keep secrets in temporary files only:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_admin_password
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_idxc_secret
```

The cluster `pass4SymmKey` is distinct from the license manager
`pass4SymmKey` and any SHC `pass4SymmKey`.

## Quick Start

Single-site bootstrap (3 peers, 1 SH, 1 manager):

```bash
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
  --phase render \
  --cluster-mode single-site \
  --cluster-label prod \
  --cluster-manager-uri https://cm01.example.com:8089 \
  --manager-hosts cm01.example.com \
  --replication-factor 3 \
  --search-factor 2 \
  --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
  --sh-hosts sh01.example.com
```

Multisite bootstrap with explicit per-site factors:

```bash
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
  --phase render \
  --cluster-mode multisite \
  --cluster-label prod \
  --cluster-manager-uri https://cm01.example.com:8089 \
  --manager-hosts cm01.example.com \
  --available-sites site1,site2 \
  --site-replication-factor "origin:2,total:3" \
  --site-search-factor "origin:1,total:2" \
  --peer-hosts "idx01.example.com=site1,idx02.example.com=site2" \
  --sh-hosts "sh01.example.com=site1"
```

Apply a cluster bundle (validates, then applies):

```bash
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
  --phase bundle-apply \
  --cluster-manager-uri https://cm01.example.com:8089 \
  --admin-password-file /tmp/splunk_admin_password
```

Searchable rolling restart with health check:

```bash
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
  --phase rolling-restart \
  --rolling-restart-mode searchable \
  --cluster-manager-uri https://cm01.example.com:8089 \
  --admin-password-file /tmp/splunk_admin_password
```

Take a peer offline (fast):

```bash
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
  --phase peer-offline \
  --peer-offline-mode fast \
  --peer-host idx02.example.com \
  --admin-password-file /tmp/splunk_admin_password
```

Migrate a single-site cluster to multisite:

```bash
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
  --phase migrate-to-multisite \
  --cluster-manager-uri https://cm01.example.com:8089 \
  --available-sites site1,site2 \
  --site-replication-factor "origin:2,total:3" \
  --site-search-factor "origin:1,total:2" \
  --site-mappings "default_mapping:site1"
```

Run targeted migration/recovery operations through the wrapper:

```bash
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
  --phase replace-manager \
  --cluster-manager-uri https://cm01.example.com:8089 \
  --new-manager-uri https://cm02.example.com:8089 \
  --idxc-secret-file /tmp/splunk_idxc_secret \
  --admin-password-file /tmp/splunk_admin_password

bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
  --phase decommission-site \
  --cluster-manager-uri https://cm01.example.com:8089 \
  --site site2 \
  --admin-password-file /tmp/splunk_admin_password

bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
  --phase move-peer-to-site \
  --cluster-manager-uri https://cm01.example.com:8089 \
  --peer-host idx02.example.com \
  --new-site site2 \
  --admin-password-file /tmp/splunk_admin_password

bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
  --phase migrate-non-clustered \
  --cluster-manager-uri https://cm01.example.com:8089 \
  --indexer-host idx03.example.com \
  --idxc-secret-file /tmp/splunk_idxc_secret \
  --admin-password-file /tmp/splunk_admin_password
```

## What It Renders

Under `splunk-indexer-cluster-rendered/cluster/`:

- `manager/<host>/server.conf` — primary + (optional) standby manager configs.
- `peer-<host>/server.conf` — per-peer config with site assignment.
- `sh-<host>/server.conf` — per-SH config with multisite/affinity.
- `bootstrap/sequenced-bootstrap.sh` — manager → peers (RF gate) → SHs.
- `bundle/{validate.sh, status.sh, apply.sh, apply-skip-validation.sh, rollback.sh}`.
- `restart/{rolling-restart.sh, searchable-rolling-restart.sh, force-searchable.sh}`.
- `maintenance/{enable.sh, disable.sh}`.
- `peer-ops/{offline-fast.sh, offline-enforce-counts.sh, remove-peer.sh, extend-restart-timeout.sh}`.
- `redundancy/{lb-haproxy.cfg, dns-record-template.txt, ha-health-check.sh}` (when redundancy enabled).
- `migration/{single-to-multisite.sh, replace-manager.sh, decommission-site.sh, move-peer-to-site.sh, migrate-non-clustered.sh}`.
- `forwarder-outputs/<host>/outputs.conf` — indexer-discovery snippets for HF/UF.
- `validate.sh` — `splunk show cluster-status --verbose`, REST `/services/cluster/manager/health`, peer count vs. RF, bundle status, version compat.

## Hand-off Contracts

- Assumes hosts are installed by `splunk-enterprise-host-setup --phase install`.
- Emits a `LICENSE_PEERS[]` stub at `splunk-indexer-cluster-rendered/cluster/handoffs/license-peers.txt` so `splunk-license-manager-setup` can wire up the license peer config.
- Warns when bundle apps include SmartStore-aware files and points to
  [`skills/splunk-index-lifecycle-smartstore-setup`](../../skills/splunk-index-lifecycle-smartstore-setup/SKILL.md) for `indexes.conf` rendering.

## References

- [reference.md](reference.md) for full multisite semantics, redundancy
  topologies, bundle reload-vs-restart classification, and rolling-restart
  health-check details.
- [template.example](template.example) for the non-secret intake worksheet.

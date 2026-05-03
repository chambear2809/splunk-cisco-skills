# Splunk Indexer Cluster Reference

## Research Basis

- Single-site cluster: manager has `[clustering] mode=manager replication_factor=N search_factor=M pass4SymmKey=...`; peers have `[general]` (no `site`) and `[clustering] mode=peer manager_uri=...`.
- Multisite cluster: manager adds `multisite=true`, `available_sites=site1,...`, `site_replication_factor=origin:N,total:M` (or per-site explicit `origin:1,site1:2,site2:2,total:5`), `site_search_factor=origin:N,total:M`. Each peer has `[general] site=siteN`. Each SH has `[general] site=siteN` and `[clustering] multisite=true`. SH `site=site0` disables affinity.
- Site-mappings: `[clustering] site_mappings = default_mapping:siteN` routes legacy buckets to a chosen site during single-to-multisite migration.
- Cluster manager redundancy: `manager_switchover_mode=auto|manual` on every manager; multi-manager `[clustermanager:cmN] manager_uri=...` priority list; LB hits `/services/cluster/manager/ha_active_status` (200=active, 503=standby).
- Bundle: stage apps in `$SPLUNK_HOME/etc/manager-apps/`; `splunk validate cluster-bundle [--check-restart]`, `splunk show cluster-bundle-status`, `splunk apply cluster-bundle [--skip-validation] [--answer-yes]`, `splunk rollback cluster-bundle`.
- Rolling restart: `splunk rolling-restart cluster-peers` (default 10%); `-searchable true` requires SF met + all-data-searchable + no-fixup; `-force true` overrides health checks; `restart_inactivity_timeout` and `decommission_force_timeout` tune timing.
- Peer offline:
  - Fast: `splunk offline [--decommission_node_force_timeout <s>]` returns cluster to valid state, not complete.
  - Permanent: `splunk offline --enforce-counts` regains valid + complete; preconditions: peers ≥ RF+1, multisite per-site preconditions, no maintenance mode.
- Remove offline peer from manager list: `splunk remove cluster-peers -peers <guid> -auth ...`.
- Maintenance mode: `splunk enable maintenance-mode` / `splunk disable maintenance-mode` on manager (suppresses bucket fixup).
- Inspect: `splunk show cluster-status --verbose`, `splunk list cluster-peers`, `splunk list cluster-config`, `splunk show cluster-buckets`, `splunk show cluster-bucket-fixup`, `splunk show cluster-generation`.
- REST: `/services/cluster/manager/info`, `/health`, `/peers`, `/sites`, `/buckets`.
- Forwarder integration: `[indexer_discovery:<tag>] manager_uri=... pass4SymmKey=...` plus `[tcpout:<group>] indexerDiscovery=<tag>` in outputs.conf. Site-aware forwarders use `site=site0` for cross-site sending.

Official references:

- Configure multisite indexer clusters with server.conf:
  <https://help.splunk.com/en/data-management/manage-splunk-enterprise-indexers/10.2/deploy-and-configure-a-multisite-indexer-cluster/configure-multisite-indexer-clusters-with-server.conf>
- Configure multisite indexer clusters with the CLI:
  <https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.2/deploy-and-configure-a-multisite-indexer-cluster/configure-multisite-indexer-clusters-with-the-cli>
- Configure the site replication factor:
  <https://help.splunk.com/en/data-management/manage-splunk-enterprise-indexers/10.2/deploy-and-configure-a-multisite-indexer-cluster/configure-the-site-replication-factor>
- Migrate an indexer cluster from single-site to multisite:
  <https://docs.splunk.com/Documentation/Splunk/latest/Indexer/Migratetomultisite>
- Decommission a site in a multisite indexer cluster:
  <https://docs.splunk.com/Documentation/Splunk/latest/Indexer/Decommissionasite>
- Move a peer to a new site:
  <https://docs.splunk.com/Documentation/Splunk/latest/Indexer/Moveapeertoanewsite>
- Migrate non-clustered indexers to a clustered environment:
  <https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.0/deploy-the-indexer-cluster/migrate-non-clustered-indexers-to-a-clustered-environment>
- Implement cluster manager redundancy:
  <https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.2/configure-the-manager-node/implement-cluster-manager-redundancy>
- Update common peer configurations and apps (cluster bundle):
  <https://docs.splunk.com/Documentation/Splunk/9.4.1/Indexer/Updatepeerconfigurations>
- Perform a rolling restart of an indexer cluster:
  <https://docs.splunk.com/Documentation/Splunk/latest/Indexer/Userollingrestart>
- Take a peer offline:
  <https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.0/manage-the-indexer-cluster/take-a-peer-offline>
- Replace the manager node on the indexer cluster:
  <https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.2/configure-the-manager-node/replace-the-manager-node-on-the-indexer-cluster>

## Bundle Best Practices

The cluster bundle should NOT contain:

- `inputs.conf` stanzas with `[splunktcp]` / `[splunktcp-ssl]` (these are listener config, not peer-shared).
- `outputs.conf` (forwarders use their own outputs.conf; peers don't forward).
- System-level files in `etc/system/local/`.
- Anything from `etc/system/default/`.
- Per-host certificates or keys.

The rendered `bundle/validate.sh` calls `splunk validate cluster-bundle --check-restart` so the manager's own validator runs before any apply.

## Rolling Restart Modes

| Mode             | CLI flag                               | Behavior                                                                          |
|------------------|----------------------------------------|-----------------------------------------------------------------------------------|
| default          | (none)                                 | Restarts ~10% of peers at a time (configurable via `percent_peers_to_restart`).   |
| searchable       | `-searchable true`                     | Restarts peers one at a time with primary reassignment; requires SF met.          |
| searchable-force | `-searchable true -force true`         | Skips health checks; required when peers exceed `restart_inactivity_timeout`.    |
| shutdown         | `rolling_restart=shutdown` in conf     | Stages peer shutdowns; you manually restart each one.                            |

The skill writes the desired default behavior into `[clustering] rolling_restart` in `manager/server.conf` so future bundle pushes inherit it.

## Peer Offline Modes

| Mode          | CLI                                  | Cluster regains       | Use case                                |
|---------------|--------------------------------------|------------------------|-----------------------------------------|
| fast          | `splunk offline`                     | Valid state            | Brief maintenance; peer comes back fast |
| enforce-counts| `splunk offline --enforce-counts`    | Valid + complete       | Permanent removal                       |

Preconditions for `enforce-counts`:

- Total peers ≥ RF + 1 (so the cluster can rebuild missing copies).
- Multisite: each affected site continues to satisfy site_replication_factor.
- Cluster is NOT in maintenance mode (bucket fixup is suppressed during maintenance).

After a peer goes offline, it remains in the manager's peer list as `GracefulShutdown` until you run `splunk remove cluster-peers -peers <guid>`.

## Cluster Manager Redundancy Topology

```
                    +---------+         +---------+
                    | cm-1 (A)|<------->| cm-2 (S)|
                    +---------+         +---------+
                          \                  /
                           \                /
                       +-------- LB --------+
                       |   /ha_active_status |
                       +---------------------+
                            |     |     |
                          peer  peer   sh
```

- "A" = active, "S" = standby. Both managers have identical `pass4SymmKey` and `cluster_label`.
- Peers and SHs reference the LB IP/DNS, never the cluster manager IP directly.
- LB forwards to whichever manager returns 200 to `/services/cluster/manager/ha_active_status`.

## Out of Scope

- Splunk Enterprise package install/upgrade (owned by host-setup).
- SmartStore configuration (owned by `splunk-index-lifecycle-smartstore-setup`).
- TLS certificate generation (owned by host-setup at v2; this skill assumes existing certs).
- Workload Management bundle entries (owned by `splunk-workload-management-setup`).
- Federated provider configuration (owned by `splunk-federated-search-setup`).

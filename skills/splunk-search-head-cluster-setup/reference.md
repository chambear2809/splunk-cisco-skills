# Splunk Search Head Cluster Setup — Reference

## Architecture

A Splunk SHC consists of:

| Component | Role |
|-----------|------|
| **Deployer** | Pushes config bundles to members via `etc/shcluster/apps/`; NOT a member |
| **SHC Members** | Search-capable peers; each runs a full `splunkd` |
| **Captain** | Elected from members; coordinates rolling restarts, KV Store |

Minimum production topology: 1 deployer + 3 members (RF=3).

## server.conf Stanzas

### Deployer (`etc/system/local/server.conf`)

```ini
[shclustering]
disabled = false
pass4SymmKey = <secret>        # matches all members
shcluster_label = prod_shc
```

### Member (`etc/system/local/server.conf`)

```ini
[shclustering]
disabled = false
conf_deploy_fetch_url = https://deployer01:8089
shcluster_label = prod_shc
replication_factor = 3
pass4SymmKey = <secret>        # same on all members + deployer
heartbeat_timeout = 60
heartbeat_period = 5
restart_inactivity_timeout = 600

[kvstore]
disabled = false
replication_factor = 3
port = 8191
```

## Bootstrap Sequence

1. **Init all members** — `splunk init shcluster-config` on each member (can run in parallel)
2. **Bootstrap captain** — `splunk bootstrap shcluster-captain` on the first member, passing all member URIs in `--servers_list`
3. **Verify** — `splunk show shcluster-status` on any member

## Deployer Bundle Mechanics

| Path | Purpose |
|------|---------|
| `$SPLUNK_HOME/etc/shcluster/apps/` | Apps deployed to all members |
| `$SPLUNK_HOME/etc/shcluster/users/` | User-scoped objects (managed by Splunk) |

**Apply bundle**: `splunk apply shcluster-bundle -auth ...` on the **deployer**.
**Validate first**: `splunk validate shcluster-bundle` before applying.

Bundle generations: each apply increments the generation counter. Check drift with `splunk show shcluster-bundle-status`.

`--skip-validation` bypasses the bundle validator — only safe if the validator itself is broken. Gate behind `--accept-skip-validation`.

## Replication Factor

The SHC RF (typically 3) determines how many members store each search artifact. It's independent of the indexer cluster RF.

**Quorum**: N/2+1 members must be up and searchable for the SHC to be fully operational. With RF=3, losing 2 members causes degraded operation.

| Members | RF | Quorum (N/2+1) | Can lose |
|---------|----|-----------------|---------:|
| 3 | 3 | 2 | 1 |
| 5 | 3 | 3 | 2 |
| 7 | 3 | 4 | 3 |

## KV Store Replication

KV Store has its own replication factor, independent of SHC RF. It runs on port 8191 by default.

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|---------|
| Replication lag | < 1s | 1–10s | > 10s |
| Oplog utilization | < 70% | 70–90% | > 90% |

**Reset status** (`kvstore/reset-status.sh`): forces a full re-sync on the target member. Use only when replication is stuck for more than 10 minutes. Gate behind `--accept-kvstore-reset`.

## Rolling Restart Modes

| Mode | Flag | Behavior | Use When |
|------|------|----------|----------|
| Searchable | `--phase rolling-restart` | Captain waits `restart_inactivity_timeout` for each member | Default — maintains search coverage |
| Default | `--rolling-restart-mode default` | Fastest; may briefly interrupt searches | Maintenance windows |
| Forced | `--accept-force-restart` | Skips inactivity check | Emergency; rare |

**Captain transfer before restart**: Always transfer the captain to a stable member before the first restart cycle to avoid captain instability mid-restart.

## Member Operations

### Add Member

1. Install Splunk Enterprise on the new host.
2. Run `splunk init shcluster-config` with the same label, deployer URI, RF, and secret.
3. The new member joins automatically; quorum check passes when it's healthy.

### Decommission Member

1. Run graceful shutdown via REST: `POST .../control/graceful_shutdown` — moves the member to GracefulShutdown state.
2. Wait for KV Store to drain (no operations against this member).
3. Run administrative remove: `DELETE .../member/members/<uuid>`.

Never force-remove a member without graceful shutdown — you risk KV Store data loss if RF is tight.

## Enterprise Security on SHC

When deploying ES on an SHC:

- ES app bundle lives on the **deployer** under `etc/shcluster/apps/`.
- KV Store must be enabled on all members (ES uses it extensively).
- Push the ES bundle via deployer, not directly to members.
- Post-install steps (threat intelligence, UEBA integration) run on the **deployer**.

## REST API Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/services/shcluster/captain/info` | GET | Captain identity, peers, status |
| `/services/shcluster/captain/peers` | GET | All members + status |
| `/services/shcluster/captain/control/control/restart_inactivity_timeout` | POST | Trigger rolling restart |
| `/services/shcluster/captain/control/control/transfer-captain` | POST | Transfer captain |
| `/services/shcluster/member/members` | GET | Member list |
| `/services/shcluster/member/members/<uuid>/control/control/graceful_shutdown` | POST | Graceful decommission |
| `/services/kvstore/status` | GET | KV Store replication status |
| `/services/kvstore/control/control/reset` | POST | Force KV Store re-sync (dangerous) |

## CLI Quick Reference

```bash
# Show SHC status
splunk show shcluster-status --verbose

# List members
splunk list shcluster-members

# Show bundle status
splunk show shcluster-bundle-status

# Show KV Store status
splunk show kvstore-status

# Bootstrap (run once on first captain)
splunk bootstrap shcluster-captain \
  -auth admin:<pass> \
  -servers_list "https://sh01:8089,https://sh02:8089,https://sh03:8089"

# Apply bundle (run on deployer)
splunk apply shcluster-bundle -auth admin:<pass> --answer-yes

# Transfer captain
splunk transfer shcluster-captain \
  -mgmt_uri https://sh02:8089
```

## Failure Mode Quick Reference

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Two captains seen | Split-brain / network partition | Restore network; older captain steps down on heartbeat |
| Search degraded, no quorum | Members down | Bring members back online |
| Bundle push fails | Validator error | Check deployer log; use `apply-skip-validation.sh` only as last resort |
| Captain crash loop | Corrupt state | Transfer captain to stable member; check `splunkd.log` |
| KV Store stuck | Oplog lag > threshold | Run `kvstore/reset-status.sh` on lagging member |

## Hand-Off Contracts

| Skill | What It Provides | What SHC Skill Consumes |
|-------|-----------------|------------------------|
| `splunk-enterprise-host-setup` | Splunk Enterprise binaries, `server.conf` base | Host must exist before SHC bootstrap |
| `splunk-enterprise-security-install` | ES bundle on deployer | Deployer URI, SHC label |
| `splunk-license-manager-setup` | License peer wiring | Member URIs |
| `splunk-platform-pki-setup` | TLS for KV Store (dual-EKU), S2S, replication port 9887 | Cert paths |
| `splunk-platform-restart-orchestrator` | Restart execution | Rolling restart phase |
| `splunk-monitoring-console-setup` | SHC peer registration | Member + deployer URIs |

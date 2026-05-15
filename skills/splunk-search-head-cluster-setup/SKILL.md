---
name: splunk-search-head-cluster-setup
description: >-
  Render, preflight, apply, validate, and operate Splunk Enterprise Search Head
  Clusters end-to-end: bootstrap (deployer + N-member init + captain election),
  deployer bundle push (validate / status / apply / apply-skip-validation /
  rollback with SHA and generation-drift tracking), rolling restart (default,
  searchable with health-check loop, forced), captain transfer, member add /
  decommission / remove, KV Store replication health (lag thresholds, oplog
  reset, captain re-election), standalone-to-SHC migration, deployer
  replacement, ES-on-SHC deployer placement, and failure-mode runbooks
  (split-brain, quorum loss, deployer mismatch, captain crash loop). SHC
  pass4SymmKey is templated as `$SHC_SECRET` for operator-managed rotation
  (see Out of Scope). Use when the user asks to bootstrap an SHC, push a
  deployer bundle, perform a searchable rolling restart, transfer the captain,
  add or remove a member, troubleshoot KV Store replication lag, migrate a
  standalone search head to SHC, or replace a deployer.
---

# Splunk Search Head Cluster Setup

This skill sits **above**
[`skills/splunk-enterprise-host-setup`](../splunk-enterprise-host-setup/SKILL.md),
which still owns per-host Splunk Enterprise install and upgrade. This skill
owns multi-host SHC orchestration: the deployer, the member cluster, and the
KV Store replication tier.

## Architecture First

- A Search Head Cluster requires at least 3 members (N/2+1 quorum). The
  deployer is a separate, non-clustered Splunk Enterprise instance. Captain
  election is automatic after bootstrap; the operator can transfer the captain
  at any time via `--phase transfer-captain`.
- KV Store replication runs independently of SHC config replication. Both must
  be healthy for full cluster operation. KV Store uses `port 8191` and its own
  `replication_factor` (configurable independently of SHC RF).
- This skill DOES NOT replace the SHC deployer with an indexer cluster manager.
  If you also have an indexer cluster, use
  [`splunk-indexer-cluster-setup`](../splunk-indexer-cluster-setup/SKILL.md)
  for the indexer-side bundle; this skill owns only the SHC deployer bundle.

## Agent Behavior — Credentials

Never paste secrets into chat.

- Use `template.example` for the non-secret intake worksheet (deployer URI,
  member URIs, SHC label, RF, KV Store RF, ES placement toggle).
- Keep secrets in temporary files only:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_admin_password
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_shc_secret
```

The SHC `pass4SymmKey` (`$SHC_SECRET`) is distinct from the indexer cluster
`$IDXC_SECRET` and the license manager `pass4SymmKey`.

## Quick Start

Bootstrap a 3-member SHC (deployer + 3 members):

```bash
bash skills/splunk-search-head-cluster-setup/scripts/setup.sh \
  --phase render \
  --shc-label prod_shc \
  --deployer-host deployer01.example.com \
  --member-hosts sh01.example.com,sh02.example.com,sh03.example.com \
  --replication-factor 3 \
  --kvstore-replication-factor 3
```

Push the deployer bundle (validates, then applies):

```bash
bash skills/splunk-search-head-cluster-setup/scripts/setup.sh \
  --phase bundle-apply \
  --deployer-host deployer01.example.com \
  --admin-password-file /tmp/splunk_admin_password
```

Searchable rolling restart with health-check loop:

```bash
bash skills/splunk-search-head-cluster-setup/scripts/setup.sh \
  --phase rolling-restart \
  --rolling-restart-mode searchable \
  --deployer-host deployer01.example.com \
  --admin-password-file /tmp/splunk_admin_password
```

Transfer the SHC captain:

```bash
bash skills/splunk-search-head-cluster-setup/scripts/setup.sh \
  --phase transfer-captain \
  --captain-uri https://sh01.example.com:8089 \
  --target-captain-uri https://sh02.example.com:8089 \
  --admin-password-file /tmp/splunk_admin_password
```

Add a new member to an existing SHC:

```bash
bash skills/splunk-search-head-cluster-setup/scripts/setup.sh \
  --phase add-member \
  --deployer-host deployer01.example.com \
  --new-member-host sh04.example.com \
  --shc-secret-file /tmp/splunk_shc_secret \
  --admin-password-file /tmp/splunk_admin_password
```

Decommission a member from the SHC:

```bash
bash skills/splunk-search-head-cluster-setup/scripts/setup.sh \
  --phase decommission-member \
  --captain-uri https://sh01.example.com:8089 \
  --member-host sh04.example.com \
  --admin-password-file /tmp/splunk_admin_password
```

Check KV Store replication status:

```bash
bash skills/splunk-search-head-cluster-setup/scripts/setup.sh \
  --phase kvstore-status \
  --captain-uri https://sh01.example.com:8089 \
  --admin-password-file /tmp/splunk_admin_password
```

Migrate a standalone search head to SHC:

```bash
bash skills/splunk-search-head-cluster-setup/scripts/setup.sh \
  --phase migrate-standalone-to-shc \
  --existing-sh-host sh01.example.com \
  --deployer-host deployer01.example.com \
  --additional-member-hosts sh02.example.com,sh03.example.com \
  --shc-label prod_shc \
  --shc-secret-file /tmp/splunk_shc_secret \
  --admin-password-file /tmp/splunk_admin_password
```

## What It Renders

Under `splunk-search-head-cluster-rendered/shc/`:

- `deployer/server.conf` — deployer `[shclustering]` stanza with
  `disabled=false`, `conf_deploy_fetch_url` pointing to self, and
  `pass4SymmKey = $SHC_SECRET`.
- `member-<host>/server.conf` — per-member `[shclustering]` with
  `conf_deploy_fetch_url`, `shcluster_label`, `replication_factor`,
  `pass4SymmKey = $SHC_SECRET`; and `[kvstore]` with `disabled=false`,
  `replication_factor`.
- `bootstrap/sequenced-bootstrap.sh` — ordered init: deployer enable →
  member `init shcluster-config` (parallel, one per member) →
  `bootstrap-shcluster-captain` on designated first captain →
  quorum-wait loop.
- `bundle/{validate.sh, status.sh, apply.sh, apply-skip-validation.sh, rollback.sh}`.
- `restart/{rolling-restart.sh, searchable-rolling-restart.sh,
  force-searchable.sh, transfer-captain.sh}`.
- `members/{add-member.sh, decommission-member.sh, remove-member.sh}`.
- `kvstore/{status.sh, reset-status.sh}`.
- `migration/{standalone-to-shc.sh, replace-deployer.sh}`.
- `runbook-failure-modes.md` — split-brain, quorum loss, deployer mismatch,
  captain crash loop.
- `validate.sh` — `splunk show shcluster-status --verbose`, REST member count
  check, KV Store quorum check, bundle generation drift check.
- `handoffs/{license-peers.txt, es-deployer.txt, monitoring-console.txt}`.
- `preflight-report.md` — per-phase preflight verdict (member count vs RF,
  Splunk version skew, KV Store quorum, deployer reachability).

## Phases

| Phase | Purpose |
|-------|---------|
| `render` | Produce all config and script assets; no live changes. |
| `preflight` | Check quorum math, version skew, deployer reachability. |
| `bootstrap` | Run `bootstrap/sequenced-bootstrap.sh` on all hosts. |
| `bundle-validate` | `splunk validate shcluster-bundle` on deployer. |
| `bundle-status` | Show per-member bundle generation and SHA. |
| `bundle-apply` | Validate then `apply shcluster-bundle`; rolling by default. |
| `bundle-apply-skip-validation` | Bypass bundle validator (requires `--accept-skip-validation`). |
| `bundle-rollback` | Restore previous bundle from `$SPLUNK_HOME/etc/shcluster-deploy-apps/`. |
| `rolling-restart` | Restart members one at a time while maintaining search capability. |
| `transfer-captain` | `splunk transfer-shcluster-captain` to target member. |
| `add-member` | Non-disruptive join with quorum preflight. |
| `decommission-member` | Graceful decommission → `GracefulShutdown`. |
| `remove-member` | Administrative removal after decommission. |
| `kvstore-status` | `splunk show kvstore-status` + lag assessment on all members. |
| `kvstore-reset` | `splunk kvstore reset-status` on a stalled member (requires `--accept-kvstore-reset`). |
| `replace-deployer` | Migrate the cluster to a new deployer instance. |
| `migrate-standalone-to-shc` | Convert a running standalone SH into an SHC member. |
| `status` | `splunk show shcluster-status --verbose` formatted snapshot. |
| `validate` | Static + (with `--live`) live REST health check. |

## Configuration Deep-dive

**`server.conf [shclustering]` (per-member):**

```ini
[shclustering]
disabled = false
conf_deploy_fetch_url = https://deployer01.example.com:8089
shcluster_label = prod_shc
replication_factor = 3
pass4SymmKey = $SHC_SECRET
heartbeat_timeout = 60
heartbeat_period = 5
restart_inactivity_timeout = 600
```

**`server.conf [kvstore]` (per-member):**

```ini
[kvstore]
disabled = false
replication_factor = 3
port = 8191
```

**Deployer `server.conf [shclustering]`:**

```ini
[shclustering]
disabled = false
pass4SymmKey = $SHC_SECRET
shcluster_label = prod_shc
```

The deployer does NOT set `conf_deploy_fetch_url` pointing to itself — members
do. The deployer hosts `$SPLUNK_HOME/etc/shcluster/apps/` for the bundle.

## Bundle Mechanics

- Apps for distribution live under `$SPLUNK_HOME/etc/shcluster/apps/` on the
  deployer (NOT `etc/manager-apps/` — that is the indexer cluster pattern).
- Deployer-only apps (local admin apps, ES) live under `etc/apps/` on the
  deployer and are NOT pushed to members via the bundle.
- Bundle SHA tracking prevents re-applying unchanged bundles.
- `--accept-skip-validation` is required to use `apply-skip-validation.sh`.
  Never use it without explicit operator request.
- After a bundle push, members reload changed configs without restart unless
  `app.conf [triggers]` requires a restart.
- Version skew preflight: all members must run the same Splunk version before
  bundle apply. The preflight check parses `/services/server/info` on each
  member and fails if any version differs.

## KV Store Replication

- Healthy lag: `< 1000 ms`. Warning: `1000–10000 ms`. Alarm: `> 10000 ms`.
- KV Store quorum requires N/2+1 members with healthy KV Store status.
- When KV Store quorum is lost, the cluster moves to read-only mode for KV
  Store writes; searches continue but Knowledge Object saves fail.
- `kvstore-reset` (`splunk kvstore reset-status`) clears stalled replication
  state on a specific member and forces a full re-sync. Use only when lag is
  stuck and will not self-recover. Requires `--accept-kvstore-reset`.

## Rolling Restart Modes

| Mode | Flag | Search during restart |
|------|------|-----------------------|
| Default | `--rolling-restart-mode default` | Brief outage per member |
| Searchable | `--rolling-restart-mode searchable` | Searches remain available via other members |
| Forced searchable | `--rolling-restart-mode forced` | Searchable + skips inactivity timeout check |

Searchable mode: transfers captain before first member restart; each member
waits for captain ACK before proceeding; `restart_inactivity_timeout` is the
ceiling. For large clusters or slow restarts, tune this value and consider
`--rolling-restart-mode forced` with explicit acceptance.

## Quorum Math

| Members | Quorum (N/2+1) | Tolerated failures |
|---------|---------------|-------------------|
| 3 | 2 | 1 |
| 5 | 3 | 2 |
| 7 | 4 | 3 |

The preflight check enforces quorum before any destructive operation
(`bundle-apply`, `rolling-restart`, `decommission-member`).

## ES-on-SHC Placement

- Install ES on the deployer under `etc/apps/SplunkEnterpriseSecuritySuite/`.
- ES-specific Knowledge Objects, macros, tags, and lookups go under
  `etc/shcluster/apps/` for bundle distribution.
- KV Store must be enabled on all members for ES data model accelerations and
  lookups.
- The `handoffs/es-deployer.txt` rendered file carries the deployer URI and
  bundle path for the
  [`splunk-enterprise-security-install`](../splunk-enterprise-security-install/SKILL.md)
  skill.

## Failure Mode Runbooks

See `runbook-failure-modes.md` in the rendered tree. Summary:

- **Split-brain** (two captains): restore network partition; older captain
  steps down on heartbeat recovery or via `transfer-shcluster-captain`.
- **Quorum loss**: bring members back to restore N/2+1.
- **Deployer mismatch** (divergent bundle generations): re-run `bundle-apply`;
  use `--accept-skip-validation` only if the bundle validator is the blocker.
- **Captain crash loop**: promote a stable member via `transfer-captain` before
  investigating and restarting the problematic member.

## Hand-off Contracts

- Assumes hosts are installed by
  [`splunk-enterprise-host-setup`](../splunk-enterprise-host-setup/SKILL.md)
  before this skill runs.
- Emits `handoffs/license-peers.txt` for
  [`splunk-license-manager-setup`](../splunk-license-manager-setup/SKILL.md).
- Emits `handoffs/es-deployer.txt` for
  [`splunk-enterprise-security-install`](../splunk-enterprise-security-install/SKILL.md).
- Emits `handoffs/monitoring-console.txt` for
  [`splunk-monitoring-console-setup`](../splunk-monitoring-console-setup/SKILL.md).
- SHC TLS (KV Store dual-EKU, S2S, replication port 9887) is handled by
  [`splunk-platform-pki-setup`](../splunk-platform-pki-setup/SKILL.md).
- Restart orchestration after bundle push is handled by
  [`splunk-platform-restart-orchestrator`](../splunk-platform-restart-orchestrator/SKILL.md).

## Out of Scope

- **SHC `pass4SymmKey` rotation**: rendered configs contain
  `pass4SymmKey = $SHC_SECRET` for operator-managed secret rotation. Rolling
  the secret cluster-wide requires a rolling restart with the new value; this
  skill does not orchestrate that rotation.
- **Splunk Cloud SHC**: Splunk-managed; this skill targets self-managed
  Splunk Enterprise only.
- **Indexer cluster bundle**: owned by
  [`splunk-indexer-cluster-setup`](../splunk-indexer-cluster-setup/SKILL.md).
- **Per-host install / upgrade**: owned by
  [`splunk-enterprise-host-setup`](../splunk-enterprise-host-setup/SKILL.md).

## References

- [reference.md](reference.md) for full `server.conf` field semantics, bundle
  trigger classification, KV Store shard model, and rolling restart health-check
  details.
- [template.example](template.example) for the non-secret intake worksheet.

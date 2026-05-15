# Splunk Deployment Server Setup — Reference

## Architecture

The Deployment Server (DS) is a Splunk Enterprise instance that distributes apps and configuration to Universal Forwarders (UFs) and Heavy Forwarders (HFs) via a poll-based model.

| Component | Role |
|-----------|------|
| **Deployment Server** | Hosts `etc/deployment-apps/`; serves `serverclass.conf` |
| **Deployment Client (UF/HF)** | Polls DS via `phoneHome`; receives apps and restarts |
| **Deployment App** | Self-contained app directory pushed to matching clients |
| **Server Class** | Grouping rule — maps apps to clients by hostname/IP filter |

**Skill boundary**: This skill owns DS runtime (bootstrap, reload, fleet ops, HA). `splunk-agent-management-setup` owns `serverclass.conf` authoring.

## phoneHome Intervals

| Fleet Size | Recommended Interval | Reason |
|-----------|---------------------|--------|
| < 500 UFs | 60s (default) | No scaling concern |
| 500–2,000 | 120s | Reduce DS REST load |
| 2,000–5,000 | 300s (5 min) | Required at this scale |
| 5,000–10,000 | 600s (10 min) | DS can become bottleneck |
| > 10,000 | 900s (15 min) + HA pair | Single DS cannot scale |

Configure in `deploymentclient.conf` (pushed via a deployment app):

```ini
[deployment-client]
phoneHomeIntervalInSecs = 300
handshakeRetryIntervalInSecs = 60
```

## Directory Structure

```
$SPLUNK_HOME/
  etc/
    deployment-apps/        # Apps served to clients
      TA-outputs/           # Global outputs.conf
        default/
          outputs.conf
      TA-inputs-linux-os/
        default/
          inputs.conf
    system/local/
      serverclass.conf      # Server class definitions (owned by splunk-agent-management-setup)
```

## filterType Default Change (Splunk 9.4.3+)

Prior to Splunk 9.4.3, `filterType` in `serverclass.conf` defaulted to `whitelist`. In 9.4.3+, the default behavior changed. Always specify explicitly:

```ini
[serverClass:my-class]
filterType = whitelist
whitelist.0 = *.corp.example.com
```

Never rely on the implicit default.

## REST API Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/services/deployment/server/clients` | GET | List enrolled clients + check-in times |
| `/services/deployment/server/serverclasses` | GET | List server classes |
| `/services/deployment/server/applications/local` | GET | List deployment apps |
| `/services/deployment/server/_reload` | POST | Reload DS config (no restart) |
| `/services/server/info` | GET | DS health check (used by LB) |

## HA Pair Configuration

For fleets > 5,000 UFs, run two DS instances behind a load balancer:

1. Both DS instances share identical `etc/deployment-apps/` and `serverclass.conf`.
2. Sync apps from primary to secondary via `ha/sync-deployment-apps.sh` (rsync) or Git pull.
3. LB health check: `GET /services/server/info` returns HTTP 200 when DS is up.
4. All UF `deploymentclient.conf` point to the VIP, not individual DS hosts.

```ini
# deploymentclient.conf on every UF
[deployment-client]
targetUri = ds-vip.corp.example.com:8089
```

**Do NOT** use DNS round-robin alone without a health check — a failed DS will still receive connections.

## Cascading DS (NOT Supported)

Splunk does not support DS-to-DS cascading (a DS acting as a client of another DS). This topology causes:
- Unpredictable app push order
- Server class evaluation ambiguity
- Support is explicitly out of scope per Splunk docs

The `setup.sh` refuses to render cascading DS configs without `--accept-cascading-ds-workaround` explicitly set.

## Client Migration (Re-targeting)

To migrate all UFs from an old DS to a new DS:

1. Deploy a new app containing `deploymentclient.conf` with the new `targetUri` via the **existing** DS to a server class covering all UFs.
2. After clients check in to the new DS, decommission the old DS.
3. Use `migrate/staged-rollout.sh` for phased rollout (canary class first).

Never update `targetUri` by hand on individual UFs — that does not scale.

## Monitoring

| Signal | Location | Threshold |
|--------|----------|-----------|
| Check-in lag | `/services/deployment/server/clients` `lastPhoneHomeTime` | > phoneHome interval × 3 = stale |
| 503 errors from DS | `rest_call_http.log` on DS | Any 503 = overload |
| App version drift | `inspect/client-drift-report.py` | Custom; alert on > 5% drift |

Hand off to `splunk-monitoring-console-setup` for Monitoring Console DS dashboard integration.

## Failure Mode Quick Reference

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| UFs not checking in | Wrong `targetUri`, DS down, network | Check `deploymentclient.log` on UF; verify DS is up |
| App not pushed | filterType implicit default, reload not run | Set explicit `filterType`; run reload |
| DS 503 overload | phoneHome interval too short | Increase `phoneHomeIntervalInSecs` fleet-wide |
| Duplicate enrollment | UF enrolled in two DSes | Remove extra `targetUri` from `deploymentclient.conf` |
| Cascading DS misbehavior | DS-to-DS topology | Rebuild as direct UF enrollment |

## Hand-Off Contracts

| Skill | Relationship |
|-------|-------------|
| `splunk-agent-management-setup` | Owns `serverclass.conf` authoring; this skill owns DS runtime |
| `splunk-universal-forwarder-setup` | Client-side enrollment; points UFs at DS URI |
| `splunk-platform-restart-orchestrator` | DS restart when needed |
| `splunk-monitoring-console-setup` | Fleet visibility and DS health dashboards |

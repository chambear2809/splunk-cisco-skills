---
name: splunk-deployment-server-setup
description: >-
  Render, preflight, bootstrap, validate, and operate the Splunk Enterprise
  Deployment Server (DS) runtime end-to-end: enable-deploy-server bootstrap,
  `etc/deployment-apps/` layout and bundle-hash tracking, `phoneHome` tuning
  (`phoneHomeIntervalInSecs`, `handshakeRetryIntervalInSecs`,
  `maxNumberOfClientApps`) with researched scale numbers (60 s default to
  300–600 s for 5000+ UF fleets), REST inspection (`GET
  /services/deployment/server/clients`, `/serverclasses`, `/applications/local`,
  `POST /services/deployment/server/_reload`), large-fleet HA pairing (two DS
  instances behind HAProxy or AWS ELB, shared `etc/deployment-apps/` via rsync
  or Git pull, LB health check `/services/server/info`), cascading-DS
  anti-pattern guard (refused without `--accept-cascading-ds-workaround`),
  SHC-deployer-as-DS anti-pattern guard, mass client re-enrollment
  (`targetUri` change + `splunk reload deploy-client`), staged rollout
  (10% per hour with rate-limit guidance), `filterType = whitelist` explicit
  rendering for Splunk 9.4.3+ default change, and failure-mode runbooks
  (503 log surge, app version drift, unenrolled client). Stays beneath
  `splunk-agent-management-setup` (which continues to own `serverclass.conf`
  and `deploymentclient.conf` authoring); this skill owns the DS runtime.
  Handoffs: `splunk-agent-management-setup` for server-class authoring,
  `splunk-universal-forwarder-setup` for UF enrollment,
  `splunk-monitoring-console-setup` for fleet visibility,
  `splunk-platform-restart-orchestrator` for DS restarts. Use when the user
  asks to bootstrap a deployment server, tune phoneHome intervals, inspect
  enrolled clients, set up DS high availability, diagnose a DS 503 flood,
  migrate clients to a new DS, or scale to 5000+ universal forwarders.
---

# Splunk Deployment Server Setup

This skill owns the **Deployment Server runtime**: bootstrap, performance
tuning, REST inspection, HA pairing, and client migration.
[`splunk-agent-management-setup`](../splunk-agent-management-setup/SKILL.md)
continues to own `serverclass.conf` authoring and `deploymentclient.conf`
rendering. The two skills compose — run `splunk-agent-management-setup` to
define server classes and apps, then use this skill for DS runtime health.

## Agent Behavior — Credentials

Never ask for secrets in chat.

- DS admin credentials live in the project-root `credentials` file (chmod 600)
  or `~/.splunk/credentials`. The shared library loads them automatically.
- If credentials are not yet configured:
  ```bash
  bash skills/shared/scripts/setup_credentials.sh
  ```
- Never pass `SPLUNK_PASS` as an env-var prefix or command-line argument.

## Quick Start

Bootstrap the DS role on a running Splunk Enterprise host:

```bash
bash skills/splunk-deployment-server-setup/scripts/setup.sh \
  --phase render \
  --ds-host ds01.example.com \
  --ds-uri https://ds01.example.com:8089 \
  --splunk-home /opt/splunk
```

Apply the bootstrap (runs `splunk enable deploy-server` on the target host):

```bash
bash skills/splunk-deployment-server-setup/scripts/setup.sh \
  --phase bootstrap \
  --ds-host ds01.example.com \
  --admin-password-file /tmp/splunk_admin_password
```

Reload `serverclass.conf` without restarting:

```bash
bash skills/splunk-deployment-server-setup/scripts/setup.sh \
  --phase reload \
  --ds-uri https://ds01.example.com:8089 \
  --admin-password-file /tmp/splunk_admin_password
```

Inspect enrolled clients and flag drift:

```bash
bash skills/splunk-deployment-server-setup/scripts/setup.sh \
  --phase inspect \
  --ds-uri https://ds01.example.com:8089 \
  --admin-password-file /tmp/splunk_admin_password
```

Render an HA pair configuration:

```bash
bash skills/splunk-deployment-server-setup/scripts/setup.sh \
  --phase render \
  --ds-host ds01.example.com \
  --ha-pair \
  --ds-secondary-host ds02.example.com \
  --lb-uri ds-lb.example.com:8089
```

Migrate all clients to a new DS:

```bash
bash skills/splunk-deployment-server-setup/scripts/setup.sh \
  --phase migrate-clients \
  --ds-uri https://ds01.example.com:8089 \
  --new-ds-uri https://ds02.example.com:8089 \
  --staged-rollout-pct 10 \
  --admin-password-file /tmp/splunk_admin_password
```

## What It Renders

Under `splunk-deployment-server-rendered/ds/`:

- `bootstrap/enable-deploy-server.sh` — `splunk enable deploy-server` wrapped
  in a preflight check for existing DS state.
- `bootstrap/deployment-apps-layout.md` — documented `etc/deployment-apps/`
  directory structure and bundle-hash behavior.
- `tuning/deploymentclient-scale.conf` — recommended `phoneHome` intervals at
  1k / 5k / 10k+ UF fleet sizes with rationale.
- `reload/reload-deploy-server.sh` — `POST /services/deployment/server/_reload`
  via the REST API (no restart required).
- `ha/{haproxy.cfg, lb-aws-target-group.json, dns-record-template.txt,
  sync-deployment-apps.sh}` — HA pair recipes.
- `inspect/{inspect-fleet.sh, client-drift-report.py}` — live client check-in
  lag, app version drift, unenrolled client detection.
- `migrate/{retarget-clients.sh, staged-rollout.sh}` — mass `targetUri` update
  scripts with a configurable percentage-per-wave guard.
- `runbook-failure-modes.md` — 503 flood, app version drift, unenrolled client,
  cascading-DS workaround.
- `validate.sh` — REST-round-trip health check, client count sanity.
- `handoffs/{agent-management.txt, monitoring-console.txt}`.
- `preflight-report.md` — DS role status, `serverclass.conf` syntax check,
  deployment-apps directory existence.

## Phases

| Phase | Purpose |
|-------|---------|
| `render` | Produce all config and script assets; no live changes. |
| `preflight` | Check DS role, `etc/deployment-apps/` layout, `serverclass.conf` parse. |
| `bootstrap` | Enable the DS role and validate the initial config. |
| `reload` | POST `_reload` to pick up `serverclass.conf` changes without restart. |
| `inspect` | Fetch client list, lag, app version drift; write `fleet-report.json`. |
| `ha-pair` | Render and (optionally apply) HA pair LB config + sync scripts. |
| `migrate-clients` | Render (and optionally execute) mass client `targetUri` migration. |
| `status` | Live `GET /services/deployment/server/clients` snapshot. |
| `validate` | Static + (with `--live`) REST health check. |

## `phoneHome` Tuning

| Fleet size | Recommended `phoneHomeIntervalInSecs` | Notes |
|-----------|---------------------------------------|-------|
| < 1,000 UFs | 60 (default) | Default is fine |
| 1,000–5,000 UFs | 120–180 | Reduce DS CPU/network I/O |
| 5,000–10,000 UFs | 300 | Dedicated DS host required |
| > 10,000 UFs | 600 | DS HA pair behind LB; dedicated host |

All values are set in `$SPLUNK_HOME/etc/apps/system/local/deploymentclient.conf`
(or via a bootstrap app pushed from the DS itself). The renderer emits a
commented `deploymentclient.conf` snippet with the recommended value based on
`--fleet-size` input.

Companion knobs:
- `handshakeRetryIntervalInSecs` — how often a client retries if the DS is
  unreachable (default 30 s; increase to 60–120 s for large fleets).
- `maxNumberOfClientApps` — maximum apps a single client can receive (default
  100; increase if server classes assign more than 100 apps per host).

## REST Inspection

Key endpoints (all authenticated as DS admin):

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/services/deployment/server/clients` | GET | List enrolled clients, last check-in, app versions |
| `/services/deployment/server/serverclasses` | GET | List defined server classes and member filters |
| `/services/deployment/server/applications/local` | GET | List deployed apps |
| `/services/deployment/server/_reload` | POST | Reload `serverclass.conf` without restart |
| `/services/server/info` | GET | LB health check endpoint (200 = alive) |

The rendered `inspect-fleet.sh` consolidates the first three into a single
report sorted by check-in lag, with a drift flag for clients where any app hash
differs from the DS-side hash.

## Large-Fleet HA

Two DS instances behind a load balancer:

1. Both instances have identical `etc/deployment-apps/` trees. Use
   `ha/sync-deployment-apps.sh` (rsync-based) or a Git pull hook.
2. Both instances have identical `serverclass.conf`. Use the same rsync script
   or deploy from a Git repo.
3. LB health check: `GET /services/server/info` (HTTP 200 = healthy). The
   rendered `ha/haproxy.cfg` sets a 5 s interval, 2 s timeout, and 3
   consecutive failures before marking a backend down.
4. Clients point to the LB URI. Do NOT use DNS round-robin (clients cache DNS
   and do not failover quickly within `phoneHomeIntervalInSecs`).
5. If one DS fails, clients retry the LB on the next `phoneHomeIntervalInSecs`
   tick. No manual client intervention needed.

AWS ELB alternative: `ha/lb-aws-target-group.json` renders an NLB target group
JSON with the same health check configuration.

## Anti-Pattern Guards

**Cascading DS (DS feeding DS) — NOT SUPPORTED.** Splunk does not support DS
chains. The renderer refuses without `--accept-cascading-ds-workaround` and
emits the documented workaround (dual-tier server classes or Git-based sync).

**SHC deployer as DS for UFs — REFUSED.** The SHC deployer
(`splunk enable shcluster-deployer`) is for SHC bundle management only. The
renderer emits a FAIL if the spec sets the DS host to a known SHC deployer.

**filterType default change.** Splunk Enterprise 9.4.3+ changed the implicit
app-level `filterType` default from `blacklist` to `whitelist`. The renderer
always emits `filterType = whitelist` (or `blacklist`) explicitly, regardless
of version, to avoid upgrade surprises. This aligns with
[`splunk-agent-management-setup`](../splunk-agent-management-setup/SKILL.md).

## Client Migration

Mass migration (moving all clients from DS1 to DS2):

1. Render the new `targetUri` `deploymentclient.conf` snippet on DS2.
2. Push the snippet as a deployment app from DS1 pointing to DS2. This self-
   migrates clients on their next `phoneHome` check-in.
3. Use `migrate/staged-rollout.sh` to roll the migration wave by wave
   (default 10% of clients per wave with a configurable dwell time).
4. Monitor DS2 `inspect-fleet.sh` to confirm clients arrive.
5. Decommission DS1 after all clients are enrolled on DS2.

Alternatively, update `targetUri` centrally via configuration management
(Ansible, Chef, Puppet) and trigger `splunk reload deploy-client` on each host.

## Failure Mode Runbooks

See `runbook-failure-modes.md` in the rendered tree:

- **503 flood on DS**: too many clients phoning home simultaneously; increase
  `phoneHomeIntervalInSecs`, add memory, or move to HA pair.
- **App version drift**: client has a stale app hash; DS has updated; normal
  re-deploy on next `phoneHome` unless a deployment-apps rsync is broken.
- **Unenrolled client**: client enrolled but not appearing in client list;
  check `targetUri` in `deploymentclient.conf`, firewall on port 8089, and
  `deploymentclient.log` for errors.
- **Cascading DS workaround**: see `runbook-failure-modes.md` section.

## Hand-off Contracts

- `splunk-agent-management-setup` — authors `serverclass.conf` and
  `deploymentclient.conf`. This skill calls `setup.sh --phase reload` after
  AM pushes a new server class to pick it up without a DS restart.
- `splunk-universal-forwarder-setup` — installs and enrolls the UF binary;
  sets `targetUri` in `deploymentclient.conf`.
- `splunk-monitoring-console-setup` — DS health dashboard and fleet monitoring.
- `splunk-platform-restart-orchestrator` — if a full DS restart is needed
  (e.g., after a Splunk upgrade).
- `handoffs/agent-management.txt` carries the AM skill invocation for
  server-class authoring.
- `handoffs/monitoring-console.txt` carries the MC skill invocation for
  fleet visibility.

## Out of Scope

- **`serverclass.conf` and `deploymentclient.conf` authoring** — owned by
  [`splunk-agent-management-setup`](../splunk-agent-management-setup/SKILL.md).
- **UF binary install / upgrade** — owned by
  [`splunk-universal-forwarder-setup`](../splunk-universal-forwarder-setup/SKILL.md).
- **Splunk Cloud Agent Management** — Splunk-managed cloud DS workflows are out
  of scope. This skill targets self-managed Splunk Enterprise deployments only.
- **DS-to-DS federation (cascading DS)** — not supported by Splunk; refused at
  render time without explicit `--accept-cascading-ds-workaround`.

## Validation

Static validation:

```bash
bash skills/splunk-deployment-server-setup/scripts/validate.sh \
  --output-dir splunk-deployment-server-rendered
```

Live validation:

```bash
bash skills/splunk-deployment-server-setup/scripts/validate.sh \
  --output-dir splunk-deployment-server-rendered \
  --live \
  --ds-uri https://ds01.example.com:8089 \
  --admin-password-file /tmp/splunk_admin_password
```

Live checks: `GET /services/deployment/server/clients` round-trip, enrolled
client count, last-check-in lag distribution.

See [reference.md](reference.md) and [template.example](template.example).

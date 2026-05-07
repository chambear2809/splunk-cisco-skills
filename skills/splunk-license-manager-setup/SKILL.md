---
name: splunk-license-manager-setup
description: >-
  Render, preflight, apply, validate, and audit a Splunk Enterprise license
  manager and its license peers, including license install, license group
  activation (Enterprise, Forwarder, Free, Trial), license stacks, license
  pools (with byte or MAX quota and per-peer slave lists), license peer
  configuration via splunk edit licenser-localpeer, license messages and
  violations, and license usage reporting. Use when the user asks about
  configuring a Splunk Enterprise license manager, license master, license
  peer, License-Master-URI, license slave, license pool, license group, or
  license usage reporting.
---

# Splunk License Manager Setup

This skill is the dedicated counterpart to
[`skills/splunk-enterprise-host-setup`](../../skills/splunk-enterprise-host-setup/SKILL.md),
which explicitly leaves license-manager bootstrap out of scope. It owns every
documented Splunk Enterprise licensing surface (REST + CLI) so a single skill
covers install, peers, pools, group activation, messages, and validation.

## Architecture First

- A license manager is normally **co-located** with another control-plane
  component (Monitoring Console, deployment server, **cluster manager**,
  search-head-cluster deployer, search head, or even an indexer). Splunk does
  not natively cluster license managers; HA is achieved with DNS-based
  failover to a cold-standby manager.
- License manager Splunk version must be **>= license peer** Splunk version
  at the major/minor level (significant at major/minor only — patch level is
  irrelevant).
- Volume-based and infrastructure (vCPU) Enterprise licenses cannot stack
  with each other. Free / Trial / Developer / Dev-Test cannot stack with
  anything.

## Agent Behavior — Credentials

Never paste passwords or secret values into chat.

- Use `template.example` for non-secret values (manager URI, peer hostnames,
  pool definitions).
- Keep secrets in temporary files only:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_admin_password
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_license_pass4symmkey
```

The license manager `pass4SymmKey` is **distinct** from the indexer cluster
`pass4SymmKey` and any SHC `pass4SymmKey`. Keep them in separate files.

## Quick Start

Render assets that install one or more `.lic` files on the manager and
configure peers to point at it:

```bash
bash skills/splunk-license-manager-setup/scripts/setup.sh \
  --phase render \
  --license-manager-uri https://lm01.example.com:8089 \
  --license-files /etc/splunk/enterprise.lic \
  --pool-spec name=ent_main,stack_id=enterprise,quota=MAX \
  --peer-hosts idx01.example.com,idx02.example.com
```

Apply on the manager (install license, activate group, create pools):

```bash
bash skills/splunk-license-manager-setup/scripts/setup.sh \
  --phase apply \
  --apply-target manager \
  --license-manager-uri https://lm01.example.com:8089 \
  --license-files /etc/splunk/enterprise.lic \
  --pool-spec name=ent_main,stack_id=enterprise,quota=MAX \
  --admin-password-file /tmp/splunk_admin_password
```

Apply on each peer (configure localpeer to point at the manager):

```bash
bash skills/splunk-license-manager-setup/scripts/setup.sh \
  --phase apply \
  --apply-target peers \
  --license-manager-uri https://lm01.example.com:8089 \
  --peer-hosts idx01.example.com,idx02.example.com \
  --admin-password-file /tmp/splunk_admin_password
```

Validate live state (peer membership, usage, messages):

```bash
bash skills/splunk-license-manager-setup/scripts/validate.sh \
  --license-manager-uri https://lm01.example.com:8089 \
  --admin-password-file /tmp/splunk_admin_password
```

## What It Renders

Under `splunk-license-manager-rendered/license/`:

- `manager/install-licenses.sh` — installs license files and uses the shared
  restart orchestrator for the manager restart.
- `manager/activate-group.sh` — `POST /services/licenser/groups/<group>`.
- `manager/pools/<name>.json` — desired-state pool definition.
- `manager/apply-pools.sh` — POST/PUT/DELETE to converge pool list.
- `peers/<host>/peer-server.conf` — `[license] manager_uri = ...` snippet.
- `peers/<host>/configure-peer.sh` — runs locally on the operator workstation
  and POSTs `manager_uri` to the peer's own
  `https://<host>:8089/services/licenser/localpeer` REST endpoint using a
  password file (`get_session_key_from_password_file`); no SSH and no
  `splunk -auth admin:<pw>` argv on either host. When
  `--restart-splunk=true`, emits a topology-aware restart handoff instead of a
  default REST restart. Override the peer URL with `PEER_MANAGEMENT_URL` (or
  just the port via `PEER_MANAGEMENT_PORT`) for non-default deployments.
- `validate.sh` — peers, usage, messages, version-compat checks.
- `audit/<timestamp>/{groups,stacks,pools,licenses,messages,localpeer,usage,peers}.json`
  snapshots.

## Out of Scope

- Splunk Cloud licensing (Splunk-managed; cannot be configured by customers).
- Commercial license procurement / renewal.

## References

- [reference.md](reference.md) for license-type matrix, terminology shift
  (`license master` → `license manager`), HA via DNS, message categories,
  and squash-threshold guidance.
- [template.example](template.example) for the non-secret intake worksheet.

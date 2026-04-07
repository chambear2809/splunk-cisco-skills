---
name: splunk-enterprise-host-setup
description: >-
  Install Splunk Enterprise packages on Linux hosts and configure them as a
  search-tier, indexer, heavy-forwarder, cluster manager, indexer peer, search
  head cluster deployer, or search head cluster member. Supports local or SSH
  execution, official URL or local package sources, role-aware forwarding, and
  single-site clustered topologies. Use when the user asks to bootstrap a
  Splunk host, install a heavy forwarder, build a search/index/forwarder tier,
  or configure clustered Splunk Enterprise nodes.
---

# Splunk Enterprise Host Setup

Bootstraps Linux hosts that should run **full Splunk Enterprise**.

## Architecture First

- A **heavy forwarder is not a separate package**. It is a full Splunk
  Enterprise install with forwarder-style configuration.
- This skill is for **self-managed Splunk Enterprise** hosts only.
- It models the deployment roles used elsewhere in this repo:
  - `search-tier`
  - `indexer`
  - `heavy-forwarder`
- It also covers the clustered control-plane roles needed to assemble those
  tiers:
  - cluster manager
  - search head cluster deployer
  - search head cluster member

## Agent Behavior

**Never ask for passwords or shared secrets in chat.**

- Use `skills/splunk-enterprise-host-setup/template.example` as the intake
  worksheet for non-secret values.
- Keep secrets in temporary files only, for example:

```bash
printf '%s\n' '<admin_password>' > /tmp/splunk_admin_password && chmod 600 /tmp/splunk_admin_password
printf '%s\n' '<idxc_secret>' > /tmp/splunk_idxc_secret && chmod 600 /tmp/splunk_idxc_secret
printf '%s\n' '<shc_secret>' > /tmp/splunk_shc_secret && chmod 600 /tmp/splunk_shc_secret
```

- Reuse the project `credentials` file or `~/.splunk/credentials` for SSH and
  REST defaults when possible.

## Package Model

Supported package sources:

1. `--source splunk-auth` for official Splunk download URLs that should use the
   stored Splunk.com credentials
2. `--source remote` for public or internal direct download URLs
3. `--source local` for packages already present on disk

If `--url` is omitted, or set to `latest`, remote and authenticated download
flows resolve the latest official Linux package URL from Splunk's Enterprise
download page at runtime. When `--package-type auto` is left in place for
latest resolution, the skill prefers `.deb` or `.rpm` based on the target OS
family and falls back to `.tgz`. Latest official downloads also require
successful verification against Splunk's official SHA512 checksum. If live
latest resolution fails, rerun with `--allow-stale-latest` to use the most
recent cached official metadata when it is younger than 30 days.

Supported package formats:

- `.tgz` / `.tar.gz`
- `.rpm`
- `.deb`

The skill caches downloaded packages in the repo-local `splunk-ta/` directory.

Install behavior:

- If the target host does not already have `SPLUNK_HOME/bin/splunk`, `install`
  performs a fresh install.
- If Splunk is already present and the package version differs, `install`
  performs an in-place upgrade for `.rpm`, `.deb`, or `.tgz`.
- If the installed version already matches the requested package version,
  `install` succeeds as a no-op and skips package replacement.
- Install-only upgrades do not require `--admin-password-file`. Password-based
  auth is still required for later `configure` or `cluster` work that uses
  authenticated Splunk CLI commands.

## Scripts

### setup.sh

Main bootstrap entrypoint:

```bash
bash skills/splunk-enterprise-host-setup/scripts/setup.sh \
  --phase all \
  --execution ssh \
  --host-bootstrap-role heavy-forwarder \
  --source remote \
  --package-type tgz \
  --admin-password-file /tmp/splunk_admin_password \
  --cluster-manager-uri https://cm01.example.com:8089 \
  --discovery-secret-file /tmp/splunk_idxc_secret
```

Useful phases:

- `download` — fetch and checksum-verify the package into `splunk-ta/`
- `install` — fresh-install, upgrade, or same-version no-op; fresh installs
  seed the admin user, upgrades stop Splunk before package replacement, and all
  successful install paths start Splunk and can enable boot-start
- `configure` — apply role-local configuration such as receiving or forwarding
- `cluster` — apply clustered settings such as manager, peer, or SHC membership
- `all` — run the full workflow

Clustered-role upgrades are still **per-host only**. The script warns when you
upgrade clustered roles, but it does not orchestrate rolling order or verify
cluster health across multiple hosts.

### validate.sh

Checks package install state, service health, role-specific config, and
clustered status where relevant.

```bash
bash skills/splunk-enterprise-host-setup/scripts/validate.sh \
  --execution ssh \
  --host-bootstrap-role indexer-peer \
  --admin-password-file /tmp/splunk_admin_password
```

### smoke_latest_resolution.sh

Quick live smoke for the latest official package resolver without downloading
the full package payload:

```bash
bash skills/splunk-enterprise-host-setup/scripts/smoke_latest_resolution.sh \
  --package-type auto
```

## Key Defaults

- `SPLUNK_HOME=/opt/splunk`
- Linux + systemd only
- single-site clustering only
- heavy forwarders default to `indexAndForward=false`
- clustered heavy forwarders default to **indexer discovery**
- search-tier roles enable Splunk Web by default
- SHC member adds require `--current-shc-member-uri` unless `--bootstrap-shc`
  is used to create a brand-new cluster

## References

- [reference.md](reference.md) for role placement, ports, and topology notes
- [template.example](template.example) for the non-secret intake worksheet

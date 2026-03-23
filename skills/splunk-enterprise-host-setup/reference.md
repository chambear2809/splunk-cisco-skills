# Splunk Enterprise Host Setup Reference

This skill bootstraps **self-managed Splunk Enterprise** hosts. It does not
provision Splunk Cloud stacks.

## Role Model

| Role | Meaning | Typical package |
|------|---------|-----------------|
| `standalone-search-tier` | Single-instance search/UI tier | Splunk Enterprise |
| `standalone-indexer` | Single-instance indexing node | Splunk Enterprise |
| `heavy-forwarder` | Full Enterprise collector/forwarder with `outputs.conf` | Splunk Enterprise |
| `cluster-manager` | Single-site indexer cluster manager | Splunk Enterprise |
| `indexer-peer` | Peer node in a single-site indexer cluster | Splunk Enterprise |
| `shc-deployer` | Search head cluster deployer | Splunk Enterprise |
| `shc-member` | Search head cluster member | Splunk Enterprise |

## Architectural Notes

- A heavy forwarder is a **full Splunk Enterprise instance**. Do not use a
  Universal Forwarder package when the role is `heavy-forwarder`.
- Search tiers own search-time knowledge, dashboards, and Splunk Web.
- Indexers own storage and S2S receiving.
- Heavy forwarders own collection, parsing, or intermediate forwarding.
- In clustered mode:
  - indexers register to the cluster manager
  - search head members integrate to the indexer cluster through the cluster
    manager
  - adding a new SHC member to an existing cluster requires a current member
    management URI so the new node can run `add shcluster-member`
  - heavy forwarders should prefer indexer discovery over static server lists

## Supported Topologies

### Standalone

- one search-tier host
- one indexer host
- one heavy forwarder that forwards to standalone indexers

### Single-Site Clustered

- one cluster manager
- one or more indexer peers
- one search head cluster deployer
- one or more search head cluster members
- one or more heavy forwarders

Out of scope in v1:

- multisite clustering
- deployment server / serverclass
- license manager bootstrap
- Universal Forwarder bootstrap
- TLS certificate generation

Existing target-side config files that this skill rewrites are backed up as
`*.bak.<timestamp>` before replacement.

## Secrets

Use file-based secret inputs only:

- admin password: `--admin-password-file`
- indexer cluster secret: `--idxc-secret-file`
- indexer discovery secret: `--discovery-secret-file`
- search head cluster secret: `--shc-secret-file`

## Key Ports

| Port | Purpose |
|------|---------|
| `8089` | Splunk management / REST |
| `8000` | Splunk Web |
| `9997` | S2S receiving on indexers |
| `9887` | indexer peer replication port |
| `8081` | SHC replication port |
| `22` | SSH for remote bootstrap mode |

## Execution Modes

- `--execution local` assumes the script is running on the target Linux host
- `--execution ssh` stages files and runs commands over SSH using the same
  password-based SSH model already used elsewhere in the repo
- If SSH mode also needs privileged package install or file writes, use a root
  SSH account or an account with non-interactive sudo available on the target

For SSH mode, the credentials file can also define:

- `SPLUNK_SSH_HOST`
- `SPLUNK_SSH_PORT`
- `SPLUNK_SSH_USER`
- `SPLUNK_SSH_PASS`
- `SPLUNK_REMOTE_TMPDIR`
- `SPLUNK_REMOTE_SUDO`

## Quick Smoke

Use the smoke entrypoint to verify live latest-resolution and official SHA512
discovery without downloading the full package:

```bash
bash skills/splunk-enterprise-host-setup/scripts/smoke_latest_resolution.sh \
  --package-type auto
```

Useful options:

- `--package-type auto|tgz|rpm|deb|all`
- `--execution local|ssh`
- `--allow-stale-latest` to fall back to cached latest metadata when live
  resolution fails

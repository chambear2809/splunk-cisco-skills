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
- TLS certificate generation — owned by [`splunk-platform-pki-setup`](../splunk-platform-pki-setup/SKILL.md), which mints Private PKI or Public PKI CSR + handoff for every Splunk surface (Splunk Web, splunkd, S2S, HEC, KV Store, indexer cluster, SHC, LM, DS, MC, SAML SP, LDAPS, Edge Processor, UF fleet)

Existing target-side config files that this skill rewrites are backed up as
`*.bak.<timestamp>` before replacement.

## Upgrade Behavior

- `--phase install` and `--phase all` automatically choose between fresh
  install, upgrade, or same-version no-op.
- `.rpm` and `.deb` upgrades reuse the platform package manager semantics.
- `.tgz` upgrades stop Splunk first, then overlay the extracted `splunk/` tree
  onto the existing `SPLUNK_HOME` so packaged defaults are replaced while
  unique local files remain in place.
- If the package version cannot be parsed, the script treats the run as an
  upgrade instead of a no-op.
- Install-only upgrades are per-host only. For clustered roles, the operator
  still owns sequencing, health checks, and rollback planning outside this
  skill.

### Enterprise 10.4 to 10.6 with ITSI 5.0.x

Splunk lists ITSI 5.0.2 as compatible with Enterprise 10.6, but documents that
ITSI 5.0.x requires postponing the Enterprise 10.6 cohosted PostgreSQL KV Store
migration. On Enterprise 10.4, set `[kvstore]
postgresMigrateOnStartup = false` before the Enterprise upgrade. The KV Store
admin skill can render this override with
`--defer-postgres-migration true`; it does not install the file, so distribute
it through the deployment's normal configuration-management mechanism and
verify effective precedence with `splunk btool server list kvstore --debug`.

Keep the standard gates: verified backup and restore, KV Store health, supported
topology and upgrade sequence, app compatibility, and documented storage
readiness. After upgrading Enterprise, confirm the setting remains false,
`migrationStatus` is `NotStarted`, and KV Store data and service are available.
This completes the Enterprise upgrade while deliberately deferring the KV
Store engine migration. Complete the migration later, after ITSI and all other
installed apps support it, in a separate maintenance window.

Sources: [Enterprise 10.6 upgrade guidance](https://help.splunk.com/en/splunk-enterprise/get-started/install-and-upgrade/10.6/upgrade-or-migrate-splunk-enterprise/about-upgrading-to-10.6-read-this-first), [cohosted KV Store migration and postponement setting](https://help.splunk.com/en/data-management/splunk-enterprise-admin-manual/10.6/administer-the-app-key-value-store/upgrade-to-a-cohosted-kv-store), [Splunk product compatibility matrix](https://help.splunk.com/en/splunk-enterprise/release-notes-and-updates/compatibility-matrix/splunk-products-version-compatibility/splunk-products-version-compatibility-matrix).

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
| `8065` | Splunk Web app server |
| `8191` | KV Store |
| `8194` | IPC Broker |
| `5432` | PostgreSQL sidecar service |
| `5433` | PostgreSQL primary service |
| `5434` | PostgreSQL replica service |
| `8008` | PostgreSQL Patroni |
| `6432` | PostgreSQL connection pooler |
| `5435` | PostgreSQL nanny |
| `2380` | Nascent etcd peer |
| `2379` | Nascent etcd client |
| `9997` | S2S receiving on indexers |
| `9887` | indexer peer replication port |
| `8081` | SHC replication port |
| `22` | SSH for remote bootstrap mode |

Fresh installs accept per-service port overrides through the matching
`--*-port` flags and `SPLUNK_*_PORT` environment variables. The setup script
checks all selected service and sidecar ports on the target before installation
and writes them before first start. When defaults conflict with an existing
instance, select free alternatives and record the chosen values for validation
and operator handoff.

## Execution Modes

- `--execution local` assumes the script is running on the target Linux host
- `--execution ssh` stages files and runs commands over SSH. The default
  `SPLUNK_SSH_AUTH_METHOD=password` uses password authentication; set it to
  `key` to use OpenSSH keys or an agent without storing a password
- If SSH mode also needs privileged package install or file writes, use a root
  SSH account or an account with non-interactive sudo available on the target

For SSH mode, the credentials file can also define:

- `SPLUNK_SSH_HOST`
- `SPLUNK_SSH_PORT`
- `SPLUNK_SSH_USER`
- `SPLUNK_SSH_PASS`
- `SPLUNK_SSH_AUTH_METHOD=password|key`
- `SPLUNK_SSH_KNOWN_HOSTS_FILE` or `SPLUNK_SSH_HOST_KEY_FINGERPRINT`
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

## Legacy Splunk Enterprise 10.4 deployment notes

For legacy 10.4-specific deployment details, read this skill alongside
[`../shared/splunk_10_4_enterprise_deployment_notes.md`](../shared/splunk_10_4_enterprise_deployment_notes.md),
the prose companion to the
[`../shared/references/splunk_platform_versions.json`](../shared/references/splunk_platform_versions.json)
version contract. Use the Enterprise 10.6 upgrade ladder above for current
self-managed planning; keep Cloud `10.5.2605` on its separate version train.

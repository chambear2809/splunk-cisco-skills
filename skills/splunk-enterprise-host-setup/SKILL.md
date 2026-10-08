---
name: splunk-enterprise-host-setup
description: "Use when the user asks to bootstrap a Splunk host, install a heavy forwarder, build a
  search/index/forwarder tier, or configure clustered Splunk Enterprise nodes. Install Splunk Enterprise
  packages on Linux hosts and configure them as a search-tier, indexer, heavy-forwarder, cluster manager,
  indexer peer, search head cluster deployer, or search head cluster member. Supports local or SSH
  execution, official URL or local package sources, role-aware forwarding, and single-site clustered
  topologies."
compatibility: "Splunk Cloud Platform 10.5.2605: not applicable. This self-managed runtime workflow is not a Cloud runtime; see the separate Enterprise 10.6 matrix for self-managed compatibility."
metadata:
  splunk_enterprise_10_6: "supported"
  enterprise_compatibility_verified: "2026-10-05"
  splunk_cloud_10_5: "self-managed-10.4"
  compatibility_verified: "2026-08-20"
---

# Splunk Enterprise Host Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Bootstrap a Splunk host, install a heavy forwarder, build a search/index/forwarder tier, or configure clustered
  Splunk Enterprise nodes.
- Preview and review the splunk enterprise host setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-enterprise-host-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-enterprise-host-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

Bootstraps Linux hosts that should run **full Splunk Enterprise**.

## Architecture First

- A **heavy forwarder is not a separate package**. It is a full Splunk
  Enterprise install with forwarder-style configuration.
- This skill is for **self-managed Splunk Enterprise** hosts only.
- The CLI takes the canonical role names below via `--host-bootstrap-role`:
  - `standalone-search-tier`
  - `standalone-indexer`
  - `heavy-forwarder`
  - `cluster-manager`
  - `indexer-peer`
  - `shc-deployer`
  - `shc-member`
- The "standalone-" prefix marks single-instance roles; clustered indexer and
  search-head-cluster control-plane roles use the unprefixed names above.

## Agent Behavior — Credentials

**Never ask for passwords or shared secrets in chat.**

- Use `skills/splunk-enterprise-host-setup/template.example` as the intake
  worksheet for non-secret values.
- Keep secrets in temporary files only, for example:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_admin_password
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_idxc_secret
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_shc_secret
```

- Reuse the project `credentials` file or `~/.splunk/credentials` for SSH and
  REST defaults when possible. SSH execution additionally requires either an
  operator-reviewed `SPLUNK_SSH_KNOWN_HOSTS_FILE` or a verified
  `SPLUNK_SSH_HOST_KEY_FINGERPRINT`. The warned
  `SPLUNK_SSH_ALLOW_TOFU=true` escape hatch is for disposable labs only.
- SSH defaults to password authentication. Set `SPLUNK_SSH_AUTH_METHOD=key`
  to use the local OpenSSH key or agent instead; do not set
  `SPLUNK_SSH_PASS` in key mode. Key mode still requires the same host-key
  trust pin.

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

Clustered-role upgrades still execute through the per-host `setup.sh` path, but
the skill can now render a rolling plan with one host per wave, pre/post
validation commands, and cluster health gates:

```bash
python3 skills/splunk-enterprise-host-setup/scripts/rolling_upgrade_plan.py \
  --role indexer-peer \
  --hosts idx01.example.com,idx02.example.com,idx03.example.com \
  --cluster-manager-host cm01.example.com \
  --cluster-manager-uri https://cm01.example.com:8089 \
  --admin-password-file /tmp/splunk_admin_password
```

The planner is render-only. It does not SSH, restart Splunk, or modify hosts;
operators still run the generated per-host commands after each health gate is
green.

### validate.sh

Checks package install state, service health, role-specific config, and
clustered status where relevant. It also waits up to 300 seconds for an enabled
KV Store to become ready. Enterprise 10.6 with the cohosted store configured
must report both member and cohosted-store readiness. Use
`--kvstore-ready-timeout-seconds` when a host needs a longer startup window; a
timeout reports the observed states and the relevant logs to inspect.
In SSH mode, REST checks run against the target's loopback management endpoint
through SSH, so the management port does not need to be reachable from the
controller machine. Password and session-key data travel over SSH stdin.

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
- standalone-search-tier roles enable Splunk Web by default
- SHC member adds require `--current-shc-member-uri` unless `--bootstrap-shc`
  is used to create a brand-new cluster

## Enterprise upgrade ladder (10.6)

Splunk Enterprise has no 10.3 or 10.5 self-managed release train. The current
baseline is **10.6.0.5**. Splunk documents direct upgrades from Enterprise
10.4.x, 10.2.x, and 10.0.x to 10.6.x; therefore **10.4.3 → 10.6** is a
supported version path. All application, topology, backup, and KV Store gates
must still pass before apply. Enterprise 9.4.x must first upgrade to 10.0.x or
10.2.x; older unsupported trains need a separately verified upgrade plan.

Invalid or high-risk jumps this skill should warn about during planning:

- **9.x → 10.4** without an intermediate **10.0** or **10.2** stop (KV Store
  MongoDB 7+ prerequisite).
- Any upgrade target below the SVD floor for the selected train (see
  `splunk-enterprise-public-exposure-hardening` or
  `skills/shared/references/splunk_platform_versions.json`).

Enterprise 10.6 automatically migrates the MongoDB-backed KV Store to the
cohosted PostgreSQL storage sidecar. Before upgrading, require KV Store server
7.0 or higher, more than 50% free space on the KV Store data filesystem, an
authenticated `splunk show kvstore-status` health check, a parallel backup,
confirmed restore evidence, application compatibility review, and a maintenance
window that allows KV Store read-only operation. On SHCs, verify stable captain
and healthy membership; never upgrade one member outside its coordinated
rolling-upgrade procedure. ITSI 5.0.x is supported on Enterprise 10.6, but
requires postponing this KV Store migration. For this documented Enterprise
10.4-to-10.6 branch, before upgrade render and review `server.conf` with
`bash skills/splunk-kvstore-admin-setup/scripts/setup.sh --defer-postgres-migration true`;
distribute `[kvstore] postgresMigrateOnStartup = false` through the host's
normal configuration-management path and confirm its effective value with
`splunk btool server list kvstore --debug`. Keep the ordinary backup,
restore-test, health, topology, and disk-readiness gates. After upgrade, confirm
the flag remains false, `migrationStatus : NotStarted`, KV Store data is
readable and service is ready; check startup logs for
`reason="startup_flag_disabled"`. Do not claim the PostgreSQL migration
completed. Plan and validate a later ITSI-compatible maintenance window before
re-enabling migration. For the normal migration branch, wait for
`migrationStatus : Migration_Succeeded`, KV Store
`status : ready`, and cohosted store `status : ready`. Authentication failures
mean the gate is unverified, not passed.

10.6 also introduces four-part version strings such as `10.6.0.5`; scripts and
CMDB integrations must parse all four numeric segments. Federated Search remote
providers must be 10.4 or higher before upgrading. Clustered deployments must
allow the documented PostgreSQL network ports between all members. Review
public TLS certificates for Client Authentication EKU removal, and keep
inter-Splunk TLS at 1.2 or higher. A custom Debian-derived OS can be used for
functional validation only when Splunk does not list that exact distribution as
supported.

For a side-by-side fresh-install test, use an isolated `SPLUNK_HOME`,
`--no-boot-start`, and distinct ports for all services. The management, Web,
app-server, KV Store, and IPC Broker defaults are `8089`, `8000`, `8065`,
`8191`, and `8194`. Enterprise 10.6 also uses PostgreSQL sidecar ports `5432`,
`5433`, `5434`, `8008`, `6432`, and `5435`, plus Nascent ports `2380` and
`2379`. Each can be overridden with its matching `--*-port` flag or
`SPLUNK_*_PORT` environment variable. Keep the defaults when they are free. If
any are occupied or the operator requests alternates, ask for the preferred
port policy; when the user delegates selection, inspect the target, choose
distinct free ports for every collision, and report the selected values before
installation. The script checks every selected port on the target immediately
before a fresh install and configures them before first start. Pass the selected
management port to `validate.sh --mgmt-port` and use the selected Web port when
opening Splunk Web. Validate the new instance, stop it, then remove only its
dedicated test directory; never remove `/opt/splunk` as test cleanup.

Route PKI and KV Store preparation to `splunk-platform-pki-setup` and
`splunk-kvstore-admin-setup` before executing host upgrades.

## References

- [reference.md](reference.md) for role placement, ports, and topology notes
- [template.example](template.example) for the non-secret intake worksheet

---
name: splunk-enterprise-security-install
description: >-
  Install, post-install, and validate Splunk Enterprise Security (ES), including
  SplunkEnterpriseSecuritySuite, essinstall, standalone search-head and SHC
  deployer workflows, required ES framework apps, local splunk-ta packages, and
  Splunkbase app 263 fallback. Use when the user asks to install, upgrade,
  bootstrap, post-install, or validate Splunk Enterprise Security.
---

# Splunk Enterprise Security Install

Installs and validates **Splunk Enterprise Security** (`SplunkEnterpriseSecuritySuite`).

## Agent Behavior

Never ask for secrets in chat. Splunk and Splunkbase credentials are read from
the project-root `credentials` file, falling back to `~/.splunk/credentials`.
If neither exists, guide the user to run:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

Use the local package under `splunk-ta/` first when it exists. If no local ES
package is available, use Splunkbase app ID `263`; pass `--app-version` to force
a specific Splunkbase version.

For Splunk Cloud Platform, do not self-service install ES unless the customer
has an explicitly supported ACS/support process. Splunk Cloud customers usually
coordinate ES search-head access and installation with Splunk Support.

## Environment

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| App name | `SplunkEnterpriseSecuritySuite` |
| Splunkbase ID | `263` |
| Local fallback | `splunk-ta/splunk-enterprise-security_851.spl` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/splunk-enterprise-security-install/scripts/` |

### Remote Splunk Connection

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

## Workflow

1. **Read the reference** for version-specific notes:

   ```text
   skills/splunk-enterprise-security-install/reference.md
   ```

2. **Preflight the target**:
   - ES is a premium product and requires a valid license.
   - The user must be an admin or equivalent with app-install capabilities.
   - Ensure KV Store is healthy and `/tmp` has approximately 3 GB free.
   - Remove `deploymentclient.conf` from apps managed by a deployment server.
   - On SHC deployers, back up `etc/shcluster/apps`, one member's `etc/apps`,
     and one member's KV Store before install.

3. **Install and run ES post-install**:

   ```bash
   bash skills/splunk-enterprise-security-install/scripts/setup.sh
   ```

   Defaults: install/update ES from the local package when present, otherwise
   Splunkbase app `263`, run `| essinstall`, then validate.

4. **For SHC deployers**, pass the deployer mode and then apply the bundle:

   ```bash
   bash skills/splunk-enterprise-security-install/scripts/setup.sh \
     --deployment-type shc_deployer
   ```

   Then run `splunk apply shcluster-bundle` from the deployer using local
   Splunk CLI credentials or your normal SHC operations process.

5. **Validate**:

   ```bash
   bash skills/splunk-enterprise-security-install/scripts/validate.sh
   ```

## Scripts

### setup.sh

Installs the ES package, runs preflight checks, runs post-install setup, and
optionally orchestrates the SHC bundle apply and the `Splunk_TA_ForIndexers`
handoff for clustered indexers.

Useful flags:

| Flag | Purpose |
|------|---------|
| `--install` | Install/update the ES package only |
| `--post-install` | Run `\| essinstall` only |
| `--validate` | Run validation only |
| `--preflight-only` | Run preflight checks and exit |
| `--skip-preflight` | Skip preflight (logs a WARN) |
| `--confirm-upgrade` | Required when an existing ES install is detected |
| `--backup-notice PATH` | Write backup runbook to PATH before upgrade |
| `--set-shc-limits` | On SHC deployer, set the required `web.conf` / `server.conf` limits via REST |
| `--allow-deployment-client` | Allow install when `deploymentclient.conf` has active stanzas |
| `--apply-bundle` | After SHC `essinstall`, run `splunk apply shcluster-bundle` via the deployer SSH profile |
| `--shc-target-uri URI` | SHC member URI for `--apply-bundle` and the post-apply health check (or set `SHC_TARGET_URI` env). Required when `SPLUNK_URI` is the deployer; otherwise the post-apply `/services/shcluster/status` query 404s. |
| `--generate-ta-for-indexers DIR` | Extract `Splunk_TA_ForIndexers` from the local ES package into `DIR` (highest version wins when multiple members exist) |
| `--deploy-ta-for-indexers CM_URI` | After staging, run `splunk validate cluster-bundle` then `splunk apply cluster-bundle` on the CM via its SSH profile. The CM_URI host MUST match the host in `SPLUNK_CLUSTER_MANAGER_PROFILE`; the script aborts on mismatch. |
| `--force-apply-bundle` | Apply the cluster-manager bundle even when `splunk validate cluster-bundle` returns non-zero (validation is otherwise blocking) |
| `--backup-kvstore` | Run `splunk backup kvstore` via the deployer/local SSH profile **before** the install/upgrade so a failed install leaves a recoverable archive. |
| `--uninstall` | Disable removable framework apps, request uninstall of ES + support apps, and leave Mission Control installed (restart required to finalize) |
| `--source auto\|splunkbase\|local` | Force package-source behavior |
| `--file PATH` | Local ES `.spl`/`.tgz` package |
| `--app-version VER` | Pin a Splunkbase version |
| `--deployment-type search_head\|shc_deployer` | Select `essinstall` deployment type |
| `--ssl-enablement strict\|auto\|ignore` | Pass through to `essinstall` |
| `--dry-run` | Run `essinstall --dry-run` |
| `--skip-essinstall` | Install package but skip post-install setup |
| `--no-validate` | Skip validation |

### generate_ta_for_indexers.sh

Extracts the Splunk Cloud-variant `Splunk_TA_ForIndexers` tarball from a local
ES package into a target directory. This is what operators stage under
`$SPLUNK_HOME/etc/manager-apps/Splunk_TA_ForIndexers` on the cluster manager
before running `splunk apply cluster-bundle`.

### validate.sh

Runs read-only checks for:

- Splunk API authentication
- ES suite version and configured state
- Required framework apps and bundled supporting apps
- KV Store status
- Data model acceleration enforcement stanzas
- Search-head and SHC platform limits (`max_upload_size`,
  `max_content_length`, `splunkdConnectionTimeout`)
- `Splunk_TA_ForIndexers` presence on the connected tier
- Key ES indexes, with warnings for distributed deployments where indexes live
  on another tier

## Key Rules

- Do not disable `Mission Control`; it is part of ES 8.x.
- Do not disable ES framework apps with `SA-` or `DA-ESS-` names.
- ES 8.x upgrades are one-way; perform a full search-head and KV Store backup
  first.
- ES 8.x on on-prem Splunk Enterprise 10.x must be installed from the command
  line rather than uploaded through Splunk Web.
- Run `essinstall --deployment_type shc_deployer` for SHC deployers.
- `ssl_enablement=auto` is not valid for SHC deployer installs.

## Additional Resources

- [reference.md](reference.md) — researched ES install requirements, package
  contents, version notes, and validation details.

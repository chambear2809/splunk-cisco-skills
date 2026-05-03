# Splunk Enterprise Security Install Reference

This reference is based on Splunk Enterprise Security 8.5 documentation and the
local package `splunk-ta/splunk-enterprise-security_851.spl`.

## Current Version

- Splunkbase app ID: `263`
- Splunk ES 8.5.1 release notes state that 8.5.1 was released April 16, 2026.
- Public Splunkbase app `263` checked on May 2, 2026 displayed latest version
  `8.4.0` from February 18, 2026, so this skill prefers the local ES package
  when present.
- Local package: `SplunkEnterpriseSecuritySuite` version `8.5.1`, build
  `263675`
- Splunkbase compatibility shown for the public listing: Splunk Enterprise and
  Splunk Cloud, platform versions `10.3`, `10.2`, `10.1`, `10.0`, `9.4`, `9.3`,
  CIM `6.x`

## Official Sources

- Splunkbase listing: `https://splunkbase.splunk.com/app/263/`
- ES 8.5 release notes:
  `https://help.splunk.com/en/splunk-enterprise-security-8/release-notes-and-resources/8.5/splunk-enterprise-security-release-notes/release-notes-for-splunk-enterprise-security`
- Deployment considerations:
  `https://help.splunk.com/en/splunk-enterprise-security-8/install/8.5/planning/deployment-considerations-for-splunk-enterprise-security`
- On-prem search head install:
  `https://help.splunk.com/en/splunk-enterprise-security-8/install/8.5/installation/install-splunk-enterprise-security-on-an-on-prem-search-head`
- SHC deployer install:
  `https://help.splunk.com/en/splunk-enterprise-security-8/install/8.5/installation/install-splunk-enterprise-security-in-a-search-head-cluster-environment`
- Deploy technology add-ons:
  `https://help.splunk.com/en/splunk-enterprise-security-8/install/8.5/installation/deploy-technology-add-ons-to-splunk-enterprise-security`

## Preflight Checklist

- Confirm ES entitlement and license.
- Confirm the install user has `admin` or `sc_admin` role, `edit_local_apps`,
  and any required platform app-install capabilities.
- Confirm KV Store is healthy before install or upgrade.
- Confirm approximately 3 GB free in `/tmp`.
- If a deployment server manages any apps or add-ons included with ES, remove
  the `deploymentclient.conf` reference and restart before install.
- On standalone or distributed on-prem deployments, configure
  `limits.conf [lookup] enforce_auto_lookup_order = true` on the standalone
  search head or search peers and indexers.
- On ES 8.x upgrades, take a full backup of the search head, including KV Store.
  ES 8.x upgrade is one-way and does not automatically back up app content or
  data.
- ES 8.x cannot be uploaded through the Splunk Web UI on on-prem Splunk
  Enterprise 10.x; use CLI or the management API from the command line.

## Deployment Guardrails

### Standalone Search Head

- Increase Splunk Web upload size when using the UI:

  ```ini
  [settings]
  max_upload_size = 2048
  ```

- After package install, run:

  ```spl
  | essinstall --deployment_type search_head --ssl_enablement strict
  ```

- `ssl_enablement` options are `strict`, `auto`, and `ignore`. `strict` fails
  if Splunk Web SSL is not enabled. `auto` updates `web.conf` to enable SSL.

### Search Head Cluster Deployer

- ES supports Linux search head clusters only.
- Do not install ES on a stretched SHC in a multi-site indexer cluster.
- Back up deployer `etc/shcluster/apps`, a member `etc/apps`, and a member KV
  Store.
- Preserve existing content in `$SPLUNK_HOME/etc/shcluster/apps`.
- Use these SHC web/server limits:

  ```ini
  [settings]
  max_upload_size = 2048
  splunkdConnectionTimeout = 300

  [httpServer]
  max_content_length = 5000000000
  ```

- `max_content_length` must be increased on both the deployer and SHC members.
- Run:

  ```spl
  | essinstall --deployment_type shc_deployer --ssl_enablement strict
  ```

- `ssl_enablement=auto` is not allowed for SHC deployers because `etc/system`
  is not replicated from deployer to members.
- Apply the SHC bundle after post-install:

  ```bash
  splunk apply shcluster-bundle --answer-yes -target <URI>:<management_port>
  ```

## Package Contents Observed Locally

The ES 8.5.1 package has top-level app `SplunkEnterpriseSecuritySuite`.
Important bundled apps under `SplunkEnterpriseSecuritySuite/install/` include:

- `DA-ESS-AccessProtection`
- `DA-ESS-EndpointProtection`
- `DA-ESS-IdentityManagement`
- `DA-ESS-NetworkProtection`
- `DA-ESS-ThreatIntelligence`
- `DA-ESS-UEBA`
- `SA-AccessProtection`
- `SA-AuditAndDataProtection`
- `SA-ContentVersioning`
- `SA-Detections`
- `SA-EndpointProtection`
- `SA-EntitlementManagement`
- `SA-IdentityManagement`
- `SA-NetworkProtection`
- `SA-TestModeControl`
- `SA-ThreatIntelligence`
- `SA-UEBA`
- `SA-Utils`
- `SplunkEnterpriseSecuritySuite`
- `Splunk_ML_Toolkit`
- `Splunk_SA_CIM`
- `Splunk_SA_Scientific_Python_linux_x86_64`
- `Splunk_SA_Scientific_Python_windows_x86_64`
- `Splunk_TA_ueba`
- `dlx-app`
- `missioncontrol`
- `ocsf_cim_addon_for_splunk`
- `exposure-analytics`
- `splunk_cloud_connect`
- `Splunk_TA_ForIndexers` for Splunk Cloud package content

Do not disable the framework apps. ES 8.5 release notes also state that
Mission Control is part of ES and must not be uninstalled.

## essinstall Command

The local package defines:

```text
essinstall --dry-run
essinstall --deployment_type search_head|shc_deployer
essinstall --ssl_enablement strict|auto|ignore
```

Use `--dry-run` to list apps that would be installed or upgraded without
performing the post-install process.

## Validation Signals

Validate these after installation:

- `SplunkEnterpriseSecuritySuite` app is installed, visible, enabled, and
  version `8.5.1` or expected.
- `ess_setup.conf [install] configured_version` is populated after setup.
- Required ES framework apps are installed and enabled.
- KV Store status is `ready`.
- `inputs.conf` contains enabled `dm_accel_settings://...` stanzas for ES data
  model acceleration enforcement.
- On SHC members, the expected `SA-` and `DA-ESS-` apps exist under `etc/apps`
  after bundle apply.
- Key ES indexes such as `notable`, `risk`, `threat_activity`,
  `cim_modactions`, `ba_test`, and `sequenced_events` exist on the appropriate
  index tier or are intentionally managed elsewhere.

## Coverage Matrix

| Feature | Flag / Script | Mode | Notes |
|---------|---------------|------|-------|
| Package install | `--install` / default | Apply | Splunkbase app 263, local `splunk-ta/` fallback, or forced local via `--file` |
| Post-install workflow | `--post-install` | Apply | Runs `\| essinstall` on the connected search head |
| Preflight (license, `/tmp`, KV Store, deploymentclient, admin role, upgrade confirmation, platform version) | `--preflight-only` or default flow | Apply (REST reads) | Hard-fails if any check fails; pass `--skip-preflight` to override with a logged WARN |
| Splunk platform version floor | (automatic in preflight) | Apply (REST read) | Compares `/services/server/info` version against `ES_MIN_PLATFORM_VERSION` (default `9.3`) |
| ES premium entitlement hint | (automatic in preflight) | Apply (REST read) | Scans `/services/licenser/stack` feature labels for `enterprise_security` / `*_es` |
| SHC platform limits (`max_upload_size`, `max_content_length`, `splunkdConnectionTimeout`) | `--set-shc-limits` | Apply | POST to `/services/configs/conf-web` and `/services/configs/conf-server` when below ES-required minimums |
| Upgrade safety | `--confirm-upgrade` + `--backup-notice PATH` | Apply | Refuses to proceed when ES is already installed unless confirmation flag is set; writes a runbook of backup commands |
| KV Store backup | `--backup-kvstore` | Apply via SSH profile | Runs `splunk backup kvstore --archive-name es_kvstore_<timestamp>` via deployer/local profile; emits handoff when no profile is configured |
| SHC bundle apply | `--apply-bundle --shc-target-uri URI` | Apply via SSH profile | Requires `SPLUNK_DEPLOYER_PROFILE` set in the credentials file; otherwise emits handoff. Reports post-apply `/services/shcluster/status` summary |
| `Splunk_TA_ForIndexers` generation | `--generate-ta-for-indexers DIR` or `generate_ta_for_indexers.sh` | Apply (local file write) | Pulls the Splunk Cloud-variant TA from the local ES package |
| `Splunk_TA_ForIndexers` cluster-bundle apply | `--deploy-ta-for-indexers CM_URI` | Apply via SSH profile | Requires `SPLUNK_CLUSTER_MANAGER_PROFILE` and that the operator has staged the TA under `manager-apps/` on the cluster manager. Runs `splunk validate cluster-bundle` before apply |
| ES uninstall | `--uninstall` | Apply | Disables removable framework apps and requests uninstall for `SplunkEnterpriseSecuritySuite` + bundled `SA-`, `DA-ESS-`, and support apps; leaves `missioncontrol` installed per ES 8.x support guidance; restart required to finalize |
| Validation | `--validate` or `validate.sh` | Validate | Read-only REST checks covering apps, KV Store, DM acceleration, platform limits, `Splunk_TA_ForIndexers` presence, and key ES indexes |

## Common Failure Modes

- Missing license or missing premium Splunkbase entitlement.
- Package uploaded through Splunk Web on Splunk Enterprise 10.x instead of CLI.
- `ssl_enablement=strict` with Splunk Web SSL disabled.
- `ssl_enablement=auto` used on an SHC deployer.
- SHC bundle too large because `max_content_length` was not raised on deployer
  and members.
- Deployment server still manages ES-included apps through
  `deploymentclient.conf`.
- KV Store unhealthy before install or during post-install.
- Technology-specific TAs expected on indexers/forwarders but not deployed.

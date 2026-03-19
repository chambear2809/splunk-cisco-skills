---
name: cisco-intersight-setup
description: >-
  Automate Cisco Intersight Add-on for Splunk (Splunk_TA_Cisco_Intersight) setup
  and configuration. Creates indexes, configures Intersight accounts via REST API
  using OAuth2 client credentials, enables audit/alarm, inventory, and metrics
  inputs, stores credentials securely, and validates the deployment. Use when the
  user asks about Cisco Intersight, UCS, HyperFlex, Intersight TA setup,
  Splunk_TA_Cisco_Intersight, or compute infrastructure monitoring.
---

# Cisco Intersight TA Setup Automation

Automates the **Cisco Intersight Add-On for Splunk** (`Splunk_TA_Cisco_Intersight` v3.1.0).

## Package Model

**Pull from Splunkbase first (latest version), fall back to `splunk-ta/`.**
Use `splunk-app-install` with `--source splunkbase --app-id 7828` to get the
latest release. If Splunkbase is unavailable, fall back to the local package
in `splunk-ta/`. This applies to both Splunk Cloud (ACS) and Splunk Enterprise.

After installation, use this skill to configure the account, inputs, macros,
and validation over search-tier REST. Any `splunk-ta/_unpacked/` tree is
review-only.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, API keys, or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials` file
(falls back to `~/.splunk/credentials`). If neither exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

For Intersight credentials (OAuth2 Client Secret), instruct the user to write the
secret to a temporary file:

```bash
# User creates the file themselves (agent never sees the secret)
echo "the_client_secret" > /tmp/client_secret && chmod 600 /tmp/client_secret
```

Then the agent passes `--client-secret-file /tmp/client_secret` to the configure
script. After the account is created, delete the temp file.

The agent may freely ask for non-secret values: account names, hostnames, client IDs, etc.

## Environment

Setup and validation use the Splunk search-tier REST API and can run from any
host with network access to the Splunk management port (`8089`). In Splunk
Cloud, app installation, index creation, and restarts are handled through ACS
instead of the search-tier REST endpoints.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs (`SPLUNK_PLATFORM` is only an override for hybrid runs) |
| TA app name | `Splunk_TA_Cisco_Intersight` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-intersight-setup/scripts/` (relative to repo root) |

### Remote Splunk Connection

To run against a remote Splunk instance:

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

## Splunk Authentication

Scripts read Splunk credentials from the project-root `credentials` file (falls back to `~/.splunk/credentials`) automatically.
No environment variables or command-line password arguments are needed:

```bash
bash scripts/validate.sh
```

If credentials are not yet configured, run the setup script first:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

## Setup Workflow

### Step 1: Create Index and Macro

```bash
bash skills/cisco-intersight-setup/scripts/setup.sh
```

Creates one index, updates the search macro, and ensures the app is visible in
Splunk Web. When run interactively (TTY), the script prompts to continue with
account configuration after the initial setup completes.

No `sudo` required when running as the `splunk` user.
In Splunk Cloud, the setup script creates this index through ACS.

| Index | Macro | Purpose | Max Size |
|-------|-------|---------|----------|
| `intersight` | `cisco_intersight_index` | All Intersight data | 512 GB |

Partial runs: `--indexes-only` or `--macros-only`.

### Step 2: Configure Account

Before running, the agent must **ask the user** for non-secret values:
- Account name (e.g., "CVF_Intersight")
- Intersight hostname (default: `intersight.com` for SaaS)
- OAuth2 Client ID
- Whether to create default inputs (true/false)

For the OAuth2 Client Secret, instruct the user to write it to a temp file and
pass `--client-secret-file`. The agent never sees the secret.

Accounts are created via the Splunk REST API, which handles credential encryption
automatically through the TA's custom REST handlers:

```bash
bash scripts/configure_account.sh \
  --name "MY_INTERSIGHT" \
  --hostname "intersight.com" \
  --client-id "YOUR_CLIENT_ID" \
  --client-secret-file /tmp/client_secret
```

REST endpoint: `/servicesNS/nobody/Splunk_TA_Cisco_Intersight/Splunk_TA_Cisco_Intersight_account`

### Step 3: Enable Inputs

```bash
bash scripts/setup.sh --enable-inputs \
  --account "MY_INTERSIGHT" --index "intersight" --input-type all
```

| Input Type | Inputs Enabled | Index |
|------------|---------------|-------|
| `audit_alarms` | 2 (audit logs, alarms) | `intersight` |
| `inventory` | 3 (general inventory, ports/interfaces, pools) | `intersight` |
| `metrics` | 2 (device metrics, network metrics) | `intersight` |
| `all` | 7 (all of the above) | `intersight` |

### Step 4: Restart If Required

On Splunk Enterprise, restart Splunk after new index creation.
On Splunk Cloud, check `acs status current-stack` and only run
`acs restart current-stack` when ACS reports `restartRequired=true`.

### Step 5: Validate

```bash
bash scripts/validate.sh
```

Checks: app installation, indexes, macros, accounts, inputs, data flow, settings.

## Sourcetypes

| Sourcetype | Content |
|---|---|
| `cisco:intersight:auditrecords` | Audit trail (login, logout, CRUD operations) |
| `cisco:intersight:alarms` | Active and historical alarms |
| `cisco:intersight:compute` | Server inventory (blades, rack units) |
| `cisco:intersight:networkelements` | Fabric Interconnects and network devices |
| `cisco:intersight:profiles` | Server/chassis/switch profiles |
| `cisco:intersight:targets` | Connected targets and claimed devices |
| `cisco:intersight:contracts` | Support contract information |
| `cisco:intersight:licenses` | License entitlements |
| `cisco:intersight:advisories` | Security advisories (PSIRTs) |
| `cisco:intersight:networkobjects` | Network configuration objects |
| `cisco:intersight:pools` | IP/MAC/UUID/IQN/FC/Resource pools |
| `cisco:intersight:metrics` | Performance metrics (CPU, memory, fan, temp, network) |
| `cisco:intersight:custom:inventory` | Custom API inventory queries |
| `cisco:intersight:custom:metrics` | Custom API metrics queries |

## MCP Server Integration

Load custom tools into the MCP Server (credentials read from the project-root `credentials` file, falls back to `~/.splunk/credentials`):

```bash
bash scripts/load_mcp_tools.sh
```

## Key Learnings / Known Issues

1. **OAuth2 authentication**: Intersight uses Client ID + Client Secret (not
   username/password). The TA's REST handler encrypts the secret automatically.
2. **Restart behavior differs by platform**: Enterprise requires a Splunk
   restart after new index creation. Splunk Cloud uses ACS restart checks.
3. **No sudo needed**: Scripts run fine as the `splunk` OS user.
4. **SSL verification**: The `ssl_validation` setting defaults to `true` in
   `splunk_ta_cisco_intersight_settings.conf`.
5. **Default inputs**: The account creation UI has a "Create Default Inputs"
   checkbox. The script defaults to not creating them (use `--create-defaults`).
6. **KVStore inventory**: The TA stores inventory snapshots in KVStore collections
   for dashboard lookups — this is normal and expected.
7. **Custom inputs**: Up to 10 custom inputs can query arbitrary Intersight API
   endpoints (set via `MAX_INPUT_LIMIT` in settings).
8. **CIM compliance**: Audit records map to Authentication and Change CIM models.
   Alarms map to the Alerts CIM model. Metrics map to Performance.
9. **ACS deployment verification**: After ACS install, verify the app identity
   via REST (`configs/conf-app/package`). ACS can occasionally deploy the wrong
   app content into an app directory. If `app.conf` shows a different app ID,
   uninstall and reinstall the app individually.
10. **Visibility after ACS install**: The app may default to `visible=false`
    after ACS install, making it invisible in Splunk Web. The setup script now
    sets `visible=true` automatically. The standalone fix is a POST to
    `/services/apps/local/Splunk_TA_Cisco_Intersight` with `visible=true`.
11. **Interactive continuation**: When run from a TTY, `setup.sh` prompts to
    continue with account configuration after the initial setup completes. This
    is skipped in non-interactive (piped) contexts.

## Additional Resources

- [reference.md](reference.md) — Complete input catalog, account fields, sizing
- [mcp_tools.json](mcp_tools.json) — MCP tool definitions

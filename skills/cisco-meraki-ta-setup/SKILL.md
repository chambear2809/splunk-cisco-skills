---
name: cisco-meraki-ta-setup
description: >-
  Automate Cisco Meraki Add-on for Splunk (Splunk_TA_cisco_meraki) setup and
  configuration. Creates indexes, configures Meraki organization accounts via
  REST API, enables data inputs, stores credentials securely, and validates the
  deployment. Use when the user asks about Cisco Meraki TA setup, Meraki
  dashboard, Meraki API, or Splunk_TA_cisco_meraki.
---

# Cisco Meraki TA Setup Automation

Automates the **Splunk Add-on for Cisco Meraki** (`Splunk_TA_cisco_meraki` v3.3.0).

## Package Model

**Pull from Splunkbase first (latest version), fall back to `splunk-ta/`.**
Use `splunk-app-install` with `--source splunkbase --app-id 5580` to get the
latest release. If Splunkbase is unavailable, fall back to the local package
in `splunk-ta/`. This applies to both Splunk Cloud (ACS) and Splunk Enterprise.

After installation, use this skill to configure the account, inputs, dashboard
macro, and validation over search-tier REST. Any `splunk-ta/_unpacked/` tree
is review-only.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, API keys, or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials` file
(falls back to `~/.splunk/credentials`). If neither exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

For the Meraki Dashboard API key, instruct the user to write it to a temporary file:

```bash
# User creates the file themselves (agent never sees the secret)
echo "the_meraki_api_key" > /tmp/meraki_api_key && chmod 600 /tmp/meraki_api_key
```

Then the agent passes `--api-key-file /tmp/meraki_api_key` to the configure script.
After the account is created, delete the temp file.

The agent may freely ask for non-secret values: account names, org IDs, regions, etc.

For prerequisite collection, use `skills/cisco-meraki-ta-setup/template.example`
as the intake worksheet. Copy it to `template.local`, fill in non-secret values
there, and keep the completed file local only.

## Environment

Setup and validation use the Splunk search-tier REST API and can run from any
host with network access to the Splunk management port (`8089`). In Splunk
Cloud, app installation, index creation, and restarts are handled through ACS
instead of the search-tier REST endpoints.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs (`SPLUNK_PLATFORM` is only an override for hybrid runs) |
| TA app name | `Splunk_TA_cisco_meraki` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-meraki-ta-setup/scripts/` (relative to repo root) |

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

### Step 1: Create Index and Configure Dashboards

```bash
bash skills/cisco-meraki-ta-setup/scripts/setup.sh
```

Creates the index, sets the `meraki_index` dashboard macro, and ensures the app
is visible in Splunk Web. When run interactively (TTY), the script prompts to
continue with account configuration after the initial setup completes.

No `sudo` required when running as the `splunk` user.
In Splunk Cloud, the setup script creates the index through ACS.

| Index | Purpose | Max Size |
|-------|---------|----------|
| `meraki` | All Meraki Dashboard data | 512 GB |

Partial runs: `--indexes-only` (skips dashboard macro and visibility fix).

### Step 2: Configure Organization Account

Before running, the agent must **ask the user** for non-secret values:
- Account name (e.g., "MY_ORG")
- Organization ID
- Region (global, india, canada, china, fedramp)
- Whether to auto-create inputs (recommended)

For the Meraki Dashboard API key, instruct the user to write it to a temp file and
pass `--api-key-file`. The agent never sees the key.

Accounts are created via the Splunk REST API, which handles API key encryption
automatically through the TA's custom REST handlers:

```bash
bash scripts/configure_account.sh \
  --name "MY_ORG" \
  --api-key-file /tmp/meraki_api_key \
  --org-id "123456789" \
  --region global \
  --auto-inputs \
  --index meraki
```

REST endpoint used (API key encryption handled automatically):
- `/servicesNS/nobody/Splunk_TA_cisco_meraki/Splunk_TA_cisco_meraki_account`

Account fields:

| Field | Required | Description |
|-------|----------|-------------|
| `--name` | Yes | Account name / stanza identifier |
| `--api-key-file` | Yes | Path to file containing Meraki Dashboard API key |
| `--org-id` | Yes | Meraki organization ID |
| `--region` | No | `global` (default), `india`, `canada`, `china`, `fedramp` |
| `--max-api-rate` | No | Max API calls/sec, 1-10 (default 5) |
| `--auto-inputs` | No | Auto-create all inputs on account creation |
| `--index` | No | Index for auto-created inputs (default `meraki`) |

### Step 3: Enable Inputs (if not using auto-create)

If `--auto-inputs` was used in Step 2, all inputs are created automatically.
Otherwise, enable manually:

```bash
bash scripts/setup.sh --enable-inputs \
  --account "MY_ORG" --index "meraki" --input-type all
```

| Input Type | Inputs Enabled | Description |
|------------|---------------|-------------|
| `all` | 39 | All standard polling inputs |
| `core` | 7 | AP, Air Marshal, audit, cameras, org security, MX, switches |
| `devices` | 5 | Devices, availability, uplinks, power, firmware |
| `wireless` | 6 | Wireless ethernet, packet loss, controllers |
| `summary` | 5 | Top appliances, devices, clients, switches, power history |
| `api` | 4 | API request history, response codes, overview, assurance |
| `vpn` | 2 | Appliance VPN stats and statuses |
| `licenses` | 4 | Overview, coterm, subscription entitlements, subscriptions |
| `switches` | 3 | Port overview, transceivers, ports by switch |
| `organization` | 2 | Networks and organizations |
| `sensor` | 1 | Sensor readings history |

### Step 4: Restart If Required

On Splunk Enterprise, restart Splunk after new index creation.
On Splunk Cloud, check `acs status current-stack` and only run
`acs restart current-stack` when ACS reports `restartRequired=true`.

### Step 5: Validate

```bash
bash scripts/validate.sh
```

Checks: app installation, index, account, inputs, data flow, settings.

## Sourcetypes

| Sourcetype | Content |
|---|---|
| `meraki:accesspoints` | Access point data |
| `meraki:securityappliances` | MX appliance data |
| `meraki:switches` | Switch data |
| `meraki:cameras` | Camera data |
| `meraki:organizationsecurity` | Organization security events |
| `meraki:audit` | Configuration change audit log |
| `meraki:airmarshal` | Wireless Air Marshal events |
| `meraki:devices` | Device inventory |
| `meraki:assurancealerts` | Assurance alerts |
| `meraki:appliancesdwanstatistics` | VPN statistics |
| `meraki:appliancesdwanstatuses` | VPN statuses |
| `meraki:licensesoverview` | License overview |
| `meraki:firmwareupgrades` | Firmware upgrade status |
| `meraki:webhook` | Webhook events (HEC) |

See [reference.md](reference.md) for the full sourcetype catalog (35+).

## MCP Server Integration

Load custom tools into the MCP Server (credentials read from the project-root `credentials` file, falls back to `~/.splunk/credentials`):

```bash
bash scripts/load_mcp_tools.sh
```

## Key Learnings / Known Issues

1. **REST API for accounts**: This TA uses custom REST handlers — always create
   accounts via the REST API, not by writing conf files manually. The handlers
   encrypt the API key automatically.
2. **Auto-create inputs**: Setting `automatic_input_creation=1` creates all
   inputs at account creation time. This is the recommended approach.
3. **Restart behavior differs by platform**: Enterprise requires a Splunk
   restart after new index creation. Splunk Cloud uses ACS restart checks.
4. **No sudo needed**: Scripts run fine as the `splunk` OS user.
5. **Region determines base URL**: `global`→`api.meraki.com`,
   `india`→`api.meraki.in`, `canada`→`api.meraki.ca`, `china`→`api.meraki.cn`,
   `fedramp`→`api.gov-meraki.com`.
6. **Webhook input is special**: The webhook input requires HEC configuration
   and is not part of the standard polling inputs.
7. **Rate limiting**: The `max_api_calls_per_second` field controls API rate
   limiting (default 5, max 10).
8. **ACS deployment verification**: After ACS install, verify the app identity
   via REST (`configs/conf-app/package`). ACS can occasionally deploy the wrong
   app content into an app directory. If `app.conf` shows a different app ID,
   uninstall and reinstall the app individually.
9. **Visibility after ACS install**: The app may default to `visible=false`
   after ACS install, making it invisible in Splunk Web. The setup script now
   sets `visible=true` automatically. The standalone fix is a POST to
   `/services/apps/local/Splunk_TA_cisco_meraki` with `visible=true`.
10. **Dashboard macro in default setup**: The `setup.sh` default flow (no flags)
    now creates indexes AND configures the `meraki_index` dashboard macro.
    `setup_dashboards.sh` still exists for standalone use or custom index names.
11. **Interactive continuation**: When run from a TTY, `setup.sh` prompts to
    continue with account configuration after the initial setup completes. This
    is skipped in non-interactive (piped) contexts.

## Additional Resources

- [reference.md](reference.md) — Complete input catalog, account fields, sizing
- [mcp_tools.json](mcp_tools.json) — MCP tool definitions

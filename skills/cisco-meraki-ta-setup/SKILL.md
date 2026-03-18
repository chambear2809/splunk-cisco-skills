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

Automates the **Splunk Add-on for Cisco Meraki** (`Splunk_TA_cisco_meraki` v3.2.0).

## Package Model

Install the original vendor archive from `splunk-ta/` as-is:

- `cisco-meraki-add-on-for-splunk_320.tgz`

For Splunk Cloud, install that archive with ACS and then use this skill to
configure the account, inputs, dashboard macro, and validation over search-tier
REST. Any `splunk-ta/_unpacked/` copy is review-only and not part of the normal
workflow.

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

## Environment

Setup and validation use the Splunk search-tier REST API and can run from any
host with network access to the Splunk management port (`8089`). In Splunk
Cloud, app installation, index creation, and restarts are handled through ACS
instead of the search-tier REST endpoints.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_URI` env var (default: `https://localhost:8089`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs (`SPLUNK_PLATFORM` is only an override for hybrid runs) |
| TA app name | `Splunk_TA_cisco_meraki` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-meraki-ta-setup/scripts/` (relative to repo root) |

### Remote Splunk Connection

To run against a remote Splunk instance:

```bash
export SPLUNK_URI="https://splunk-host:8089"
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

### Step 1: Create Index

```bash
bash skills/cisco-meraki-ta-setup/scripts/setup.sh
```

Creates one index. No `sudo` required when running as the `splunk` user.
In Splunk Cloud, the setup script creates this index through ACS.

| Index | Purpose | Max Size |
|-------|---------|----------|
| `meraki` | All Meraki Dashboard data | 512 GB |

Partial runs: `--indexes-only`.

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

### Step 4: Configure Dashboards

The Meraki TA includes **32 built-in dashboards**. All dashboards use the
`meraki_index` macro, which defaults to `index IN(main)`. This must be updated
to point to the `meraki` index.

```bash
bash scripts/setup_dashboards.sh
```

Or with a custom index name:

```bash
bash scripts/setup_dashboards.sh my_custom_index
```

This updates `meraki_index` via the TA's REST configuration endpoint so all 32
dashboards query the correct index. Search-tier Splunk credentials are required.

Built-in dashboards include:

| Category | Dashboards |
|----------|------------|
| Core | Access Points, Air Marshal, Audit, Cameras, Switches, Security Appliances, Org Security |
| Devices | Devices, Device Availability, Device Uplinks, Firmware Upgrades |
| Wireless | Wireless Ethernet Statuses, Wireless Packet Loss |
| Summary | Top Appliances, Top Clients, Top Devices, Top Switches by Energy |
| VPN | Appliance VPN Stats, Appliance VPN Statuses |
| Licenses | Coterm, Subscription Entitlements, Subscriptions |
| Switch | Switch Port Overview |
| Sensor | Sensor Reading History |
| API | API Request History, Request Overview, Response Codes |
| Assurance | Assurance Alerts |
| Organization | Organizations, Organization Networks |

### Step 5: Restart If Required

On Splunk Enterprise, restart Splunk after new index creation.
On Splunk Cloud, check `acs status current-stack` and only run
`acs restart current-stack` when ACS reports `restartRequired=true`.

### Step 6: Validate

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

## Additional Resources

- [reference.md](reference.md) — Complete input catalog, account fields, sizing
- [mcp_tools.json](mcp_tools.json) — MCP tool definitions

---
name: cisco-catalyst-ta-setup
description: >-
  Automate Cisco Catalyst Add-on for Splunk (TA_cisco_catalyst) setup and
  configuration. Creates indexes, configures Catalyst Center/ISE/SD-WAN/Cyber
  Vision accounts via REST API, enables data inputs, stores credentials
  securely, and validates the deployment. Use when the user asks about Cisco
  Catalyst Center, DNA Center, DNAC, ISE, SD-WAN, Cyber Vision TA setup,
  or TA_cisco_catalyst.
---

# Cisco Catalyst TA Setup Automation

Automates the **Cisco Catalyst Add-on for Splunk** (`TA_cisco_catalyst` v3.0.0).

## Package Model

Install the original vendor archive from `splunk-ta/` as-is:

- `cisco-catalyst-add-on-for-splunk_310.tar.gz`

For Splunk Cloud, install that archive with ACS and then use this skill to
configure accounts, inputs, and validation over search-tier REST. Any
`splunk-ta/_unpacked/` copy is review-only and not part of the normal workflow.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, API keys, or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials` file
(falls back to `~/.splunk/credentials`). If neither exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

For device credentials (Catalyst Center password, ISE password, SD-WAN password,
Cyber Vision API token), instruct the user to write the secret to a temporary file:

```bash
# User creates the file themselves (agent never sees the secret)
echo "the_device_password" > /tmp/device_pass && chmod 600 /tmp/device_pass
```

Then the agent passes `--password-file /tmp/device_pass` or `--api-token-file /tmp/token`
to the configure script. After the account is created, delete the temp file.

The agent may freely ask for non-secret values: account names, hostnames, account types, etc.

## Environment

Setup and validation use the Splunk search-tier REST API and can run from any
host with network access to the Splunk management port (`8089`). In Splunk
Cloud, app installation, index creation, and restarts are handled through ACS
instead of the search-tier REST endpoints.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_URI` env var (default: `https://localhost:8089`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs (`SPLUNK_PLATFORM` is only an override for hybrid runs) |
| TA app name | `TA_cisco_catalyst` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-catalyst-ta-setup/scripts/` (relative to repo root) |

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

### Step 1: Create Indexes

```bash
bash skills/cisco-catalyst-ta-setup/scripts/setup.sh
```

Creates four indexes. No `sudo` required when running as the `splunk` user.
In Splunk Cloud, the setup script creates these indexes through ACS.

| Index | Purpose | Max Size |
|-------|---------|----------|
| `catalyst` | Catalyst Center (DNAC) data | 512 GB |
| `ise` | ISE authentication/admin data | 512 GB |
| `sdwan` | SD-WAN health/tunnel data | 512 GB |
| `cybervision` | Cyber Vision OT data | 512 GB |

Partial runs: `--indexes-only`.

### Step 2: Configure Account

Before running, the agent must obtain from the user (non-secret values only):
- Account type (catalyst_center, ise, sdwan, cybervision)
- Account name (e.g., "CVF_Cat_Center")
- Connection details (host, username)
- Device password or API token — user writes to temp file; agent passes `--password-file` or `--api-token-file`

Accounts are created via the Splunk REST API, which handles password encryption
automatically through the TA's custom REST handlers:

```bash
bash scripts/configure_account.sh \
  --type catalyst_center \
  --name "MY_CATC" \
  --host "https://10.100.0.60" \
  --username "device_user" \
  --password-file /tmp/device_pass
```

Account types and their required fields:

| Type | Required Fields | Conf File |
|------|----------------|-----------|
| `catalyst_center` | `--host`, `--username`, `--password-file` | `ta_cisco_catalyst_account.conf` |
| `ise` | `--host`, `--username`, `--password-file` | `ta_cisco_catalyst_ise_account.conf` |
| `sdwan` | `--host`, `--username`, `--password-file` | `ta_cisco_catalyst_sdwan_account.conf` |
| `cybervision` | `--host`, `--api-token-file` | `ta_cisco_catalyst_cyber_vision_account.conf` |

REST endpoints used (password encryption handled automatically):
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_account`
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_ise_account`
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_sdwan_account`
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_cyber_vision_account`

### Step 3: Enable Inputs

```bash
bash scripts/setup.sh --enable-inputs \
  --account "MY_CATC" --index "catalyst" --input-type catalyst_center
```

| Input Type | Inputs Enabled | Index | Account Field |
|------------|---------------|-------|---------------|
| `catalyst_center` | 9 (clienthealth, devicehealth, compliance, issue, networkhealth, securityadvisory, client, audit_logs, site_topology) | `catalyst` | `cisco_dna_center_account` |
| `ise` | 1 (administrative_input with 3 data_types) | `ise` | `ise_account` |
| `sdwan` | 2 (health, site_and_tunnel_health) | `sdwan` | `sdwan_account` |
| `cybervision` | 6 (activities, components, devices, events, flows, vulnerabilities) | `cybervision` | `cyber_vision_account` |

### Step 4: Restart If Required

On Splunk Enterprise, restart Splunk after new index creation.
On Splunk Cloud, check `acs status current-stack` and only run
`acs restart current-stack` when ACS reports `restartRequired=true`.

### Step 5: Validate

```bash
bash scripts/validate.sh
```

Checks: app installation, indexes, accounts, inputs, data flow, settings.

## Sourcetypes

| Sourcetype | Product | Content |
|---|---|---|
| `cisco:dnac:issue` | Catalyst Center | Network issues and assurance |
| `cisco:dnac:clienthealth` | Catalyst Center | Client health scores |
| `cisco:dnac:devicehealth` | Catalyst Center | Device health scores |
| `cisco:dnac:compliance` | Catalyst Center | Device compliance status |
| `cisco:dnac:networkhealth` | Catalyst Center | Network health summary |
| `cisco:dnac:securityadvisory` | Catalyst Center | PSIRTs and advisories |
| `cisco:dnac:client` | Catalyst Center | Client details |
| `cisco:dnac:audit:logs` | Catalyst Center | Audit trail |
| `cisco:dnac:site:topology` | Catalyst Center | Site hierarchy |
| `cisco:cybervision:activities` | Cyber Vision | OT activities |
| `cisco:cybervision:components` | Cyber Vision | OT components |
| `cisco:cybervision:devices` | Cyber Vision | OT devices |
| `cisco:cybervision:events` | Cyber Vision | OT events |
| `cisco:cybervision:flows` | Cyber Vision | OT network flows |
| `cisco:cybervision:vulnerabilities` | Cyber Vision | OT vulnerabilities |

ISE and SD-WAN sourcetypes vary by data type and are prefixed `cisco:ise*` and
`cisco:sdwan*` respectively.

## MCP Server Integration

```bash
bash scripts/load_mcp_tools.sh
```

## Key Learnings / Known Issues

1. **REST API for accounts**: This TA uses custom REST handlers — always create
   accounts via the REST API, not by writing conf files manually. The handlers
   encrypt passwords automatically.
2. **Restart behavior differs by platform**: Enterprise requires a Splunk
   restart after new index creation. Splunk Cloud uses ACS restart checks.
3. **No sudo needed**: Scripts run fine as the `splunk` OS user.
4. **SSL verification**: The TA's `verify_ssl` setting defaults to True. Set to
   False for self-signed certs via `ta_cisco_catalyst_settings.conf`.
5. **Cyber Vision uses API tokens**: Unlike other account types, Cyber Vision
   uses `api_token` instead of username/password.
6. **ISE data types**: The ISE input accepts `data_type` with comma-separated
   values: `security_group_tags`, `authz_policy_hit`, `ise_tacacs_rule_hit`.

## Additional Resources

- [reference.md](reference.md) — Complete input catalog, account fields, sizing
- [mcp_tools.json](mcp_tools.json) — MCP tool definitions

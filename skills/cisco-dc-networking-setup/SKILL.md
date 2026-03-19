---
name: cisco-dc-networking-setup
description: >-
  Automate Cisco DC Networking TA setup and configuration on Splunk. Creates
  indexes, configures ACI/Nexus Dashboard/Nexus 9K accounts, enables data
  inputs, stores credentials securely, and validates the deployment. Use when
  the user asks about Cisco DC networking, ACI, APIC, Nexus Dashboard, Nexus
  9K TA setup, Splunk TA automation, or cisco_dc_networking_app_for_splunk.
---

# Cisco DC Networking TA Setup Automation

Automates the **Cisco DC Networking App for Splunk** (`cisco_dc_networking_app_for_splunk` v1.2.0).

## Package Model

**Pull from Splunkbase first (latest version), fall back to `splunk-ta/`.**
Use `splunk-app-install` with `--source splunkbase --app-id 7777` to get the
latest release. If Splunkbase is unavailable, fall back to the local package
in `splunk-ta/`. This applies to both Splunk Cloud (ACS) and Splunk Enterprise.

After installation, use this skill to configure accounts, inputs, macros, and
validation over search-tier REST. Any `splunk-ta/_unpacked/` tree is
review-only.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, API keys, or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials` file
(falls back to `~/.splunk/credentials`). If neither exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

For device credentials (APIC password, Nexus Dashboard password, Nexus 9K password),
instruct the user to write the secret to a temporary file:

```bash
# User creates the file themselves (agent never sees the secret)
echo "the_device_password" > /tmp/device_pass && chmod 600 /tmp/device_pass
```

Then the agent passes `--password-file /tmp/device_pass` to the configure script.
After the account is created, delete the temp file.

The agent may freely ask for non-secret values: account names, hostnames, account types, etc.

## Environment

Setup and validation use the Splunk search-tier REST API and can run from any
host with network access to the Splunk management port (`8089`). In Splunk
Cloud, app installation, index creation, and restarts are handled through ACS
instead of the search-tier REST endpoints.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs (`SPLUNK_PLATFORM` is only an override for hybrid runs) |
| TA app name | `cisco_dc_networking_app_for_splunk` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-dc-networking-setup/scripts/` (relative to repo root) |

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

### Step 1: Create Indexes and Macros

```bash
bash skills/cisco-dc-networking-setup/scripts/setup.sh
```

Creates three indexes and three search macros. No `sudo` required when running
as the `splunk` user.
In Splunk Cloud, the setup script creates these indexes through ACS.

| Index | Macro | Purpose | Max Size |
|-------|-------|---------|----------|
| `cisco_aci` | `cisco_dc_aci_index` | ACI fabric data | 512 GB |
| `cisco_nd` | `cisco_dc_nd_index` | Nexus Dashboard data | 512 GB |
| `cisco_nexus_9k` | `cisco_dc_nexus_9k_index` | Nexus 9K switch data | 512 GB |

Partial runs: `--indexes-only` or `--macros-only`.

### Step 2: Configure Account

Before running, the agent must obtain from the user (non-secret values only):
- Account name (e.g., "CVF_NYC")
- Device hostname(s) or IP(s)
- Username for the device
- Device password — user writes to temp file; agent passes `--password-file`

The configure script stores credentials securely via Splunk's encrypted credential manager:

```bash
bash scripts/configure_account.sh \
  --type aci \
  --name "MY_FABRIC" \
  --hostname "10.0.0.1,10.0.0.2,10.0.0.3" \
  --port 443 \
  --auth-type password_authentication \
  --username "device_user" \
  --password-file /tmp/device_pass
```

Account types: `aci` (uses `--hostname`), `nd` (uses `--hostname`), `nexus9k` (uses `--device-ip`).

### Step 3: Enable Inputs

```bash
bash scripts/setup.sh --enable-inputs --account "MY_FABRIC" --index "cisco_aci" --input-type aci
```

| Input Type | Inputs Enabled | Index |
|------------|---------------|-------|
| `aci` | 9 inputs (auth, faults, audit, endpoints, fex, health, tenants, microseg, stats) | `cisco_aci` |
| `nd` | 11 inputs (advisories, anomalies, congestion, endpoints, fabrics, switches, flows, protocols, MSO) | `cisco_nd` |
| `nexus9k` | 10 inputs (hostname, version, module, inventory, temp, interfaces, neighbors, transceivers, power, resources) | `cisco_nexus_9k` |

### Step 4: Restart If Required

On Splunk Enterprise, restart Splunk after new index creation.
On Splunk Cloud, check `acs status current-stack` and only run
`acs restart current-stack` when ACS reports `restartRequired=true`.

### Step 5: Validate

```bash
bash scripts/validate.sh
```

Checks: app installation, indexes, macros, accounts, inputs, data flow, settings.

## Sourcetypes (from live ACI data)

| Sourcetype | Source Example | Content |
|---|---|---|
| `cisco:dc:aci:class` | `cisco_nexus_aci://classInfo_*`, `cisco_nexus_aci://microsegment` | Faults, endpoints, ACLs, audit, topology |
| `cisco:dc:aci:health` | `cisco_nexus_aci://health_*`, `cisco_nexus_aci://fex` | Fabric health scores, FEX status |
| `cisco:dc:aci:authentication` | `cisco_nexus_aci://authentication` | APIC session/login records |

## MCP Server Integration

```bash
bash scripts/load_mcp_tools.sh
```

Tools: `cisco_dc_check_health`, `cisco_dc_list_inputs`, `cisco_dc_aci_faults`,
`cisco_dc_aci_endpoints`, `cisco_dc_aci_health_summary`, `cisco_dc_aci_audit_log`,
`cisco_dc_nd_anomalies`, `cisco_dc_n9k_interface_stats`.

## Key Learnings / Known Issues

1. **Password storage**: The configure script stores credentials in Splunk's
   encrypted password store automatically. Use `--password-file` for device passwords.
2. **Restart behavior differs by platform**: Enterprise requires a Splunk
   restart after new index creation. Splunk Cloud uses ACS restart checks.
3. **No sudo needed**: Scripts run fine as the `splunk` OS user.
4. **Health data shape**: ACI health events don't always populate `healthAvg`
   at the top level — the dn-based structure varies by object type.
5. **Fault codes**: F0103 (interface down), F1011/F1014 (missing policy relations)
   are the most common in typical ACI fabrics.

## Additional Resources

- [reference.md](reference.md) — Complete input catalog, account fields, sizing
- [mcp_tools.json](mcp_tools.json) — MCP tool definitions

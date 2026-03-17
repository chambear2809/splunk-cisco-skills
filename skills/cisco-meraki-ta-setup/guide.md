# Quick Start Guide — Cisco Meraki TA Agent

This guide explains how to use the Cursor AI agent with the `cisco-meraki-ta-setup`
skill to automate Cisco Meraki Add-on deployments on Splunk.

## What It Does

The skill automates the full lifecycle of the **Splunk Add-on for Cisco Meraki**
(`Splunk_TA_cisco_meraki` v3.2.0), which collects data from the Meraki Dashboard
API including:

- **Devices** — inventory, availability, uplinks, power, firmware
- **Security** — organization security events, Air Marshal, MX appliances
- **Wireless** — APs, controllers, packet loss, ethernet status
- **Switches** — ports, transceivers, power history, energy usage
- **VPN** — SD-WAN statistics and tunnel statuses
- **Licensing** — overview, coterm, subscriptions
- **Operations** — audit log, assurance alerts, API usage, sensor readings

## How to Use

### Fresh Install (Full Setup)

Just tell the agent what you want:

> "Set up the Cisco Meraki TA for my organization."

The agent will ask you for:
- Meraki Dashboard API key
- Meraki organization ID
- Region (global, india, canada, china, fedramp)
- Splunk admin username and password

Then it will create the `meraki` index, configure the organization account via
REST API (with automatic API key encryption), auto-create all inputs, and tell
you to restart Splunk.

### Manual Input Setup

If you prefer not to use auto-create:

> "Set up Meraki but let me pick which inputs to enable."

The agent will create the account without auto-create, then ask which input
groups you want: core, devices, wireless, summary, api, vpn, licenses,
switches, organization, sensor, or all.

### Setting Up Dashboards

> "Set up the Meraki dashboards."

The agent will update the `meraki_index` macro in the TA so all 32 built-in
dashboards point to the correct index instead of the default `main`.

### Checking Status

> "Validate the Meraki TA setup."
> "Are we getting data in the meraki index?"

### Loading MCP Tools

> "Load the Meraki MCP tools."

This gives any MCP-connected client direct access to Meraki searches for
devices, audit, security, VPN, licenses, and more.

## Example Conversation

```
You:   I just installed the Cisco Meraki TA. Set it up.

Agent: I need a few details:
       - Account name? (e.g., "MY_ORG")
       - Meraki Dashboard API key?
       - Meraki organization ID?
       - Region? (global, india, canada, china, fedramp)
       - Splunk username and password?

You:   Name: CVF, API key: abc123..., org ID: 685673043267160891
       Region: global, Splunk: splunk / SplunkPass1!

Agent: [Creates meraki index]
       [Creates organization account via REST API with auto-input-creation]
       All 39 standard inputs auto-created.
       [Updates meraki_index macro to point to meraki index]
       Please restart Splunk to activate the new index.

You:   Done, restarted.

Agent: [Runs validation, queries REST API]
       meraki index active with events across 35+ sourcetypes. Setup complete.
```

## How Credentials Work

The agent will **ask you** for credentials when needed — nothing is hardcoded.

| Credential | What It's For | When Agent Asks |
|------------|---------------|-----------------|
| **Splunk user/pass** | REST API calls for account creation, validation, MCP tools | Account setup, validation |
| **Meraki API key** | Authenticating to Meraki Dashboard API | Account configuration |
| **Meraki org ID** | Identifying the Meraki organization | Account configuration |

## File Reference

| File | Purpose |
|------|---------|
| `SKILL.md` | Agent instructions |
| `reference.md` | Input catalog, account fields, sizing |
| `guide.md` | This file |
| `mcp_tools.json` | 8 MCP tool definitions |
| `scripts/setup.sh` | Creates indexes, enables inputs |
| `scripts/configure_account.sh` | Creates accounts via REST API |
| `scripts/setup_dashboards.sh` | Configures companion app for Meraki dashboards |
| `scripts/validate.sh` | Validates deployment |
| `scripts/load_mcp_tools.sh` | Loads MCP tools into KV Store |

## Tips

- The agent will ask for credentials — never assumes them
- No `sudo` needed — scripts work as the `splunk` OS user
- After index creation, Splunk must be restarted
- Use `--auto-inputs` when creating the account to auto-create all 39 inputs
- The webhook input requires separate HEC configuration
- Rate limit defaults to 5 API calls/sec (max 10)
- Region determines which Meraki API endpoint is used

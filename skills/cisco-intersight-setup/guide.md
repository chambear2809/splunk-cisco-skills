# Quick Start Guide — Cisco Intersight TA Agent

This guide explains how to use the Cursor AI agent with the `cisco-intersight-setup`
skill to automate Cisco Intersight Add-on deployments on Splunk.

## What It Does

The skill automates the full lifecycle of the **Cisco Intersight Add-On for Splunk**
(`Splunk_TA_Cisco_Intersight` v3.1.0), which collects data from:

- **Audit & Alarms** — login/logout events, CRUD operations, active/historical alarms
- **Inventory** — servers, Fabric Interconnects, profiles, targets, contracts, licenses, advisories, pools, ports
- **Metrics** — CPU, memory, fan, temperature, network throughput
- **Custom Inputs** — arbitrary Intersight API endpoint queries

## How to Use

### Fresh Install (Full Setup)

Just tell the agent what you want:

> "Set up the Cisco Intersight TA. My Intersight account uses Client ID abc123."

The agent will ask you for:
- Intersight Client Secret
- Intersight hostname (defaults to intersight.com for SaaS)
- Account name
- Splunk admin username and password

Then it will create the index, configure the account via REST API (with automatic
credential encryption), enable inputs, and tell you to restart Splunk.

### Adding More Inputs

> "Enable metrics collection for my Intersight account."

### Checking Status

> "Validate the Intersight TA setup."
> "Are we getting data in the intersight index?"

### Loading MCP Tools

> "Load the Intersight TA MCP tools."

This gives any MCP-connected client direct access to Intersight searches.

## Example Conversation

```
You:   I just installed the Cisco Intersight TA. Set it up.

Agent: I need a few details:
       - Account name? (e.g., "CVF_Intersight")
       - Intersight hostname? (default: intersight.com)
       - OAuth2 Client ID?
       - OAuth2 Client Secret?
       - Splunk username and password?

You:   Name: CVF_Intersight, hostname: intersight.com
       Client ID: abc123def456...
       Client Secret: secret789xyz...
       Splunk: splunk / SplunkPass1!

Agent: [Creates index: intersight]
       [Updates macro: cisco_intersight_index]
       [Creates Intersight account via REST API]
       [Enables 7 inputs: 2 audit/alarms, 3 inventory, 2 metrics]
       Please restart Splunk to activate the new index.

You:   Done, restarted.

Agent: [Runs validation, queries REST API]
       Index active. intersight index receiving events across
       multiple sourcetypes. Setup complete.
```

## How Credentials Work

The agent will **ask you** for credentials when needed — nothing is hardcoded.

| Credential | What It's For | When Agent Asks |
|------------|---------------|-----------------|
| **Splunk user/pass** | REST API calls for account creation, validation, MCP tools | Account setup, validation |
| **Intersight Client ID** | OAuth2 authentication to Intersight API | Account configuration |
| **Intersight Client Secret** | OAuth2 authentication to Intersight API | Account configuration |

## Key Differences from Other Cisco TA Skills

| Feature | Catalyst TA | DC Networking TA | Intersight TA |
|---------|-------------|------------------|---------------|
| Auth method | Username/password | Username/password | OAuth2 (Client ID/Secret) |
| Account types | 4 (CatC, ISE, SDWAN, CV) | 3 (ACI, ND, N9K) | 1 (Intersight) |
| Credential storage | Custom REST handler | /storage/passwords | Custom REST handler |
| KVStore usage | No | No | Yes (extensive inventory) |
| CIM mapping | Limited | Limited | Full (Alerts, Auth, Change, Performance) |

## File Reference

| File | Purpose |
|------|---------|
| `SKILL.md` | Agent instructions |
| `reference.md` | Input catalog, account fields, sizing |
| `guide.md` | This file |
| `mcp_tools.json` | MCP tool definitions |
| `scripts/setup.sh` | Creates indexes, macros, enables inputs |
| `scripts/configure_account.sh` | Creates accounts via REST API |
| `scripts/validate.sh` | Validates deployment |
| `scripts/load_mcp_tools.sh` | Loads MCP tools into KV Store |

## Tips

- The agent will ask for credentials — never assumes them
- No `sudo` needed — scripts work as the `splunk` OS user
- After any index changes, Splunk must be restarted
- Intersight uses OAuth2 (Client ID + Client Secret), not username/password
- The TA stores inventory in KVStore collections for dashboard lookups
- Up to 10 custom inputs can query arbitrary Intersight API endpoints
- Default Intersight hostname is `intersight.com` (SaaS); use custom hostname for on-prem appliances

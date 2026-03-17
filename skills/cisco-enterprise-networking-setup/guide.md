# Quick Start Guide — Cisco Enterprise Networking Agent

This guide explains how to use the Cursor AI agent with the
`cisco-enterprise-networking-setup` skill to configure the Cisco Enterprise
Networking dashboards on Splunk.

## What It Does

The skill automates the **Cisco Enterprise Networking for Splunk Platform**
(`cisco-catalyst-app` v3.0.0), which provides dashboards for:

- **Cisco Catalyst Center** — network health, issues, compliance, advisories
- **Cisco ISE** — authentication, security posture, endpoint profiling
- **Cisco SD-WAN** — WAN health, tunnel status, NetFlow
- **Cisco Cyber Vision** — OT devices, activities, vulnerabilities

**Important**: This app only provides dashboards. Data collection is handled by
the Cisco Catalyst Add-on (`TA_cisco_catalyst`). Use the
`cisco-catalyst-ta-setup` skill first to set up data collection.

## How to Use

### Configure After TA Setup

> "I just set up the Catalyst TA. Now configure the Enterprise Networking
> dashboards."

The agent will update the index macro to match your TA indexes and verify
saved searches are enabled.

### Custom Index List

> "Update the Enterprise Networking app to search indexes catalyst, ise,
> and meraki."

### Enable Data Model Acceleration

> "Enable data model acceleration for the Enterprise Networking app."

### Check Status

> "Validate the Enterprise Networking app setup."
> "Are the dashboards working?"

### Load MCP Tools

> "Load the Enterprise Networking MCP tools."

## Example Conversation

```
You:   The Catalyst TA is configured. Set up the dashboards app.

Agent: I'll update the index macro and verify the dashboards. What's your
       Splunk username and password?

You:   splunk / MyPass1!

Agent: [Updates cisco_catalyst_app_index to include catalyst, ise, sdwan, cybervision]
       [Verifies all 8 dashboards are present]
       [Checks saved searches are enabled]
       [Queries REST API for data in each index]
       
       Setup complete. The cisco_catalyst_app_index macro now searches
       all 4 product indexes. Dashboards should populate within the
       saved search schedule (hourly for locations, daily for lookups).
       
       Tip: Enable data model acceleration for production use.
```

## How Credentials Work

The agent will **ask you** for Splunk credentials when needed.

| Credential | What It's For | When Agent Asks |
|------------|---------------|-----------------|
| **Splunk user/pass** | REST API for validation and MCP tools | Validation, MCP tool loading |

## Relationship to Catalyst TA

```
┌─────────────────────────┐     ┌─────────────────────────────┐
│   TA_cisco_catalyst     │     │   cisco-catalyst-app         │
│   (Data Collection)     │────>│   (Dashboards & Searches)    │
│                         │     │                              │
│ • Catalyst Center acct  │     │ • cisco_catalyst_app_index   │
│ • ISE account           │     │ • 8 dashboards               │
│ • SD-WAN account        │     │ • 5 saved searches           │
│ • Cyber Vision account  │     │ • 1 data model               │
│ • 18 input types        │     │                              │
│                         │     │ Reads from indexes:           │
│ Writes to indexes:      │     │   catalyst, ise, sdwan,      │
│   catalyst, ise, sdwan, │     │   cybervision                │
│   cybervision           │     │                              │
└─────────────────────────┘     └─────────────────────────────┘
```

## File Reference

| File | Purpose |
|------|---------|
| `SKILL.md` | Agent instructions |
| `reference.md` | Macros, saved searches, dashboards, data model |
| `guide.md` | This file |
| `mcp_tools.json` | 6 MCP tool definitions |
| `scripts/setup.sh` | Updates macros, enables acceleration |
| `scripts/validate.sh` | Validates deployment |
| `scripts/load_mcp_tools.sh` | Loads MCP tools into KV Store |

## Tips

- Always set up the TA first, then this app
- The `cisco_catalyst_app_index` macro must match the TA's indexes
- Data model acceleration improves dashboard performance in production
- Saved searches build lookups on a schedule — run them manually if needed

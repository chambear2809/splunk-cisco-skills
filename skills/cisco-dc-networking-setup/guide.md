# Quick Start Guide — Cisco DC Networking Agent

This guide explains how to use the Cursor AI agent with the `cisco-dc-networking-setup`
skill to automate Cisco DC Networking TA deployments on Splunk.

## What Is This?

A Cursor **Agent Skill** that teaches the AI assistant how to:

- Set up the Cisco DC Networking App for Splunk from scratch
- Create indexes, configure device accounts, enable data inputs
- Store credentials securely in Splunk's credential manager
- Validate that data is flowing correctly
- Load custom MCP tools for AI-powered Splunk queries

The skill activates automatically when you mention Cisco DC networking, ACI,
APIC, Nexus Dashboard, Nexus 9K, or Splunk TA setup in conversation.

## How to Use

### Fresh Install (Full Setup)

Just tell the agent what you want:

> "I just installed the Cisco DC Networking app on Splunk. Set it up with
> my ACI fabric at 10.0.0.1,10.0.0.2,10.0.0.3 using username admin."

The agent will:
1. Run `setup.sh` to create indexes and macros
2. Run `configure_account.sh` to create the ACI account
3. Store the password in Splunk's credential manager via REST API
4. Run `setup.sh --enable-inputs` to enable all ACI inputs
5. Prompt you to restart Splunk
6. Run `validate.sh` to verify everything is working

### Add a New Device

> "Add a Nexus 9K switch at 10.0.1.50 called CORE-SW-01 to the DC networking TA."

The agent will configure the Nexus 9K account and enable the 10 switch inputs.

### Check Status

> "Is my Cisco DC networking data collection healthy?"

The agent will run the validation script and/or query the Splunk REST API to
check index event counts, input status, and recent data flow.

### Load MCP Tools

> "Load the Cisco DC networking tools into the Splunk MCP Server."

The agent will run `load_mcp_tools.sh` to register 8 custom search tools in
the MCP Server's KV Store.

### Investigate ACI Issues

> "Show me the critical ACI faults in the last 4 hours."

The agent will query the `cisco_aci` index via the Splunk REST API and
present fault codes, severities, and affected objects.

## Example Conversations

### Example 1: First-Time Setup

```
You:   Set up the Cisco DC Networking TA for my ACI fabric.

Agent: I'll need a few details to configure the account:
       - What's the account name? (e.g., "PROD_ACI")
       - APIC hostname(s) or IP(s)?
       - APIC username?
       - APIC password?
       - Splunk username and password? (to store credentials securely)

You:   Account: CVF_NYC, APICs: 10.110.7.110,10.110.7.111,10.110.7.112
       APIC user: aleccham, password: MyApicPass1!
       Splunk user: splunk, password: MySplunkPass1!

Agent: [Creates indexes and macros]
       [Configures ACI account CVF_NYC]
       [Stores password in Splunk credential manager]
       [Enables 9 ACI inputs]
       Please restart Splunk to activate the new indexes.

You:   Done, restarted.

Agent: [Queries REST API for event counts]
       All 3 indexes active. cisco_aci receiving ~13K events/5min
       across 3 sourcetypes. Setup complete.
```

### Example 2: Adding Nexus Dashboard

```
You:   Add our Nexus Dashboard.

Agent: I need the connection details:
       - Account name?
       - Nexus Dashboard hostname?
       - Username and password?

You:   Name: PROD_ND, host: nd.mycompany.com, user: ndadmin, pass: NdPass1!

Agent: [Configures ND account, enables 11 ND inputs, stores credentials]
       Restart Splunk to activate. After restart I'll verify data flow.
```

### Example 3: Troubleshooting

```
You:   I'm not seeing any data in the cisco_aci index.

Agent: Let me check. What's your Splunk username and password so I can
       query the REST API?

You:   splunk / MyPass1!

Agent: [Checks inputs.conf, account conf, REST API for errors]
       Found the issue: password wasn't stored in the credential manager.
       Storing now... Done. Data should appear within 5 minutes.
```

## File Reference

| File | Purpose |
|------|---------|
| `SKILL.md` | Main skill instructions (read by the agent) |
| `reference.md` | Complete input catalog, account fields, index sizing |
| `guide.md` | This guide |
| `mcp_tools.json` | 8 custom MCP tool definitions |
| `scripts/setup.sh` | Create indexes, macros, enable inputs |
| `scripts/configure_account.sh` | Configure ACI/ND/Nexus 9K accounts |
| `scripts/validate.sh` | Full deployment validation |
| `scripts/load_mcp_tools.sh` | Load tools into Splunk MCP Server |

## How Credentials Work

Splunk credentials are read from the project-root `credentials` file (falls back to
`~/.splunk/credentials`) automatically. Device passwords should be provided via
`--password-file`:

| Credential | How It's Handled |
|------------|-----------------|
| **Splunk user/pass** | Read from project-root `credentials` (run `setup_credentials.sh` to configure) |
| **Device user/pass** | Passed via `--password-file /path/to/file` to `configure_account.sh` |

## Tips

- The agent will never ask for passwords in chat
- No `sudo` needed — scripts work as the `splunk` OS user
- After any account or input changes, Splunk must be restarted
- The agent can query data directly via the Splunk REST API for live verification
- MCP tools give any MCP-connected client (Claude, Cursor, etc.) direct access
  to Cisco DC searches without writing SPL manually

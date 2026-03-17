# Quick Start Guide — Cisco Catalyst TA Agent

This guide explains how to use the Cursor AI agent with the `cisco-catalyst-ta-setup`
skill to automate Cisco Catalyst Add-on deployments on Splunk.

## What It Does

The skill automates the full lifecycle of the **Cisco Catalyst Add-on for Splunk**
(`TA_cisco_catalyst` v3.0.0), which collects data from:

- **Cisco Catalyst Center** (formerly DNA Center) — issues, health, compliance, advisories
- **Cisco ISE** — authentication, admin data, SGT mappings
- **Cisco SD-WAN** — WAN health, tunnel status
- **Cisco Cyber Vision** — OT activities, devices, flows, vulnerabilities

## How to Use

### Fresh Install (Full Setup)

Just tell the agent what you want:

> "Set up the Cisco Catalyst TA for my Catalyst Center at 10.100.0.60,
> username admin."

The agent will ask you for non-secret values (hostnames, account names, usernames).
Passwords and secrets are read from credential files — the agent will **never** ask
for passwords in chat. If credentials are not yet configured, the agent will guide
you to run `setup_credentials.sh` or create a temporary secret file.

It will then create indexes, configure the account via REST API (with automatic
password encryption), enable all 9 Catalyst Center inputs, and tell you to
restart Splunk.

### Adding ISE

> "Add my ISE server to the Catalyst TA."

The agent will ask for non-secret values:
- Account name (e.g., "PROD_ISE")
- ISE host URL
- ISE username

Passwords are handled via credential files, not in chat.

### Adding SD-WAN

> "Configure SD-WAN data collection."

### Adding Cyber Vision

> "Set up Cyber Vision. My portal is at 192.168.1.100."

The agent will ask for your API token (Cyber Vision uses tokens, not passwords).

### Checking Status

> "Validate the Catalyst TA setup."
> "Are we getting data in the catalyst index?"

### Loading MCP Tools

> "Load the Catalyst TA MCP tools."

This gives any MCP-connected client direct access to Catalyst Center, ISE,
SD-WAN, and Cyber Vision searches.

## Example Conversation

```
You:   I just installed the Cisco Catalyst TA. Set it up for Catalyst Center.

Agent: I need a few details:
       - Account name? (e.g., "PROD_CATC")
       - Catalyst Center URL? (e.g., https://10.100.0.60)
       - Catalyst Center username?

       Splunk and device passwords are read from credential files.
       Have you run setup_credentials.sh yet?

You:   Yes. Name: CVF_Cat_Center, host: https://10.100.0.60, user: admin

Agent: I'll also need the Catalyst Center password in a file:
       echo "the_password" > /tmp/catc_pass && chmod 600 /tmp/catc_pass

You:   Done.

Agent: [Creates indexes: catalyst, ise, sdwan, cybervision]
       [Creates Catalyst Center account via REST API using --password-file]
       [Enables 9 Catalyst Center inputs]
       Please restart Splunk and delete /tmp/catc_pass.

You:   Done, restarted.

Agent: [Runs validation, queries REST API]
       All 4 indexes active. catalyst index receiving events across
       9 sourcetypes. Setup complete.
```

## How Credentials Work

The agent **never asks for passwords in chat**. All secrets are handled via files.

| Credential | Source | How It's Used |
|------------|--------|---------------|
| **Splunk user/pass** | Project-root `credentials` file (falls back to `~/.splunk/credentials`) | REST API calls for setup, validation, MCP tools |
| **Catalyst Center password** | `--password-file /tmp/secret` | Account configuration via REST API |
| **ISE password** | `--password-file /tmp/secret` | Account configuration |
| **SD-WAN password** | `--password-file /tmp/secret` | Account configuration |
| **Cyber Vision API token** | `--api-token-file /tmp/token` | Account configuration |

Run `bash skills/shared/scripts/setup_credentials.sh` to set up Splunk credentials.
For device passwords, create a temporary file and pass the path to the script.

## Prerequisites

Ensure Splunk credentials are configured:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

## Improvement Over DC Networking Skill

This skill uses the TA's **REST API handlers** to create accounts, which
automatically handle password encryption. No manual `/storage/passwords` calls
needed — the custom handlers do it transparently.

## File Reference

| File | Purpose |
|------|---------|
| `SKILL.md` | Agent instructions |
| `reference.md` | Input catalog, account fields, sizing |
| `guide.md` | This file |
| `mcp_tools.json` | 8 MCP tool definitions |
| `scripts/setup.sh` | Creates indexes, enables inputs |
| `scripts/configure_account.sh` | Creates accounts via REST API |
| `scripts/validate.sh` | Validates deployment |
| `scripts/load_mcp_tools.sh` | Loads MCP tools into KV Store |

## Tips

- The agent reads credentials from files — never asks for passwords in chat
- No `sudo` needed — scripts work as the `splunk` OS user
- After any index or input changes, Splunk must be restarted
- Cyber Vision uses API tokens, not username/password
- ISE input accepts multiple data types in one input stanza

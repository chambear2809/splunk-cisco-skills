---
name: cisco-catalyst-enhanced-netflow-setup
description: >-
  Install and validate the Cisco Catalyst Enhanced Netflow Add-on for Splunk
  (splunk_app_stream_ipfix_cisco_hsl). Use when the user asks about the
  optional Enhanced Netflow add-on, Cisco HSL/IPFIX mappings, app ID 6872, or
  extra Cisco Enterprise Networking NetFlow dashboards.
---

# Cisco Catalyst Enhanced Netflow Add-on Setup

Automates installation and validation of the **Cisco Catalyst Enhanced Netflow
Add-on for Splunk** (`splunk_app_stream_ipfix_cisco_hsl`).

## Package Model

**Pull from Splunkbase first (latest version), fall back to `splunk-ta/`.**
Use `skills/cisco-catalyst-enhanced-netflow-setup/scripts/setup.sh --install`
to install the add-on through the shared app installer. The script resolves the
latest Splunkbase release for app ID `6872` and falls back to the local package
cache when needed.

This add-on is **optional**. It adds Cisco HSL/IPFIX element mappings for extra
NetFlow-focused dashboards in Cisco Enterprise Networking. It does **not**
create accounts, inputs, or indexes of its own.

## Agent Behavior

**The agent must NEVER ask for passwords or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials`
file (falls back to `~/.splunk/credentials`). If neither exists, guide the user
to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

The agent may ask non-secret questions such as:
- whether the user wants the optional NetFlow-focused dashboards
- whether a NetFlow/IPFIX receiver already exists
- whether the target is a standalone Splunk instance or a forwarder/heavy forwarder

## Environment

This add-on targets **forwarder-side or standalone Splunk deployments**. The
package manifest declares `_forwarders` as the target workload.

Run this skill against the Splunk instance that parses or receives the
NetFlow/IPFIX data. In a hybrid environment that also has Splunk Cloud
credentials, set:

```bash
export SPLUNK_PLATFORM=enterprise
```

before using this skill so the scripts target the forwarder-side management API
instead of the Cloud search tier.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Preferred install target | Standalone Splunk or customer-controlled HF/UF |
| App name | `splunk_app_stream_ipfix_cisco_hsl` |
| Splunkbase ID | `6872` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-catalyst-enhanced-netflow-setup/scripts/` |

## Setup Workflow

### Step 1: Install The Add-on

```bash
bash skills/cisco-catalyst-enhanced-netflow-setup/scripts/setup.sh --install
```

This installs the optional add-on from Splunkbase first, then falls back to the
local package cache in `splunk-ta/` if needed.

### Step 2: Review The NetFlow Receiver Context

```bash
bash skills/cisco-catalyst-enhanced-netflow-setup/scripts/setup.sh
```

The setup script confirms that the add-on is installed and reports whether the
same target also has `Splunk_TA_stream` configured with a NetFlow receiver.

### Step 3: Validate

```bash
bash skills/cisco-catalyst-enhanced-netflow-setup/scripts/validate.sh
```

Checks: app installation, Stream forwarder context, NetFlow receiver settings,
and optional consumer apps.

## What This Add-on Does

- Ships static IPFIX mappings in `default/ipfixmap.conf`
- Ships Cisco HSL field metadata in `default/cisco.hsl.json` and `default/cisco.hsl.xml`
- Requires a Splunk restart after install
- Does not expose custom REST handlers, account stanzas, or input stanzas

## Key Learnings / Known Issues

1. **No app-local setup surface**: There are no accounts or inputs to configure
   inside this add-on. Installation plus receiver-path validation is the real workflow.
2. **Forwarder-side target**: The package manifest targets `_forwarders`, so do
   not treat this like a Cloud search-tier app.
3. **Existing NetFlow path required**: This add-on only contributes field
   mappings. It does not create the NetFlow/IPFIX receiver itself.
4. **Stream alignment matters**: If the host should receive NetFlow/IPFIX, use
   the `splunk-stream-setup` skill to configure `Splunk_TA_stream`.
5. **Dashboard consumption is optional**: The add-on is most often used to add
   extra dashboard coverage for `cisco-catalyst-app`, but it can be installed
   independently on the parsing tier.

## Additional Resources

- [reference.md](reference.md) — package contents, topology, and validation notes

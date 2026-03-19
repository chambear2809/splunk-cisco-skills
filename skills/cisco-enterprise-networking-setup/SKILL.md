---
name: cisco-enterprise-networking-setup
description: >-
  Automate Cisco Enterprise Networking for Splunk Platform (cisco-catalyst-app)
  setup. Configures index macros, sourcetype macros, saved searches, data model
  acceleration, and validates dashboards. Use when the user asks about Cisco
  Enterprise Networking app, cisco-catalyst-app, Catalyst dashboards, ISE
  dashboards, SD-WAN dashboards, or Cyber Vision dashboards.
---

# Cisco Enterprise Networking App Setup Automation

Automates the **Cisco Enterprise Networking for Splunk Platform**
(`cisco-catalyst-app` v3.0.0).

## Package Model

**Pull from Splunkbase first (latest version), fall back to `splunk-ta/`.**
Use `splunk-app-install` with `--source splunkbase --app-id 7539` to get the
latest release. If Splunkbase is unavailable, fall back to the local package
in `splunk-ta/`. This applies to both Splunk Cloud (ACS) and Splunk Enterprise.

After installation, use this skill to configure macros, saved searches,
acceleration, and validation over search-tier REST. Any `splunk-ta/_unpacked/`
tree is review-only.

This is a **visualization app** — it provides dashboards and saved searches but
does not collect data. Data collection is handled by the companion
**Cisco Catalyst Add-on** (`TA_cisco_catalyst`). Use the
`cisco-catalyst-ta-setup` skill for TA configuration.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials` file
(falls back to `~/.splunk/credentials`). If neither exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

The agent may freely ask for non-secret values: index names, macro settings, etc.

## Environment

Setup and validation use the Splunk search-tier REST API and can run from any
host with network access to the Splunk management port (`8089`). In Splunk
Cloud, stack-level restarts are handled through ACS instead of the search-tier
REST endpoints.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs (`SPLUNK_PLATFORM` is only an override for hybrid runs) |
| TA app name | `cisco-catalyst-app` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-enterprise-networking-setup/scripts/` (relative to repo root) |

### Remote Splunk Connection

To run against a remote Splunk instance:

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

## Prerequisites

The Cisco Catalyst Add-on (`TA_cisco_catalyst`) must be installed and configured
before this app can display data. Use the `cisco-catalyst-ta-setup` skill first.

## Setup Workflow

### Step 1: Update Index Macro

The app uses the `cisco_catalyst_app_index` macro to know which indexes to
search. This must match the indexes configured in the TA.

```bash
bash skills/cisco-enterprise-networking-setup/scripts/setup.sh
```

This updates `cisco_catalyst_app_index` to include all four product indexes:
`catalyst`, `ise`, `sdwan`, `cybervision`.

Partial runs: `--macros-only`, `--custom-indexes "idx1,idx2,idx3"`.

### Step 2: Enable Saved Searches

The app has 5 saved searches that build lookup tables. The setup script enables
them by default:

| Saved Search | Schedule | Lookup Built |
|---|---|---|
| `cisco_catalyst_location` | Hourly | `cisco_catalyst_ise_location.csv` |
| `cisco_catalyst_sdwan_netflow` | Daily | `cisco_catalyst_sdwan_application_tag` (KV) |
| `cisco_catalyst_sdwan_policy` | Daily | `cisco_catalyst_sdwan_policy_mapping` (KV) |
| `cisco_catalyst_meraki_organization_mapping` | Daily | `meraki_org_id_name_lookup.csv` |
| `cisco_catalyst_meraki_devices_serial_mapping` | Daily | `cisco_catalyst_meraki_device_serial_mapping.csv` |

### Step 3: Enable Data Model Acceleration (Optional)

```bash
bash skills/cisco-enterprise-networking-setup/scripts/setup.sh --accelerate
```

Enables acceleration on the `Cisco_Catalyst_App` data model for faster
dashboard loading.

If Splunk Cloud later reports `restartRequired=true`, use
`acs restart current-stack` instead of trying to restart the deployment through
the search-tier REST API.

### Step 4: Validate

```bash
bash skills/cisco-enterprise-networking-setup/scripts/validate.sh
```

Checks: app installation, macros, saved searches, data model, data presence.

## Macros

| Macro | Default | Purpose |
|---|---|---|
| `cisco_catalyst_app_index` | `index IN ("main")` | Tells dashboards which indexes to search |
| `cisco_catalyst_app_sourcetypes` | `sourcetype IN ("cisco:ise*", "cisco:sdwan*", "cisco:dnac*", ...)` | Filters to known Cisco sourcetypes |
| `summariesonly` | `summariesonly=false` | Controls data model acceleration usage |

The setup script updates `cisco_catalyst_app_index` to:
```
index IN ("catalyst", "ise", "sdwan", "cybervision")
```

## Dashboards

| Dashboard | Description |
|---|---|
| Overview | High-level summary across all products |
| Network Insights | Network health and topology |
| Security Insights | ISE and security posture |
| Events And Incident Viewer | Event timeline and drill-down |
| Endpoints (Clients) | Client/endpoint details |
| Users And Applications | User and application activity |
| Performance | Network performance metrics |
| Sensors | Sensor and device telemetry |

## MCP Server Integration

```bash
bash skills/cisco-enterprise-networking-setup/scripts/load_mcp_tools.sh
```

## Key Learnings / Known Issues

1. **Macro alignment**: The `cisco_catalyst_app_index` macro MUST include all
   indexes configured in the TA, or dashboards will show no data.
2. **Data model acceleration**: Enable for production; keep disabled during
   initial setup/testing.
3. **Saved searches**: The lookup-building saved searches should run at least
   once before dashboards referencing those lookups will populate.
4. **No inputs here**: This app only visualizes — all data collection config
   belongs in the TA (`TA_cisco_catalyst`).
5. **No `configure_account.sh`**: Unlike the TA skills, this app does not
   collect data and has no add-on accounts to configure. Account and input
   setup belongs in the companion `cisco-catalyst-ta-setup` skill.

## Additional Resources

- [reference.md](reference.md) — Macro definitions, saved searches, dashboards
- [mcp_tools.json](mcp_tools.json) — MCP tool definitions

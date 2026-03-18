---
name: cisco-thousandeyes-setup
description: >-
  Automate Cisco ThousandEyes App for Splunk (ta_cisco_thousandeyes) setup and
  configuration. Handles OAuth 2.0 device code authentication, HEC token
  management, index creation, streaming and polling data inputs, and optional
  ITSI integration. Use when the user asks about ThousandEyes, network
  monitoring, path visualization, CEA tests, endpoint tests, or
  ta_cisco_thousandeyes.
---

# Cisco ThousandEyes App Setup Automation

Automates the **Cisco ThousandEyes App for Splunk** (`ta_cisco_thousandeyes` v0.6.0).

## How This App Differs From Other Cisco TAs

This app is architecturally different from the Catalyst, Meraki, Intersight, and
DC Networking TAs in several ways:

- **OAuth 2.0 Device Code Flow** — no API keys or passwords. The user must
  visit a URL in their browser to authorize.
- **HEC-based data delivery** — ThousandEyes pushes most data TO Splunk via HEC
  (HTTP Event Collector) streams, rather than Splunk polling an API.
- **Hybrid collection** — 3 delivery mechanisms: streaming (HEC push), API
  polling, and webhooks.
- **Full app with dashboards** — not just a TA. Includes network, application,
  voice, alerts, traces, and configuration status dashboards.
- **ITSI integration** — optional bidirectional integration with Splunk IT
  Service Intelligence.

## Package Model

**Pull from Splunkbase first (latest version), fall back to `splunk-ta/`.**
Use `splunk-app-install` with `--source splunkbase --app-id 7719` to get the
latest release. If Splunkbase is unavailable, fall back to the local package
in `splunk-ta/`. This applies to both Splunk Cloud (ACS) and Splunk Enterprise.

After installation, use this skill to authenticate via OAuth, configure HEC,
create indexes, and enable inputs. Any `splunk-ta/_unpacked/` tree is
review-only.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, API keys, or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials`
file (falls back to `~/.splunk/credentials`). If neither exists, guide the user
to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

### ThousandEyes OAuth Authentication

Unlike other TAs, this app uses an **interactive OAuth 2.0 device code flow**.
No password file or API key file is needed. Instead:

1. The `configure_account.sh` script initiates the OAuth flow and displays a
   **verification URL** and **user code**.
2. The agent instructs the user: "Visit the URL shown in your terminal and
   enter the code to authorize."
3. The script polls until the user completes authorization in their browser.
4. Tokens are stored and encrypted automatically by Splunk.

The agent never handles or sees the OAuth tokens.

## Environment

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs |
| App name | `ta_cisco_thousandeyes` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| HEC requirement | Required for metrics, traces, activity logs, and alerts inputs |
| Skill scripts | `skills/cisco-thousandeyes-setup/scripts/` (relative to repo root) |

### Remote Splunk Connection

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

## Splunk Authentication

Scripts read Splunk credentials from the project-root `credentials` file (falls
back to `~/.splunk/credentials`) automatically:

```bash
bash skills/cisco-thousandeyes-setup/scripts/validate.sh
```

If credentials are not yet configured:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

## Setup Workflow

### Step 1: Install the App

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source splunkbase --app-id 7719
```

### Step 2: Verify or Create HEC Token

ThousandEyes pushes most data via HEC. A valid HEC token and endpoint are
required before creating streaming inputs.

```bash
bash skills/cisco-thousandeyes-setup/scripts/setup.sh --hec-only
```

This checks for an existing HEC token named `thousandeyes` and creates one if
it does not exist. For Splunk Cloud, it uses ACS; for Enterprise, it uses the
REST API.

### Step 3: Create Indexes

```bash
bash skills/cisco-thousandeyes-setup/scripts/setup.sh --indexes-only
```

Creates six indexes. In Splunk Cloud, indexes are created through ACS.

| Index | Purpose | Sourcetype |
|-------|---------|------------|
| `thousandeyes_metrics` | Test metrics data | `cisco:thousandeyes:metric` |
| `thousandeyes_traces` | Test traces data | `cisco:thousandeyes:trace` |
| `thousandeyes_events` | ThousandEyes events | `cisco:thousandeyes:event` |
| `thousandeyes_activity` | Activity/audit logs | `cisco:thousandeyes:activity` |
| `thousandeyes_alerts` | Alert notifications | `cisco:thousandeyes:alerts` |
| `thousandeyes_pathvis` | Path visualization | `cisco:thousandeyes:path-vis` |

### Step 4: Authenticate via OAuth

```bash
bash skills/cisco-thousandeyes-setup/scripts/configure_account.sh
```

The script will:
1. Display a verification URL and user code
2. Wait for the user to authorize in their browser
3. Store the OAuth tokens in Splunk's encrypted credential store

The agent should instruct the user to visit the URL shown in the terminal
output and enter the displayed code.

### Step 5: Enable Inputs

Before running, the agent must ask the user for:
- ThousandEyes account name (the email shown after OAuth)
- ThousandEyes account group (ask user or use script to list available groups)
- Which input types to enable
- HEC token name (default: `thousandeyes`)

```bash
bash skills/cisco-thousandeyes-setup/scripts/setup.sh --enable-inputs \
  --account "user@example.com" \
  --account-group "My Account Group" \
  --hec-token "thousandeyes" \
  --input-type all
```

| Input Type | Delivery | Description |
|------------|----------|-------------|
| `metrics` | HEC stream | Test metrics via ThousandEyes Streaming API |
| `traces` | HEC stream | Test traces via ThousandEyes Streaming API |
| `events` | API polling | ThousandEyes events (default interval: 3600s) |
| `activity` | HEC stream | Activity/audit logs via Streaming API |
| `alerts` | HEC webhook | Alert notifications via webhook |
| `all` | Mixed | All of the above |

### Step 6: ITSI Integration (Optional)

If Splunk ITSI (`SA-ITOA`) is installed, the app can forward Splunk notable
events to ThousandEyes and receive alert data. The validate script checks for
ITSI presence automatically.

### Step 7: Restart If Required

On Splunk Enterprise, restart Splunk after new index creation.
On Splunk Cloud, check `acs status current-stack` and only run
`acs restart current-stack` when ACS reports `restartRequired=true`.

### Step 8: Validate

```bash
bash skills/cisco-thousandeyes-setup/scripts/validate.sh
```

Checks: app installation, HEC token, indexes, OAuth account, token refresh
input, data inputs, data flow, settings, and optional ITSI status.

## Sourcetypes

| Sourcetype | Delivery | Content |
|---|---|---|
| `cisco:thousandeyes:metric` | HEC stream | Test metrics (OpenTelemetry v2) |
| `cisco:thousandeyes:trace` | HEC stream | Test traces (OpenTelemetry v2) |
| `cisco:thousandeyes:path-vis` | API polling | Path visualization data |
| `cisco:thousandeyes:event` | API polling | ThousandEyes events |
| `cisco:thousandeyes:activity` | HEC stream | Activity/audit logs |
| `cisco:thousandeyes:alerts` | HEC webhook | Alert notifications |

## MCP Server Integration

```bash
bash skills/cisco-thousandeyes-setup/scripts/load_mcp_tools.sh
```

## Key Learnings / Known Issues

1. **OAuth device code flow**: This is the only authentication method. There is
   no API key or username/password option. The user must complete authorization
   in a browser.
2. **HEC is required**: Metrics, traces, activity logs, and alerts all require a
   working HEC endpoint. Verify HEC is enabled and the token is valid before
   creating streaming inputs.
3. **Token refresh**: The app includes a `thousandeyes_refresh_tokens` modular
   input that runs weekly to regenerate OAuth tokens. Ensure this input is
   enabled.
4. **Streaming API creates ThousandEyes-side resources**: When you create a
   metrics or traces input, the app creates a "stream" object in ThousandEyes
   that pushes data to Splunk. Deleting the input should clean up the stream.
5. **Alerts use webhooks**: The alerts input creates webhook operations and
   connectors in ThousandEyes that push data to Splunk's HEC endpoint.
6. **Cloud HEC URL format**: For Splunk Cloud, HEC targets use
   `https://http-inputs-{stack}.splunkcloud.com:443`.
7. **Client ID is hardcoded**: The OAuth client ID (`0oalgciz1dyS1Uonr697`) is
   built into the app; you do not need to provide it.
8. **ITSI is optional**: The ITSI integration only activates if `SA-ITOA` is
   installed. The app works fully without it.

## Additional Resources

- [reference.md](reference.md) — Complete input catalog, account fields, API
  endpoints, HEC configuration
- [mcp_tools.json](mcp_tools.json) — MCP tool definitions

---
name: cisco-appdynamics-setup
description: >-
  Automate Cisco Splunk Add-on for AppDynamics (Splunk_TA_AppDynamics) setup and
  configuration. Creates the AppDynamics index, sets add-on defaults, configures
  controller and optional analytics connections, enables common input groups,
  and validates the deployment. Use when the user asks about AppDynamics setup,
  Splunk_TA_AppDynamics, controller connections, analytics connections, or
  AppDynamics dashboards in Splunk.
---

# Cisco AppDynamics Setup Automation

Automates the **Cisco Splunk Add-on for AppDynamics**
(`Splunk_TA_AppDynamics` v3.2.0).

This package is a **combined add-on plus built-in dashboards** bundle. There is
no separate companion Splunk app in the local package cache for this workflow.

## Package Model

**Pull from Splunkbase first (latest version), then fall back to local or custom packages.**

Use `splunk-app-install` with `--source splunkbase --app-id 3471` to get the
latest release. If Splunkbase is unavailable, fall back to the local archive in
`splunk-ta/` (`cisco-splunk-add-on-for-appdynamics_*.tar.gz`) or a custom URL.
This applies to both Splunk Cloud (ACS) and Splunk Enterprise.

After installation, use this skill to configure the AppDynamics index, add-on
settings, controller connections, optional analytics connections, inputs, and
validation over search-tier REST. Any `splunk-ta/_unpacked/` tree is
review-only.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, API client secrets, or analytics secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials`
file (falls back to `~/.splunk/credentials`). If neither exists, guide the user
to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

For the AppDynamics controller client secret, instruct the user to write it to a
temporary file:

```bash
# User creates the file themselves (agent never sees the secret)
echo "the_appd_client_secret" > /tmp/appd_client_secret && chmod 600 /tmp/appd_client_secret
```

For the optional AppDynamics analytics secret:

```bash
# User creates the file themselves (agent never sees the secret)
echo "the_appd_analytics_secret" > /tmp/appd_analytics_secret && chmod 600 /tmp/appd_analytics_secret
```

Then the agent passes `--client-secret-file` or `--analytics-secret-file` to
the configure scripts. After configuration completes, delete the temp files.

The agent may freely ask for non-secret values: connection names, controller
URLs, analytics endpoint choice, global account names, index names, and input
types.

For prerequisite collection, use `skills/cisco-appdynamics-setup/template.example`
as the intake worksheet. Copy it to `template.local`, fill in non-secret values
there, and keep the completed file local only.

## Environment

Setup and validation use the Splunk search-tier REST API and can run from any
host with network access to the Splunk management port (`8089`). In Splunk
Cloud, app installation, index creation, and restarts are handled through ACS
instead of the search-tier REST endpoints.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs (`SPLUNK_PLATFORM` is only an override for hybrid runs) |
| App name | `Splunk_TA_AppDynamics` |
| Default index | `appdynamics` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-appdynamics-setup/scripts/` (relative to repo root) |

### Remote Splunk Connection

To run against a remote Splunk instance:

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

## Splunk Authentication

Scripts read Splunk credentials from the project-root `credentials` file
(falls back to `~/.splunk/credentials`) automatically.

```bash
bash scripts/validate.sh
```

## Setup Workflow

### Step 1: Create the Index and Set Add-on Defaults

```bash
bash skills/cisco-appdynamics-setup/scripts/setup.sh
```

Creates the `appdynamics` index, sets the add-on default output index in
`splunk_ta_appdynamics_settings.conf`, and ensures the app is visible in
Splunk Web.

Partial runs:

- `--indexes-only`
- `--settings-only`

### Step 2: Configure the Controller Connection

Before running, the agent must **ask the user** for non-secret values:

- Connection name
- Controller URL
- AppDynamics client name
- Whether to enable common inputs immediately

Create or update the controller connection via the add-on REST handler:

```bash
bash skills/cisco-appdynamics-setup/scripts/configure_account.sh \
  --name "PROD" \
  --controller-url "https://example.saas.appdynamics.com" \
  --client-name "splunk-integration" \
  --client-secret-file /tmp/appd_client_secret \
  --create-inputs recommended
```

REST endpoint used:

- `/servicesNS/nobody/Splunk_TA_AppDynamics/Splunk_TA_AppDynamics_account`

### Step 3: Configure the Optional Analytics Connection

Only needed if the user wants **Analytics Search** inputs.

```bash
bash skills/cisco-appdynamics-setup/scripts/configure_analytics.sh \
  --name "PROD_ANALYTICS" \
  --global-account-name "customer1_abcdef" \
  --analytics-secret-file /tmp/appd_analytics_secret
```

Optional follow-on: create an analytics input at the same time with `--query`.

REST endpoint used:

- `/servicesNS/nobody/Splunk_TA_AppDynamics/Splunk_TA_AppDynamics_analytics_account`

### Step 4: Enable Inputs

Enable common controller-backed inputs:

```bash
bash skills/cisco-appdynamics-setup/scripts/setup.sh --enable-inputs \
  --account "PROD" --index "appdynamics" --input-type recommended
```

Input groups:

| Input Type | Inputs Enabled | Notes |
|------------|----------------|-------|
| `recommended` | status, events, security, audit, licenses | Best default starting point |
| `all` | recommended + database + hardware + snapshots | Excludes analytics and custom |
| `status` | high-level status | Uses all built-in status categories |
| `database` | database metrics | Uses vendor defaults |
| `hardware` | hardware metrics | Uses vendor defaults |
| `snapshots` | application snapshots | Uses vendor defaults |
| `security` | Secure Application data | Uses vendor defaults |
| `events` | events data | Uses the package default event filter set |
| `audit` | controller audit logs | Controller connection only |
| `licenses` | controller license usage | Controller connection only |
| `analytics` | analytics search | Requires `--analytics-account` and `--query` |
| `custom` | custom metrics | Requires `--metric-paths` |

Analytics example:

```bash
bash scripts/setup.sh --enable-inputs \
  --index appdynamics \
  --input-type analytics \
  --analytics-account "PROD_ANALYTICS" \
  --query "SELECT * FROM transactions LIMIT 100"
```

Custom metrics example:

```bash
bash scripts/setup.sh --enable-inputs \
  --account "PROD" \
  --index appdynamics \
  --input-type custom \
  --metric-paths "Overall Application Performance|Calls per Minute"
```

### Step 5: Dashboards

The package already includes dashboards and forms:

- `ingestion_statistics`
- `status`
- `events`
- `license_usage`
- `audit_log`
- `troubleshooting`

There is **no macro rewrite step** for this add-on. Dashboard forms use an
inline `Index` text token that defaults to `appdynamics`. If the user chooses a
different index, they must enter that index in the dashboard form when viewing
the built-in dashboards.

### Step 6: Validate

```bash
bash skills/cisco-appdynamics-setup/scripts/validate.sh
```

Checks: app installation, visibility, index, settings, controller connections,
analytics connections, inputs, and data flow.

## Sourcetypes

Primary sourcetypes:

- `appdynamics_status`
- `appdynamics_databases`
- `appdynamics_hardware`
- `appdynamics_snapshots`
- `appdynamics_analytics`
- `appdynamics_security`
- `appdynamics_events`
- `appdynamics_audit`
- `appdynamics_licenses`

Custom metrics default to the user-facing source type `appdynamics_custom_data`.

See [reference.md](reference.md) for the input catalog, settings, dashboards,
and sourcetype details.

## Optional ITSI Path

If the user wants the **Content Pack for Splunk AppDynamics** or ITSI/ITE Work
service modeling, treat that as a follow-on workflow. This skill only automates
the `Splunk_TA_AppDynamics` package and its built-in dashboards.

## MCP Server Integration

Load custom tools into the MCP Server:

```bash
bash scripts/load_mcp_tools.sh
```

## Key Learnings / Known Issues

1. **Single package**: The local package is `Splunk_TA_AppDynamics` and already
   includes built-in dashboards.
2. **Default index matters**: The shipped dashboards default to `appdynamics`.
   Using that index avoids manual dashboard edits.
3. **Two connection types**: Controller and Analytics connections are separate
   REST handlers and should be configured separately.
4. **No macro management**: Unlike some Cisco app skills, there is no dashboard
   macro to rewrite for index selection.
5. **Advanced inputs**: Analytics Search and Custom Metrics need additional
   query/path parameters and are not part of the `recommended` bundle.
6. **Restart behavior differs by platform**: Enterprise may need a restart after
   index creation. Splunk Cloud uses ACS restart checks.
7. **Visibility after install**: The app can be present but hidden in Splunk
   Web after install. `setup.sh` forces `visible=true`.

## Additional Resources

- [reference.md](reference.md) — Connection fields, input catalog, dashboards, sourcetypes
- [mcp_tools.json](mcp_tools.json) — MCP tool definitions

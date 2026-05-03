---
name: cisco-secure-access-setup
description: >-
  Install and configure the Cisco Secure Access App for Splunk
  (cisco-cloud-security) and required event Add-on
  (TA-cisco-cloud-security-addon). Supports org account creation, investigate
  index, private app index, and app discovery index provisioning. Use when the
  user asks about Cisco Secure Access, app IDs 5558/7569, cisco-cloud-security,
  or Secure Access dashboards.
---

# Cisco Secure Access Setup

Automates installation and core account configuration of the **Cisco Secure
Access App for Splunk** (`cisco-cloud-security`) plus the required **Cisco
Secure Access Add-on for Splunk** (`TA-cisco-cloud-security-addon`).

## Package Model

**Pull from Splunkbase first (latest version), fall back to `splunk-ta/`.**
Use the setup script with `--install` to install add-on ID `7569` and app ID
`5558`. The shared installer falls back to local packages
`cisco-secure-access-add-on-for-splunk_*` and
`cisco-secure-access-app-for-splunk_*` when needed.

The app hosts dashboards and account/settings endpoints. The add-on is required
for Secure Access, Umbrella, and Cloudlock event-log ingestion and index
settings.

## Agent Behavior — Credentials

**The agent must NEVER ask for API keys, secrets, or tokens in chat.**

Splunk credentials are read from the project-root `credentials` file (falls
back to `~/.splunk/credentials`). If neither exists, guide the user to create
it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

For Secure Access API secrets, instruct the user to write them to temp files:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/secure_access_api_key
bash skills/shared/scripts/write_secret_file.sh /tmp/secure_access_api_secret
```

## Environment

This app supports standalone and distributed deployments and can be used on
Splunk Enterprise or Splunk Cloud.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs |
| App name | `cisco-cloud-security` |
| Add-on name | `TA-cisco-cloud-security-addon` |
| Splunkbase IDs | `5558` app, `7569` add-on |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-secure-access-setup/scripts/` |

## Setup Workflow

### Step 1: Install The Add-On And App

```bash
bash skills/cisco-secure-access-setup/scripts/setup.sh --install
```

### Step 2: Configure One Org Account

```bash
bash skills/cisco-secure-access-setup/scripts/configure_account.sh \
  --org-id example-org-id \
  --base-url https://api.us.security.cisco.com \
  --timezone UTC \
  --storage-region us \
  --api-key-file /tmp/secure_access_api_key \
  --api-secret-file /tmp/secure_access_api_secret \
  --investigate-index cisco_secure_access_investigate \
  --privateapp-index cisco_secure_access_private_apps \
  --appdiscovery-index cisco_secure_access_app_discovery
```

The account configurator can auto-create the supplied indexes. The app’s own
`org_accounts` endpoint provisions the Private Apps and App Discovery modular
inputs when those indexes are provided.

If you need to discover the org ID first:

```bash
bash skills/cisco-secure-access-setup/scripts/configure_account.sh \
  --discover-org-id \
  --base-url https://api.us.security.cisco.com \
  --api-key-file /tmp/secure_access_api_key \
  --api-secret-file /tmp/secure_access_api_secret
```

### Step 3: Configure App Settings For Dashboard Readiness

```bash
bash skills/cisco-secure-access-setup/scripts/configure_settings.sh \
  --org-id example-org-id \
  --bootstrap-roles \
  --accept-terms \
  --apply-dashboard-defaults
```

You can also configure optional dashboard-side settings such as:

- Cloudlock settings
- selected destination lists
- S3-backed dashboard indexes
- explicit refresh rate overrides

### Step 4: Validate

```bash
bash skills/cisco-secure-access-setup/scripts/validate.sh
```

To validate one specific org:

```bash
bash skills/cisco-secure-access-setup/scripts/validate.sh --org-id example-org-id
```

## Dashboards

The app ships dashboards in the package. They appear in Splunk Web
automatically after installation.

To access them: **Apps → Cisco Secure Access App for Splunk**

**Prerequisites for dashboards to show data:**

1. Org account must be created (Step 2) so the app has a valid API connection.
2. App settings must be configured for dashboard readiness (Step 3), including
   terms acceptance and optional role bootstrap.
3. The required add-on must be installed so event-log ingestion and log-index
   settings are present.
4. Modular inputs must be running and delivering events to the configured indexes
   (`investigate_index`, `privateapp_index`, `appdiscovery_index`, and the
   Secure Access event indexes configured in the add-on).

The `--apply-dashboard-defaults` flag in Step 3 initializes the app's stored
dashboard settings (refresh rate, Cloudlock, destination lists, S3 index
wiring) so the UI starts in a consistent state rather than falling back to
defaults on first load.

On **Splunk Cloud**, dashboards are available immediately after ACS installs
the app. All post-install configuration (account creation, settings) runs over
search-tier REST.

## What This Automation Covers

The current skill automates:

- OAuth/org account creation and update
- required add-on and app installation
- investigate index registration
- private app index registration
- app discovery index registration
- automatic creation or update of the corresponding modular inputs
- app bootstrap steps such as terms acceptance and optional role creation
- dashboard settings, destination lists, Cloudlock settings, and S3-backed
  dashboard index wiring

## Key Learnings / Known Issues

1. **Custom API surface**: This app stores configuration through custom REST
   endpoints and KV store records rather than simple static conf edits.
2. **Core account fields move together**: `apiKey`, `apiSecret`, and `baseURL`
   are treated as a credential set.
3. **Org-aware indexes**: `privateapp_index` and `appdiscovery_index` create
   or update matching modular inputs for the same organization.
4. **Terms gate the UI**: The app UI stores a TOC acceptance record before some
   settings views become available.
5. **Dashboard defaults exist in the UI**: If no dashboard interval is stored,
   the frontend falls back to 12 hours. This skill can write those settings
   explicitly so the app is initialized consistently.

## Additional Resources

- [reference.md](reference.md) — endpoint behavior and payload fields
- [template.example](template.example) — non-secret intake worksheet

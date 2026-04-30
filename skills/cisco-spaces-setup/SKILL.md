---
name: cisco-spaces-setup
description: >-
  Automate Cisco Spaces Add-on for Splunk (ta_cisco_spaces) setup and
  configuration. Creates indexes, configures Cisco Spaces meta stream
  accounts via REST API, enables firehose data inputs, stores activation
  tokens securely, and validates the deployment. Use when the user asks
  about Cisco Spaces, Spaces firehose, indoor location analytics,
  ta_cisco_spaces, or Spaces setup in Splunk.
---

# Cisco Spaces TA Setup Automation

Automates the **Cisco Spaces Add-on for Splunk** (`ta_cisco_spaces`).

## Package Model

**Pull from Splunkbase first (latest version), fall back to `splunk-ta/`.**
Use `splunk-app-install` with `--source splunkbase --app-id 8485` to get the
latest release. If Splunkbase is unavailable, fall back to the local package
in `splunk-ta/`. This applies to both Splunk Cloud (ACS) and Splunk Enterprise.

After installation, use this skill to configure the meta stream, inputs, and
validation over search-tier REST. Any `splunk-ta/_unpacked/` tree is
review-only.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, API keys, or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials` file
(falls back to `~/.splunk/credentials`). If neither exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

For the Cisco Spaces activation token, instruct the user to write it to a temporary file:

```bash
# User creates the file themselves (agent never sees the secret)
bash skills/shared/scripts/write_secret_file.sh /tmp/spaces_token
```

Then the agent passes `--token-file /tmp/spaces_token` to the configure script.
After the stream is created, delete the temp file.

The agent may freely ask for non-secret values: stream names, regions, etc.

For prerequisite collection, use `skills/cisco-spaces-setup/template.example`
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
| TA app name | `ta_cisco_spaces` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-spaces-setup/scripts/` (relative to repo root) |

### Remote Splunk Connection

To run against a remote Splunk instance:

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

## Splunk Authentication

Scripts read Splunk credentials from the project-root `credentials` file (falls back to `~/.splunk/credentials`) automatically.
No environment variables or command-line password arguments are needed:

```bash
bash skills/cisco-spaces-setup/scripts/validate.sh
```

If credentials are not yet configured, run the setup script first:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

## Setup Workflow

### Step 1: Create Index

```bash
bash skills/cisco-spaces-setup/scripts/setup.sh
```

Creates the `cisco_spaces` index and ensures the app is visible in Splunk Web.
When run interactively (TTY), the script prompts to continue with stream
configuration after the initial setup completes.

No `sudo` required when running as the `splunk` user.
In Splunk Cloud, the setup script creates the index through ACS.

| Index | Purpose | Max Size |
|-------|---------|----------|
| `cisco_spaces` | All Cisco Spaces firehose data | 512 GB |

### Step 2: Configure Meta Stream

Before running, the agent must **ask the user** for non-secret values:
- Stream name (e.g., "production")
- Region (io, eu, sg)
- Whether to record device location updates (default: no)

For the Cisco Spaces activation token, instruct the user to write it to a temp
file and pass `--token-file`. The agent never sees the token.

Meta streams are created via the Splunk REST API, which handles activation token
encryption automatically through the TA's custom REST handlers:

```bash
bash skills/cisco-spaces-setup/scripts/configure_stream.sh \
  --name "production" \
  --token-file /tmp/spaces_token \
  --region io \
  --auto-inputs \
  --index cisco_spaces
```

Copy/paste secret-file prep command:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/spaces_token
```

REST endpoint used (activation token encryption handled automatically):
- `/servicesNS/nobody/ta_cisco_spaces/ta_cisco_spaces_stream`

Stream fields:

| Field | Required | Description |
|-------|----------|-------------|
| `--name` | Yes | Stream name / stanza identifier |
| `--token-file` | Yes | Path to file containing Cisco Spaces activation token |
| `--region` | Yes | Cisco Spaces region: `io`, `eu`, or `sg` |
| `--location-updates` | No | Record device location updates (default: off) |
| `--auto-inputs` | No | Auto-create firehose input on stream creation |
| `--index` | No | Index for auto-created inputs (default `cisco_spaces`) |

### Step 3: Enable Inputs (if not using auto-create)

If `--auto-inputs` was used in Step 2, the firehose input is created
automatically. Otherwise, enable manually:

```bash
bash skills/cisco-spaces-setup/scripts/setup.sh --enable-inputs \
  --stream "production" --index "cisco_spaces"
```

| Input Type | Description |
|------------|-------------|
| `cisco_spaces_firehose` | Streaming SSE connection to Cisco Spaces Firehose API |

The firehose input connects to `https://partners.dnaspaces.<region>/api/partners/v1/firehose/events`
using SSE-style streaming. The `interval` field (default 300s) controls the retry
wait if the connection drops.

### Step 4: Restart If Required

On Splunk Enterprise, restart Splunk after new index creation.
On Splunk Cloud, check `acs status current-stack` and only run
`acs restart current-stack` when ACS reports `restartRequired=true`.

### Step 5: Validate

```bash
bash skills/cisco-spaces-setup/scripts/validate.sh
```

Checks: app installation, index, stream configuration, inputs, data flow, settings.

## Sourcetypes

| Sourcetype | Content |
|---|---|
| `cisco:spaces:firehose` | Cisco Spaces firehose events (device presence, location updates, IoT telemetry, etc.) |

## Key Learnings / Known Issues

1. **REST API for streams**: This TA uses UCC custom REST handlers — always create
   streams via the REST API, not by writing conf files manually. The handlers
   encrypt the activation token automatically.
2. **Meta stream model**: Cisco Spaces uses "meta streams" as the account/connection
   entity. Each stream has a region, activation token, and optional location
   updates toggle. Firehose inputs then reference a stream by name.
3. **Streaming input**: The firehose is a long-lived SSE connection, not a polling
   input. The `interval` field is only the retry delay when the connection drops.
4. **Region determines endpoint**: `io`→`dnaspaces.io`, `eu`→`dnaspaces.eu`,
   `sg`→`dnaspaces.sg`. The API URL base is `https://partners.dnaspaces.<region>`.
5. **Location updates volume**: Enabling device location updates (`location_updates_status`)
   significantly increases data volume. The default is off; only enable when needed.
6. **Splunkbase app ID 8485**: The TA is listed on Splunkbase. Use
   `--source splunkbase --app-id 8485` for installation. Cisco EULA license
   acknowledgment is required.
7. **Restart behavior differs by platform**: Enterprise requires a Splunk
   restart after new index creation. Splunk Cloud uses ACS restart checks.
8. **No sudo needed**: Scripts run fine as the `splunk` OS user.
9. **SHC replication**: The TA ships `server.conf` entries for SHC conf replication
   of `ta_cisco_spaces_settings` and `ta_cisco_spaces_stream`.

---
name: cisco-spaces-setup
description: Use when configuring or validating Cisco Spaces meta stream accounts, firehose inputs, and data in Splunk.
compatibility: >-
  Splunk Cloud Platform 10.5.2605: conditional. Follow documented package,
  entitlement, topology, and customer-managed runtime guardrails; self-managed
  paths remain on the public 10.4 baseline.
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Cisco Spaces TA Setup Automation

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash, `curl`, and `jq` | Run setup and REST configuration helpers | `command -v bash curl jq` |
| Splunk administrative access | Create the index, account, and firehose input | Confirm search-tier REST access |
| Cisco Spaces activation token | Authorize the selected meta stream | Store the token in a protected file |

## Workflow Overview

```text
┌───────────┐   ┌────────────┐   ┌──────────────────┐   ┌───────────────┐
│ Preflight │ → │ Install TA │ → │ Configure stream │ → │ Validate data │
└───────────┘   └────────────┘   └──────────────────┘   └───────────────┘
```

## When to Activate

- Onboard a Cisco Spaces meta stream or firehose into Splunk.
- Configure `ta_cisco_spaces` accounts, indexes, or modular inputs.
- Diagnose activation, stream, source-type, or ingestion failures.

## Scope

This skill configures the Splunk side of a documented Spaces stream. It does
not request activation tokens in chat, change location policy, or enable an
unreviewed firehose without considering event volume.

## Examples

Run diagnostic checks before account creation:

```bash
bash skills/cisco-spaces-setup/scripts/validate.sh
```

Expected output: tools, package, Splunk connectivity, and account prerequisites
are reported without changing Spaces or Splunk inputs.

Run completion validation after enabling a firehose:

```bash
bash skills/cisco-spaces-setup/scripts/validate.sh --completion
```

Expected output: account, input, index, source type, and recent event evidence
report `[PASS]`; an idle or unauthorized stream exits nonzero.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Activation fails | Token is expired, scoped incorrectly, or unreadable | Replace the protected token file and retry |
| Connected but idle | Wrong stream/no activity | Verify the selected stream |
| Wrong index | Input differs from plan | Correct it and rerun checks |
| Reconnect loop | Network is unstable | Inspect logs and outbound access |

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

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

Scripts read Splunk credentials from the project-root `credentials` file. They
fall back to `~/.splunk/credentials` automatically.
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
bash skills/cisco-spaces-setup/scripts/validate.sh --completion
```

Checks: app installation, index, stream configuration, inputs, data flow, settings.

## Sourcetypes

| Sourcetype | Content |
|---|---|
| `cisco:spaces:firehose` | Cisco Spaces firehose events (device presence, location updates, IoT telemetry, etc.) |
| `cisco:spaces:firehose:health` | Firehose connection and collector-health events |
| `cisco:spaces:log` | Add-on internal collector logs |

Package `2.0.1` defines all three source types; `1.0.7` shipped no `props.conf`
and therefore no health sourcetype. Validation requires primary firehose data
and reports health data separately rather than claiming that every installed
package must emit it.

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

## Validation Modes

Run `scripts/validate.sh` for diagnostics. Use `--completion` (alias `--strict`)
to require a stream stanza, enabled input, index, events, and the primary
`cisco:spaces:firehose` sourcetype. The validator also reports the version-bound
`cisco:spaces:firehose:health` sourcetype independently. The Cisco Spaces TA
ships no dashboards; the consuming dashboard/content handoff is therefore
explicit rather than inferred.

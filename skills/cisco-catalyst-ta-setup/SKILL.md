---
name: cisco-catalyst-ta-setup
description: Use when configuring or validating Catalyst Center, ISE, SD-WAN, or Cyber Vision with TA_cisco_catalyst.
compatibility: >-
  Splunk Cloud Platform 10.5.2605: conditional. Follow documented package,
  entitlement, topology, and customer-managed runtime guardrails; self-managed
  paths remain on the public 10.4 baseline.
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Cisco Catalyst TA Setup Automation

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash, `curl`, and `jq` | Run setup and REST configuration helpers | `command -v bash curl jq` |
| Splunk administrative access | Create indexes, accounts, and modular inputs | Confirm search-tier REST access |
| Cisco product account | Authorize the selected product API | Store its secret in a protected file |

## Workflow Overview

```text
┌───────────┐   ┌────────────┐   ┌──────────────────┐   ┌───────────────┐
│ Preflight │ → │ Install TA │ → │ Configure inputs │ → │ Validate data │
└───────────┘   └────────────┘   └──────────────────┘   └───────────────┘
```

## When to Activate

- Onboard Catalyst Center or legacy DNA Center data.
- Configure Cisco ISE, SD-WAN, or Cyber Vision modular inputs.
- Diagnose a `TA_cisco_catalyst` account, input, or dashboard readiness failure.

## Scope

This skill owns Splunk account and input configuration for supported products.
It does not ask for secrets in chat, alter Cisco appliance policy, or enable
unreviewed inputs. Keep credentials file-backed and review polling load first.

## Examples

Run the diagnostic preflight without requiring completed ingestion:

```bash
bash skills/cisco-catalyst-ta-setup/scripts/validate.sh
```

Expected output: package, command, credential, and connectivity readiness is
reported; unresolved prerequisites are identified without mutation.

Run the strict gate after configuring and enabling inputs:

```bash
bash skills/cisco-catalyst-ta-setup/scripts/validate.sh --completion
```

Expected output: configured accounts, enabled inputs, expected source types,
events, and dashboard evidence report `[PASS]` or exit nonzero.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| REST returns 401/403 | Splunk or Cisco authorization is incomplete | Verify the account and secret-file permissions |
| Enabled input is idle | URL, scope, or reachability is wrong | Validate and inspect input logs |
| Duplicate events | Inputs overlap | Confirm ownership, then disable one |
| Empty dashboards | Macro/index is misaligned | Run data-source readiness checks |

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Automates the **Cisco Catalyst Add-on for Splunk** (`TA_cisco_catalyst`).

## Package Model

**Pull from Splunkbase first, fall back to `splunk-ta/`.** Use
`splunk-app-install` with `--source splunkbase --app-id 7538`; the shared
installer defaults to the repository-verified release. If Splunkbase is
unavailable, fall back to the local package in `splunk-ta/`.

After installation, use this skill to configure accounts, inputs, and
validation over search-tier REST. Any `splunk-ta/_unpacked/` tree is
review-only.

### Package Verification Boundary

The repository's package-derived account/input baseline is `3.1.0`. The
current public release is `3.2.35` and advertises Splunk 10.5 support, but its
package contents have not been verified here. The shared installer defaults to
verified `3.1.0`; only `--accept-unverified-release` follows public `3.2.35`.
After that explicit override, review the UCC REST handlers, account/input
schemas, source types, and dashboards before using `3.1.0` assumptions.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, API keys, or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials` file
(falls back to `~/.splunk/credentials`). If neither exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

For device credentials (Catalyst Center password, ISE password, SD-WAN password,
Cyber Vision API token), instruct the user to write the secret to a temporary file:

```bash
# User creates the file themselves (agent never sees the secret)
bash skills/shared/scripts/write_secret_file.sh /tmp/catalyst_center_password
bash skills/shared/scripts/write_secret_file.sh /tmp/ise_password
bash skills/shared/scripts/write_secret_file.sh /tmp/sdwan_password
bash skills/shared/scripts/write_secret_file.sh /tmp/cybervision_api_token
```

Then the agent passes the matching `--password-file` or `--api-token-file`
to the configure script. After the account is created, delete the temp file.

The agent may freely ask for non-secret values: account names, hostnames, account types, etc.

For prerequisite collection, use `skills/cisco-catalyst-ta-setup/template.example`
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
| TA app name | `TA_cisco_catalyst` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-catalyst-ta-setup/scripts/` (relative to repo root) |

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
bash skills/cisco-catalyst-ta-setup/scripts/validate.sh
```

If credentials are not yet configured, run the setup script first:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

## Setup Workflow

### Step 1: Create Indexes

```bash
bash skills/cisco-catalyst-ta-setup/scripts/setup.sh
```

Creates four indexes. No `sudo` required when running as the `splunk` user.
In Splunk Cloud, the setup script creates these indexes through ACS.

| Index | Purpose | Max Size |
|-------|---------|----------|
| `catalyst` | Catalyst Center (DNAC) data | 512 GB |
| `ise` | ISE authentication/admin data | 512 GB |
| `sdwan` | SD-WAN health/tunnel data | 512 GB |
| `cybervision` | Cyber Vision OT data | 512 GB |

Partial runs: `--indexes-only`.

### Step 2: Configure Account

Before running, the agent must obtain from the user (non-secret values only):
- Account type (catalyst_center, ise, sdwan, cybervision)
- Account name (e.g., "CVF_Cat_Center")
- Connection details (host, username)
- Device password or API token — user writes to temp file; agent passes `--password-file` or `--api-token-file`

Accounts are created via the Splunk REST API, which handles password encryption
automatically through the TA's custom REST handlers:

```bash
bash skills/cisco-catalyst-ta-setup/scripts/configure_account.sh \
  --type catalyst_center \
  --name "MY_CATC" \
  --host "https://10.100.0.60" \
  --username "device_user" \
  --password-file /tmp/device_pass
```

Copy/paste secret-file prep commands:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/catalyst_center_password
bash skills/shared/scripts/write_secret_file.sh /tmp/ise_password
bash skills/shared/scripts/write_secret_file.sh /tmp/sdwan_password
bash skills/shared/scripts/write_secret_file.sh /tmp/cybervision_api_token
```

Account types and their required fields:

| Type | Required Fields | Conf File |
|------|----------------|-----------|
| `catalyst_center` | `--host`, `--username`, `--password-file` | `ta_cisco_catalyst_account.conf` |
| `ise` | `--host`, `--username`, `--password-file` | `ta_cisco_catalyst_ise_account.conf` |
| `sdwan` | `--host`, `--username`, `--password-file` | `ta_cisco_catalyst_sdwan_account.conf` |
| `cybervision` | `--host`, `--api-token-file` | `ta_cisco_catalyst_cyber_vision_account.conf` |

REST endpoints used (password encryption handled automatically):
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_account`
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_ise_account`
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_sdwan_account`
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_cyber_vision_account`

### Step 3: Enable Inputs

```bash
bash skills/cisco-catalyst-ta-setup/scripts/setup.sh --enable-inputs \
  --account "MY_CATC" --index "catalyst" --input-type catalyst_center
```

| Input Type | Inputs Enabled | Index | Account Field |
|------------|---------------|-------|---------------|
| `catalyst_center` | 9 | `catalyst` | `cisco_dna_center_account` |
| `ise` | 1 (administrative_input with 3 data_types) | `ise` | `ise_account` |
| `sdwan` | 2 (health, site_and_tunnel_health) | `sdwan` | `sdwan_account` |
| `cybervision` | 6 | `cybervision` | `cyber_vision_account` |

The Catalyst Center inputs cover client/device/network health, compliance,
issues, advisories, clients, audit logs, and site topology. Cyber Vision covers
activities, components, devices, events, flows, and vulnerabilities.

### Step 4: Restart If Required

On Splunk Enterprise, restart Splunk after new index creation.
On Splunk Cloud, check `acs status current-stack` and only run
`acs restart current-stack` when ACS reports `restartRequired=true`.

### Step 5: Validate

```bash
bash skills/cisco-catalyst-ta-setup/scripts/validate.sh --completion
```

Checks: app installation, indexes, accounts, inputs, data flow, settings.

## Sourcetypes

| Sourcetype | Product | Content |
|---|---|---|
| `cisco:dnac:issue` | Catalyst Center | Network issues and assurance |
| `cisco:dnac:clienthealth` | Catalyst Center | Client health scores |
| `cisco:dnac:devicehealth` | Catalyst Center | Device health scores |
| `cisco:dnac:compliance` | Catalyst Center | Device compliance status |
| `cisco:dnac:networkhealth` | Catalyst Center | Network health summary |
| `cisco:dnac:securityadvisory` | Catalyst Center | PSIRTs and advisories |
| `cisco:dnac:client` | Catalyst Center | Client details |
| `cisco:dnac:audit:logs` | Catalyst Center | Audit trail |
| `cisco:dnac:site:topology` | Catalyst Center | Site hierarchy |
| `cisco:cybervision:activities` | Cyber Vision | OT activities |
| `cisco:cybervision:components` | Cyber Vision | OT components |
| `cisco:cybervision:devices` | Cyber Vision | OT devices |
| `cisco:cybervision:events` | Cyber Vision | OT events |
| `cisco:cybervision:flows` | Cyber Vision | OT network flows |
| `cisco:cybervision:vulnerabilities` | Cyber Vision | OT vulnerabilities |

ISE and SD-WAN sourcetypes vary by data type and are prefixed `cisco:ise*` and
`cisco:sdwan*` respectively.

## MCP Server Integration

```bash
bash skills/cisco-catalyst-ta-setup/scripts/load_mcp_tools.sh
```

## Key Learnings / Known Issues

1. **REST API for accounts**: This TA uses custom REST handlers — always create
   accounts via the REST API, not by writing conf files manually. The handlers
   encrypt passwords automatically.
2. **Restart behavior differs by platform**: Enterprise requires a Splunk
   restart after new index creation. Splunk Cloud uses ACS restart checks.
3. **No sudo needed**: Scripts run fine as the `splunk` OS user.
4. **SSL verification**: The TA's `verify_ssl` setting defaults to True. Set to
   False for self-signed certs via `ta_cisco_catalyst_settings.conf`.
5. **Cyber Vision uses API tokens**: Unlike other account types, Cyber Vision
   uses `api_token` instead of username/password.
6. **ISE data types**: The ISE input accepts `data_type` with comma-separated
   values: `security_group_tags`, `authz_policy_hit`, `ise_tacacs_rule_hit`.

## Additional Resources

- [reference.md](reference.md) — Complete input catalog, account fields, sizing
- [mcp_tools.json](mcp_tools.json) — MCP tool definitions

## Validation Modes

Run `scripts/validate.sh` for diagnostics. Run it with `--completion` (alias
`--strict`) to require at least one configured product account, an enabled
input, Cisco event flow, required indexes, and visible companion dashboards.

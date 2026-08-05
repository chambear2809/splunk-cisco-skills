---
name: cisco-catalyst-ta-setup
description: Use when configuring or validating Catalyst Center, ISE, Catalyst SD-WAN API or syslog collection, Cyber Vision, or the beta IOS-XE CLI collector with TA_cisco_catalyst.
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
- Design or validate Catalyst SD-WAN text syslog, UTD, ZBFW, SC4S, HSL, or
  Unified Logging collection.
- Collect a cataloged read-only IOS-XE command when no suitable controller API
  exists and raw device output is explicitly required.
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

The inspected TA source-contract baseline is `3.2.44`. It covers 29 modular
input types, per-input polling defaults, generic endpoint catalogs, scheduled
reports, SD-WAN audit and energy collection, and the TA's Data Collection
Health dashboard. The Splunkbase package-evidence baseline remains `3.1.0`;
the tracked public metadata snapshot reports `3.2.35` as the latest release.

These are deliberately separate claims. The shared installer defaults to the
package-verified `3.1.0`; only `--accept-unverified-release` follows the public
release selected by the registry. After that explicit override, compare the
installed UCC REST handlers, account/input schemas, source types, and dashboard
views with the `3.2.44` source contract before applying automation.

### Source Contract Highlights

- Splunk 10.4 and Python 3.13 runtime support, including packaged ISE
   Analytics Reports SSH/SFTP dependencies.
- Canonical structured logging for `poll-complete`, `api-call`, `api-error`,
   `collection-exception`, `state-transition`, and `auth-failure` events.
- Data Collection Health, Data Quality, resource-utilization, report-pipeline,
   and input-freshness troubleshooting in the TA-owned React dashboard.
- Catalyst Center CIM 8.5 mappings for Network Sessions, Change, Alerts,
   Vulnerabilities, Performance, Inventory, and Updates when Splunk CIM is
   installed on the search tier.
- Per-record event emission, corrected event timestamps, normalized host
   metadata, KV Store checkpointing, and per-account TLS verification.
- Catalog-driven generic API inputs for all four products, Catalyst report
   multi-select/automatic discovery, SD-WAN audit and energy collection, SWIM,
   application visibility, and optional Device Health interface statistics.
- SD-WAN API Endpoint Collection device scope for one, selected, or all
   reachable WAN Edge devices, with bounded fan-out and `target_device_id`
   enrichment for cataloged read-only endpoints that require `deviceId`.
- Editable polling intervals on all five SD-WAN and all seven Cyber Vision API
   input forms, including the existing below-recommendation confirmation.
- Dedicated Catalyst SD-WAN text-syslog setup for TA-managed relay, redirect,
   or direct-listener methods, plus a documented external SC4S-to-HEC path that
   preserves the `cisco:firewall:logs` ingress sourcetype.
- Stable `cisco:sdwan:syslog` routing for generic IOS-XE
   `%FAC-SEV-MNEM:` messages, while named ZBFW and UTD sourcetypes remain
   unchanged.
- A separate **Beta** IOS-XE CLI input for five backend-allowlisted, read-only
   commands over host-key-pinned SSH. It is one device per account and one
   command per input, does not issue `enable`, and is not an arbitrary command
   runner.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, API keys, or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials` file
(falls back to `~/.splunk/credentials`). If neither exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

For device credentials (Catalyst Center password, ISE password, SD-WAN password,
Cyber Vision API token, or IOS-XE CLI password), instruct the user to write the
secret to a temporary file:

```bash
# User creates the file themselves (agent never sees the secret)
bash skills/shared/scripts/write_secret_file.sh /tmp/catalyst_center_password
bash skills/shared/scripts/write_secret_file.sh /tmp/ise_password
bash skills/shared/scripts/write_secret_file.sh /tmp/sdwan_password
bash skills/shared/scripts/write_secret_file.sh /tmp/cybervision_api_token
bash skills/shared/scripts/write_secret_file.sh /tmp/iosxe_cli_password
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
- Account type (catalyst_center, ise, sdwan, cybervision, iosxe_cli)
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
bash skills/shared/scripts/write_secret_file.sh /tmp/iosxe_cli_password
```

Account types and their required fields:

| Type | Required Fields | Conf File |
|------|----------------|-----------|
| `catalyst_center` | `--host`, `--username`, `--password-file` | `ta_cisco_catalyst_account.conf` |
| `ise` | `--host`, `--username`, `--password-file` | `ta_cisco_catalyst_ise_account.conf` |
| `sdwan` | `--host`, `--username`, `--password-file` | `ta_cisco_catalyst_sdwan_account.conf` |
| `cybervision` | `--host`, `--api-token-file` | `ta_cisco_catalyst_cyber_vision_account.conf` |
| `iosxe_cli` | `--host`, `--port`, `--username`, `--password-file`, `--host-key-fingerprint` | `ta_cisco_catalyst_cli_account.conf` |

REST endpoints used (password encryption handled automatically):
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_account`
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_ise_account`
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_sdwan_account`
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_cyber_vision_account`
- `/servicesNS/nobody/TA_cisco_catalyst/TA_cisco_catalyst_cli_account`

### Step 3: Enable Inputs

```bash
bash skills/cisco-catalyst-ta-setup/scripts/setup.sh --enable-inputs \
  --account "MY_CATC" --index "catalyst" --input-type catalyst_center
```

| Input Type | Inputs Enabled | Index | Account Field |
|------------|---------------|-------|---------------|
| `catalyst_center` | 11 dedicated inputs | `catalyst` | `cisco_dna_center_account` |
| `ise` | 1 (administrative_input with 3 data_types) | `ise` | `ise_account` |
| `sdwan` | 4 (health, site/tunnel health, audit logs, energy stats) | `sdwan` | `sdwan_account` |
| `cybervision` | 6 | `cybervision` | `cyber_vision_account` |
| `iosxe_cli` | 1 selected cataloged command | Operator-selected network index | `cli_account` |

The Catalyst Center inputs cover client/device/network health, compliance,
issues, advisories, SWIM, application traffic, clients, audit logs, and site
topology. Cyber Vision covers activities, components, devices, events, flows,
and vulnerabilities. Setup preserves the TA's tuned 300, 900, and 3600-second
polling intervals instead of applying a uniform interval.

The six environment-specific input families are not created automatically:
Catalyst Center, ISE, and Cyber Vision generic endpoint inputs and the SD-WAN
**API Endpoint Collection** input require an explicit allow-listed endpoint;
Catalyst Center reports require report selection; ISE analytics reports require
repository settings. Configure those through the TA UI after reviewing endpoint
support and polling load.

#### SD-WAN BFD API example

Use three SD-WAN API Endpoint Collection stanzas for a focused BFD
outage-readiness example. Select one, selected, or all reachable WAN Edge
devices through **Device Scope**; do not put `deviceId` in Query Parameters.

| Data | Endpoint | Sourcetype |
|---|---|---|
| Summary | `/dataservice/device/bfd/summary` | `cisco:sdwan:custom:device_bfd_summary` |
| Current synchronized sessions | `/dataservice/device/bfd/synced/sessions` | `cisco:sdwan:custom:device_bfd_synced_sessions` |
| Session history | `/dataservice/device/bfd/history` | `cisco:sdwan:custom:device_bfd_history` |

Start broad all-device fan-out at 900 seconds or longer unless controller
capacity testing supports a lower interval. This is structured vManage REST
collection—the API-based equivalent for the BFD operational-data requirement.
It does not execute `show sdwan bfd session`, expose CLI Template Exec, or
provide arbitrary CLI access for commands without a supported API equivalent.

#### Catalyst SD-WAN text syslog

Treat the Cisco logging paths separately:

| Data family | Preferred collection | Important behavior |
|---|---|---|
| Ordinary IOS-XE system syslog | SC4S/HEC or a TA-managed local receiver | Transport and destination port are configurable. Generic `%FAC-SEV-MNEM:` events route to `cisco:sdwan:syslog`; unmatched content falls back to `cisco:sdwan:system:logs`. |
| Traditional ZBFW text syslog | Supported for light/diagnostic use | `%FW-*` events route to named `cisco:sdwan:*` sourcetypes, but Cisco rate-limits firewall text syslog. |
| UTD external text syslog | UDP 514 on affected releases/templates | IPS/IDS, URL filtering, AMP/file inspection, and TLS-decryption events route to `cisco:sdwan:utd:logs`. The affected UTD `logging host` surface exposes no alternate port or transport. |
| ZBFW High Speed Logging (HSL) / Unified Logging | Splunk Stream plus `cisco-catalyst-enhanced-netflow-setup` | This is NetFlow/IPFIX, not text syslog, and is not collected by the TA's UDP listener. HSL is the preferred production ZBFW export path when text-syslog rate limiting matters. |

For a single text-syslog receiver that must include UTD, use UDP 514. Opening
the listener does not enable Cisco-side producers: separately enable ordinary
system logging, the relevant ZBFW rule logging, and UTD flow/external logging.
HSL does not disable ordinary IOS-XE or UTD syslog, but equivalent `%FW-*`
duplicates must not be assumed for every HSL record.

Do not confuse UTD events with UTD health: `cisco:sdwan:utd:logs` contains the
external text-syslog security events, while `cisco:sdwan:utdhealth` is an HTTPS
vManage API snapshot of the per-device UTD engine health.

Use `cisco:firewall:logs` as the dedicated SD-WAN **ingress** sourcetype for
TA-managed listeners and SC4S-to-HEC delivery. Do not leave SC4S events as
`cisco:viptela`, `cisco:ios`, or generic `syslog`; those do not enter this TA's
SD-WAN split chain. Install the TA on the first full parsing tier receiving the
raw events. See [reference.md](reference.md) for the receiver, parsing, and
validation contract.

#### Beta IOS-XE CLI command example

Use the direct-device CLI input only after confirming that a structured API is
not suitable or that raw output is specifically required:

```bash
bash skills/cisco-catalyst-ta-setup/scripts/configure_account.sh \
  --type iosxe_cli \
  --name EDGE_01 \
  --host edge01.example.local \
  --port 22 \
  --username splunk_ro \
  --password-file /tmp/iosxe_cli_password \
  --host-key-fingerprint 'SHA256:<verified-device-key>'

bash skills/cisco-catalyst-ta-setup/scripts/setup.sh --enable-inputs \
  --input-type iosxe_cli --account EDGE_01 --index sdwan \
  --command-id sdwan_bfd_sessions
```

The login must already reach sufficient privilege; the collector does not send
an interactive `enable`. The backend allows only `dspfarm_profile`,
`sdwan_bfd_sessions`, `sdwan_bfd_history`, `version`, and `inventory`. For
normal BFD monitoring, prefer the structured SD-WAN API Endpoint Collection.

### Step 4: Operator-Controlled Restart If Required

Index or app changes can require a restart. The agent must not restart Splunk;
ask the operator to perform any required Splunk Enterprise restart. On Splunk
Cloud, inspect `acs status current-stack` and ask the operator to restart only
when ACS reports `restartRequired=true`.

### Step 5: Validate

```bash
bash skills/cisco-catalyst-ta-setup/scripts/validate.sh --completion
```

Checks: app installation, indexes, accounts, inputs, canonical events from the
last 24 hours, TLS verification settings, and the TA's shipped Data Collection
Health dashboard. If the optional Cisco Enterprise Networking app is installed,
its views and index macro are checked too.

## Sourcetypes

| Sourcetype | Product | Content |
|---|---|---|
| `cisco:dnac:issue` | Catalyst Center | Network issues and assurance |
| `cisco:dnac:clienthealth` | Catalyst Center | Client health scores |
| `cisco:dnac:devicehealth` | Catalyst Center | Device health scores |
| `cisco:dnac:compliance` | Catalyst Center | Device compliance status |
| `cisco:dnac:networkhealth` | Catalyst Center | Network health summary |
| `cisco:dnac:securityadvisory` | Catalyst Center | PSIRTs and advisories |
| `cisco:dnac:swim` | Catalyst Center | Software image inventory and compliance |
| `cisco:dnac:application:traffic` | Catalyst Center | Application visibility traffic statistics |
| `cisco:dnac:client` | Catalyst Center | Client details |
| `cisco:dnac:audit:logs` | Catalyst Center | Audit trail |
| `cisco:dnac:site:topology` | Catalyst Center | Site hierarchy |
| `cisco:dnac:custom:*` | Catalyst Center | Allow-listed generic endpoint data |
| `cisco:catalyst:center:*:report` | Catalyst Center | Scheduled report data |
| `cisco:ise:*` | ISE | Administrative, analytics-report, and generic API data |
| `cisco:sdwan:*` | SD-WAN | Health, tunnels, audit, energy, and generic API data |
| `cisco:sdwan:custom:device_bfd_summary` | SD-WAN | Per-device BFD summary from API Endpoint Collection |
| `cisco:sdwan:custom:device_bfd_synced_sessions` | SD-WAN | Current synchronized per-device BFD sessions |
| `cisco:sdwan:custom:device_bfd_history` | SD-WAN | Per-device BFD session history |
| `cisco:firewall:logs` | SD-WAN | Required ingress sourcetype for dedicated text-syslog splitting; normally rewritten at index time |
| `cisco:sdwan:utd:logs` | SD-WAN | UTD IPS/IDS, URL filtering, AMP/file, and TLS-decryption text events |
| `cisco:sdwan:syslog` | SD-WAN | Stable generic IOS-XE `%FAC-SEV-MNEM:` operational syslog |
| `cisco:sdwan:system:logs` | SD-WAN | Unmatched SD-WAN text-syslog fallback |
| `cisco:iosxe:cli:*` | IOS-XE CLI (Beta) | Cataloged direct-device command snapshots |
| `cisco:cybervision:activities` | Cyber Vision | OT activities |
| `cisco:cybervision:components` | Cyber Vision | OT components |
| `cisco:cybervision:devices` | Cyber Vision | OT devices |
| `cisco:cybervision:events` | Cyber Vision | OT events |
| `cisco:cybervision:flows` | Cyber Vision | OT network flows |
| `cisco:cybervision:vulnerabilities` | Cyber Vision | OT vulnerabilities |

ISE and SD-WAN sourcetypes vary by data type and are prefixed `cisco:ise*` and
`cisco:sdwan*` respectively. Completion and dashboard searches use those
canonical families. The installed TA may still accept old raw aliases and
normalize them, but the current SCAN contract no longer advertises
unqualified `cisco:ise`, `cisco:sdwan:sytem:logs`, or `cisco:sgacl:logs`.

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
4. **TLS verification**: Account `verify_ssl` defaults to true. Keep it enabled
   in production; use `--no-verify-ssl` only for an isolated account while a
   trusted CA path is being established. The flag does not alter other accounts.
5. **Cyber Vision uses API tokens**: Unlike other account types, Cyber Vision
   uses `api_token` instead of username/password.
6. **ISE data types**: The ISE input accepts `data_type` with comma-separated
   values: `security_group_tags`, `authz_policy_hit`, `ise_tacacs_rule_hit`.
7. **SD-WAN API boundary**: API Endpoint Collection supports only cataloged,
   read-only vManage GET endpoints. It does not run arbitrary CLI commands.
8. **SD-WAN syslog is multi-path**: UTD external text syslog is effectively
   fixed to UDP 514 on affected releases/templates; ordinary IOS-XE system
   syslog remains configurable; HSL/Unified Logging is a separate NetFlow/IPFIX
   path. Do not describe all three as one listener or one producer.
9. **SC4S metadata is deliberate**: Route only the SD-WAN sender population to
   ingress sourcetype `cisco:firewall:logs`. A default `cisco:viptela` or
   `cisco:ios` assignment bypasses this TA's SD-WAN content splitting.
10. **CLI remains Beta and bounded**: One host-key-pinned device account and one
    cataloged command per input. No interactive privilege escalation, free-form
    commands, pipes, redirects, shell, or configuration mode.

## Additional Resources

- [reference.md](reference.md) — Complete input catalog, account fields, sizing
- [mcp_tools.json](mcp_tools.json) — MCP tool definitions

## Validation Modes

Run `scripts/validate.sh` for diagnostics. Run it with `--completion` (alias
`--strict`) to require at least one configured product account, an enabled
input, recent canonical Cisco event flow, required indexes, and the visible TA
Data Collection Health dashboard. Companion-app checks apply only when the
optional Cisco Enterprise Networking app is installed.

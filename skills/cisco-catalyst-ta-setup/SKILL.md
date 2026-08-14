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
The setup scripts capability-probe 3.2.44-only input and IOS-XE CLI handlers
before mutation. Missing optional Catalyst Center handlers are skipped; missing
IOS-XE CLI handlers fail closed with an upgrade/verification message.

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

1. Create the `catalyst`, `ise`, `sdwan`, and `cybervision` indexes:

   ```bash
   bash skills/cisco-catalyst-ta-setup/scripts/setup.sh
   ```

2. Collect the account type, account name, host, and username. Have the operator
   write passwords or API tokens to a temporary secret file; never accept a
   secret in an argument or environment variable. Configure one of
   `catalyst_center`, `ise`, `sdwan`, `cybervision`, or `iosxe_cli` through
   `scripts/configure_account.sh`. The TA's REST handler encrypts the stored
   credential. Consult the product-specific account-field tables in
   [reference.md](reference.md) before invoking the script.

3. Enable only the selected input family:

   ```bash
   bash skills/cisco-catalyst-ta-setup/scripts/setup.sh --enable-inputs \
     --account "MY_CATC" --index "catalyst" --input-type catalyst_center
   ```

   Preserve the TA's tuned polling intervals. Generic endpoints, reports, ISE
   analytics repositories, and SD-WAN API Endpoint Collection require explicit
   operator selections and are not created automatically. Use the detailed
   input inventories and fields in [reference.md](reference.md).

4. For SD-WAN, prefer structured vManage REST collection. Treat ordinary
   IOS-XE/ZBFW syslog, UTD syslog, and NetFlow/IPFIX High Speed Logging (HSL)
   as distinct paths.
   A text-syslog path entering this TA must use ingress sourcetype
   `cisco:firewall:logs`, and the TA must be installed on the first full parsing
   tier. UTD may require UDP 514; HSL requires Splunk Stream plus
   `cisco-catalyst-enhanced-netflow-setup`. Use beta IOS-XE CLI only when a
   structured API is unsuitable, with a verified host-key fingerprint and one
   of the collector's allow-listed commands. The structured BFD API path
   does not execute `show sdwan bfd session`. The complete BFD, syslog, UTD,
   HSL, and CLI contracts are in [reference.md](reference.md).

5. Do not restart Splunk. If a restart is required, hand it to the operator; on
   Splunk Cloud, first confirm ACS reports `restartRequired=true`.

6. Run completion validation:

   ```bash
   bash skills/cisco-catalyst-ta-setup/scripts/validate.sh --completion
   ```

   Completion requires the app, indexes, accounts, a TA-owned input or evidenced
   external SD-WAN syslog path, recent canonical data, secure TLS settings, and
   the shipped Data Collection Health dashboard. See the completion contract in
   [reference.md](reference.md).

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
`--strict`) to require at least one configured product account, an enabled TA
input or recent external SD-WAN syslog evidence, recent canonical Cisco event
flow, required indexes, and a visible TA Data Collection Health dashboard with
recent collection-health data. Companion-app checks apply only when the optional
Cisco Enterprise Networking app is installed.

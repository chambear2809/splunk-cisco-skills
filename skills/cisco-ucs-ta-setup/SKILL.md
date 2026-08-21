---
name: cisco-ucs-ta-setup
description: Use when configuring Cisco UCS Manager records, task inputs, templates, or cisco:ucs data in Splunk.
compatibility: >-
  Splunk Cloud Platform 10.5.2605: conditional. Follow documented package,
  entitlement, topology, and customer-managed runtime guardrails; self-managed
  paths remain on the public 10.4 baseline.
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Cisco UCS TA Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and `curl` | Run setup and REST configuration helpers | `command -v bash curl` |
| Splunk administrative access | Install the TA and configure tasks | Confirm search-tier REST access |
| UCS Manager account | Poll the selected domain | Store its password in a protected file |

## Workflow Overview

```text
┌───────────┐   ┌────────────┐   ┌────────────────┐   ┌───────────────┐
│ Preflight │ → │ Install TA │ → │ Configure tasks│ → │ Validate data │
└───────────┘   └────────────┘   └────────────────┘   └───────────────┘
```

## When to Activate

- Onboard a Cisco UCS Manager or Fabric Interconnect domain.
- Configure server records, default/custom templates, or `cisco_ucs_task` inputs.
- Diagnose missing `cisco:ucs` events or task failures.

## Scope

This skill configures the Splunk add-on and task schedule. It does not change
UCS infrastructure, request passwords in chat, or enable overlapping tasks
without considering API and ingestion load.

## Examples

Install the Cisco UCS add-on through the reviewed package path:

```bash
bash skills/cisco-ucs-ta-setup/scripts/setup.sh --install
```

Expected output: the package is installed or a topology-specific manual
handoff is emitted without configuring a UCS password inline.

Run strict completion checks after configuring a task:

```bash
bash skills/cisco-ucs-ta-setup/scripts/validate.sh --completion
```

Expected output: package, server, task, index, `cisco:ucs` event, and dashboard
handoff checks report `[PASS]` or exit nonzero.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| UCS login fails | Host, username, or protected password is wrong | Verify the account outside chat and retry |
| Task has no events | Template/domain access is incomplete | Review template and logs |
| API load is high | Tasks overlap or poll too frequently | Reduce task scope or increase intervals |
| No TA dashboards | TA supplies collection/parsing | Validate consuming content |

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Automates the Splunk Add-on for Cisco UCS (`Splunk_TA_cisco-ucs`, Splunkbase
`2731`) using the package's REST handlers and configuration model.

## Package Model

Install with `splunk-app-install --source splunkbase --app-id 2731`. This
skill then creates the `cisco_ucs` index, configures default class-ID
templates, creates UCS Manager server records, and enables `cisco_ucs_task`
inputs.

## Credentials

Never ask for UCS passwords in chat. Ask the user to create a local secret file:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/ucs_password
```

Then pass `--password-file /tmp/ucs_password`.

## Workflow

1. Install and initialize:

```bash
bash skills/cisco-ucs-ta-setup/scripts/setup.sh --install
```

2. Configure one UCS Manager:

```bash
bash skills/cisco-ucs-ta-setup/scripts/configure_server.sh \
  --name UCS_PROD \
  --server-url ucs-manager.example.com \
  --account-name splunk \
  --password-file /tmp/ucs_password
```

3. Configure an input task:

```bash
bash skills/cisco-ucs-ta-setup/scripts/configure_task.sh \
  --name UCS_PROD_all \
  --servers UCS_PROD \
  --templates UCS_Fault,UCS_Inventory,UCS_Performance \
  --index cisco_ucs
```

4. Validate:

```bash
bash skills/cisco-ucs-ta-setup/scripts/validate.sh --completion
```

See `reference.md` for default templates and package-derived CIM/source details.

## Validation Modes

Run the command above for diagnostics. Add `--completion` (alias `--strict`) to
require the UCS index, all default templates, a UCS Manager server record, an
enabled task input, and `cisco:ucs` events. This TA ships no standalone
dashboards.

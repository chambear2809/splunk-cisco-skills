---
name: splunk-servicenow-ta-setup
description: "Use when the user asks about Splunk_TA_snow, the Splunk Add-on for ServiceNow, ServiceNow incident or
  change or CMDB ingestion, snow:// inputs, or ITSM data onboarding in Splunk. Install, render, configure,
  and validate the Splunk Add-on for ServiceNow (Splunk_TA_snow, Splunkbase 1928). Renders real per-table
  snow:// inputs.conf stanzas (incident, change_request, problem, em_event, sys_user, cmdb_ci, and more)
  with the correct account, table, timefield, and id_field, emits a basic-auth or OAuth account runbook,
  creates the snow index, maps tables to snow:<table> source types, and validates ingestion."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Splunk Add-on for ServiceNow Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Splunk_TA_snow, the Splunk Add-on for ServiceNow, ServiceNow incident or change or CMDB ingestion, snow:// inputs,
  or ITSM data onboarding in Splunk.
- Preview and review the splunk servicenow ta setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-servicenow-ta-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-servicenow-ta-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first automation for the **Splunk Add-on for ServiceNow**
(`Splunk_TA_snow`, Splunkbase `1928`). The add-on pulls ServiceNow table records
through the REST API; each `snow://<table>` input emits the `snow:<table>`
source type.

The add-on runs on the search tier or a heavy forwarder. Run a given table input
on a single node to avoid duplicate collection.

## Package Verification Boundary

This skill's package-derived inputs and handlers were verified against
`11.0.2`, the current public release, which advertises Splunk 10.5. The package
was downloaded, unpacked, and inspected here, so the shared installer's default
pin needs no review override. When Splunkbase publishes a newer release, inspect
its input/account schema and repeat the completion-gate validation before
advancing the pin.

## Tables And Source Types

| Input | Source type |
| --- | --- |
| `snow://incident` | `snow:incident` |
| `snow://change_request` | `snow:change_request` |
| `snow://problem` | `snow:problem` |
| `snow://em_event` | `snow:em_event` |
| `snow://sys_user` | `snow:sys_user` |
| `snow://sys_user_group` | `snow:sys_user_group` |
| `snow://cmdb_ci` | `snow:cmdb_ci` |

## Credentials

Never paste a ServiceNow password or OAuth secret in chat or argv. Use a
read-only integration user. Write the secret to a local file and configure the
account in the add-on Configuration tab:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/snow_password
```

See the rendered `account-setup.md` for both basic-auth and OAuth modes.

## Workflow

1. Render reviewable assets (offline):

```bash
bash skills/splunk-servicenow-ta-setup/scripts/setup.sh --render \
  --index snow --account-name snow_prod --tables incident,change_request,problem,em_event
```

2. Install the add-on and create the index:

```bash
bash skills/splunk-servicenow-ta-setup/scripts/setup.sh --install --create-index --index snow
```

3. Configure the account (`account-setup.md`) and enable the rendered inputs.

4. Validate:

```bash
bash skills/splunk-servicenow-ta-setup/scripts/validate.sh --index snow
```

ServiceNow incident/change data is commonly consumed by Splunk ITSI; hand off
service and KPI modeling to `splunk-itsi-config`. See `reference.md` for the
full input/account model, checkpointing, source types, and placement guardrails.

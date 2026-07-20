---
name: cisco-asa-ta-setup
description: Use when onboarding or validating Cisco ASA or FTD syslog with Splunk_TA_cisco-asa and SC4S.
compatibility: >-
  Splunk Cloud Platform 10.5.2605: conditional. Follow documented package,
  entitlement, topology, and customer-managed runtime guardrails; self-managed
  paths remain on the public 10.4 baseline.
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Cisco ASA TA Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Render and validate the onboarding packet | `bash --version && python3 --version` |
| Splunk admin access | Install and search | Confirm target tier and index |
| SC4S or managed syslog receiver | Own the ASA/FTD transport path | Confirm listener, source, and routing ownership |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌─────────────────┐   ┌───────────────┐
│ Preflight │ → │ Render/review │ → │ Install/handoff │ → │ Validate data │
└───────────┘   └───────────────┘   └─────────────────┘   └───────────────┘
```

## When to Activate

- Onboard Cisco ASA or Firepower Threat Defense (FTD) syslog into Splunk.
- Diagnose missing or incorrectly typed `cisco:asa` events.
- Validate Common Information Model (CIM) and dashboard readiness after installation.

## Scope

This skill renders and validates the Splunk-side plan. It does not silently
open network listeners, alter firewall policy, or take ownership from an
existing syslog service. Hand off receiver mutation to the named SC4S or
platform owner.

## Examples

Render a review packet without mutation:

```bash
bash skills/cisco-asa-ta-setup/scripts/setup.sh --render \
  --index cisco_asa --sourcetype cisco:asa --syslog-owner sc4s --include-ftd
```

Expected output: a `cisco-asa-ta-rendered/` packet containing install, routing,
and validation assets without changing Splunk or the receiver.

Run the strict completion gate after installation and routing:

```bash
bash skills/cisco-asa-ta-setup/scripts/validate.sh \
  --rendered-dir cisco-asa-ta-rendered --live --completion
```

Expected output: package, index, source type, event, CIM, and dashboard-handoff
checks report `[PASS]`; missing evidence exits nonzero.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| No `cisco:asa` events | Receiver or route is incomplete | Verify the SC4S/listener handoff before changing the TA |
| Wrong source type | Receiver metadata differs | Correct the receiver route |
| No TA dashboards | The TA ships parsing | Validate consuming ES/firewall content |
| Live checks fail | Splunk is unreachable | Run offline checks and hand off live validation |

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first workflow for `Splunk_TA_cisco-asa` and Cisco ASA/FTD syslog data.
The skill emits reviewed placement notes, syslog handoffs, validation SPL, and
readiness evidence templates. It does not open syslog listeners, install apps,
or mutate Splunk in render-only mode. The explicit `--install` and `--all`
modes delegate package installation to `splunk-app-install`; syslog receiver
mutation remains a separate handoff.

## Commands

```bash
bash skills/cisco-asa-ta-setup/scripts/setup.sh --render \
  --index cisco_asa --sourcetype cisco:asa --syslog-owner sc4s --include-ftd
```

Review the rendered `install-commands.sh`, syslog checklist, and validation
searches before delegating installs or receiver work to `splunk-app-install`,
`splunk-connect-for-syslog-setup`, or platform owners.

## Execute

Preview the executable plan:

```bash
bash skills/cisco-asa-ta-setup/scripts/setup.sh --all --dry-run --json
```

Install the TA package and run local validation:

```bash
bash skills/cisco-asa-ta-setup/scripts/setup.sh --all
```

Add `--live` to make validation perform read-only Splunk REST/search checks.
The syslog receiver remains delegated to SC4S/syslog ownership workflows.

```bash
bash skills/cisco-asa-ta-setup/scripts/validate.sh \
  --rendered-dir cisco-asa-ta-rendered --live
```

The no-flag/live validator is diagnostic. Add `--completion` (alias `--strict`)
to require the installed TA, target index, and `cisco:asa` event evidence; the
completion flags require `--live`. `setup.sh --all --live` invokes this strict
gate automatically. The TA supplies parsing/CIM knowledge rather than
standalone dashboards, so dashboard use is handed off to ES/firewall content.

See `reference.md` for source type, CIM, and receiver guardrails.

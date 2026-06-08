---
name: cisco-asa-ta-setup
description: >-
  Render and validate a Splunk Add-on for Cisco ASA onboarding plan for
  Splunk_TA_cisco-asa, Cisco ASA or FTD syslog, cisco:asa source typing, SC4S
  or customer syslog receiver ownership, CIM Network_Traffic and
  Intrusion_Detection readiness, and ES/firewall dashboard evidence. Use when
  the user asks to onboard, configure, route, or validate Cisco ASA or FTD data
  in Splunk.
---

# Cisco ASA TA Setup

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
or mutate Splunk by itself.

## Workflow

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

See `reference.md` for source type, CIM, and receiver guardrails.

---
name: splunk-supported-addons-setup
description: >-
  Resolve Splunk Supported Add-ons to the correct install, configuration,
  forwarder, ingest, and post-ingest readiness workflow. Use when the user asks
  for Splunk-supported add-on coverage, supported-addons gap analysis, Unix or
  Linux add-on setup, database add-ons, Microsoft Exchange, Microsoft SCOM,
  NetApp ONTAP, Carbon Black, Symantec Endpoint Protection, Splunk_TA_nix,
  Splunk_TA_Linux, Linux CollectD, auditd, *nix scripted inputs, or router
  guidance before using splunk-app-install.
---

# Splunk Supported Add-ons Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Use this skill as the router for Splunk-supported add-ons before choosing an
install or configuration workflow. First-class profiles cover Unix/Linux:

- `Splunk_TA_nix` - Splunk Add-on for Unix and Linux, Splunkbase `833`
- `Splunk_TA_Linux` - Splunk Add-on for Linux, Splunkbase `3412`

Package-verified handoffs also cover selected database, Microsoft
infrastructure, NetApp ONTAP, web/proxy/syslog, cloud, endpoint, and security
appliance add-ons. Unresolved entries remain install-only handoffs instead of
invented configuration.

## What It Does

- Resolves add-on names, Splunkbase IDs, app folder names, source types, and
  domain aliases against `catalog.json`.
- Tracks the full official Splunk Supported Add-ons glossary as a coverage
  index and classifies entries as first-class profiles, skill handoffs, or
  install-only handoffs.
- Renders a reviewable setup plan, starter input overlays, validation SPL, and
  handoff commands.
- For official add-ons outside the first-class Unix/Linux domain, routes to a
  package-verified skill handoff when available or renders a generic handoff
  packet with official docs and local, remote, or Splunkbase package install
  templates.
- Routes app installation to `splunk-app-install`.
- Routes Universal Forwarder fleet deployment to `splunk-agent-management-setup`
  and UF runtime enrollment to `splunk-universal-forwarder-setup`.
- Routes post-ingest validation to `splunk-data-source-readiness-doctor`.
- Routes supported SPL2 size-reduction templates to `splunk-spl2-pipeline-kit`.

## Primary Commands

List supported domain profiles:

```bash
bash skills/splunk-supported-addons-setup/scripts/setup.sh --phase list --json
```

List official Supported Add-ons coverage:

```bash
bash skills/splunk-supported-addons-setup/scripts/setup.sh --phase coverage --json
```

Resolve a Unix/Linux profile:

```bash
bash skills/splunk-supported-addons-setup/scripts/setup.sh \
  --profile "Splunk_TA_nix" \
  --phase resolve \
  --json
```

Render a review packet:

```bash
bash skills/splunk-supported-addons-setup/scripts/setup.sh \
  --profile unix-linux \
  --phase render \
  --event-index os \
  --metrics-index os_metrics
```

Execute the routed install/setup command for a supported add-on:

```bash
bash skills/splunk-supported-addons-setup/scripts/setup.sh \
  --profile "Cisco ASA" \
  --execute
```

Preview that action without changing Splunk:

```bash
bash skills/splunk-supported-addons-setup/scripts/setup.sh \
  --profile "Cisco ASA" \
  --execute \
  --dry-run \
  --json
```

Validate the catalog and renderer:

```bash
bash skills/splunk-supported-addons-setup/scripts/validate.sh
```

## Agent Behavior

- Use `--execute --dry-run` first when routing an add-on install/setup from
  this skill. `--execute` runs the routed skill or install command directly.
- Treat Unix/Linux as the first-class implemented domain. For other official
  Supported Add-ons, use `--phase coverage` or `--phase resolve` to determine
  whether the router has a local skill handoff or a generic install-only path.
- For `Splunk_TA_nix`, prefer deployment-server or Agent Management rollout for
  configured forwarder apps. Its official docs support Deployment Server rollout.
- For `Splunk_TA_Linux`, do not push configured credential-bearing copies by
  Deployment Server; the official docs call out credential-vault and duplicate
  collection risks. Render handoffs instead.
- For FIPS environments, verify the target add-on's credential storage and
  modular input behavior before assigning collection to that tier. Some
  Splunk-supported add-ons require a non-FIPS heavy forwarder for collection.
- Keep HEC tokens, Splunkbase credentials, and Splunk credentials in local
  secret files. Never put secret values in chat, argv, rendered files, or docs.
- Read `reference.md` before changing version metadata, role placement, source
  type mappings, or guardrails.

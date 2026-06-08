---
name: splunk-windows-ta-setup
description: >-
  Install, render, configure, and validate the Splunk Add-on for Microsoft
  Windows (Splunk_TA_windows, Splunkbase 742). Renders reviewable
  inputs.local.conf overlays for WinEventLog (Security/System/Application,
  Defender, PowerShell), Perfmon, and WinHostMon inputs, creates the
  wineventlog and perfmon indexes, enforces UF/HF/search-tier placement, and
  maps source types to CIM data models. Use when the user asks about
  Splunk_TA_windows, the Splunk Add-on for Microsoft Windows, WinEventLog or
  Perfmon inputs, Windows Security event onboarding, Sysmon, or Windows CIM
  readiness in Splunk.
---

# Splunk Add-on for Microsoft Windows Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first automation for the **Splunk Add-on for Microsoft Windows**
(`Splunk_TA_windows`, Splunkbase `742`). The add-on collects Windows Event Log,
performance counters, and host-monitoring data. Inputs run on Windows
Universal Forwarders; parsing, knowledge objects, and CIM mappings run on the
search tier and indexers.

This skill renders reviewable `inputs.conf`/`props.conf` overlays, creates the
event and metrics indexes through the Splunk control plane, and hands the
Windows-side input rollout to `splunk-agent-management-setup`. It never edits a
Windows host directly.

## Placement

| Role | Splunk_TA_windows |
| --- | --- |
| Universal Forwarder (Windows) | Required for inputs (WinEventLog, Perfmon, WinHostMon) |
| Heavy Forwarder | Supported when an HF collects/parses Windows data |
| Indexer | Supported for index-time parsing |
| Search tier | Required for search-time knowledge objects and CIM |

Enable inputs on Windows forwarders with local configuration files, not the
Splunk Web setup page. Keep the add-on visible off on search heads.

## Workflow

1. Render reviewable assets (no Splunk credentials needed):

```bash
bash skills/splunk-windows-ta-setup/scripts/setup.sh --render \
  --event-index wineventlog --perfmon-index perfmon
```

2. Install the add-on on the search tier and create indexes:

```bash
bash skills/splunk-windows-ta-setup/scripts/setup.sh --install \
  --event-index wineventlog --perfmon-index perfmon
```

3. Roll the forwarder app out to Windows hosts through Agent Management:

```bash
bash skills/splunk-agent-management-setup/scripts/setup.sh \
  --mode agent-manager --deployment-app-name Splunk_TA_windows
```

4. Validate the deployment:

```bash
bash skills/splunk-windows-ta-setup/scripts/validate.sh
```

5. Score post-ingest CIM/data readiness:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack windows_security
```

## Rendered Inputs

The renderer emits a starter `inputs.local.conf` overlay with WinEventLog
Security/System/Application (plus Defender and PowerShell operational
channels), Perfmon CPU / memory / network / disk counters, and WinHostMon
stanzas, each pinned to the chosen indexes. Sysmon is a separate add-on and is
listed as a handoff, not bundled here. Review channels, intervals, and counter
catalogs before enabling in production.

See `reference.md` for the full source-type catalog, CIM data-model mapping,
index model, and placement guardrails.

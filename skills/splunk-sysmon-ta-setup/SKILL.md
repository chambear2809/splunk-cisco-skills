---
name: splunk-sysmon-ta-setup
description: >-
  Install, render, configure, and validate the Splunk Add-on for Microsoft
  Sysmon (Splunk_TA_microsoft_sysmon, Splunkbase 5709). Renders package-backed
  endpoint or Windows Event Collector WinEventLog inputs from extracted
  defaults, prevents duplicate direct-plus-WEC ingestion, hands off Universal
  Forwarder rollout, constrains readiness to the Sysmon source, and validates
  XmlWinEventLog Sysmon data. Use for Sysmon, WEC Sysmon, Microsoft Sysinternals
  Sysmon, or Splunk_TA_microsoft_sysmon onboarding. Use when the user asks to
  onboard, configure, render, or validate Microsoft Sysmon data in Splunk.
---

# Splunk Add-on for Microsoft Sysmon Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first automation for `Splunk_TA_microsoft_sysmon` (Splunkbase `5709`,
verified `5.0.0`). The renderer emits one collection mode at a time:
endpoint direct collection or Windows Event Collector. It does not install
Sysmon on endpoints.

## Workflow

Endpoint mode:

```bash
bash skills/splunk-sysmon-ta-setup/scripts/setup.sh --render --mode endpoint --index sysmon
```

WEC mode:

```bash
bash skills/splunk-sysmon-ta-setup/scripts/setup.sh --render --mode wec --index sysmon
```

Install and create the index:

```bash
bash skills/splunk-sysmon-ta-setup/scripts/setup.sh --install --create-index --index sysmon
```

Roll out the rendered deployment app through `splunk-universal-forwarder-setup`
or `splunk-agent-management-setup`, then validate:

```bash
bash skills/splunk-sysmon-ta-setup/scripts/validate.sh --index sysmon
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack sysmon
```

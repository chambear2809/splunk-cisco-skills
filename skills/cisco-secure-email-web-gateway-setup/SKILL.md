---
name: cisco-secure-email-web-gateway-setup
description: Use when onboarding Cisco ESA or WSA logs through supported Splunk add-ons and managed ingestion.
compatibility: >-
  Splunk Cloud Platform 10.5.2605: conditional. Follow documented package,
  entitlement, topology, and customer-managed runtime guardrails; self-managed
  paths remain on the public 10.4 baseline.
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Cisco Secure Email/Web Gateway Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash | Render package, index, macro, and transport assets | `bash --version` |
| Splunk administrative access | Install ESA/WSA add-ons and run searches | Confirm target-tier access |
| SC4S or file-monitor owner | Deliver ESA/WSA events to the parsing tier | Confirm one transport owner per source |

## Workflow Overview

```text
┌───────────┐   ┌─────────────────┐   ┌──────────────────┐   ┌───────────────┐
│ Preflight │ → │ Render packages │ → │ Configure ingest │ → │ Validate data │
└───────────┘   └─────────────────┘   └──────────────────┘   └───────────────┘
```

## When to Activate

- Onboard Cisco Email Security Appliance (ESA) or Web Security Appliance (WSA) logs.
- Configure email/netproxy indexes, macros, parser placement, or transport ownership.
- Diagnose missing source types, CIM fields, or dashboard evidence.

## Scope

This skill renders and validates Splunk-side ESA/WSA onboarding. It does not
configure appliance policy or silently create competing syslog and file-monitor
paths. Select one transport owner and preserve parser placement.

## Examples

Render both product paths for SC4S ownership:

```bash
bash skills/cisco-secure-email-web-gateway-setup/scripts/setup.sh \
  --product both --transport sc4s
```

Expected output: reviewable package, index, macro, parser, transport, and
validation assets are written without changing an appliance.

Run strict validation after events arrive:

```bash
bash skills/cisco-secure-email-web-gateway-setup/scripts/validate.sh \
  --completion --product both
```

Expected output: ESA and WSA package, source type, event, CIM, and dashboard
handoff checks report `[PASS]` or exit nonzero.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Events are duplicated | SC4S and file monitoring both collect the source | Keep one transport owner |
| Fields are missing | Parsing add-on is placed on the wrong tier | Correct parser placement and retest new events |
| Wrong dashboard index | Macros differ from inputs | Align macros with the index plan |
| One product passes | Only ESA or WSA transport is active | Validate each selected product independently |

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Automates Splunk-side setup for:

- Cisco Email Security Appliance add-on (`Splunk_TA_cisco-esa`, Splunkbase
  `1761`)
- Cisco Web Security Appliance add-on (`Splunk_TA_cisco-wsa`, Splunkbase
  `1747`)

These packages are parser/search-time add-ons. They do not contain device API
inputs, credentials, or custom REST account handlers. Collection is handled by
ESA/WSA syslog export, SC4S, or file-monitor deployment.

## Package Verification Boundary

The repository's ESA package-derived behavior was verified against `1.7.0`.
The current public ESA listing is `1.7.1` and advertises Splunk 10.5 support,
but this repository has not inspected that newer package. The shared installer
defaults to verified `1.7.0`; only `--accept-unverified-release` follows public
`1.7.1`. After that explicit override, re-check its manifest, source types,
eventtypes, and parser/dashboard evidence. The WSA package has no corresponding
verified/public-version drift in the registry.

## Workflow

Install and configure one or both products:

```bash
bash skills/cisco-secure-email-web-gateway-setup/scripts/setup.sh \
  --product both \
  --install
```

Render collector handoff assets:

```bash
bash skills/cisco-secure-email-web-gateway-setup/scripts/render_ingestion_assets.sh \
  --product both \
  --output-dir ./cisco-secure-email-web-gateway-rendered
```

Validate Splunk-side readiness:

```bash
bash skills/cisco-secure-email-web-gateway-setup/scripts/validate.sh --completion --product both
```

## Defaults

| Product | App | Index | Macro |
|---|---|---|---|
| ESA | `Splunk_TA_cisco-esa` | `email` | `Cisco_ESA_Index` |
| WSA | `Splunk_TA_cisco-wsa` | `netproxy` | `Cisco_WSA_Index` |

Use `splunk-connect-for-syslog-setup` for SC4S runtime deployment. This skill
only prepares the Splunk-side add-ons, indexes, macros, and rendered handoff
snippets.

## Validation Modes

Run `scripts/validate.sh` for diagnostics. Use `--completion` (alias `--strict`)
to require the selected parser TA, index, macro, and matching event data. The
ESA/WSA parser packages do not provide standalone dashboards, so the explicit
SC4S/file-monitor transport handoff plus data evidence is the completion gate.

---
name: splunk-secure-gateway-setup
description: >-
  Render, validate, and apply Splunk Secure Gateway (Spacebridge) setup: enable
  or disable the splunk_secure_gateway app on Splunk Enterprise, Spacebridge
  outbound egress preflight, deployment settings and app-visibility runbooks,
  MDM instance-ID configuration, Private Spacebridge endpoint config, and mobile
  device registration runbooks. Splunk Cloud targets are routed to the managed
  readiness workflow without app-state mutation. Use when the user asks to set
  up Splunk Secure Gateway, connect the Splunk mobile apps (Connected
  Experiences), configure Spacebridge or Private Spacebridge, enable or disable
  Secure Gateway, register devices, or prepare MDM distribution.
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Secure Gateway Setup

This skill renders and applies Splunk Secure Gateway configuration. It is
render-first because enabling the app opens outbound connectivity to Spacebridge
on Splunk's cloud infrastructure.

## Agent Behavior

Never ask for secrets; app enable/disable uses the project `credentials` file.
Enabling Secure Gateway opens outbound 443 to the Spacebridge host and refuses
to proceed without `--accept-spacebridge-egress`. Device registration uses auth
codes or QR codes and is inherently interactive (rendered as a runbook).

App-state mutation is limited to Splunk Enterprise. Before apply, `--platform
auto` resolves the configured target; managed Splunk Cloud returns exit `2`
without enabling, disabling, or configuring `splunk_secure_gateway`. For Splunk
Cloud Platform 10.5.2605, use `splunk-secure-gateway --platform cloud` to render
the managed-service readiness and operator handoff bundle.

## Quick Start

Render deployment assets:

```bash
bash skills/splunk-secure-gateway-setup/scripts/setup.sh --deployment-name prod-sh --visible-apps search,cisco-catalyst-app
```

Check Spacebridge egress:

```bash
bash skills/splunk-secure-gateway-setup/scripts/setup.sh --platform enterprise --phase preflight
```

Enable the app live (gated):

```bash
bash skills/splunk-secure-gateway-setup/scripts/setup.sh --platform enterprise \
  --phase apply --action enable --accept-spacebridge-egress
```

Disable the app:

```bash
bash skills/splunk-secure-gateway-setup/scripts/setup.sh --platform enterprise \
  --phase apply --action disable
```

## What It Renders

- `egress-preflight.sh` - outbound 443 check to the Spacebridge host (no inbound ports)
- `instance-id-config.json` - MDM custom app configuration skeleton (incl. Private Spacebridge `endpoint_config`)
- `deployment-settings-runbook.md` - Splunk Web deployment name / app visibility / region
- `registration-runbook.md` - device registration via auth code, QR, or MDM

Secure Gateway routes encrypted data through Spacebridge over outbound 443 to
`prod.spacebridge.spl.mobi`. Deployment settings and registration are Splunk Web
and MDM operations. This skill manages app state only on Splunk Enterprise; on
Splunk Cloud it renders assets and routes to the managed workflow.

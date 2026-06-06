---
name: splunk-secure-gateway-setup
description: >-
  Render, validate, and apply Splunk Secure Gateway (Spacebridge) setup: enable
  or disable the splunk_secure_gateway app, Spacebridge outbound egress
  preflight, deployment settings and app-visibility runbooks, MDM instance-ID
  configuration, Private Spacebridge endpoint config, and mobile device
  registration runbooks. Use when the user asks to set up Splunk Secure Gateway,
  connect the Splunk mobile apps (Connected Experiences), configure Spacebridge
  or Private Spacebridge, enable or disable Secure Gateway, register devices, or
  prepare MDM distribution.
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

## Quick Start

Render deployment assets:

```bash
bash skills/splunk-secure-gateway-setup/scripts/setup.sh --deployment-name prod-sh --visible-apps search,cisco-catalyst-app
```

Check Spacebridge egress:

```bash
bash skills/splunk-secure-gateway-setup/scripts/setup.sh --phase preflight
```

Enable the app live (gated):

```bash
bash skills/splunk-secure-gateway-setup/scripts/setup.sh --phase apply --action enable --accept-spacebridge-egress
```

Disable the app:

```bash
bash skills/splunk-secure-gateway-setup/scripts/setup.sh --phase apply --action disable
```

## What It Renders

- `egress-preflight.sh` - outbound 443 check to the Spacebridge host (no inbound ports)
- `instance-id-config.json` - MDM custom app configuration skeleton (incl. Private Spacebridge `endpoint_config`)
- `deployment-settings-runbook.md` - Splunk Web deployment name / app visibility / region
- `registration-runbook.md` - device registration via auth code, QR, or MDM

Secure Gateway routes encrypted data through Spacebridge over outbound 443 to
`prod.spacebridge.spl.mobi`. Deployment settings and registration are Splunk Web
and MDM operations; this skill manages app state and validates egress.

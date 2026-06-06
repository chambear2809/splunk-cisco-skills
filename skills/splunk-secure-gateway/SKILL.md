---
name: splunk-secure-gateway
description: >-
  Render, preflight, and validate Splunk Secure Gateway and Splunk Connected
  Experiences (Splunk Mobile, Splunk TV, Splunk AR) readiness: Spacebridge
  outbound connectivity checks, splunk_secure_gateway app enablement, token
  (JWT) authentication readiness, device registration handoff, and an MDM
  AppConfig template. Use when the user asks to set up Splunk Mobile or Connected
  Experiences, enable or troubleshoot Splunk Secure Gateway, verify Spacebridge
  connectivity, register mobile devices, configure MDM for Splunk Mobile, or
  check mobile alert/dashboard delivery readiness.
---

# Splunk Secure Gateway / Mobile

This skill renders Splunk Secure Gateway (`splunk_secure_gateway`) and Connected
Experiences (Splunk Mobile, Splunk TV, Splunk AR) readiness assets: Spacebridge
outbound connectivity preflight, app enablement, token (JWT) authentication
readiness, device registration handoff, and an MDM AppConfig template. It is
render-first because Secure Gateway depends on outbound Spacebridge connectivity
and token auth that must be verified before users can register devices.

## How It Works

Secure Gateway routes encrypted traffic through **Spacebridge**, a Splunk-hosted
relay. There are **no inbound** firewall rules; you only need **outbound 443**
to `prod.spacebridge.spl.mobi` (WebSocket). Devices register via an in-app
authentication code or via MDM. Token (JWT) authentication must be enabled for
the Connected Experiences apps to work.

## Agent Behavior

This skill does not handle secrets in chat. Token authentication is enabled in
Splunk (Settings > Tokens) by an admin; this skill checks readiness and hands
off, it does not mint tokens. Use `template.example` for non-secret values:
region, deployment name, platform, and MDM toggle.

## Quick Start

Render and run the Spacebridge connectivity preflight:

```bash
bash skills/splunk-secure-gateway/scripts/setup.sh --region default --phase preflight
```

Render the full readiness bundle (connectivity + enable + registration + MDM):

```bash
bash skills/splunk-secure-gateway/scripts/setup.sh \
  --region us-east-1 --deployment-name "Prod SH" --mdm true
```

Validate rendered assets and check status live:

```bash
bash skills/splunk-secure-gateway/scripts/validate.sh --live
```

## What It Renders

- `connectivity-preflight.sh` — Spacebridge `health_check` (primary + regional)
  and the WebSocket upgrade test on outbound 443
- `enable.sh` — enable `splunk_secure_gateway` and check token-auth readiness
- `register.sh` — device registration handoff (in-app auth code) and prerequisites
- `mdm-appconfig.xml` — Managed App Configuration template for Splunk Mobile MDM
- `status.sh` — app state, token-auth state, and connectivity recheck
- `README.md` / `metadata.json` — review context

## Operating Notes

- Outbound 443 to `prod.spacebridge.spl.mobi` is required; no inbound ports.
- If a proxy does SSL decryption, it must support WebSockets or exempt
  `prod.spacebridge.spl.mobi`.
- Token (JWT) authentication must be enabled or device registration fails;
  changing a user's credentials unregisters their device.
- On Splunk Cloud, Secure Gateway is managed for you; connectivity is from the
  Splunk-managed search head. On Enterprise, verify egress from the search head.

Read `reference.md` before enabling token auth broadly or rolling out MDM.

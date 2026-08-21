---
name: splunk-secure-gateway-setup
description: "Use when the user asks about Splunk Secure Gateway, Connected Experiences, Spacebridge, Private
  Spacebridge, or mobile distribution. Apply only splunk_secure_gateway app enable/disable on an explicit
  Splunk Enterprise target. Render an Enterprise egress check, endpoint and instance-ID placeholder
  skeletons, and Splunk Web/MDM/device-registration operator runbooks; configure has no live API. Splunk
  Cloud permits plain render/support handoff only, with no local probe, session authentication, or live REST."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Splunk Secure Gateway Setup

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

- Set up Splunk Secure Gateway, connect the Splunk mobile apps (Connected Experiences), configure Spacebridge or
  Private Spacebridge, enable or disable Secure Gateway, register devices, or prepare MDM distribution.
- Preview and review the splunk secure gateway setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-secure-gateway-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-secure-gateway-setup/scripts/validate.sh --help
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

This skill renders and applies Splunk Secure Gateway configuration. It is
render-first because enabling the app opens outbound connectivity to Spacebridge
on Splunk's cloud infrastructure.

## Agent Behavior

Never ask for secrets; app enable/disable uses the project `credentials` file.
Enabling Secure Gateway opens outbound 443 to the Spacebridge host and refuses
to proceed without `--accept-spacebridge-egress`. Device registration uses auth
codes or QR codes and is inherently interactive (rendered as a runbook).

App-state mutation is limited to Splunk Enterprise. `--platform auto` resolves
the configured target before rendering. Managed Splunk Cloud preflight, status,
apply, all, and render-with-apply requests return exit `2` before artifacts,
probes, authentication, or live requests. Plain Cloud render emits review-only
instance-ID skeletons and operator runbooks plus an exit-2 egress handoff; local
egress is not valid Cloud evidence.

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

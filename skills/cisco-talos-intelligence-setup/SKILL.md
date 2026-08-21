---
name: cisco-talos-intelligence-setup
description: Use when validating Cisco Talos reputation enrichment and service-account readiness in Splunk ES Cloud.
compatibility: >-
  Splunk Cloud Platform 10.5.2605: conditional. Follow documented package,
  entitlement, topology, and customer-managed runtime guardrails; self-managed
  paths remain on the public 10.4 baseline.
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Cisco Talos Intelligence Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash | Run package and completion checks | `bash --version` |
| ES Cloud admin access | Install and validate Talos | Confirm administrative access |
| Service certificate | Authorize enrichment | Verify without printing it |

## Workflow Overview

```text
┌───────────┐   ┌────────────────┐   ┌───────────────────┐   ┌─────────────────────┐
│ Preflight │ → │ Install add-on │ → │ Verify capability │ → │ Validate enrichment │
└───────────┘   └────────────────┘   └───────────────────┘   └─────────────────────┘
```

## When to Activate

- Install or validate `Splunk_TA_Talos_Intelligence` in ES Cloud.
- Check Talos service-account certificate and capability readiness.
- Diagnose failed enrichment, adaptive response, or threat-list state.

## Scope

This skill validates the supported ES Cloud integration surface. It does not
mint certificates, enable deprecated blacklist collection silently, or claim
support for an unverified self-managed topology.

## Examples

Install the reviewed Talos package path:

```bash
bash skills/cisco-talos-intelligence-setup/scripts/setup.sh --install
```

Expected output: the package is installed through the supported topology path,
or a precise ES Cloud administrative handoff is emitted.

Run the strict readiness gate:

```bash
bash skills/cisco-talos-intelligence-setup/scripts/validate.sh --completion
```

Expected output: package, certificate, `get_talos_enrichment`, adaptive action,
and disabled-threat-list checks report `[PASS]` or exit nonzero.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Enrichment capability is absent | Role or package setup is incomplete | Correct ES capability mapping and retest |
| Certificate fails | Material is missing/expired | Renew through its owner |
| Adaptive response fails | Permissions/app state is incomplete | Verify ES action setup |
| Legacy blacklist is enabled | Unsupported threat-list state remains | Review and disable it before completion |

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Automates readiness checks for Cisco Talos Intelligence for Enterprise Security
Cloud (`Splunk_TA_Talos_Intelligence`, Splunkbase `7557`).

This is not a normal polling input add-on. The package provides:

- a custom `/query_reputation` REST handler
- `get_talos_enrichment` capability
- adaptive response actions for collection and enrichment
- an encrypted Talos service account certificate/private-key stanza
- a disabled Talos IP blacklist threatlist

## Package Verification Boundary

This skill's package-derived capability, REST-handler, and alert-action model
was verified against `1.0.3`, the current public release, which advertises
Splunk 10.5. The package was downloaded, unpacked, and inspected here, so the
shared installer's default pin needs no review override. Still repeat the
capability, action, configuration-stanza, and threatlist-state checks against
the live stack before declaring readiness.

## Support Posture

Treat this as ES Cloud-first. Splunk documents the app for supported Splunk
Enterprise Security Cloud deployments, ES `7.3.2+`, and non-FedRAMP
environments.

Do not ask the user for the Talos service account certificate/private key in
chat. Splunk Cloud normally provisions the service account material; this skill
validates its presence and fingerprint.

## Workflow

Install and create the optional collection index:

```bash
bash skills/cisco-talos-intelligence-setup/scripts/setup.sh --install
```

Validate readiness:

```bash
bash skills/cisco-talos-intelligence-setup/scripts/validate.sh --completion
```

Only use file-based service account injection for explicit diagnostics:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/talos_service_account.pem
bash skills/cisco-talos-intelligence-setup/scripts/configure_service_account.sh \
  --service-account-file /tmp/talos_service_account.pem
```

The IP blacklist threatlist stays disabled unless the user explicitly enables it.

## Validation Modes

Run `scripts/validate.sh` for readiness diagnostics. Use `--completion` (alias
`--strict`) to require the provisioned Talos service-account stanza and
fingerprint in addition to the required ES app, capabilities, and alert
actions. Talos provides ES enrichment actions rather than standalone
dashboards or a continuously enabled event input.

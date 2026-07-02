---
name: cisco-talos-intelligence-setup
description: >-
  Install and validate Cisco Talos Intelligence for Splunk Enterprise Security
  Cloud. Covers ES Cloud support posture, Talos service account certificate
  readiness, get_talos_enrichment capability, adaptive response actions,
  optional collection index, and disabled IP blacklist threatlist checks. Use
  when the user asks about Cisco Talos Intelligence, Talos reputation
  enrichment, Splunk_TA_Talos_Intelligence, or Talos ES Cloud readiness.
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Cisco Talos Intelligence Setup

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
was verified against `1.0.1`. The current public release is `1.0.3` and
advertises Splunk 10.5 support, but this repository has not inspected that
newer package. The shared installer defaults to verified `1.0.1`; only
`--accept-unverified-release` follows public `1.0.3`. After that explicit
override, repeat the capability, action, configuration-stanza, and
dashboard/package-evidence checks before declaring readiness.

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

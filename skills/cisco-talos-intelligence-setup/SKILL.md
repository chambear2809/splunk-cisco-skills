---
name: cisco-talos-intelligence-setup
description: >-
  Install and validate Cisco Talos Intelligence for Splunk Enterprise Security
  Cloud. Covers ES Cloud support posture, Talos service account certificate
  readiness, get_talos_enrichment capability, adaptive response actions,
  optional collection index, and disabled IP blacklist threatlist checks. Use
  when the user asks about Cisco Talos Intelligence, Talos reputation
  enrichment, Splunk_TA_Talos_Intelligence, or Talos ES Cloud readiness.
---

# Cisco Talos Intelligence Setup

Automates readiness checks for Cisco Talos Intelligence for Enterprise Security
Cloud (`Splunk_TA_Talos_Intelligence`, Splunkbase `7557`).

This is not a normal polling input add-on. The package provides:

- a custom `/query_reputation` REST handler
- `get_talos_enrichment` capability
- adaptive response actions for collection and enrichment
- an encrypted Talos service account certificate/private-key stanza
- a disabled Talos IP blacklist threatlist

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
bash skills/cisco-talos-intelligence-setup/scripts/validate.sh
```

Only use file-based service account injection for explicit diagnostics:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/talos_service_account.pem
bash skills/cisco-talos-intelligence-setup/scripts/configure_service_account.sh \
  --service-account-file /tmp/talos_service_account.pem
```

The IP blacklist threatlist stays disabled unless the user explicitly enables it.

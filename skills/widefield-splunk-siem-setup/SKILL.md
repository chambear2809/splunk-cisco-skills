---
name: widefield-splunk-siem-setup
description: >-
  Render, apply, and validate Splunk SIEM readiness for WideField Security
  events using a WideField index, HEC token, schema-light spath searches,
  saved searches, macros, and starter dashboard assets. Use when the user asks
  to send WideField Security events to Splunk, create WideField HEC/index
  plumbing, validate WideField ingest, or prepare SIEM searches and dashboard
  readiness for identity threat detections.
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# WideField Splunk SIEM Setup

Prepare Splunk Platform to receive and search WideField Security events.

## Workflow

Render reviewable assets:

```bash
bash skills/widefield-splunk-siem-setup/scripts/setup.sh --render
```

Apply in Splunk Enterprise with a file-backed HEC token value:

```bash
bash skills/widefield-splunk-siem-setup/scripts/setup.sh --apply --accept-apply \
  --splunk-platform enterprise \
  --hec-token-file /secure/splunk/widefield_hec_token
```

For Splunk Cloud, let ACS create the token and write the returned value to a
local-only file:

```bash
bash skills/widefield-splunk-siem-setup/scripts/setup.sh --apply --accept-apply \
  --splunk-platform cloud \
  --write-hec-token-file /secure/splunk/widefield_hec_token
```

## Defaults

- Index: `widefield`
- Sourcetype: `widefield:security`
- Source: `widefield`
- HEC token name: `widefield_security_hec`

The skill delegates token lifecycle to `splunk-hec-service-setup` and uses
schema-light `spath` searches so WideField event shapes can evolve safely.

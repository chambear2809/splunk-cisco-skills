---
name: splunk-hec-service-setup
description: >-
  Render, preflight, apply, and validate Splunk HTTP Event Collector service
  configuration for Splunk Enterprise and Splunk Cloud. Use when the user asks
  for reusable HEC token management, inputs.conf rendering, ACS HEC tokens,
  allowed index restrictions, indexer acknowledgement, HEC port/TLS settings,
  or a shared ingestion endpoint for apps and external collectors.
---

# Splunk HEC Service Setup

This skill prepares a reusable Splunk HTTP Event Collector service. It renders
reviewable Enterprise `inputs.conf` assets and Splunk Cloud ACS payloads without
placing token values in chat, metadata, or command-line arguments.

## Agent Behavior

Never ask for HEC token values in chat. Use file-based token handling:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/app_hec_token
```

Use `template.example` for non-secret values:

- platform
- token name
- default and allowed indexes
- source and sourcetype defaults
- HEC port and TLS mode
- whether indexer acknowledgement is appropriate
- token-file paths

## Quick Start

Render Enterprise HEC assets:

```bash
bash skills/splunk-hec-service-setup/scripts/setup.sh \
  --platform enterprise \
  --token-name app_hec \
  --default-index app \
  --allowed-indexes app,summary
```

Apply on a Splunk Enterprise HEC tier after review:

```bash
bash skills/splunk-hec-service-setup/scripts/setup.sh \
  --platform enterprise \
  --phase apply \
  --token-file /tmp/app_hec_token \
  --token-name app_hec \
  --default-index app \
  --allowed-indexes app,summary
```

Create or update a Splunk Cloud HEC token through ACS:

```bash
bash skills/splunk-hec-service-setup/scripts/setup.sh \
  --platform cloud \
  --phase apply \
  --write-token-file /tmp/app_hec_token \
  --token-name app_hec \
  --default-index app \
  --allowed-indexes app,summary
```

## What It Renders

- `inputs.conf.template` for Enterprise `splunk_httpinput/local`
- `acs-hec-token.json` for the ACS HEC token API shape
- `acs-hec-token-bulk.json` for ACS CLI bulk workflows
- helper scripts for preflight, Enterprise apply, Cloud ACS apply, and status

Enterprise apply substitutes the token from a local token file at apply time.
Cloud apply lets ACS create the token value and writes it to a local-only file
only when requested.

Read `reference.md` before enabling `useACK` or deploying to clustered
Enterprise HEC tiers.

---
name: splunk-asset-risk-intelligence-setup
description: >-
  Install, configure readiness, and validate Splunk Asset and Risk
  Intelligence (`SplunkAssetRiskIntelligence`, Splunkbase app 7180), including
  ARI indexes, KV Store readiness, ARI roles, and Enterprise Security Exposure
  Analytics handoff. Use when a user asks to set up ARI, Splunk Asset and Risk
  Intelligence, or ES Exposure Analytics readiness.
---

# Splunk Asset and Risk Intelligence Setup

Use this skill for Splunk Asset and Risk Intelligence (ARI).

## Primary Commands

Preview:

```bash
bash skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh --dry-run --json
```

Install, create ARI indexes, and validate:

```bash
bash skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh --file /path/to/splunk-asset-and-risk-intelligence.tgz
```

Validate only:

```bash
bash skills/splunk-asset-risk-intelligence-setup/scripts/validate.sh
```

## Agent Behavior

- Prefer `--file` when Splunkbase access is restricted for app `7180`.
- Create and validate `ari_staging`, `ari_asset`, `ari_internal`, and `ari_ta`.
- Validate KV Store and ARI role readiness, but do not assign users to roles.
- Route Enterprise Security 8.5+ Exposure Analytics setup to the ES config
  workflow as a handoff.

Read `reference.md` for app IDs, required indexes, and source links.

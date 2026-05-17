---
name: splunk-asset-risk-intelligence-setup
description: >-
  Install, prepare, validate, and plan Splunk Asset and Risk Intelligence
  (`SplunkAssetRiskIntelligence`, Splunkbase app 7180), including ARI indexes,
  KV Store, roles/capabilities, app readiness, data visibility, Enterprise
  Security integration, ES 8.5+ Exposure Analytics, ARI Technical Add-ons, ARI
  Echo, upgrade, and uninstall prerequisite handoffs. Use when a user asks to
  set up ARI, Splunk Asset and Risk Intelligence, asset/identity risk
  inventory, or ARI-backed ES Exposure Analytics readiness.
---

# Splunk Asset and Risk Intelligence Setup

Use this skill for Splunk Asset and Risk Intelligence (ARI). It is
setup-plus-handoff coverage, not ARI config-as-code.

## Prerequisites

- A Splunk credentials file readable by the shared credential helper. If not
  yet configured, run
  `bash skills/shared/scripts/setup_credentials.sh`
  or copy `credentials.example` and edit it (`chmod 600 credentials`).
- App delivery uses the
  [`splunk-app-install`](../splunk-app-install/SKILL.md) wrapper
  (`skills/splunk-app-install/scripts/install_app.sh`) so Splunkbase auth and
  ACS upload paths stay in one place. ARI is currently a restricted-entitlement
  app on Splunkbase; pass `--file <path-to-tgz>` when Splunkbase pulls fail.
- For SHC deployments, run the install/setup against the deployer/captain
  (the search-tier role placement is `required`); this skill does not split
  per-member work.
- Treat Splunk platform compatibility carefully: Splunkbase lists ARI `1.2.1`
  for Splunk `9.0` through `10.3`, while ARI docs signal `9.1.3+` for current
  ARI releases. Warn below `9.1.3`; do not hard-fail only on that conflict.

## Primary Commands

Preview:

```bash
bash skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh --dry-run --json
```

Full read-only handoff plan:

```bash
bash skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh --full-handoff
```

Install, create ARI indexes, and validate:

```bash
bash skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh --file /path/to/splunk-asset-and-risk-intelligence.tgz
```

Validate only:

```bash
bash skills/splunk-asset-risk-intelligence-setup/scripts/validate.sh
```

## Handoff Flags

Use these flags for read-only planning without modifying Splunk unless combined
with `--install`:

- `--preflight-only`
- `--full-handoff`
- `--post-install-handoff`
- `--admin-handoff`
- `--risk-handoff`
- `--response-audit-handoff`
- `--investigation-handoff`
- `--es-integration-handoff`
- `--exposure-analytics-handoff`
- `--addon-handoff`
- `--echo-handoff`
- `--upgrade-handoff`
- `--uninstall-handoff`

## Agent Behavior

- Prefer `--file` when Splunkbase access is restricted for app `7180`.
- Create and validate `ari_staging`, `ari_asset`, `ari_internal`, and `ari_ta`.
- Validate KV Store, ARI roles, ARI capabilities, app-owned saved-search
  visibility, `ari_ta` data visibility, ES presence/version hints, and
  related-product evidence where observable.
- Do not automate ARI app-specific UI/API configuration, role assignment,
  secret-bearing Echo connections, Universal Forwarder rollout details,
  destructive data cleanup, index removal, app removal, or ES integration
  changes by default.
- Route Enterprise Security 8.5+ Exposure Analytics implementation detail to
  `splunk-enterprise-security-config`; only ARI Asset, IP, Mac, and User entity
  discovery sources belong in that mode.
- Keep normal ARI-to-ES integration separate from ES 8.5+ Exposure Analytics:
  normal mode covers asset/identity sync, swim lanes, workflow actions,
  `ari_lookup_host()`, `ari_lookup_ip()`, ES field mapping, `ari_risk_score`,
  and ES risk factors.
- Include related-product handoffs for ARI Technical Add-ons (Windows `7214`,
  Linux `7416`, macOS `7417`) and ARI Echo. Do not automate Echo installation
  until the Splunkbase ID/package name is locally verified.

Read `reference.md` for the official coverage map, app IDs, lifecycle surfaces,
and source links.

## MCP Tools

This skill includes checked-in, read-only Splunk MCP custom tools generated
from `mcp_tools.source.yaml`.

Validate or regenerate the tool artifact:

```bash
python3 skills/shared/scripts/mcp_tools.py validate skills/splunk-asset-risk-intelligence-setup
python3 skills/shared/scripts/mcp_tools.py generate skills/splunk-asset-risk-intelligence-setup
```

Load the tools into Splunk MCP Server:

```bash
bash skills/splunk-asset-risk-intelligence-setup/scripts/load_mcp_tools.sh
```

The loader uses the supported `/mcp_tools` REST batch endpoint by default. Use
`--allow-legacy-kv` only for older MCP Server app versions that lack that
endpoint.

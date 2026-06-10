# Splunk 10.4 Enterprise Deployment Notes

Verified for Splunk Enterprise/Universal Forwarder `10.4.0` and Splunk Cloud
Platform `10.4.2603` planning.

These notes are the prose companion to the machine-readable platform-version
contract in `skills/shared/references/splunk_platform_versions.json` (loaded via
`skills/shared/lib/platform_versions.py` and
`skills/shared/lib/platform_version_helpers.sh`). The JSON contract is the single
source of truth for default versions, supported compatibility lists, and SVD
floors; this document explains the operational gates behind those defaults.

Use these notes from skills that render or validate enterprise deployment
assets, especially admin doctor, search head cluster, deployment server/Agent
Management, license manager, Monitoring Console, HEC, ACS, restart, PKI, and
host bootstrap workflows.

## Runtime Posture

- Linux Enterprise hosts remain the production self-managed apply target for
  this repo. Run Splunk as a dedicated non-root service user; root-owned
  package installation is acceptable only for package/file placement and must
  hand back service ownership before runtime.
- Windows Enterprise is render-only in this repo. Splunk 10.4 plans must choose
  the installer-managed local service account (`NT SERVICE\Splunkd`) or a
  dedicated non-admin domain/local DUA service account and must not embed
  passwords in rendered assets. Do not use the removed Local System User path
  for new Windows Enterprise installs.
- macOS Enterprise is not a production deployment target here. Use it only for
  non-production development or product inspection.

## Upgrade And App Compatibility

- Enforce supported upgrade paths before touching binaries. Splunk Enterprise
  10.4 upgrades must start from a supported 10.x hop such as 10.0.x or 10.2.x;
  do not upgrade 9.3/9.4 hosts directly to 10.4. Universal Forwarder 10.4 direct
  upgrades require an installed UF 10.0.x or newer.
- Search-head and SHC upgrades must verify KV Store/Mongo server version before
  the binary upgrade. Direct 9.x-or-below to 10.4 is blocked when KV Store/Mongo
  is below 7.x; upgrade KV Store on an intermediate supported release first.
- Review custom apps for Splunk 10.4's Python 3.13 default, Python 3.9 fallback
  usage, Node.js removal exposure, and removed jQuery 2 dependencies.
- Do not assume add-ons that worked on 10.2/10.3 are 10.4-compatible. Public
  Splunkbase apps need explicit 10.4 compatibility metadata or an explicit
  unsupported status in `skills/shared/app_registry.json`.
- Remove or replace SHA-1 certificate/signature dependencies before 10.4
  promotion. PKI renders should use SHA-256 or stronger signatures, and FIPS/STIG
  renders must keep their stricter cipher and signature choices.

## Clustered And Distributed Deployments

- Search head clusters use deployer-based app/config distribution and captain
  orchestration. Do not use deployment server/Agent Management to manage SHC
  members.
- Indexer clusters use cluster-manager bundles for peer configuration. Do not
  use deployment server/Agent Management for indexer peer apps.
- Deployment server/Agent Management serverclass plans must avoid removed or
  deprecated serverclass parameters and must explicitly set app-level
  `filterType` so 9.4.3+ and 10.4 behavior is reviewable.
- License manager, Monitoring Console, HEC, federated search, and restart plans
  need topology-aware handoffs: standalone, distributed search, indexer cluster,
  SHC, deployment server, license manager, and Monitoring Console are separate
  operational roles even when they share hosts in small environments.
- KV Store TLS reviews must inspect `[kvstore]`, `[sslConfig]`, and
  `[kvstoreSslClientConfig]`; Splunk 10.4 evaluates KV Store TLS settings per
  field, so partial legacy `[kvstore]` overrides can become active.
- Azure SmartStore upgrades must confirm `[general] encrypt_fields` covers
  `remote.azure.tenant_id` and `remote.azure.client_id` when those fields are in
  use before 10.4 promotion.
- Dashboard Studio dashboards that require auto-refresh need explicit
  `auto_refresh_dashboards` capability guidance.

## Cloud And ACS

- Splunk Cloud Platform 10.4 planning should use the `10.4.2603` ACS
  documentation set for allowlists, HEC tokens, restarts, and ACS capability
  requirements. `10.3.2512` remains a supported alternate Cloud train.
- Model Cloud experience explicitly. Victoria has no IDM, does not support
  Hybrid Search, and migrations from Classic move IDM apps/configuration to the
  search tier; any IDM-era allowlists must be reviewed against search head or
  SHC member IPs.
- Cloud workflows must use ACS or supported Splunk Web/API paths. They must not
  claim filesystem edits, restarts, app installs, HEC token writes, or allowlist
  changes that ACS does not expose.

# Splunk Asset and Risk Intelligence Reference

`last_verified: 2026-05-03`

## Product Identity

- Product: Splunk Asset and Risk Intelligence (ARI)
- App ID: `7180`
- App name: `SplunkAssetRiskIntelligence`
- Latest researched version: `1.2.1` (October 9, 2025)
- Package pattern: `splunk-asset-and-risk-intelligence_*`
- Access: restricted downloaders only
- Splunkbase compatibility researched: Splunk Enterprise / Cloud Platform
  `9.0` through `10.3`
- Documentation compatibility signal: ARI `1.2.x` / `1.1.3` on `9.1.3+`
  including `10.x`; warn below `9.1.3`, do not hard-fail solely because the
  two official signals differ.

## Automated Coverage

- Install app `7180` through `splunk-app-install`, with local package fallback.
- Create and validate required indexes:
  - `ari_staging`
  - `ari_asset`
  - `ari_internal`
  - `ari_ta`
- Validate app presence/version, Splunk platform version, KV Store, ARI roles,
  ARI capabilities, app-owned saved-search visibility, `ari_ta` data visibility,
  ES presence/version hints, and related-product evidence where observable.

## Required Roles and Capabilities

- Roles:
  - `ari_admin`
  - `ari_analyst`
- ARI capabilities:
  - `ari_manage_data_source_settings`
  - `ari_manage_metric_settings`
  - `ari_manage_report_exceptions`
  - `ari_dashboard_add_alerts`
  - `ari_edit_table_fields`
  - `ari_save_filters`
  - `ari_manage_filters`
  - `ari_manage_homepage_settings`

The skill validates role/capability visibility but does not assign users or
modify role membership.

## Operator Handoffs

- Preflight: search head/indexer sizing, KV Store, platform version, Splunk
  Cloud vs Enterprise vs SHC path, restart requirement, usage-data notice,
  restricted entitlement.
- Post-install: restart, Post-install configuration, internal lookups,
  enrichment rules, `ari_admin`/`ari_analyst`, ARI capabilities.
- Admin/data: company subnet and user directories, known/custom data sources,
  event searches, data source activation, source priorities, field priorities,
  field mappings, custom fields, discovery searches, saved filters, asset and
  identity types, entity zones, ephemeral discovery, vulnerability key mode,
  transparent federated-search mode, inventory retention, and data deletion
  danger-zone review.
- Risk/compliance: known/custom metrics, metric logic, metric split fields,
  metric exceptions, cybersecurity frameworks, risk scoring filters/rules,
  identity risk scoring, and risk processing settings.
- Response/audit: responses, response actions, alerts from metric defects,
  audit reports, operational logs, data export, license usage, operational
  health.
- Investigation: asset, identity, IP, MAC, software, vulnerability, and subnet
  investigation; activity views; anomaly reports; attack surface explorer;
  notes; field reference.
- Lifecycle: upgrade backup, disable processing searches, upgrade, rerun
  post-install configuration, re-enable processing searches, browser cache/bump
  guidance, and uninstall prerequisite to remove ES integration first.

## Enterprise Security Modes

Normal ARI-to-Enterprise-Security integration covers:

- asset and identity sync
- asset/identity swim lanes
- workflow actions
- `ari_lookup_host()`
- `ari_lookup_ip()`
- ES field mapping
- `ari_risk_score`
- ES risk factors

For ES 8.5+ Exposure Analytics, configure only these ARI entity discovery
sources, then turn off normal ARI ES integration:

- Splunk Asset and Risk Intelligence - Asset
- Splunk Asset and Risk Intelligence - IP
- Splunk Asset and Risk Intelligence - Mac
- Splunk Asset and Risk Intelligence - User

Route Exposure Analytics implementation detail through
`splunk-enterprise-security-config`.

## Related Products

ARI Technical Add-ons:

- Windows: Splunkbase `7214`
- Linux: Splunkbase `7416`
- macOS: Splunkbase `7417`

Deploy the matching ARI Technical Add-ons to indexers without local config and
to Universal Forwarders with local `inputs.conf`. Validate data in `ari_ta`
with sourcetypes such as `ari_ta:asset` and `ari_ta:software`; known ARI Add-on
data sources include Asset, Software, and Encryption.

ARI Echo:

- Restricted secondary-search-head product.
- Documented handoff only until the Splunkbase ID/package name is locally
  verified.
- Synchronization surfaces: inventories, asset associations, metrics, and sync
  history.

## Explicit Non-goals

- Do not automate ARI app-specific UI/API configuration until stable
  app-specific REST contracts are proven.
- Do not delete data, remove indexes, uninstall apps, disable integrations, or
  change ES integration state by default.
- Do not put ServiceNow, Echo, or other secret-bearing credentials on command
  lines; keep those workflows file-based or UI-based.
- Do not perform Universal Forwarder rollout from this search-tier skill; emit
  Add-on handoff guidance instead.

## Sources

- https://www.splunk.com/en_us/products/asset-and-risk-intelligence.html
- https://splunkbase.splunk.com/app/7180
- https://splunkbase.splunk.com/app/7214
- https://splunkbase.splunk.com/app/7416
- https://splunkbase.splunk.com/app/7417
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/install-and-set-up-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/introduction-and-system-requirements/system-requirements-and-performance-impact-for-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/introduction-and-system-requirements/splunk-asset-and-risk-intelligence-product-compatibility-matrix
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/create-indexes-for-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/initialize-data-for-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/set-up-roles-and-capabilities-for-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/getting-started-with-administration/splunk-asset-and-risk-intelligence-onboarding-guide-for-admins
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/add-or-modify-a-data-source-in-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/create-and-modify-event-searches-in-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/activate-data-sources-in-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/assign-data-source-priorities-in-splunk-asset-and-risk-intelligence
- https://help.splunk.com/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/manage-data-source-field-mappings/data-source-field-mapping-reference
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/manage-metrics-and-risk/create-and-manage-metrics-in-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/investigate-assets-and-assess-risk-in-splunk-asset-and-risk-intelligence/1.2/assess-risk-using-metrics/assess-risk-using-metrics-in-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/manage-metrics-and-risk/create-and-manage-risk-scoring-rules-in-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/respond-to-discoveries/add-and-manage-responses-in-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/audit-configurations-and-operational-logs/monitor-export-and-share-audit-data-in-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/investigate-assets-and-assess-risk/1.2/discover-and-investigate-assets/investigate-assets-and-identities-in-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/investigate-assets-and-assess-risk/1.2/discover-and-investigate-assets/use-splunk-asset-and-risk-intelligence-data-with-splunk-enterprise-security
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/configure-splunk-asset-and-risk-intelligence-with-splunk-enterprise-security-exposure-analytics/using-splunk-asset-and-risk-intelligence-after-upgrading-to-splunk-enterprise-security-8.5/configure-exposure-analytics-to-use-with-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-add-on-for-asset-and-risk-intelligence/1.2/install-and-configure/install-the-splunk-add-on-for-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-add-on-for-asset-and-risk-intelligence/1.2/manage/known-data-sources-available-for-the-splunk-add-on-for-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-add-on-for-asset-and-risk-intelligence/1.2/manage/data-collected-by-the-splunk-add-on-for-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-asset-and-risk-intelligence-echo/1.2/introduction/get-started-with-splunk-asset-and-risk-intelligence-echo
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-asset-and-risk-intelligence-echo/1.2/install-and-configure/install-splunk-asset-and-risk-intelligence-echo
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/splunk-asset-and-risk-intelligence-echo/1.2/manage/manage-synchronization-between-splunk-asset-and-risk-intelligence-echo-and-the-primary-search-head
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/upgrade-splunk-asset-and-risk-intelligence/upgrade-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/uninstall-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/troubleshooting/troubleshoot-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/api-reference/splunk-rest-api-reference-for-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/release-notes

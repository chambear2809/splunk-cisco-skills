# Splunk Asset and Risk Intelligence Reference

`last_verified: 2026-05-03`

## Splunkbase

- App ID: `7180`
- App name: `SplunkAssetRiskIntelligence`
- Latest researched version: `1.2.1`
- Package pattern: `splunk-asset-and-risk-intelligence_*`
- Access: restricted downloaders only
- Splunk platform compatibility researched: Splunk Enterprise / Cloud Platform
  9.0 through 10.3

## Required Indexes

- `ari_staging`
- `ari_asset`
- `ari_internal`
- `ari_ta`

## ES Exposure Analytics Handoff

For ES 8.5+ deployments with sufficient search-head capacity, configure
Exposure Analytics to use ARI entity discovery sources:

- Splunk Asset and Risk Intelligence - Asset
- Splunk Asset and Risk Intelligence - IP
- Splunk Asset and Risk Intelligence - Mac
- Splunk Asset and Risk Intelligence - User

Do not add other entity discovery sources for this integration.

## Sources

- https://splunkbase.splunk.com/app/7180
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/install-and-set-up-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/create-indexes-for-splunk-asset-and-risk-intelligence
- https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/configure-splunk-asset-and-risk-intelligence-with-splunk-enterprise-security-exposure-analytics/using-splunk-asset-and-risk-intelligence-after-upgrading-to-splunk-enterprise-security-8.5/configure-exposure-analytics-to-use-with-splunk-asset-and-risk-intelligence

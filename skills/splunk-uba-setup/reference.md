# Splunk UBA Setup Reference

last_verified: 2026-05-03

## Product Status

Splunk announced end-of-sale for standalone Splunk User Behavior Analytics on
December 12, 2025. End of life and end of support are January 31, 2027. This
applies to the standalone UBA software product; Splunk directs customers toward
the newer UEBA capability in Splunk Enterprise Security Premier.

## Coverage

| Area | Object | Status | Notes |
|------|--------|--------|-------|
| Standalone UBA server | UBA appliance/software | manual_gap | Professional Services / supported migration handoff only. |
| UEBA in ES Premier | Enterprise Security Premier UEBA | handoff | Route to `splunk-enterprise-security-config` for ES readiness and cloud integrations. |
| UBA Kafka ingestion | `Splunk-UBA-SA-Kafka`, Splunkbase `4147` | optional | Install only when requested and package access exists. |
| ES/UEBA support apps | `SA-UEBA`, `DA-ESS-UEBA`, `Splunk_TA_ueba` | validate | Presence checks for existing deployments. |
| UBA indexes | `ueba`, `ueba_summaries`, `ubaroute`, `ers` | validate | Readiness checks only; no default index creation. |

## Migration Guidance

- Existing standalone UBA customers should plan migration before the published
  end-of-support date.
- New UEBA work should use Enterprise Security Premier UEBA rather than a new
  standalone UBA server deployment.
- Keep any Kafka ingestion app work tightly scoped to existing deployments and
  customer-approved transition plans.

## Sources

- https://help.splunk.com/en/security-offerings/splunk-user-behavior-analytics/release-notes/5.4.5/additional-resources/splunk-announces-end-of-sale-and-end-of-life-for-standalone-splunk-user-behavior-analytics-software
- https://www.splunk.com/en_us/products/enterprise-security.html
- https://help.splunk.com/?resourceId=UBA_Install_Overview

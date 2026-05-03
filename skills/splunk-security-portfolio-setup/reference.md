# Splunk Security Portfolio Coverage

`last_verified: 2026-05-03`

The first-class coverage target is the public Splunk Products security row:
Enterprise Security, Security Essentials, SOAR, User Behavior Analytics,
Attack Analyzer, and Asset and Risk Intelligence.

## Product Coverage

| Product | Status | Local route | Notes |
|---|---|---|---|
| Splunk Enterprise Security | `existing_skill` | `splunk-enterprise-security-install`, `splunk-enterprise-security-config` | ES install and operational config remain the source of truth. |
| Splunk Security Essentials | `first_class` | `splunk-security-essentials-setup` | Search-tier app install plus setup checklist validation. |
| Splunk SOAR | `first_class` | `splunk-soar-setup` | Covers Splunk App for SOAR, SOAR Export, and Automation Broker readiness. Does not install SOAR server. |
| Splunk User Behavior Analytics | `partial` | `splunk-uba-setup` | Standalone UBA is end-of-sale as of December 12, 2025 and end-of-life/end-of-support is January 31, 2027; skill handles readiness, ES/UEBA validation, Kafka ingestion app, and migration guidance. |
| Splunk Attack Analyzer | `first_class` | `splunk-attack-analyzer-setup` | Installs app/add-on, prepares `saa`, configures dashboard macro, and validates handoff state. |
| Splunk Asset and Risk Intelligence | `first_class` | `splunk-asset-risk-intelligence-setup` | Installs restricted app package, prepares ARI indexes, validates role/KV Store readiness, and routes ES Exposure Analytics. |

## Associated Security Offerings

| Offering | Status | Route | Notes |
|---|---|---|---|
| Mission Control | `bundled_es` | `splunk-enterprise-security-config` | ES 8.x component; do not uninstall or split into a product skill. |
| Exposure Analytics | `bundled_es` | `splunk-enterprise-security-config` | ES capability; ARI integration links back to ES config. |
| Detection Studio | `bundled_es` | `splunk-enterprise-security-config` | ES detection lifecycle capability. |
| TIM Cloud | `bundled_es` | `splunk-enterprise-security-config` | ES threat intelligence workflow. |
| Splunk Cloud Connect | `bundled_es` | `splunk-enterprise-security-config` | ES cloud integration readiness. |
| DLX | `bundled_es` | `splunk-enterprise-security-install` | ES packaged support component. |
| Splunk ES Content Update | `install_only` | `splunk-enterprise-security-config` content library | Splunkbase `3449`, app `DA-ESS-ContentUpdate`. |
| Splunk UBA Kafka Ingestion App | `partial` | `splunk-uba-setup` | Splunkbase `4147`, search-head-only, restricted. |
| Splunk App for PCI Compliance | `install_only` | `splunk-app-install` | Splunkbase `1143` or ES installer `2897`; paid/restricted compliance app. |
| InfoSec App for Splunk | `install_only` | `splunk-app-install` | Splunkbase `4240`, starter security dashboards. |
| Splunk Common Information Model | `install_only` | `splunk-app-install` | Splunkbase `1621`; bundled with ES/PCI in many deployments. |
| Splunk App for Lookup File Editing | `install_only` | `splunk-app-install` | Splunkbase `1724`; prerequisite for selected apps. |
| Splunk AI Toolkit / MLTK | `install_only` | `splunk-app-install` | Splunkbase `2890`; not a security portfolio product. |
| Splunk App for Fraud Analytics | `manual_gap` | Manual package/install-only handoff | Official docs reference `Splunk_Fraud_Analytics.tar.gz`; keep as explicit non-product gap. |
| Splunk Automation Broker | `partial` | `splunk-soar-setup` | Container readiness and handoff only. |

## Source Links

- Splunk Products: https://www.splunk.com/en_us/products.html
- Security offerings help index: https://help.splunk.com/en/release-notes-and-updates/about-the-help-portal/splunk-enterprise-security-and-security-offerings
- Security Essentials install/config: https://help.splunk.com/en/splunk-enterprise-security-8/security-essentials/install-and-configure/3.8/install-splunk-security-essentials/install-splunk-security-essentials
- UBA end-of-sale/end-of-life: https://help.splunk.com/en/security-offerings/splunk-user-behavior-analytics/release-notes/5.4.5/additional-resources/splunk-announces-end-of-sale-and-end-of-life-for-standalone-splunk-user-behavior-analytics-software
- Attack Analyzer add-on configuration: https://help.splunk.com/en/security-offerings/splunk-attack-analyzer/splunk-add-on-for-splunk-attack-analyzer/1.2/install-and-configure-the-splunk-add-on-for-splunk-attack-analyzer/configure-the-splunk-add-on-for-splunk-attack-analyzer
- ARI index setup: https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/create-indexes-for-splunk-asset-and-risk-intelligence
- Splunk App for SOAR: https://help.splunk.com/en/splunk-soar/splunk-app-for-soar/install-and-configure

# PCI Compliance Reference

Primary app: Splunk App for PCI Compliance. Splunkbase `1143` is the Splunk
Enterprise installer; Splunkbase `2897` is the Enterprise Security installer.

## Readiness Scope

- Select the installer that matches standalone Splunk Enterprise or Enterprise
  Security.
- Identify cardholder data environment indexes and PCI dashboard/report macros.
- Confirm CIM data models and data sources for authentication, change, endpoint,
  malware, network traffic, intrusion detection, and vulnerability evidence.
- Review PCI roles, reports, scheduled searches, and dashboard population.

## Handoffs

- Package install: `splunk-app-install`
- ES/CIM/data-model readiness: `splunk-enterprise-security-config` and
  `splunk-cim-data-model-setup`
- Lookup and macro governance: `splunk-knowledge-objects-setup`

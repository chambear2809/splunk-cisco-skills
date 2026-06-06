# Fraud Analytics Reference

The Splunk App for Fraud Analytics depends on Enterprise Security and Lookup
File Editing. It is a consumer/content app, not a raw telemetry source pack.

## Prerequisites

- Enterprise Security is installed and healthy.
- Lookup File Editing is installed for fraud lookup maintenance.
- Risk-based alerting indexes and risk modifiers are ready.
- Required fraud data models, transaction data, identity context, and lookup
  content are available.

## Handoffs

- Package install: `splunk-app-install` or local package handoff.
- Lookup maintenance: `splunk-lookup-file-editing-setup`.
- ES/RBA and correlation-search review: `splunk-enterprise-security-config`.
- CIM/data models: `splunk-cim-data-model-setup`.

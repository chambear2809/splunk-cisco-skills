# Splunk VMware TA Setup Reference

This skill consolidates the VMware entries from the Splunk Supported Add-ons
glossary into one operator workflow. The implementation is conservative: it
renders reviewable Splunk-side and collector-side assets, but it does not invent
private VMware add-on REST endpoints or force a package ID where the operator
must choose the approved VMware package set for their Splunk release.

## Covered Surfaces

- VMware app/add-on search-tier package placement.
- vCenter collection account and data collection node ownership.
- ESXi syslog collection handoff through SC4S, syslog-ng, or a managed receiver.
- Event, inventory, task/event, ESXi log, and metrics index planning.
- Metrics index template with `datatype = metric`.
- Dashboard, Monitoring Console, ITSI, and data-source-readiness validation,
  including a starter `vmware-readiness-evidence.template.json`.

## Role Placement

| Role | Placement |
| --- | --- |
| Search tier | VMware app UI, search-time knowledge, dashboards, macros, lookups |
| Indexers | Index definitions and any index-time parsing package required by the selected VMware add-on |
| Heavy forwarder / DCN | vCenter API collection and forwarding |
| Universal forwarder | Only for explicitly supported file/syslog relay scenarios |
| External collector | ESXi syslog receiver such as SC4S or a managed syslog path |

## Index Model

The renderer defaults to:

- `vmware` for vCenter inventory, task, event, and log data.
- `vmware_esxi` for ESXi syslog when a separate log index is desired.
- `vmware_metrics` for metrics data with `datatype = metric`.

Change these to match the organization's retention, RBAC, and ITSI/entity
strategy. Keep macros, dashboards, and readiness searches aligned with the final
names.

## Data Collection Guardrails

- One vCenter collection owner per scope. Duplicate DCNs usually create duplicate
  task, event, inventory, and performance data.
- Use a dedicated least-privilege vCenter account. Store its password in a local
  file and configure it through the add-on account workflow.
- Keep ESXi syslog transport and sourcetype decisions explicit. If SC4S owns
  syslog normalization, render SC4S assets there and use this skill for
  Splunk-side index/readiness planning.
- Validate sample events before enabling ITSI content packs or dashboard
  readiness claims.

## Handoffs

- Package install: `splunk-app-install`.
- ESXi syslog collector: `splunk-connect-for-syslog-setup`.
- Forwarder/DCN rollout: `splunk-agent-management-setup` or a customer change
  process.
- ITSI object modeling: `splunk-itsi-config`.
- Post-ingest scoring: `splunk-data-source-readiness-doctor`.

## Source Anchors

- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/vmware
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons

# Azure Data Manager Reference

Azure Data Manager coverage includes Microsoft Entra ID, Azure Activity Logs,
Azure Event Hubs, Azure Monitor source types that Data Manager lists through
Event Hubs, ARM templates, and migration from the Splunk Add-on for Microsoft
Cloud Services.

## Guardrails

- Azure Function runtime versions 2.x and 3.x are unsupported. Validate runtime
  4.x expectations.
- Install the Splunk Add-on for Microsoft Cloud Services for CIM normalization.
- ARM templates must run in `what-if` mode before apply.
- Azure Event Hubs migration requires MSCS 5.4.0 or higher.
- Before exporting Event Hubs from MSCS, inputs must be inactive and health must
  be Ready.
- Migrating the same Event Hub twice can corrupt data; require a duplicate check.
- Migration does not affect modular inputs in MSCS.

## Artifact Handling

The renderer creates ARM validation/apply wrappers around a user-supplied or
Data Manager-downloaded template path. Secret values must be supplied through
files and not written into rendered command lines.

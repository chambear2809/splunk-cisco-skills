# Splunk_TA_MS_Security Reference

Package source of truth: `splunk-ta/_unpacked/Splunk_TA_MS_Security-3.0.0/Splunk_TA_MS_Security`.

## Inputs

| Input | Source type |
| --- | --- |
| `microsoft_365_defender_endpoint_incidents://<name>` | `ms365:defender:incident` |
| `microsoft_defender_endpoint_atp_alerts://<name>` | `ms:defender:atp:alerts` |
| `microsoft_defender_endpoint_machines://<name>` | `ms:defender:machines` |
| `microsoft_defender_endpoint_simulations://<name>` | `ms:defender:simulations` |
| `microsoft_defender_event_hub://<name>` | `ms:defender:eventhub` |
| `microsoft_defender_threat_intelligence_datasets://<name>` | `ms:defender:ti:articles` plus TI subtype transforms |

The package also ships incident/advanced-hunting sourcetypes such as
`m365:defender:incident:advanced_hunting` and
`ms365:defender:incident:alerts`.

## Package Alert Actions

`defender_advanced_hunting`, `defender_update_incident`,
`defender_update_incident_graph`, and `defender_dismiss_azure_alert`.

## Guardrails

- Configure Entra app client secrets only through the add-on account.
- For Splunk Cloud, use supported UI/REST configuration paths and coordinate
  Event Hub egress or ACS allowlists before enabling streaming.
- Disable duplicate legacy Defender inputs during migration.
- Configure package macros (`defender_index`, `defender_atp_index`) for shipped
  dashboards/searches; no custom dashboards are generated.

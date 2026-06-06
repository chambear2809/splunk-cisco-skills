# Splunk_TA_box Reference

Package source of truth: `splunk-ta/_unpacked/Splunk_TA_box-4.0.0/Splunk_TA_box`.

## Package Identity

| Field | Value |
| --- | --- |
| Splunkbase | `2679` |
| App directory | `Splunk_TA_box` |
| Verified version | `4.0.0` |

## Inputs And Source Types

| Input | Source type family |
| --- | --- |
| `box_service://<name>` | `box:events`, `box:users`, `box:groups`, folders and file metadata |
| `box_live_monitoring_service://<name>` | `box:events` |
| `box_file_ingestion_service://<name>` | `box:filecontent`, `box:filecontent:csv`, `box:filecontent:json`, `box:filecontent:xml` |

Package source types include `box:events`, `box:users`, `box:groups`,
`box:folder`, `box:file`, `box:fileComment`, `box:fileTask`,
`box:folderCollaboration`, and the file content source types above.

## REST Handlers

- `Splunk_TA_box_account`
- `Splunk_TA_box_oauth`
- `Splunk_TA_box_box_service`
- `Splunk_TA_box_box_live_monitoring_service`
- `Splunk_TA_box_box_file_ingestion_service`
- `Splunk_TA_box_settings`

## Guardrails

- Store OAuth client details only through the add-on account flow.
- Run the historical and live inputs on one collector node per Box enterprise.
- Keep Box file ingestion scoped to approved folders and file types before
  enabling broad content collection.

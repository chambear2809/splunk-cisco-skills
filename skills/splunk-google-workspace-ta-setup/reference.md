# Splunk_TA_Google_Workspace Reference

Package source of truth: `splunk-ta/_unpacked/Splunk_TA_Google_Workspace-4.0.0/Splunk_TA_Google_Workspace`.

## Inputs

| Input | Key fields | Source type |
| --- | --- | --- |
| `activity_report://<name>` | `account`, `application`, `lookbackOffset`, `interval`, `index` | `gws:reports:<application>` |
| `gws_gmail_logs://<name>` | `account`, `gcp_project_id`, `dataset_name`, `dataset_location` | `gws:gmail` |
| `gws_gmail_logs_migrated://<name>` | BigQuery dataset fields plus `table_name` | `gws:gmail` |
| `gws_user_identity://<name>` | `account`, `gws_customer_id`, `gws_view_type` | `gws:users:identity` |
| `gws_alert_center://<name>` | `account`, `alert_source` | `gws:alerts` |
| `gws_usage_report://<name>` | `account`, `endpoint`, `start_date` | `gws:usage_reports:<endpoint>` |

Package REST handlers include `splunk_ta_google_workspace_account`, settings,
and all six input handlers.

## Guardrails

- Configure certificate/private-key material only in the add-on account.
- Run each API input on one collection node.
- Gmail log inputs need BigQuery dataset access for the configured service
  account.
- Use package-shipped knowledge objects and documented companion apps only; this
  skill does not invent dashboards.

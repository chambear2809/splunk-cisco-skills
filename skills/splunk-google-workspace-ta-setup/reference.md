# Splunk_TA_Google_Workspace Reference

Package source of truth: `splunk-ta/_unpacked/Splunk_TA_Google_Workspace-4.0.0/Splunk_TA_Google_Workspace`.

## Package Version Boundary

- Repo-verified package: `4.0.0`. Current public release: `5.1.0` as of
  2026-11-16, according to the shared live metadata refresh.
- Both records advertise Splunk `10.5`; the earlier platform gap for public
  5.0.x is not the current default's limitation. Retain `4.0.0` because the
  newer package/configuration contract was not inspected in the Cisco audit.
- No unrelated package pin was advanced by the full-registry metadata refresh.
  Review the exact 5.1.0 package fields, runtime and deployment before adoption.
  This skill has no platform preflight wrapper; do not infer a new package's
  configuration compatibility from its listing declaration.

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

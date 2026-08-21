# Splunk_TA_Google_Workspace Reference

Package source of truth: `splunk-ta/_unpacked/Splunk_TA_Google_Workspace-4.0.0/Splunk_TA_Google_Workspace`.

## Package Version Boundary

- Repo-verified package: `4.0.0`. Current public release: `5.0.0`.
- The `4.0.0` release record lists Splunk `10.5`; `5.0.0` lists versions only
  through `10.4`. The pin therefore stays on `4.0.0` so the default install path
  keeps working on a `10.5` stack.
- Install `5.0.0` only on a stack at `10.4` or below, and only with documented
  vendor approval for that exact version. This skill has no platform preflight
  wrapper, so nothing refuses a mismatched package for you.

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

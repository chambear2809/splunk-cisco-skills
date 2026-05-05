# Cisco Webex Package Reference

Sources: Webex Add-on for Splunk `1.4.0` and Webex App for Splunk `2.0.0`
package inspection, plus the upstream README.

## Apps

| Splunkbase ID | App | Purpose | Workloads |
|---|---|---|---|
| `8365` | `ta_cisco_webex_add_on_for_splunk` | Webex REST API collection | `_search_heads` |
| `4992` | `cisco_webex_meetings_app_for_splunk` | Dashboards/searches/macros | `_search_heads` |

## Dashboard Macros

| Macro | Default |
|---|---|
| `webex_meeting` | `index=wx` |
| `webex_calling` | `index=wxc` |
| `webex_contact_center` | `index=wxcc` |
| `webex_indexes` | `` `webex_meeting` OR `webex_calling` OR `webex_contact_center` `` |

## Inputs And Sourcetypes

| Input type | Sourcetype |
|---|---|
| `webex_meetings` | `cisco:webex:meetings` |
| `webex_meetings_summary_report` | `cisco:webex:meeting:usage:reports`, `cisco:webex:meeting:attendee:reports` |
| `webex_admin_audit_events` | `cisco:webex:admin:audit:events` |
| `webex_security_audit_events` | `cisco:webex:security:audit:events` |
| `webex_meeting_qualities` | `cisco:webex:meeting:qualities` |
| `webex_detailed_call_history` | `cisco:webex:call:detailed_history` |
| `webex_generic_endpoint` | `cisco:webex:<endpoint path with / replaced by :>`; requires `webex_endpoint` and `webex_base_url` |
| `webex_contact_center_search` | `cisco:webex:contact:center:AAR`, `cisco:webex:contact:center:ASR`, `cisco:webex:contact:center:CAR`, `cisco:webex:contact:center:CSR` |

## Scopes

| Data set | Required scopes |
|---|---|
| Scheduled meetings | `meeting:admin_schedule_read spark-admin:people_read` |
| Meeting usage/attendee reports | `meeting:admin_schedule_read meeting:admin_participants_read meeting:admin_config_read` |
| Admin/security audit events | `audit:events_read spark:organizations_read` |
| Meeting qualities | `analytics:read_all` |
| Detailed call history | `spark-admin:calling_cdr_read` |
| Generic endpoint | Endpoint-specific Webex API scopes |

## Guardrails

- Timestamps must be UTC in `YYYY-MM-DDTHH:MM:SSZ` format.
- Meeting summary, admin audit, security audit, meeting quality, detailed call
  history, and Contact Center Search inputs require `start_time`.
- Meeting summary report inputs require `site_url`.
- Meeting summary report data is historical, can lag about 24 hours, has a
  30-day max window, and should not start earlier than 90 days.
- Meeting quality data should not start earlier than 7 days.
- Detailed call history start/end windows are constrained to recent data
  (roughly 5 minutes to 48 hours depending on endpoint behavior).
- Contact Center Search uses query templates `AAR`, `ASR`, `CAR`, and `CSR`
  against `https://<region>.webexapis.com/v1/contactCenter/search`.

# Splunk_TA_salesforce Reference

Package source of truth: `splunk-ta/_unpacked/Splunk_TA_salesforce-6.0.2/Splunk_TA_salesforce`.

## Package Identity

| Field | Value |
| --- | --- |
| Splunkbase | `3549` |
| App directory | `Splunk_TA_salesforce` |
| Verified version | `6.0.2` |

## Inputs And Source Types

| Input | Source type |
| --- | --- |
| `sfdc_object://<object>` | `sfdc:object` plus object-specific `sfdc:<object>` knowledge |
| `sfdc_event_log://<name>` | `sfdc:logfile` |

Package props and lookups cover `sfdc:user`, `sfdc:loginhistory`,
`sfdc:account`, `sfdc:opportunity`, `sfdc:dashboard`, `sfdc:report`,
`sfdc:contentversion`, and add-on log source types.

## REST Handlers

- `Splunk_TA_salesforce_account`
- `Splunk_TA_salesforce_oauth`
- `Splunk_TA_salesforce_sfdc_object`
- `Splunk_TA_salesforce_sfdc_event_log`
- `Splunk_TA_salesforce_settings`

## Guardrails

- Store connected-app credentials only through the add-on account setup flow;
  do not put credentials in rendered files or command-line arguments.
- Run a given Salesforce org collection path on one search head or heavy
  forwarder to avoid checkpoint contention.
- Keep generic HEC or JSON data out of the Salesforce readiness pack unless it
  has package-backed `sfdc:*` source types.

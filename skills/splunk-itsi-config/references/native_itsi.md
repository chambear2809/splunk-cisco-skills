# Native ITSI Workflow

The native workflow manages live ITSI objects through the ITSI REST API:

- `entity`
- `service`
- `notable_event_aggregation_policy`

## Supported Native Spec Shape

```yaml
connection:
  base_url: https://splunk.example.com:8089
  username_env: SPLUNK_USERNAME
  password_env: SPLUNK_PASSWORD
  session_key_env: SPLUNK_SESSION_KEY
  verify_ssl: false

defaults:
  sec_grp: default_itsi_security_group

entities:
  - title: edge-sw-01
    description: Example entity
    identifier_fields:
      - field: host
        value: edge-sw-01
      - field: ip
        value: 10.20.30.40
    informational_fields:
      - field: location
        value: dc-1

services:
  - title: Network Edge
    description: Example service
    enabled: false
    entity_rules:
      - field: host
        field_type: alias
        value: edge-sw-*
    kpis:
      - title: Interface Errors
        search: index=network sourcetype=interface_errors | stats sum(errors) as errors by host
        threshold_field: errors
        aggregate_statop: sum
        entity_statop: sum
        entity_id_fields: host
        entity_breakdown_id_field: host
        thresholds:
          aggregate:
            baseSeverityLabel: normal
            baseSeverityValue: 2
            metricField: errors
            thresholdLevels:
              - severityLabel: high
                severityValue: 5
                thresholdValue: 10
              - severityLabel: critical
                severityValue: 6
                thresholdValue: 20
    depends_on:
      - service: WAN Core
        kpis:
          - Availability

neaps:
  - title: Example NEAP
    description: Example custom NEAP
    payload:
      rule_type: custom
```

## Notes

- The workflow intentionally preserves unmanaged fields and extra live KPIs instead of pruning them.
- Service dependencies are merged in a second pass because dependency services must exist before they can be referenced.
- Custom NEAP support is raw-payload oriented in v1. Supply the live policy fields under `payload`.
- The validator compares only the fields this skill manages.


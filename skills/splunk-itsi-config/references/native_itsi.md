# Native ITSI Workflow

The native workflow manages live ITSI objects through the ITSI REST API:

- `team`
- `entity`
- `entity_type`
- `service`
- `base_service_template`
- `kpi_base_search`
- `kpi_template`
- `kpi_threshold_template`
- `custom_threshold_windows`
- custom threshold window service/KPI links
- custom content packs through the content pack authorship API
- `notable_event_aggregation_policy`
- `event_management_state`
- `correlation_search`
- `notable_event_email_template`
- `maintenance_calendar`
- backup/restore jobs through the backup/restore interface
- `deep_dive`
- `glass_table`
- glass table icons through the icon collection API
- `home_view`
- `kpi_entity_threshold`

The core `entity`, `service`, service `kpis`, and `neaps` sections keep their typed convenience fields and also merge additional top-level ITSI schema fields plus `payload` into the REST body. The extended ITSI object sections are typed passthrough upserts: the skill sets `title`, `description`, `sec_grp`, and `object_type`, then merges any additional top-level keys and `payload` into the REST body. Use `payload` for exact exported ITSI schema fields when Splunk changes object shapes between ITSI versions.

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

teams:
  - title: Network Operations
    payload:
      roles:
        read: [itoa_admin]
        write: [itoa_admin]

entity_types:
  - title: Network Device
    data_drilldowns:
      - title: Network events
        type: events

kpi_base_searches:
  - title: Interface Error Base Search
    search: index=network sourcetype=interface_errors | stats sum(errors) as errors by host

kpi_threshold_templates:
  - title: Interface Error Threshold Template
    payload:
      thresholdLevels:
        - severityLabel: critical
          severityValue: 6
          thresholdValue: 20

custom_threshold_windows:
  - title: Business Hours
    payload:
      recurrence: true
      duration: 8
      window_type: percentage
      window_config_percentage: 10

service_templates:
  - title: Network Device Template
    kpis:
      - title: Interface Errors
        kpi_base_search_id: replace-with-live-base-search-key
        threshold_field: errors
        importance: 7

custom_content_packs:
  - title: Network Operations Pack
    payload:
      cp_version: 1.0.0
      author: Platform Engineering

entities:
  - title: edge-sw-01
    description: Example entity
    entity_type_titles:
      - Network Device
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
    service_template: Network Device Template
    service_tags:
      tags: [network, edge]
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
        alert_period: 5
        alert_lag: 30
        importance: 9
        adaptive_thresholds_is_enabled: false
        gap_severity: critical
        adaptive_thresholding:
          enabled: false
        anomaly_detection:
          enabled: false
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

custom_threshold_window_links:
  - window: Business Hours
    services:
      - service: Network Edge
        kpis:
          - Interface Errors

neaps:
  - title: Example NEAP
    description: Example custom NEAP
    payload:
      rule_type: custom

event_management_states:
  - title: Example Episode Review View
    description: Replace payload fields with an exported Episode Review custom view.
    payload:
      viewingOption: standard

correlation_searches:
  - title: Example Third-Party Alert Normalization
    search: index=alerts sourcetype=third_party_alerts | eval severity=6
    payload:
      enabled: false

maintenance_windows:
  - title: Example Network Maintenance
    payload:
      start_time: 1735689600
      end_time: 1735693200

backup_restore_jobs:
  - title: Example ITSI Backup
    payload:
      job_type: Backup
      include_lookup_files: true

glass_tables:
  - title: Network Operations Overview
    payload:
      layout:
        type: absolute

glass_table_icons:
  - title: Network Router
    svg_path: M0 0h24v24H0z
    width: 24
    height: 24
    category: Network

# Optional, non-idempotent helper actions. These are blocked unless each action
# explicitly sets allow_operational_action: true.
operational_actions:
  - action: custom_threshold_window_disconnect
    allow_operational_action: true
    disconnect_all: true
    window: Business Hours
  - action: kpi_threshold_recommendation
    allow_operational_action: true
    payload:
      itsi_service_id: replace-with-live-service-key
      itsi_kpi_id: replace-with-live-kpi-key
  - action: entity_retire
    allow_operational_action: true
    entity_keys:
      - replace-with-live-entity-key
  - action: entity_retire_retirable
    allow_operational_action: true
    retire_all_retirable: true
```

## Notes

- The workflow intentionally preserves unmanaged fields and extra live KPIs instead of pruning them.
- Core `entities`, `services`, and service `kpis` accept documented ITSI schema fields at the top level. Use `payload` for fields that need exact exported object shape or would conflict with local DSL keys.
- Service dependencies are merged in a second pass because dependency services must exist before they can be referenced.
- Keyed updates on the generic ITSI, Event Management, maintenance, and backup/restore route families set `is_partial_data=1` so unmanaged fields are preserved. Full-payload special routes such as `kpi_entity_threshold`, icon collection, and content-pack authorship do not use that parameter.
- Services can declare `service_template` (or `from_template`) by title or key. The workflow links through the ITSI `service/<_key>/base_service_template` endpoint and refreshes the service before dependency validation.
- `custom_threshold_window_links` links services and KPIs to a custom threshold window after services exist. Use `window` / `service` / `kpis` for title-based references, or `window_key` / `service_key` / `kpi_ids` when you already have live ITSI IDs. Links are additive; unmanaged existing links are preserved.
- Custom threshold window stop and disconnect actions are operational/destructive transitions, so they are intentionally outside the additive upsert model.
- Entities can declare `entity_type_titles`; these resolve against live `entity_type` objects or entity types created earlier in the same spec.
- Custom NEAP support accepts top-level policy fields and `payload`; both are merged into the live aggregation-policy body through the ITSI event management interface. Managed, packaged, and default NEAPs are protected from overwrite.
- Extended sections are additive/idempotent and do not delete unmanaged objects.
- `custom_content_packs` use the ITSI content pack authorship route. This is separate from the `packs` installation workflow in `references/content_packs.md`.
- `event_management_states`, `correlation_searches`, `notable_event_email_templates`, and `neaps` use the ITSI `event_management_interface`; lookups use that route's `filter_data` request parameter rather than the core ITSI `filter` parameter. Event Management creates are wrapped in the documented `data` envelope; keyed updates send the object payload directly.
- `correlation_searches` can use `title` in the YAML spec for readability; the workflow writes it as the ITSI `name` field because the correlation-search schema uses `name` as the stable object name.
- `deep_dives` are normalized from the existing live object before update so required owner fields remain in the update payload.
- `glass_table_icons` use the ITSI icon collection API, which upserts icons in bulk. The native workflow handles that special route behind the same preview/apply/validate behavior.
- `backup_restore_jobs` are exposed for backup automation. Restore payloads can be destructive in a live ITSI environment and are rejected unless the spec sets `allow_restore: true`; that local guard is not sent to ITSI.
- `operational_actions` are explicit non-idempotent helper transitions. Supported actions are `entity_retire`, `entity_restore`, `entity_retire_retirable`, `custom_threshold_window_disconnect`, `custom_threshold_window_stop`, `kpi_threshold_recommendation`, `kpi_entity_threshold_recommendation`, and `shift_time_offset`. Each action is blocked unless it sets `allow_operational_action: true`; `custom_threshold_window_disconnect` also requires `disconnect_all: true` because the documented endpoint disconnects all KPIs from the selected window. `entity_retire_retirable` also requires `retire_all_retirable: true` because the documented endpoint retires every entity currently marked retirable.
- `entity_retire` and `entity_restore` accept `entity_keys` as a convenience shorthand for the documented `payload.data` list.
- Operational Event Analytics records and APIs such as notable events, notable event groups, notable event comments, ticket actions, and action execution are intentionally not modeled as idempotent upsert sections.
- Unused object types and helper APIs such as entity discovery searches, `entity_filter_rule`, `entity_relationship`, `entity_relationship_rule`, content-pack submit/download, and destructive deletes are not modeled because they do not have a safe additive preview/apply/validate shape.
- The validator compares only the fields this skill manages.

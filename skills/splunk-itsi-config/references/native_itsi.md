# Native ITSI Workflow

The native workflow manages live ITSI objects through the ITSI REST API:

- `team`
- `entity`
- `entity_type`
- `entity_management_policies`
- `entity_management_rules`
- `data_integration_template`
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
- `refresh_queue_job`
- `sandbox`
- `sandbox_service`
- `sandbox_sync_log`
- `upgrade_readiness_prechecks`
- `summarization`
- `summarization_feedback`
- `user_preference`

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

inventory:
  maintenance_object_keys:
    - replace-with-live-service-or-entity-key
  notable_event_group_filter:
    status: 5

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

entity_management_policies:
  - title: Example Entity Discovery Policy
    enabled: false

entity_management_rules:
  - title: Example Entity Discovery Rule
    field: host

data_integration_templates:
  - title: Example Data Integration Template
    payload:
      source: third_party

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

refresh_queue_jobs:
  - title: Example Refresh Queue Job
    payload:
      status: queued

sandboxes:
  - title: Example Imported Services Sandbox
    payload:
      description: Review imported service tree before publish.

sandbox_services:
  - title: Example Sandbox Service
    payload:
      service_title: Network Edge

sandbox_sync_logs:
  - title: Example Sandbox Sync Log
    payload:
      status: complete

upgrade_readiness_prechecks:
  - title: Example Upgrade Readiness Precheck
    payload:
      status: ready

summarizations:
  - title: Example KPI Summary
    payload:
      window: 15m

summarization_feedback:
  - title: Example KPI Summary Feedback
    payload:
      rating: useful

user_preferences:
  - title: Example ITSI User Preferences
    payload:
      landing_page: service_analyzer

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
  - action: notable_event_action_execute
    allow_operational_action: true
    allow_notable_event_action_execute: true
    action_name: send_email
    group_ids:
      - replace-with-live-episode-key
    params:
      message: Review this episode.
  - action: ticket_link
    allow_operational_action: true
    group_key: replace-with-live-episode-key
    ticket_system: jira
    ticket_id: NET-123
    ticket_url: https://jira.example/browse/NET-123
```

## Notes

- The workflow intentionally preserves unmanaged fields and extra live KPIs instead of pruning them.
- Brownfield read-only modes are available via `setup.sh --workflow native --mode export|inventory|prune-plan`. Use `export --output exported.native.yaml --output-format yaml` to generate a native YAML skeleton from live ITSI, `inventory` for object/app/KV Store counts plus supported-object/alias/notable-action discovery, and `prune-plan` to list unmanaged live objects without deleting them. Export and prune-plan skip optional ITSI route families that are not exposed by the live host and report warning diagnostics/unavailable sections instead of aborting the whole run.
- `inventory.maintenance_object_keys` adds read-only active/window-count checks for specific live service or entity keys. `inventory.notable_event_group_filter` is passed to the Event Management count endpoint when the host exposes it.
- Guarded cleanup is available via `setup.sh --workflow native --mode cleanup-apply --backup-output cleanup-backup.native.yaml`. A cleanup spec must copy the current `prune-plan` `plan_id` and selected `candidate_ids`, set `cleanup.allow_destroy: true`, set `cleanup.confirm: DELETE_UNMANAGED_ITSI_OBJECTS`, and set a positive `cleanup.max_deletes`. The CLI writes the backup export before any delete call.
- High-risk cleanup candidates for `custom_content_packs`, `glass_table_icons`, and `kpi_entity_thresholds` are manual-review by default. To make them delete-eligible, rerun `prune-plan` with `cleanup.allow_high_risk_deletes: true` and `cleanup.confirm_high_risk: DELETE_HIGH_RISK_ITSI_OBJECTS`; `cleanup-apply` also requires every selected high-risk `candidate_id` to appear in `cleanup.high_risk_candidate_ids`.
- Cleanup defaults are conservative. Keyless objects, unsupported route families, and known default/shipped ITSI or content-pack objects are marked manual-review only. Set `cleanup.allow_system_objects: true` only when you intentionally want those protected candidates to become delete-eligible after reviewing the current prune plan.
- `python3 scripts/native_offline_smoke.py --spec-json <path>` exercises native preview/apply/validate/export/inventory/prune-plan plus an in-memory cleanup delete and never connects to Splunk.
- Validation diagnostics include field-level diffs for managed drift where the live object exists.
- Preview/apply/validate emit warning diagnostics for obvious KPI/correlation-search preflight issues, such as searches without explicit index constraints or threshold fields not visible in the SPL text.
- Core `entities`, `services`, and service `kpis` accept documented ITSI schema fields at the top level. Use `payload` for fields that need exact exported object shape or would conflict with local DSL keys.
- Service dependencies are merged in a second pass because dependency services must exist before they can be referenced.
- Keyed updates on the generic ITSI, Event Management, maintenance, and backup/restore route families set `is_partial_data=1` so unmanaged fields are preserved. Full-payload special routes such as `kpi_entity_threshold`, icon collection, and content-pack authorship do not use that parameter.
- Services can declare `service_template` (or `from_template`) by title or key. The workflow links through the ITSI `service/<_key>/base_service_template` endpoint and refreshes the service before dependency validation.
- `custom_threshold_window_links` links services and KPIs to a custom threshold window after services exist. Use `window` / `service` / `kpis` for title-based references, or `window_key` / `service_key` / `kpi_ids` when you already have live ITSI IDs. Links are additive; unmanaged existing links are preserved.
- Custom threshold window stop and disconnect actions are operational/destructive transitions, so they are intentionally outside the additive upsert model.
- Entities can declare `entity_type_titles`; these resolve against live `entity_type` objects or entity types created earlier in the same spec.
- Custom NEAP support accepts top-level policy fields and `payload`; both are merged into the live aggregation-policy body through the ITSI event management interface. Managed, packaged, and default NEAPs are protected from overwrite.
- Extended sections are additive/idempotent and do not delete unmanaged objects. They include entity-management policies/rules, data-integration templates, refresh queue jobs, sandboxes, sandbox services/sync logs, upgrade-readiness prechecks, summarizations/feedback, and user preferences as schema passthrough sections.
- `custom_content_packs` use the ITSI content pack authorship route. This is separate from the `packs` installation workflow in `references/content_packs.md`.
- `event_management_states` use the core ITSI object route on tested ITSI 4.21.2 hosts. `correlation_searches`, `notable_event_email_templates`, and `neaps` use the ITSI `event_management_interface`; lookups use that route's `filter_data` request parameter rather than the core ITSI `filter` parameter. Event Management interface creates are wrapped in the documented `data` envelope; keyed updates send the object payload directly.
- `correlation_searches` can use `title` in the YAML spec for readability; the workflow writes it as the ITSI `name` field because the correlation-search schema uses `name` as the stable object name.
- `deep_dives` are normalized from the existing live object before update so required owner fields remain in the update payload.
- `glass_table_icons` use the ITSI icon collection API, which upserts icons in bulk. The native workflow handles that special route behind the same preview/apply/validate behavior.
- `backup_restore_jobs` are exposed for backup automation. Restore payloads can be destructive in a live ITSI environment and are rejected unless the spec sets `allow_restore: true`; that local guard is not sent to ITSI.
- `operational_actions` are explicit non-idempotent helper transitions. Supported actions are `entity_retire`, `entity_restore`, `entity_retire_retirable`, `custom_threshold_window_disconnect`, `custom_threshold_window_stop`, `kpi_threshold_recommendation`, `kpi_entity_threshold_recommendation`, `shift_time_offset`, `notable_event_group_update`, `notable_event_action_execute`, `ticket_link`, `ticket_unlink`, and `episode_export_create`. Each action is blocked unless it sets `allow_operational_action: true`; higher-risk actions require a second explicit guard such as `disconnect_all`, `retire_all_retirable`, `allow_episode_field_change`, `allow_notable_event_action_execute`, or `allow_ticket_unlink`.
- `entity_retire` and `entity_restore` accept `entity_keys` as a convenience shorthand for the documented `payload.data` list.
- Operational Event Analytics records and APIs such as notable events, notable event groups, notable event comments, ticket actions, and action execution are intentionally not modeled as idempotent upsert sections.
- Unused object types and helper APIs such as entity discovery searches, `entity_filter_rule`, `entity_relationship`, `entity_relationship_rule`, and content-pack submit/download are not modeled because they do not have a safe additive preview/apply/validate shape.
- Cleanup deletes are intentionally narrower than the prune plan. Content-pack authorship objects, glass-table icons, and KPI entity thresholds can be deleted only with the separate high-risk guard fields described above.
- The validator compares only the fields this skill manages, but reports path-level diffs for those managed fields when possible.

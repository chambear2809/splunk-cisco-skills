# Native ITSI Workflow

The native workflow configures an existing ITSI deployment. It does not install,
upgrade, license, or restart ITSI and it does not install prerequisite apps.
Run repo-root lint first, then GET-only preview/inventory, explicit `--apply`,
and completion validation as described in `../SKILL.md`.

The following list is a route inventory, not a claim that every object has a
typed and live-certified local schema. See `product_coverage.md`: core entities,
services, embedded KPIs, dependencies, and selected links are typed; many
extended objects below are experimental same-version passthroughs; operational
helpers are guarded.

The route inventory includes:

- `team`
- `entity`
- `entity_type`
- `entity_filter_rule`
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
- `summarization_rule` (ITSI 5.0)
- `user_preference`

The core `entity`, `service`, service `kpis`, and custom `neaps` sections keep
typed convenience fields and can merge reviewed ITSI schema fields from
`payload`. Extended object sections are **experimental passthroughs**: the skill
can select a route and merge fields, but it does not prove the complete schema,
mutability, permissions, or lifecycle semantics. Use only payloads exported
from the same ITSI version, lint them, and require a clean live preview. Do not
describe a passthrough as full product-feature support.

## Supported Native Spec Shape

The following block is a field catalog for advanced review. It is not a starter
spec and must not be applied as written: it contains placeholder identifiers,
experimental passthrough objects, and enabled examples of non-idempotent helper
actions. Build a minimal `template.local` containing only the requested object
families.

```yaml
schema_version: 1
metadata:
  template: true

connection:
  base_url: https://splunk.example.com:8089
  username_env: SPLUNK_USERNAME
  password_env: SPLUNK_PASSWORD
  session_key_env: SPLUNK_SESSION_KEY
  verify_ssl: true

defaults:
  sec_grp: default_itsi_security_group

inventory:
  maintenance_object_keys:
    - replace-with-live-service-or-entity-key
  entity_discovery_entity_keys:
    - replace-with-live-entity-key
  notable_event_group_filter:
    status: 5
  notable_event_action_names:
    - send_email

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

entity_filter_rules:
  - title: Network Device Entity Filter
    payload:
      description: Replace payload fields with an exported entity filter rule.

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

summarization_rules:
  - title: Example Event iQ Diagnose Rule
    description: ITSI 5.0 only; replace with a target-version exported rule.
    payload:
      enabled: false

# `summarizations` and `summarization_feedback` are operational records, not
# declarative configuration. Apply rejects them. Use read-only inventory or a
# separately reviewed operational workflow instead.

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
  - action: notable_event_comment
    allow_operational_action: true
    group_key: replace-with-live-episode-key
    comment: Reviewed by the platform team.
  - action: ticket_link
    allow_operational_action: true
    group_key: replace-with-live-episode-key
    ticket_system: jira
    ticket_id: NET-123
    ticket_url: https://jira.example/browse/NET-123
  - action: ticket_read
    allow_operational_action: true
    group_key: replace-with-live-episode-key
  - action: episode_export_get
    allow_operational_action: true
    export_key: replace-with-live-export-key
  - action: episode_export_download
    allow_operational_action: true
    filename: replace-with-export.csv
    output_path: /tmp/itsi-episode-export.csv
  - action: episode_export_delete
    allow_operational_action: true
    allow_episode_export_delete: true
    export_key: replace-with-live-export-key
  - action: templatize_object
    allow_operational_action: true
    object_type: service
    key: replace-with-live-service-key
    output_path: /tmp/itsi-service-template.json
  - action: bulk_update
    allow_operational_action: true
    allow_bulk_update: true
    object_type: entity
    payloads:
      - _key: replace-with-live-entity-key
        title: Example Entity
  - action: custom_content_pack_submit
    allow_operational_action: true
    content_pack_key: replace-with-live-custom-content-pack-key
  - action: custom_content_pack_download
    allow_operational_action: true
    content_pack_key: replace-with-live-custom-content-pack-key
    output_path: /tmp/custom-content-pack.tar.gz
```

The single block above is a field catalog, **not a copy-and-apply starter**. It
contains placeholder IDs and non-idempotent actions. Start from
`templates/beginner.topology.yaml` or a small same-version export copied to
`skills/splunk-itsi-config/template.local`. Lint refuses unresolved starter
placeholders and unsafe reusable action intent before a live run.

## Notes

- The workflow intentionally preserves unmanaged fields and extra live KPIs instead of pruning them.
- Brownfield read-only modes are available via
  `bash skills/splunk-itsi-config/scripts/setup.sh --workflow native --spec <path> --mode export|inventory|prune-plan`.
  Use export with `--output exported.native.yaml --output-format yaml` to
  generate a review skeleton, inventory for object/app/KV Store counts and
  supported discovery, and prune-plan to list unmanaged objects without
  deleting them. These modes are GET-only. Export skips managed/default NEAPs
  by default; set `export.include_managed_neaps: true` only for an explicit
  audit need. Unavailable optional route families are warnings and remain
  unverified, not silently “supported.”
- `inventory.use_count_endpoints: true` records documented REST count-endpoint totals alongside listed objects, and `inventory.count_only: true` uses those count endpoints without collecting titles for large estates. Normal inventory/prune scans request only lightweight identity/source fields where the route supports field projections. `inventory.maintenance_object_keys` adds read-only active/window-count checks for specific live service or entity keys. `inventory.entity_discovery_entity_keys` reads the documented entity-discovery-searches route for specific live entities. `inventory.notable_event_group_filter` and `inventory.notable_event_filter` are passed to Event Management count/read endpoints when the host exposes them; set `inventory.list_notable_events: true`, `inventory.notable_event_limit`, and `inventory.notable_event_fields` for bounded notable-event readback. `inventory.notable_event_action_names`, `inventory.ticket_episode_keys`, `inventory.episode_export_filter`, `inventory.episode_export_keys`, and `inventory.templatize_objects` add read-only action-detail, ticket, export, and template-generation coverage. Inventory also reports the `entity/count_retirable` target list/count when the live host exposes it.
- `bulk_apply.enabled: true` is an opt-in native apply mode for large estates. It batches eligible existing keyed updates through `itoa_interface/<object_type>/bulk_update` while preserving per-object preview and change records. Use `bulk_apply.sections` to restrict the batch to known-safe sections; creates, special route families, dependency merges, high-risk cleanup, and explicit operational actions keep their separate guarded paths.
- Guarded cleanup is available via
  `bash skills/splunk-itsi-config/scripts/setup.sh --workflow native --spec <path> --mode cleanup-apply --backup-output cleanup-backup.native.yaml`.
  A cleanup spec must copy the current prune-plan `plan_id` and selected
  `candidate_ids`, set `cleanup.allow_destroy: true`, set
  `cleanup.confirm: DELETE_UNMANAGED_ITSI_OBJECTS`, and set a positive
  `cleanup.max_deletes`. The local backup export is evidence, not a guarantee of
  full ITSI restore capability.
- High-risk cleanup candidates for `custom_content_packs`, `glass_table_icons`, and `kpi_entity_thresholds` are manual-review by default. To make them delete-eligible, rerun `prune-plan` with `cleanup.allow_high_risk_deletes: true` and `cleanup.confirm_high_risk: DELETE_HIGH_RISK_ITSI_OBJECTS`; `cleanup-apply` also requires every selected high-risk `candidate_id` to appear in `cleanup.high_risk_candidate_ids`.
- Cleanup defaults are conservative. Keyless objects, unsupported route families, and known default/shipped ITSI or content-pack objects are marked manual-review only. Set `cleanup.allow_system_objects: true` only when you intentionally want those protected candidates to become delete-eligible after reviewing the current prune plan.
- `python3 skills/splunk-itsi-config/scripts/native_offline_smoke.py --spec-json <path>`
  exercises native preview/apply/validate/export/inventory/prune-plan plus an
  in-memory cleanup delete and never connects to Splunk. Prefer the supported
  repo-root `setup.sh ... --mode lint` gate for a YAML intake spec.
- Validation diagnostics include field-level diffs for managed drift where the live object exists.
- Preview/apply/validate emit warning diagnostics for obvious KPI/correlation-search preflight issues, such as searches without explicit index constraints or threshold fields not visible in the SPL text.
- Core `entities`, `services`, and service `kpis` accept documented ITSI schema fields at the top level. Use `payload` for fields that need exact exported object shape or would conflict with local DSL keys.
- Service dependencies are merged in a second pass because dependency services must exist before they can be referenced.
- Keyed updates on the generic ITSI, Event Management, maintenance, and backup/restore route families set `is_partial_data=1` so unmanaged fields are preserved. Full-payload special routes such as `kpi_entity_threshold`, icon collection, and content-pack authorship do not use that parameter.
- Services can declare `service_template` (or `from_template`) by title or key. The workflow links through the ITSI `service/<_key>/base_service_template` endpoint and refreshes the service before dependency validation. That REST endpoint has append-only entity-rule behavior, so preview/apply call this out and operators should use the ITSI UI when they need replace or keep-existing entity-rule choices.
- `custom_threshold_window_links` links services and KPIs to a custom threshold window after services exist. Use `window` / `service` / `kpis` for title-based references, or `window_key` / `service_key` / `kpi_ids` when you already have live ITSI IDs. Links are additive; unmanaged existing links are preserved.
- Custom threshold window stop and disconnect actions are operational/destructive transitions, so they are intentionally outside the additive upsert model.
- Entities can declare `entity_type_titles`; these resolve against live `entity_type` objects or entity types created earlier in the same spec.
- Custom NEAP support accepts top-level policy fields and `payload`; both are merged into the live aggregation-policy body through the ITSI event management interface. Managed, packaged, and default NEAPs are protected from overwrite.
- Extended sections are experimental passthroughs and do not imply safe,
  complete, or idempotent feature management. They include entity-management
  policies/rules, data-integration templates, refresh queue jobs, sandboxes,
  sandbox services/sync logs, upgrade-readiness prechecks, ITSI 5.0
  `summarization_rules`, and user preferences. Require same-version export
  evidence and live preview for each use. `summarizations` and
  `summarization_feedback` represent operational Event iQ request/result and
  per-user feedback records; apply rejects those sections rather than treating
  them as titled desired-state objects.
- `custom_content_packs` use the ITSI content pack authorship route. Submit and download are explicit guarded operational actions because they are lifecycle transitions, not idempotent upserts. This is separate from the `packs` import workflow in `references/content_packs.md`.
- `event_management_states` use the core ITSI object route on tested ITSI 4.21.2 hosts. `correlation_searches`, `notable_event_email_templates`, and `neaps` use the ITSI `event_management_interface`; lookups use that route's `filter_data` request parameter rather than the core ITSI `filter` parameter. Event Management interface creates are wrapped in the documented `data` envelope; keyed updates send the object payload directly.
- `correlation_searches` can use `title` in the YAML spec for readability; the workflow writes it as the ITSI `name` field because the correlation-search schema uses `name` as the stable object name.
- `deep_dives` are normalized from the existing live object before update so required owner fields remain in the update payload.
- `glass_table_icons` use the ITSI icon collection API, which upserts icons in bulk. The native workflow handles that special route behind the same preview/apply/validate behavior.
- `backup_restore_jobs` is an experimental payload path, not a recovery
  guarantee. Restore can replace matching objects and is rejected unless the
  spec sets `allow_restore: true`; that flag is only a local guard. Also verify
  product backup dependencies, permissions, service-template sync state, and a
  tested rollback plan. Prefer the supported ITSI backup/restore workflow for
  production recovery.
- `operational_actions` are explicit non-idempotent helper transitions, not
  declarative desired state. Supported local helpers include `entity_retire`,
  `entity_restore`, `entity_retire_retirable`, custom-threshold stop/disconnect,
  threshold recommendations, time shifting, selected episode/comment/action and
  ticket operations, episode exports, templatize, bulk update, and custom pack
  submit/download. Each action needs `allow_operational_action: true`; higher-
  risk actions need their documented second guard. Keep actions in a one-run
  intake, preview the exact targets, remove the authorization after execution,
  and never assume rerunning apply is safe.
- `entity_retire` and `entity_restore` accept `entity_keys` as a convenience shorthand for the documented `payload.data` list.
- Operational Event Analytics records and APIs such as notable events, notable event groups, notable event comments, ticket actions, and action execution are intentionally not modeled as idempotent upsert sections; use guarded `operational_actions` for explicit appends or transitions. Notable-event records are covered only by read-only inventory/count filters.
- `entity_filter_rule` is an experimental passthrough section. Relationship
  object types (`entity_relationship` and `entity_relationship_rule`) remain
  outside the managed model because Splunk documents them as unused. Entity
  discovery searches are read-only inventory helpers rather than managed
  upsert objects.
- Cleanup deletes are intentionally narrower than the prune plan. Content-pack authorship objects, glass-table icons, and KPI entity thresholds can be deleted only with the separate high-risk guard fields described above.
- The validator compares only the fields this skill manages, but reports path-level diffs for those managed fields when possible.

# Splunk Data Source Readiness Doctor Reference

`scripts/doctor.py` is the source of truth for this skill:

- `COVERAGE_MANIFEST` declares every readiness domain.
- `RULE_CATALOG` declares every finding, target impact, fix kind, handoff
  skill, and trigger.
- `validate_catalog()` fails when a readiness domain lacks rule coverage.
- `build_scores()` turns active findings into ES/ITSI/ARI readiness scores.

## What This Doctor Covers

The doctor complements `splunk-admin-doctor`. Admin Doctor checks platform and
administration health. This skill checks whether data that is already flowing is
usable by product content:

- Registry and source identity alignment.
- Expected indexes, sourcetypes, and macros.
- Sample-event freshness, ingest latency, expected-volume baselines, history
  depth, duplicate signal, metrics freshness, and parser quality.
- Retention and historical lookback coverage for raw indexes, archived/frozen
  data, data model summaries, ITSI backfill, ARI last-detect history, and
  dashboard time ranges.
- Ingest pipeline, destination, route, metadata-rewrite, drop, dead-letter,
  Edge Processor, and Ingest Processor flow evidence.
- Required field extraction and schema coverage.
- CIM eventtypes, tags, required/recommended fields, dataset constraints,
  value-format validation, data model mapping, and data model acceleration
  state, including index constraints, tag allowlists, summary ranges, and
  acceleration storage/enforcement evidence.
- Search-time enrichment through automatic lookups, lookup transforms/tables,
  field aliases, calculated fields, KV Store collections, permissions, and
  search-time operation order.
- OCSF-CIM add-on installation, supported classes, transform status, and
  OCSF-to-CIM bridging, including `ocsf:` sourcetype setup and timestamp
  extraction readiness.
- Enterprise Security enrichment, detection, notable, risk, adaptive-response,
  risk object/risk modifier, threat-intelligence, ESCU, correlation-search,
  content-mapping, and asset/identity readiness.
- Federated and remote datasets, including provider/index definitions, provider
  mode, remote-search errors, role mappings, zero-result checks, and Amazon
  Security Lake/OCSF mapping handoffs.
- ITSI content-pack dependencies, entity-discovery searches, KPI base searches,
  service imports, KPI data, entity split/filter fields, threshold policies,
  service-template propagation, Event Analytics aggregation policies, KPI
  runtime/backfill, and ITSI summary/metrics summary evidence.
- ARI indexes, data-source activation, event searches, required field mapping,
  relevant-event filtering, key inventory fields, priorities, Technical Add-on
  data, and ES/Exposure Analytics integration mode.
- Dashboard macro alignment, saved-search status, base/chain search
  definitions, tokens, lookup permissions, concurrency, and populated panels.
- Scheduled content execution for ES correlation searches, ITSI KPI searches,
  ARI event searches, dashboard saved searches, scheduler skips/failures,
  stale runs, runtime overruns, and quota/concurrency blocks.
- Search/RBAC access to indexes, data models, and knowledge objects.
- Handoff coverage for every fixable readiness gap.

## Source Packs And Live Collection

`source_packs.json` adds source-specific defaults and searches without turning
the rule catalog into per-vendor code. Packs can match by `skill`, `app_name`,
`product`, `name`, exact source, exact sourcetype, source+sourcetype pair, or
sourcetype prefix. Use `source_sourcetype_pairs` for generic sourcetypes such
as `_json` or `httpevent`; the collector base search then includes the paired
`source` constraint so live evidence is not gathered from unrelated HEC/JSON
streams. A matched pack fills missing evidence-contract keys only;
user-supplied evidence always wins.

Supported v1 packs:

- `aws_cloudtrail`
- `aws_security_lake_ocsf`
- `aws_securityhub_guardduty`
- `aws_vpc_flow_logs`
- `cisco_asa`
- `cisco_secure_access_firewall`
- `cisco_secure_firewall`
- `crowdstrike_falcon`
- `duo_security`
- `fortinet_fortigate`
- `github_audit`
- `google_workspace`
- `kubernetes_audit`
- `linux_secure_auditd`
- `microsoft_entra_id`
- `microsoft_o365_management_activity`
- `okta_identity_cloud`
- `palo_alto_networks`
- `windows_security`
- `zscaler_internet_access`

Use `--phase source-packs` to inspect the catalog. Use `--source-pack ID` to
force a subset when rendering or collecting.

`--phase collect` writes `collector-manifest.json`, `collection-searches.spl`,
and `source-pack-report.json`. If `--splunk-uri` and `--session-key-file` are
both supplied, it runs only POST requests to
`/services/search/v2/jobs/export` with `output_mode=json`, bounded by
`--max-searches`, `--max-rows`, and `--collect-timeout-seconds`. The session key
must live in a chmod-600 local file and is never written to outputs. The
collector does not run SPL mutating commands such as `collect`, `mcollect`,
`outputlookup`, `delete`, or configuration REST writes.

`--phase synthesize` consumes a collector result file, defaults to
`live-collector-results.redacted.json` under the output directory, and produces:

- `evidence/live-evidence.synthesized.json`
- `dashboard-dependency-graph.json`
- `synthesis-report.json`

Synthesis turns sample freshness rows into `sample_events.count`,
latest-age, observed/missing index and sourcetype evidence; turns
`fieldsummary` rows into observed and missing CIM/ARI fields; records
data-model and source-pack live checks; extracts Dashboard Studio and saved
search dependencies from `ds.search`, `ds.savedSearch`, and `ds.chain`; and
folds collector health signals for HEC, deployment clients, SC4S, SC4SNMP,
Splunk OTel Collector, and Data Manager into non-mutating evidence.

## Official Source Anchors

- Splunk ES uses CIM data model acceleration for dashboards, views, and
  detections, with acceleration enforcement handled through modular inputs:
  `https://help.splunk.com/splunk-enterprise-security-8/install/8.3/installation/configure-data-models-for-splunk-enterprise-security`
- Technology add-ons feed CIM by assigning eventtypes and tags, and CIM data
  model searches use those tags plus index constraints:
  `https://help.splunk.com/en/splunk-enterprise-security-8/common-information-model/6.1/using-the-common-information-model/match-ta-event-types-with-cim-data-models-to-accelerate-searches`
- CIM setup covers index allowlists, tag allowlists, acceleration, and summary
  range settings; data model acceleration storage and retention can affect ES
  and dashboard usability:
  `https://help.splunk.com/en/splunk-cloud-platform/common-information-model/6.1/introduction/set-up-the-splunk-common-information-model-add-on`
  and
  `https://help.splunk.com/splunk-enterprise/manage-knowledge-objects/knowledge-management-manual/9.0/use-data-summaries-to-accelerate-searches/accelerate-data-models`
- The OCSF CIM add-on provides search-time knowledge objects that map OCSF
  events to CIM; Splunk documents Splunkbase app `6841` for installation:
  `https://help.splunk.com/en/splunk-enterprise/common-information-model/6.3/introduction/overview-of-the-ocsf-cim-add-on`
  and
  `https://help.splunk.com/en/splunk-enterprise-security-8/common-information-model/8.5/introduction/overview-of-the-ocsf-cim-add-on/installing-the-ocsf-cim-add-on`
- OCSF-formatted data must be configured with `ocsf:`-prefixed sourcetypes in
  the OCSF-CIM add-on so the add-on creates the needed field-extraction stanza;
  Splunk's Edge/Processor documentation also calls out timestamp extraction and
  supported sourcetype/event-type conversion behavior:
  `https://help.splunk.com/en/data-management/common-information-model/6.3/introduction/overview-of-the-ocsf-cim-add-on/configuring-ocsf-cim-add-on`
  and
  `https://help.splunk.com/en/splunk-cloud-platform/process-data-at-the-edge/use-edge-processors-for-splunk-cloud-platform/9.3.2411/process-data-using-pipelines/convert-data-to-ocsf-format-using-an-edge-processor/working-with-ocsf-formatted-data-in-the-splunk-platform-and-splunk-enterprise-security`
- Splunk ES ships most correlation searches disabled and requires operators to
  enable relevant content and response actions; SSE data inventory introspection
  and content mapping are separate readiness inputs for security content
  coverage:
  `https://help.splunk.com/en/splunk-enterprise-security-7/administer/7.2/correlation-searches/configure-correlation-searches-in-splunk-enterprise-security`
  and
  `https://help.splunk.com/en/splunk-enterprise-security-8/security-essentials/install-and-configure/3.7/configure-splunk-security-essentials/configure-splunk-security-essentials`
- ES risk modifiers require risk fields such as `risk_score`, `risk_object`,
  and `risk_object_type`; threat intelligence feeds detections and investigation
  enrichment; ESCU provides analytic stories and tested detection searches:
  `https://help.splunk.com/splunk-enterprise-security-7/risk-based-alerting/7.2/modify-risk/how-risk-modifiers-impact-risk-scores-in-splunk-enterprise-security`
  `https://help.splunk.com/en/splunk-enterprise-security-8/administer/8.1/threat-intelligence`
  and
  `https://help.splunk.com/en/splunk-enterprise-security-8/security-content-update/how-to-use-splunk-security-content/5.7/use-splunk-security-content/what-is-splunk-enterprise-security-content-update`
- ITSI entity discovery requires index macros for custom metrics/event indexes,
  and content packs provide dashboards, reports, entity searches, service
  templates, KPIs, and glass tables:
  `https://help.splunk.com/splunk-it-service-intelligence/splunk-it-service-intelligence/discover-and-integrate-it-components/4.18/create-and-manage-entities/overview-of-itsi-entity-discovery-searches`
  and
  `https://help.splunk.com/en/splunk-it-service-intelligence/content-packs-for-itsi`
- ITSI KPI base searches require entity split/filter fields, threshold fields,
  calculation settings, and runtime discipline; threshold and entity-split
  readiness affect service analyzer, deep dives, and glass-table outputs:
  `https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/4.19/create-kpis/create-kpi-base-searches-in-itsi`
  and
  `https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/4.19/create-kpis/split-and-filter-a-kpi-by-entities-in-itsi`
- ITSI Event Analytics groups notable events into episodes using aggregation
  policies, and ITSI summary indexes store KPI and health-score output used by
  Service Analyzer:
  `https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/detect-and-act-on-notable-events/4.18/event-aggregation/overview-of-aggregation-policies-in-itsi`
  and
  `https://help.splunk.com/splunk-it-service-intelligence/splunk-it-service-intelligence/administer/4.19/itsi-indexes/itsi-summary-index-reference`
- Metrics-backed ITSI KPIs and dashboards depend on metrics indexes, metric
  names, dimensions, default metrics-index access, and `mstats` visibility:
  `https://help.splunk.com/en/splunk-enterprise/get-data-in/metrics/10.0/work-with-metrics/search-and-monitor-metrics`
  and
  `https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/10.2/search-commands/mstats`
- Splunk Ingest Monitoring exposes ingest latency and related ingest health;
  Edge Processor and Ingest Processor documentation expose pipeline, processor,
  and destination metrics that determine whether expected events reach searchable
  indexes and sourcetypes:
  `https://help.splunk.com/en/data-management/monitor-and-troubleshoot/ingest-monitoring/1.0/about-ingest-monitoring`
  `https://help.splunk.com/en/data-management/monitor-and-troubleshoot/ingest-monitoring/1.0/metrics/review-data-ingest-latency-metrics`
  `https://help.splunk.com/en/splunk-cloud-platform/process-data-at-the-edge/use-edge-processors-for-splunk-cloud-platform/9.3.2411/monitor-edge-processors/metrics-for-edge-processors`
  and
  `https://help.splunk.com/en/splunk-cloud-platform/process-data-at-ingest-time/use-ingest-processors-for-splunk-cloud-platform/9.3.2411/monitor-ingest-processors/monitor-data-destinations-pipeline-metrics`
- Splunk indexes age through buckets and can move data out of searchable
  retention; `frozenTimePeriodInSecs` defines a minimum availability window.
  Data model acceleration summaries and ITSI backfill also depend on historical
  raw data and summary range/backfill settings:
  `https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/9.0/indexing-overview/manage-index-storage/how-the-indexer-stores-indexes`
  `https://help.splunk.com/en/splunk-enterprise/administer/update-your-deployment/10.2/troubleshooting/troubleshoot-performance-issues/change-the-index-retention-period`
  `https://help.splunk.com/splunk-enterprise/manage-knowledge-objects/knowledge-management-manual/9.0/use-data-summaries-to-accelerate-searches/accelerate-data-models`
  and
  `https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/4.19/create-kpis/enable-backfill-for-a-kpi-in-itsi`
- Splunk knowledge-object endpoints and lookup documentation cover automatic
  lookups, lookup definitions, field aliases, and calculated fields; Splunk also
  documents the order of search-time operations, which matters when enrichment
  fields feed CIM, ES, ITSI, ARI, and dashboards:
  `https://help.splunk.com/en/splunk-enterprise/knowledge-manager-manual/10.0/use-the-configuration-files-to-configure-lookups/define-an-automatic-lookup-in-splunk-web`
  `https://help.splunk.com/en/splunk-enterprise/rest-api-reference/9.4/knowledge-endpoints/knowledge-endpoint-descriptions`
  and
  `https://help.splunk.com/en/splunk-enterprise/knowledge-manager-manual/9.4/get-started-with-knowledge-objects/the-sequence-of-search-time-operations`
- Federated Search uses provider and federated-index definitions; Splunk's REST
  API documents `data/federated/provider` and `data/federated/index`, and
  Splunk Secured Federated Analytics documents Amazon Security Lake searches:
  `https://help.splunk.com/en/splunk-enterprise/search/federated-search/9.3/about-federated-search/about-federated-search`
  `https://help.splunk.com/en/splunk-enterprise/rest-api-reference/9.3/federated-search-endpoints`
  and
  `https://help.splunk.com/splunk-enterprise-security-8/splunk-secured-federated-analytics/8.2/amazon-security-lake/search-amazon-security-lake-with-splunk-secured-federated-analytics`
- ES correlation searches can be real-time or scheduled, and skipped real-time
  searches do not backfill data gaps. Dashboard Studio saved-search data
  sources depend on scheduled reports and concurrency limits:
  `https://help.splunk.com/splunk-enterprise-security-7/administer/7.2/correlation-searches/configure-correlation-searches-in-splunk-enterprise-security`
  `https://help.splunk.com/en/splunk-enterprise/search/search-manual/10.0/save-and-schedule-searches/scheduling-searches`
  and
  `https://help.splunk.com/en/splunk-cloud-platform/create-dashboards-and-reports/dashboard-studio/9.2.2406/use-data-sources/use-reports-and-saved-searches-with-ds.savedsearch`
- The REST collector uses Splunk's documented search export endpoint, including
  `search/v2/jobs/export`, POST-only v2 behavior, and `output_mode=json`:
  `https://help.splunk.com/en/splunk-cloud-platform/rest-api-reference/9.3.2408/search-endpoints/search-endpoint-descriptions`
  and
  `https://help.splunk.com/en/splunk-enterprise/search/search-manual/9.0/export-search-results/export-data-using-the-splunk-rest-api`
- HEC readiness needs both token inventory and live health/error signal.
  Splunk documents HEC token management, the `services/collector/health`
  endpoint, and per-token metrics such as event/error/parser-error counts:
  `https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-enterprise/http-event-collector-rest-api-endpoints`
  and
  `https://help.splunk.com/en/splunk-enterprise/get-data-in/get-started-with-getting-data-in/10.0/get-data-with-http-event-collector/troubleshoot-http-event-collector`
- Deployment-server readiness needs client phone-home evidence. Splunk
  documents deployment clients/server classes and exposes
  `/services/deployment/server/clients` in the REST API:
  `https://help.splunk.com/en/splunk-enterprise/administer/manage-distributed-deployments/9.4/deployment-server-and-forwarder-management/deployment-server-architecture`
  and
  `https://help.splunk.com/en?resourceId=Splunk_RESTREF_RESTdeploy&version=splunk-9_0`
- Data Manager inputs expose deployment and ingestion status through the Data
  Management UI, CloudFormation StackSets, HEC token checks, and AWS
  troubleshooting workflows:
  `https://help.splunk.com/en/splunk-cloud-platform/ingest-data-from-cloud-services/data-manager-user-manual/1.13/amazon-web-services-data/verify-the-data-input-for-aws-in-data-manager`
  and
  `https://help.splunk.com/en/splunk-cloud-platform/ingest-data-from-cloud-services/data-manager-troubleshooting-manual`
- ARI requires `ari_staging`, `ari_asset`, `ari_internal`, and `ari_ta`; ARI
  data sources require field mappings for processing types such as Asset, IP,
  MAC, Identity, Software, Vulnerability, and Cloud applications:
  `https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/create-indexes-for-splunk-asset-and-risk-intelligence`
  and
  `https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/manage-data-source-field-mappings/data-source-field-mapping-reference`
- ARI source suitability also depends on key inventory fields, relevant-event
  filters, data-source type, batched versus real-time event-search shape, and
  `ari_lastdetect` behavior:
  `https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/identify-data-sources-and-filter-by-relevant-events-in-splunk-asset-and-risk-intelligence`
  and
  `https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/create-and-modify-event-searches-in-splunk-asset-and-risk-intelligence`
- Dashboard Studio dashboards can use `ds.search`, `ds.savedSearch`, and
  `ds.chain` data sources. Chain searches depend on base-search shape and
  emitted fields; saved-search dashboards depend on report app/permissions,
  schedule/concurrency, and token substitution:
  `https://help.splunk.com/en/splunk-enterprise/create-dashboards-and-reports/dashboard-studio/9.2/use-data-sources/chain-searches-together-with-a-base-search-and-chain-searches`
  `https://help.splunk.com/splunk-cloud-platform/create-dashboards-and-reports/dashboard-studio/9.2.2406/use-data-sources/use-reports-and-saved-searches-with-ds.savedsearch`
  and
  `https://help.splunk.com/splunk-enterprise/create-dashboards-and-reports/dashboard-studio/9.3/use-data-sources/create-search-based-visualizations-with-ds.search`
- Source-pack anchors:
  `https://help.splunk.com/en/supported-add-ons`
  `https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/splunk-supported-add-ons/microsoft-windows`
  `https://help.splunk.com/en/splunk-enterprise/get-data-in/integrate-data-with-splunk-supported-add-ons/unix-and-linux`
  `https://help.splunk.com/en/data-management/integrate-data-with-add-ons/splunk-supported-add-ons/microsoft-office-365`
  `https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/cisco-asa_1`
  `https://research.splunk.com/sources/`
  `https://research.splunk.com/sources/e8ace6db-1dbd-4c72-a1fb-334684619a38/`
  `https://research.splunk.com/sources/1dcf9cfb-0e91-44c6-81b3-61b2574ec898/`
  `https://research.splunk.com/sources/18878597-8f8a-4bca-a805-bfbe35e00032/`
  `https://research.splunk.com/sources/6c25181a-0c07-4aaf-90e6-77ab1f0e6699/`
  `https://research.splunk.com/sources/ec26febe-e760-4981-bbee-72e107c7b9d2/`
  `https://research.splunk.com/sources/f1a044e3-113a-4e4d-84f2-b153ade83087/`
  `https://research.splunk.com/sources/52b38751-b0db-4965-a800-ebaabd1fd7d5/`
  `https://research.splunk.com/sources/cbb06880-9dd9-4542-ac60-bd6e5d3c3e4e/`
  `https://research.splunk.com/sources/182a83bc-c31a-4817-8c7a-263744cec52a/`
  `https://research.splunk.com/sources/b02bfbf3-294f-478e-99a1-e24b8c692d7e/`
  `https://research.splunk.com/sources/ce520b1c-79fe-48ef-a0f9-71fbbd4837b0/`

## Evidence Shape

Evidence is JSON. Common top-level keys:

- `platform`: `cloud` or `enterprise`
- `targets`: optional list such as `["es", "itsi", "ari"]`
- `products`: installed product hints, for example `products.es.installed`
- `registry`: optional registry evidence or overrides
- `data_sources`: list of source objects
- `data_models`, `cim`, `ingest`, `knowledge`, `ocsf`, `federated`,
  `retention`, `scheduled_searches`, `scheduler`, `es`, `itsi`, `ari`,
  `dashboards`, `rbac`, and `handoffs` for global readiness evidence

Each `data_sources[]` object can include:

- Identity: `name`, `app_name`, `skill`, `splunkbase_id`, `product`
- Source packs: `source_pack_id` or `source_pack` to force a bundled pack
- Contract: `expected_indexes`, `expected_sourcetypes`, `expected_macros`,
  `expected_sources`, `cim.expected_models`, `cim.required_fields`,
  `itsi.expected_content_packs`, `ari.expected_processing_types`,
  `dashboards.expected`
- Observed state: `indexes.missing`, `sourcetypes.missing`,
  `macros.missing`, `sample_events.count`, `sample_events.latest_age_minutes`,
  `sample_events.volume_below_baseline`,
  `sample_events.expected_count_gap`, `sample_events.ingest_latency_minutes`,
  `sample_events.late_arriving_events`,
  `sample_events.duplicate_rate_pct`, `sample_events.history_depth_gaps`
- Retention/lookback: `retention.lookback_gaps`,
  `retention.raw_history_gaps`, `retention.archive_unsearchable_gaps`,
  `retention.frozen_time_too_short`, `retention.bucket_aging_gaps`,
  `indexes.retention_gaps`, `indexes.frozen_time_too_short`,
  `indexes.archive_unsearchable_gaps`,
  `data_models.summary_range_shorter_than_detection`
- Ingest flow: `ingest.pipeline_errors`, `ingest.destination_errors`,
  `ingest.dropped_events`, `ingest.dead_letter_queue_events`,
  `ingest.pipeline_inactive`, `ingest.routing_gaps`,
  `ingest.metadata_rewrite_gaps`, `ingest.edge_processor_errors`,
  `ingest.ingest_processor_errors`, `ingest.ingest_latency_minutes`
- Normalization: `cim.missing_tags`, `cim.missing_eventtypes`,
  `cim.missing_required_fields`, `cim.validation_errors`,
  `cim.dataset_constraint_gaps`, `cim.field_value_regex_failures`,
  `cim.recommended_field_gaps`, `cim.data_models_without_events`
- Knowledge/enrichment: `knowledge.automatic_lookup_gaps`,
  `knowledge.lookup_definition_gaps`, `knowledge.lookup_table_empty`,
  `knowledge.lookup_staleness_gaps`, `knowledge.lookup_permission_gaps`,
  `knowledge.field_alias_gaps`, `knowledge.calculated_field_errors`,
  `knowledge.search_time_order_gaps`, `knowledge.kvstore_collection_gaps`
- Acceleration: `data_models.acceleration_disabled`,
  `data_models.acceleration_errors`, `data_models.lag_minutes`,
  `data_models.index_constraint_gaps`, `data_models.tags_whitelist_gaps`,
  `data_models.summary_range_gaps`,
  `data_models.acceleration_enforcement_gaps`,
  `data_models.acceleration_storage_gaps`
- Metrics: `metrics.indexes_missing`, `metrics.metric_names_missing`,
  `metrics.dimensions_missing`, `metrics.mstats_zero_results`,
  `metrics.default_metrics_index_gaps`, `metrics.case_sensitivity_gaps`,
  `metrics.high_cardinality_dimensions`, `metrics.field_filter_gaps`
- OCSF: `ocsf.required`, `ocsf.addon_installed`, `ocsf.missing_transforms`,
  `ocsf.unsupported_classes`, `ocsf.mapped_to_cim`,
  `ocsf.unprefixed_sourcetypes`, `ocsf.unconfigured_sourcetypes`,
  `ocsf.timestamp_extraction_gaps`, `ocsf.props_conf_gaps`,
  `ocsf.conversion_failures`
- Federated: `federated.provider_gaps`, `federated.federated_index_gaps`,
  `federated.mode_unsupported`, `federated.remote_search_errors`,
  `federated.role_mapping_gaps`, `federated.zero_results`,
  `federated.dataset_acceleration_gaps`,
  `federated.dataset_constraint_gaps`,
  `federated.amazon_security_lake_mapping_gaps`
- Scheduled execution: `scheduled_searches.skipped`,
  `scheduled_searches.failed`, `scheduled_searches.latest_run_stale`,
  `scheduled_searches.runtime_exceeded`,
  `scheduled_searches.concurrency_queued`,
  `scheduled_searches.schedule_window_gaps`,
  `scheduler.skipped_searches`, `scheduler.dispatch_errors`,
  `scheduler.quota_gaps`
- Products: `es.*`, `itsi.*`, `ari.*`, `dashboards.*`, `rbac.*`

Product-specific evidence keys commonly used by the rule catalog:

- ES/SSE: `es.correlation_searches_disabled`, `es.adaptive_response_gaps`,
  `es.notable_action_disabled`, `es.risk_modifier_gaps`,
  `es.content_mapping_gaps`, `sse.data_inventory_missing`,
  `sse.content_mapping_stale`, `sse.cim_compliance_check_gaps`,
  `es.security_content_update_missing`, `es.security_content_update_stale`,
  `es.analytic_story_gaps`, `es.detection_version_gaps`,
  `es.risk_modifier_field_gaps`, `es.risk_object_field_gaps`,
  `es.risk_object_type_gaps`, `es.risk_score_gaps`,
  `es.risk_datamodel_gaps`, `es.threat_intel_source_gaps`,
  `es.threat_intel_lookup_empty`, `es.threat_intel_kvstore_gaps`,
  `es.threat_match_gaps`, `es.observable_field_gaps`,
  `es.correlation_search_skips`, `es.correlation_search_lag_gaps`
- ITSI: `itsi.threshold_gaps`, `itsi.entity_split_field_gaps`,
  `itsi.pseudo_entity_gaps`, `itsi.service_template_gaps`,
  `itsi.kpi_runtime_gaps`, `itsi.kpi_importance_gaps`,
  `itsi.adaptive_threshold_training_gaps`, `itsi.kpi_backfill_gaps`,
  `itsi.event_analytics_gaps`, `itsi.aggregation_policy_gaps`,
  `itsi.episode_split_field_gaps`, `itsi.episode_breaking_gaps`,
  `itsi.itsi_tracked_alerts_gaps`, `itsi.episode_severity_gaps`,
  `itsi.summary_index_gaps`, `itsi.summary_metrics_gaps`,
  `itsi.service_health_score_gaps`, `itsi.kpi_summary_zero_results`,
  `itsi.itsi_summary_access_gaps`, `itsi.kpi_scheduler_skips`,
  `itsi.backfill_period_gaps`
- ARI: `ari.key_field_gaps`, `ari.relevant_event_filter_gaps`,
  `ari.event_search_shape_errors`, `ari.duplicate_asset_events`,
  `ari.lastdetect_gaps`, `ari.batched_search_not_tabular`,
  `ari.realtime_search_uses_pipes`, `ari.event_search_schedule_gaps`,
  `ari.lastdetect_history_gaps`
- Dashboards: `dashboards.search_errors`, `dashboards.base_search_errors`,
  `dashboards.chain_search_gaps`, `dashboards.token_gaps`,
  `dashboards.saved_search_reference_gaps`,
  `dashboards.saved_search_staleness_gaps`,
  `dashboards.time_range_retention_gaps`,
  `dashboards.lookup_permission_gaps`, `dashboards.concurrency_gaps`

The doctor redacts secret-like keys and token-looking values before writing
evidence to disk.

## Score Model

Scores are reported for `es`, `itsi`, and `ari` by default. Every active finding
declares a target impact. Scores start at `100` and subtract the target-specific
impact, then clamp to `0..100`.

Status tiers:

- `ready`: score is at least `90` and the target has no high/critical finding.
- `usable_with_gaps`: score is at least `75`.
- `blocked`: score is below `75` or any critical target finding is active.

The JSON report includes per-target finding IDs and per-data-source score
breakdowns so an operator can see why a source is or is not usable.

## Fix Policy

`direct_fix` renders a local checklist. `delegated_fix` routes to a mature
skill. `manual_support` renders a support/runbook packet. `diagnose_only`
explains a gap that needs operator review but is not selectable in `apply`.

Do not change `apply` to execute Splunk REST calls, searches, app installs,
data model rebuilds, ARI source activation, ES writes, ITSI imports, or any
other live mutation unless the mutation is separately designed, safety-gated,
tested, and documented in this reference.

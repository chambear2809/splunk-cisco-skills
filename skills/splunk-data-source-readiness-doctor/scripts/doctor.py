#!/usr/bin/env python3
"""Render Splunk data-source readiness reports and handoff packets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import ssl
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


SKILL_NAME = "splunk-data-source-readiness-doctor"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "splunk-data-source-readiness-doctor-rendered"
DEFAULT_REGISTRY_FILE = REPO_ROOT / "skills/shared/app_registry.json"
DEFAULT_SOURCE_PACKS_FILE = REPO_ROOT / "skills/splunk-data-source-readiness-doctor/source_packs.json"
DEFAULT_TARGETS = ("es", "itsi", "ari")
ALL_TARGETS = {"es", "itsi", "ari"}

FIX_KINDS = {
    "direct_fix",
    "delegated_fix",
    "manual_support",
    "diagnose_only",
}
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
FIX_KIND_RANK = {"direct_fix": 4, "delegated_fix": 3, "manual_support": 2, "diagnose_only": 1}
REQUIRED_RULE_FIELDS = {
    "id",
    "domain",
    "scope",
    "severity",
    "evidence",
    "source_doc",
    "fix_kind",
    "preview_command",
    "apply_command",
    "handoff_skill",
    "rollback_or_validation",
    "target_impacts",
}

SOURCE_DOCS = {
    "cim_eventtypes": "https://help.splunk.com/en/splunk-enterprise-security-8/common-information-model/6.1/using-the-common-information-model/match-ta-event-types-with-cim-data-models-to-accelerate-searches",
    "cim_overview": "https://help.splunk.com/en/splunk-enterprise-security-8/common-information-model/5.1/introduction/overview-of-the-splunk-common-information-model",
    "cim_reference_tables": "https://help.splunk.com/splunk-cloud-platform/common-information-model/6.1/data-models/how-to-use-the-cim-data-model-reference-tables",
    "cim_setup": "https://help.splunk.com/en/splunk-cloud-platform/common-information-model/6.1/introduction/set-up-the-splunk-common-information-model-add-on",
    "dashboard_chain": "https://help.splunk.com/en/splunk-enterprise/create-dashboards-and-reports/dashboard-studio/9.2/use-data-sources/chain-searches-together-with-a-base-search-and-chain-searches",
    "dashboard_search": "https://help.splunk.com/splunk-enterprise/create-dashboards-and-reports/dashboard-studio/9.3/use-data-sources/create-search-based-visualizations-with-ds.search",
    "dashboard_savedsearch": "https://help.splunk.com/splunk-cloud-platform/create-dashboards-and-reports/dashboard-studio/9.2.2406/use-data-sources/use-reports-and-saved-searches-with-ds.savedsearch",
    "es_data_models": "https://help.splunk.com/splunk-enterprise-security-8/install/8.3/installation/configure-data-models-for-splunk-enterprise-security",
    "es_data_sources": "https://help.splunk.com/en/splunk-enterprise-security-8/install/8.3/planning/data-source-planning-for-splunk-enterprise-security",
    "es_correlation_searches": "https://help.splunk.com/en/splunk-enterprise-security-7/administer/7.2/correlation-searches/configure-correlation-searches-in-splunk-enterprise-security",
    "es_correlation_scheduling": "https://help.splunk.com/splunk-enterprise-security-7/administer/7.2/correlation-searches/configure-correlation-searches-in-splunk-enterprise-security",
    "es_risk": "https://help.splunk.com/splunk-enterprise-security-7/risk-based-alerting/7.2/modify-risk/how-risk-modifiers-impact-risk-scores-in-splunk-enterprise-security",
    "es_security_content_update": "https://help.splunk.com/en/splunk-enterprise-security-8/security-content-update/how-to-use-splunk-security-content/5.7/use-splunk-security-content/what-is-splunk-enterprise-security-content-update",
    "es_threat_intel": "https://help.splunk.com/en/splunk-enterprise-security-8/administer/8.1/threat-intelligence",
    "es_assets": "https://help.splunk.com/en/splunk-enterprise-security-7/administer/7.2/asset-and-identity-overview",
    "federated_search": "https://help.splunk.com/en/splunk-enterprise/search/federated-search/9.3/about-federated-search/about-federated-search",
    "federated_security_lake": "https://help.splunk.com/splunk-enterprise-security-8/splunk-secured-federated-analytics/8.2/amazon-security-lake/search-amazon-security-lake-with-splunk-secured-federated-analytics",
    "automatic_lookups": "https://help.splunk.com/en/splunk-enterprise/knowledge-manager-manual/10.0/use-the-configuration-files-to-configure-lookups/define-an-automatic-lookup-in-splunk-web",
    "search_time_order": "https://help.splunk.com/en/splunk-enterprise/knowledge-manager-manual/9.4/get-started-with-knowledge-objects/the-sequence-of-search-time-operations",
    "ingest_monitoring": "https://help.splunk.com/en/data-management/monitor-and-troubleshoot/ingest-monitoring/1.0/about-ingest-monitoring",
    "ingest_latency": "https://help.splunk.com/en/data-management/monitor-and-troubleshoot/ingest-monitoring/1.0/metrics/review-data-ingest-latency-metrics",
    "edge_processor_metrics": "https://help.splunk.com/en/splunk-cloud-platform/process-data-at-the-edge/use-edge-processors-for-splunk-cloud-platform/9.3.2411/monitor-edge-processors/metrics-for-edge-processors",
    "ingest_processor_destinations": "https://help.splunk.com/en/splunk-cloud-platform/process-data-at-ingest-time/use-ingest-processors-for-splunk-cloud-platform/9.3.2411/monitor-ingest-processors/monitor-data-destinations-pipeline-metrics",
    "index_storage": "https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/9.0/indexing-overview/manage-index-storage/how-the-indexer-stores-indexes",
    "index_retention": "https://help.splunk.com/en/splunk-enterprise/administer/update-your-deployment/10.2/troubleshooting/troubleshoot-performance-issues/change-the-index-retention-period",
    "itsi_entity": "https://help.splunk.com/splunk-it-service-intelligence/splunk-it-service-intelligence/discover-and-integrate-it-components/4.18/create-and-manage-entities/overview-of-itsi-entity-discovery-searches",
    "itsi_event_analytics": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/detect-and-act-on-notable-events/4.18/event-aggregation/overview-of-aggregation-policies-in-itsi",
    "itsi_kpi": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/4.19/create-kpis/create-kpi-base-searches-in-itsi",
    "itsi_packs": "https://help.splunk.com/en/splunk-it-service-intelligence/content-packs-for-itsi",
    "itsi_summary": "https://help.splunk.com/splunk-it-service-intelligence/splunk-it-service-intelligence/administer/4.19/itsi-indexes/itsi-summary-index-reference",
    "itsi_thresholds": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/4.19/create-kpis/configure-kpi-thresholds-in-itsi",
    "itsi_entity_split": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/4.19/create-kpis/split-and-filter-a-kpi-by-entities-in-itsi",
    "metrics_search": "https://help.splunk.com/en/splunk-enterprise/get-data-in/metrics/10.0/work-with-metrics/search-and-monitor-metrics",
    "metrics_mstats": "https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/10.2/search-commands/mstats",
    "ari_indexes": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/create-indexes-for-splunk-asset-and-risk-intelligence",
    "ari_sources": "https://help.splunk.com/en/splunk-enterprise-security-8/administer/8.4/exposure-analytics/set-up-data-sources-for-splunk-asset-and-risk-intelligence",
    "ari_relevant_events": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/identify-data-sources-and-filter-by-relevant-events-in-splunk-asset-and-risk-intelligence",
    "ari_event_searches": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/set-up-data-sources/create-and-modify-event-searches-in-splunk-asset-and-risk-intelligence",
    "ari_fields": "https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/administer/1.2/manage-data-source-field-mappings/data-source-field-mapping-reference",
    "ocsf_overview": "https://help.splunk.com/en/splunk-enterprise/common-information-model/6.3/introduction/overview-of-the-ocsf-cim-add-on",
    "ocsf_install": "https://help.splunk.com/en/splunk-enterprise-security-8/common-information-model/8.5/introduction/overview-of-the-ocsf-cim-add-on/installing-the-ocsf-cim-add-on",
    "ocsf_config": "https://help.splunk.com/en/data-management/common-information-model/6.3/introduction/overview-of-the-ocsf-cim-add-on/configuring-ocsf-cim-add-on",
    "ocsf_platform": "https://help.splunk.com/en/splunk-cloud-platform/process-data-at-the-edge/use-edge-processors-for-splunk-cloud-platform/9.3.2411/process-data-using-pipelines/convert-data-to-ocsf-format-using-an-edge-processor/working-with-ocsf-formatted-data-in-the-splunk-platform-and-splunk-enterprise-security",
    "sse_config": "https://help.splunk.com/en/splunk-enterprise-security-8/security-essentials/install-and-configure/3.7/configure-splunk-security-essentials/configure-splunk-security-essentials",
    "sse_cim_compliance": "https://help.splunk.com/en/splunk-enterprise-security-7/splunk-security-essentials/use-splunk-security-essentials/3.7/use-security-operations-in-splunk-security-essentials/check-if-your-data-is-cim-compliant-with-the-common-information-model-compliance-check-dashboard",
    "registry": "skills/shared/app_registry.json",
}


COVERAGE_MANIFEST = [
    {
        "domain": "Registry and source identity",
        "targets": ["es", "itsi", "ari"],
        "policy": "Every source must resolve to an app, product skill, or explicit owner and must declare a usable expected-data contract.",
    },
    {
        "domain": "Indexes sourcetypes and macros",
        "targets": ["es", "itsi", "ari"],
        "policy": "Expected indexes, sourcetypes, and dashboard/content macros must exist and resolve to the data actually being searched.",
    },
    {
        "domain": "Ingest pipeline and transport flow",
        "targets": ["es", "itsi", "ari"],
        "policy": "Pipeline, destination, routing, latency, drop, and metadata-rewrite evidence must prove that expected events reach searchable datasets intact.",
    },
    {
        "domain": "Sample freshness and volume",
        "targets": ["es", "itsi", "ari"],
        "policy": "Recent sample events must exist before ES detections, ITSI KPIs, ARI data sources, or dashboards are considered usable.",
    },
    {
        "domain": "Retention and historical lookback",
        "targets": ["es", "itsi", "ari"],
        "policy": "Raw-data retention, archive/searchability, and historical backfill coverage must satisfy detection, KPI, ARI inventory, acceleration, and dashboard lookback windows.",
    },
    {
        "domain": "Parser and event quality",
        "targets": ["es", "itsi", "ari"],
        "policy": "Timestamp, line-breaking, host, source, and field extraction issues are data-readiness blockers, not platform-admin defects.",
    },
    {
        "domain": "CIM tags eventtypes and fields",
        "targets": ["es", "itsi"],
        "policy": "TA eventtypes and tags must connect events to CIM datasets, and required/recommended fields, dataset constraints, and value formats must pass representative validation.",
    },
    {
        "domain": "Data model acceleration",
        "targets": ["es", "itsi"],
        "policy": "CIM and ES data models must be accelerated, current, constrained to relevant indexes, tag-allowlisted when needed, correctly ranged, and producing tstats-visible data.",
    },
    {
        "domain": "Knowledge object enrichment",
        "targets": ["es", "itsi", "ari"],
        "policy": "Automatic lookups, lookup definitions/tables, field aliases, calculated fields, KV Store collections, and search-time operation order must enrich representative events for downstream content.",
    },
    {
        "domain": "Metrics indexes and dimensions",
        "targets": ["itsi"],
        "policy": "Metrics-backed KPIs and dashboards must have searchable metrics indexes, metric names, dimensions, default metrics-index access, and mstats-visible recent data.",
    },
    {
        "domain": "OCSF to CIM bridging",
        "targets": ["es", "itsi"],
        "policy": "OCSF data requires the OCSF-CIM add-on, ocsf:-prefixed configured sourcetypes, timestamp handling, supported classes, enabled transforms, and successful CIM bridge output.",
    },
    {
        "domain": "Enterprise Security readiness",
        "targets": ["es"],
        "policy": "ES readiness includes product presence, CIM data model coverage, asset/identity enrichment, risk/notable indexes, risk modifier fields, threat intelligence, ESCU currency, detection data, correlation-search activation, adaptive responses, and SSE data inventory/content mapping.",
    },
    {
        "domain": "Federated and remote dataset readiness",
        "targets": ["es", "itsi", "ari"],
        "policy": "Federated providers, federated indexes, remote roles, remote-result shape, and Security Lake/OCSF mappings must be valid before remote data is scored as usable.",
    },
    {
        "domain": "ITSI readiness",
        "targets": ["itsi"],
        "policy": "ITSI readiness includes content-pack dependencies, entity discovery, KPI base searches, service imports, non-empty KPI data, entity split/filter fields, threshold policies, service templates, Event Analytics aggregation, and runtime/backfill/summary health.",
    },
    {
        "domain": "Asset and Risk Intelligence readiness",
        "targets": ["ari"],
        "policy": "ARI readiness includes required indexes, active data sources, relevant-event filters, key inventory fields, event-search shape, field mappings, priorities, TA sourcetypes, and ES/Exposure Analytics mode.",
    },
    {
        "domain": "Dashboard and saved-search usability",
        "targets": ["es", "itsi", "ari"],
        "policy": "Dashboards and scheduled searches must have macros, valid data-source definitions, working base/chain searches, token defaults, lookup permissions, enabled reports, permissions, and populated panels.",
    },
    {
        "domain": "Scheduled content execution",
        "targets": ["es", "itsi", "ari"],
        "policy": "Scheduled ES, ITSI, ARI, and dashboard content must run recently without skips, dispatch failures, quota blocks, stale results, or unacceptable lag.",
    },
    {
        "domain": "Search access and RBAC",
        "targets": ["es", "itsi", "ari"],
        "policy": "Analyst/service roles must be able to search the required indexes, data models, macros, lookups, and app knowledge objects.",
    },
    {
        "domain": "Handoff and fix routing coverage",
        "targets": ["es", "itsi", "ari"],
        "policy": "Every readiness gap must route to an existing skill, direct checklist, or explicit manual/support packet.",
    },
]


def rule(
    *,
    rule_id: str,
    domain: str,
    scope: str,
    severity: str,
    evidence: str,
    source_doc: str,
    fix_kind: str,
    preview_command: str,
    apply_command: str,
    handoff_skill: str,
    rollback_or_validation: str,
    target_impacts: dict[str, int],
    trigger: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "domain": domain,
        "scope": scope,
        "severity": severity,
        "evidence": evidence,
        "source_doc": source_doc,
        "fix_kind": fix_kind,
        "preview_command": preview_command,
        "apply_command": apply_command,
        "handoff_skill": handoff_skill,
        "rollback_or_validation": rollback_or_validation,
        "target_impacts": target_impacts,
        "trigger": trigger,
    }


RULE_CATALOG = [
    rule(
        rule_id="DSRD-ARI-DATA-SOURCE-INACTIVE",
        domain="Asset and Risk Intelligence readiness",
        scope="both",
        severity="high",
        evidence="ari.inactive_data_sources, ari.activation_gaps, or ari.data_source_active=false indicates ARI cannot process this source.",
        source_doc=SOURCE_DOCS["ari_sources"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh --help",
        apply_command="Render ARI data-source activation handoff only; activation remains in ARI UI/API workflow.",
        handoff_skill="splunk-asset-risk-intelligence-setup",
        rollback_or_validation="Validate the ARI data source, then rerun this doctor and verify the ARI score improves.",
        target_impacts={"ari": -22, "es": -5},
        trigger={
            "any": [
                {"path": "ari.inactive_data_sources", "truthy": True},
                {"path": "ari.activation_gaps", "truthy": True},
                {"path": "ari.data_source_active", "equals": False},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ARI-FIELD-MAPPING-GAP",
        domain="Asset and Risk Intelligence readiness",
        scope="both",
        severity="high",
        evidence="ari.missing_required_fields or ari.field_mapping_errors is populated for Asset/IP/MAC/Identity/Software/Vulnerability/Cloud application processing.",
        source_doc=SOURCE_DOCS["ari_fields"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh --help",
        apply_command="Render ARI field mapping/event-search handoff only.",
        handoff_skill="splunk-asset-risk-intelligence-setup",
        rollback_or_validation="Run ARI data source validation and verify required fields have values.",
        target_impacts={"ari": -25, "es": -6},
        trigger={
            "any": [
                {"path": "ari.missing_required_fields", "truthy": True},
                {"path": "ari.field_mapping_errors", "truthy": True},
                {"path": "ari.event_search_errors", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ARI-INDEX-GAP",
        domain="Asset and Risk Intelligence readiness",
        scope="both",
        severity="high",
        evidence="ARI indexes are missing or not searchable: ari_staging, ari_asset, ari_internal, or ari_ta.",
        source_doc=SOURCE_DOCS["ari_indexes"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh --mode validate --dry-run",
        apply_command="Render ARI index-readiness handoff; index creation stays in ARI or platform index workflows.",
        handoff_skill="splunk-asset-risk-intelligence-setup,splunk-hec-service-setup",
        rollback_or_validation="Verify ARI index visibility and rerun this doctor.",
        target_impacts={"ari": -28, "es": -4},
        trigger={
            "any": [
                {"path": "ari.indexes_missing", "truthy": True},
                {"path": "ari.index_visibility_errors", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ARI-PRIORITY-GAP",
        domain="Asset and Risk Intelligence readiness",
        scope="both",
        severity="medium",
        evidence="ari.priority_gaps or ari.source_priority_unset is present, so ARI conflict resolution may keep stale or lower-trust values.",
        source_doc=SOURCE_DOCS["ari_sources"],
        fix_kind="manual_support",
        preview_command="Review generated ARI source-priority support packet.",
        apply_command="Render ARI source/field priority review packet only.",
        handoff_skill="",
        rollback_or_validation="Review ARI source and field priorities, then rerun this doctor.",
        target_impacts={"ari": -12},
        trigger={
            "any": [
                {"path": "ari.priority_gaps", "truthy": True},
                {"path": "ari.source_priority_unset", "equals": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ARI-RELEVANT-EVENT-FILTER-GAP",
        domain="Asset and Risk Intelligence readiness",
        scope="both",
        severity="high",
        evidence="ari.key_field_gaps, ari.relevant_event_filter_gaps, ari.event_search_shape_errors, ari.duplicate_asset_events, or ari.lastdetect_gaps indicates ARI cannot reliably build inventories from relevant events.",
        source_doc=SOURCE_DOCS["ari_relevant_events"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh --mode validate --dry-run",
        apply_command="Render ARI relevant-event and event-search handoff only.",
        handoff_skill="splunk-asset-risk-intelligence-setup",
        rollback_or_validation="Test the ARI event search, verify key fields per processing type, and rerun this doctor.",
        target_impacts={"ari": -18, "es": -4},
        trigger={
            "any": [
                {"path": "ari.key_field_gaps", "truthy": True},
                {"path": "ari.relevant_event_filter_gaps", "truthy": True},
                {"path": "ari.event_search_shape_errors", "truthy": True},
                {"path": "ari.duplicate_asset_events", "truthy": True},
                {"path": "ari.lastdetect_gaps", "truthy": True},
                {"path": "ari.batched_search_not_tabular", "equals": True},
                {"path": "ari.realtime_search_uses_pipes", "equals": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-CIM-DATAMODEL-NO-EVENTS",
        domain="Data model acceleration",
        scope="both",
        severity="high",
        evidence="cim.data_models_without_events is populated or cim.datamodel_sample_count is zero.",
        source_doc=SOURCE_DOCS["es_data_models"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode inventory --help",
        apply_command="Render ES/CIM data-model handoff only; no acceleration rebuild is triggered.",
        handoff_skill="splunk-enterprise-security-config",
        rollback_or_validation="Run tstats against the relevant data models and rerun this doctor.",
        target_impacts={"es": -24, "itsi": -10},
        trigger={
            "any": [
                {"path": "cim.data_models_without_events", "truthy": True},
                {"path": "cim.datamodel_sample_count", "equals": 0},
            ]
        },
    ),
    rule(
        rule_id="DSRD-CIM-FIELD-GAP",
        domain="CIM tags eventtypes and fields",
        scope="both",
        severity="high",
        evidence="cim.missing_required_fields is populated for the expected CIM dataset.",
        source_doc=SOURCE_DOCS["cim_overview"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode preview --help",
        apply_command="Render CIM field-mapping handoff only; TA/parser changes stay with the owning app or product skill.",
        handoff_skill="splunk-enterprise-security-config,splunk-app-install",
        rollback_or_validation="Validate representative events with fieldsummary and CIM data model searches.",
        target_impacts={"es": -22, "itsi": -8},
        trigger={"any": [{"path": "cim.missing_required_fields", "truthy": True}]},
    ),
    rule(
        rule_id="DSRD-CIM-TAG-EVENTTYPE-GAP",
        domain="CIM tags eventtypes and fields",
        scope="both",
        severity="high",
        evidence="cim.missing_tags, cim.missing_eventtypes, or cim.eventtype_errors is populated.",
        source_doc=SOURCE_DOCS["cim_eventtypes"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode preview --help",
        apply_command="Render CIM eventtype/tag handoff only.",
        handoff_skill="splunk-enterprise-security-config,splunk-app-install",
        rollback_or_validation="Verify tags/eventtypes and rerun tstats against the target data model.",
        target_impacts={"es": -25, "itsi": -10},
        trigger={
            "any": [
                {"path": "cim.missing_tags", "truthy": True},
                {"path": "cim.missing_eventtypes", "truthy": True},
                {"path": "cim.eventtype_errors", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-CIM-VALIDATION-GAP",
        domain="CIM tags eventtypes and fields",
        scope="both",
        severity="medium",
        evidence="cim.validation_errors, cim.dataset_constraint_gaps, cim.field_value_regex_failures, cim.recommended_field_gaps, or sse.cim_compliance_check_gaps indicates schema quality problems beyond required-field presence.",
        source_doc=SOURCE_DOCS["cim_reference_tables"],
        fix_kind="delegated_fix",
        preview_command="Review CIM validation/SSE compliance evidence and the owning TA or ES configuration skill.",
        apply_command="Render CIM validation handoff only; no TA/parser changes are performed.",
        handoff_skill="splunk-enterprise-security-config,splunk-security-essentials-setup,splunk-app-install",
        rollback_or_validation="Run CIM validation or the SSE CIM Compliance Check dashboard and verify field values pass expected patterns.",
        target_impacts={"es": -12, "itsi": -8},
        trigger={
            "any": [
                {"path": "cim.validation_errors", "truthy": True},
                {"path": "cim.dataset_constraint_gaps", "truthy": True},
                {"path": "cim.field_value_regex_failures", "truthy": True},
                {"path": "cim.recommended_field_gaps", "truthy": True},
                {"path": "sse.cim_compliance_check_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-DASHBOARDS-MACRO-GAP",
        domain="Dashboard and saved-search usability",
        scope="both",
        severity="medium",
        evidence="dashboards.missing_macros, macros.missing, or macros.unresolved is populated.",
        source_doc=SOURCE_DOCS["registry"],
        fix_kind="delegated_fix",
        preview_command="Review macro handoff and the owning setup skill.",
        apply_command="Render dashboard/macro handoff only.",
        handoff_skill="splunk-enterprise-security-config,splunk-itsi-config,cisco-product-setup,splunk-app-install",
        rollback_or_validation="Rerun dashboard searches and verify macros expand to searchable indexes.",
        target_impacts={"es": -8, "itsi": -12, "ari": -8},
        trigger={
            "any": [
                {"path": "dashboards.missing_macros", "truthy": True},
                {"path": "macros.missing", "truthy": True},
                {"path": "macros.unresolved", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-DASHBOARDS-PANEL-ZERO",
        domain="Dashboard and saved-search usability",
        scope="both",
        severity="medium",
        evidence="dashboards.zero_result_panels is populated, dashboards.populated=false, or saved_searches.disabled_required is populated.",
        source_doc=SOURCE_DOCS["registry"],
        fix_kind="diagnose_only",
        preview_command="Review zero-result panel and saved-search evidence.",
        apply_command="No saved-search enablement or dashboard modification in v1.",
        handoff_skill="",
        rollback_or_validation="Rerun dashboard panels after fixing the upstream data or macro issue.",
        target_impacts={"es": -8, "itsi": -10, "ari": -8},
        trigger={
            "any": [
                {"path": "dashboards.zero_result_panels", "truthy": True},
                {"path": "dashboards.populated", "equals": False},
                {"path": "saved_searches.disabled_required", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-DASHBOARDS-SEARCH-DEFINITION-GAP",
        domain="Dashboard and saved-search usability",
        scope="both",
        severity="medium",
        evidence="dashboards.search_errors, dashboards.base_search_errors, dashboards.chain_search_gaps, dashboards.token_gaps, dashboards.saved_search_reference_gaps, dashboards.lookup_permission_gaps, or dashboards.concurrency_gaps is populated.",
        source_doc=SOURCE_DOCS["dashboard_chain"],
        fix_kind="diagnose_only",
        preview_command="Review dashboard data-source, base-search, chain-search, token, saved-search, lookup, and concurrency evidence.",
        apply_command="No dashboard JSON, report, token, lookup, or concurrency mutation in v1.",
        handoff_skill="",
        rollback_or_validation="Rerun affected dashboard data sources after fixing base searches, chain fields, saved-search references, token defaults, or lookup permissions.",
        target_impacts={"es": -8, "itsi": -8, "ari": -8},
        trigger={
            "any": [
                {"path": "dashboards.search_errors", "truthy": True},
                {"path": "dashboards.base_search_errors", "truthy": True},
                {"path": "dashboards.chain_search_gaps", "truthy": True},
                {"path": "dashboards.token_gaps", "truthy": True},
                {"path": "dashboards.saved_search_reference_gaps", "truthy": True},
                {"path": "dashboards.lookup_permission_gaps", "truthy": True},
                {"path": "dashboards.concurrency_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-DM-ACCELERATION-GAP",
        domain="Data model acceleration",
        scope="both",
        severity="high",
        evidence="data_models.acceleration_disabled, data_models.acceleration_errors, or high data_models.lag_minutes is present.",
        source_doc=SOURCE_DOCS["es_data_models"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode inventory --help",
        apply_command="Render ES data model acceleration handoff; no rebuild or acceleration setting is changed by this doctor.",
        handoff_skill="splunk-enterprise-security-config",
        rollback_or_validation="Check the ES Data Model Audit dashboard or rest /services/data/models, then rerun this doctor.",
        target_impacts={"es": -22, "itsi": -8},
        trigger={
            "any": [
                {"path": "data_models.acceleration_disabled", "truthy": True},
                {"path": "data_models.acceleration_errors", "truthy": True},
                {"path": "data_models.summarization_status", "in": ["disabled", "error", "failed", "stale"]},
                {"path": "data_models.lag_minutes", "gt": 120},
            ]
        },
    ),
    rule(
        rule_id="DSRD-DM-CONSTRAINT-GAP",
        domain="Data model acceleration",
        scope="both",
        severity="medium",
        evidence="data_models.index_constraint_gaps, data_models.tags_whitelist_gaps, data_models.summary_range_gaps, data_models.acceleration_enforcement_gaps, or data_models.acceleration_storage_gaps is present.",
        source_doc=SOURCE_DOCS["cim_setup"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode inventory --help",
        apply_command="Render data-model constraint/summary-range handoff only; no CIM setup or datamodels.conf change is made.",
        handoff_skill="splunk-enterprise-security-config",
        rollback_or_validation="Verify CIM index allowlists, tag allowlists, summary ranges, enforcement modular input state, and acceleration storage before rerunning.",
        target_impacts={"es": -12, "itsi": -8},
        trigger={
            "any": [
                {"path": "data_models.index_constraint_gaps", "truthy": True},
                {"path": "data_models.tags_whitelist_gaps", "truthy": True},
                {"path": "data_models.summary_range_gaps", "truthy": True},
                {"path": "data_models.acceleration_enforcement_gaps", "truthy": True},
                {"path": "data_models.acceleration_storage_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ES-ASSET-IDENTITY-GAP",
        domain="Enterprise Security readiness",
        scope="both",
        severity="high",
        evidence="es.asset_identity_gaps, es.asset_lookup_empty, or es.identity_lookup_empty is present.",
        source_doc=SOURCE_DOCS["es_assets"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode preview --help",
        apply_command="Render ES asset/identity enrichment handoff only.",
        handoff_skill="splunk-enterprise-security-config,splunk-asset-risk-intelligence-setup",
        rollback_or_validation="Validate get_asset/get_identity macros and rerun this doctor.",
        target_impacts={"es": -18, "ari": -5},
        trigger={
            "any": [
                {"path": "es.asset_identity_gaps", "truthy": True},
                {"path": "es.asset_lookup_empty", "equals": True},
                {"path": "es.identity_lookup_empty", "equals": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ES-CONTENT-ACTION-GAP",
        domain="Enterprise Security readiness",
        scope="both",
        severity="high",
        evidence="ES/SSE content activation evidence shows disabled relevant correlation searches, missing adaptive response actions, stale content mapping, or missing data inventory introspection.",
        source_doc=SOURCE_DOCS["es_correlation_searches"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode inventory --help",
        apply_command="Render ES content/action readiness handoff only.",
        handoff_skill="splunk-enterprise-security-config,splunk-security-essentials-setup",
        rollback_or_validation="Verify selected correlation searches, notable/risk actions, and SSE data inventory/content mapping after remediation.",
        target_impacts={"es": -16},
        trigger={
            "any": [
                {"path": "es.correlation_searches_disabled", "truthy": True},
                {"path": "es.adaptive_response_gaps", "truthy": True},
                {"path": "es.notable_action_disabled", "truthy": True},
                {"path": "es.risk_modifier_gaps", "truthy": True},
                {"path": "es.content_mapping_gaps", "truthy": True},
                {"path": "sse.data_inventory_missing", "equals": True},
                {"path": "sse.content_mapping_stale", "equals": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ES-CONTENT-UPDATE-GAP",
        domain="Enterprise Security readiness",
        scope="both",
        severity="medium",
        evidence="es.security_content_update_missing, es.security_content_update_stale, es.analytic_story_gaps, or es.detection_version_gaps indicates ESCU detection coverage cannot be trusted for this source.",
        source_doc=SOURCE_DOCS["es_security_content_update"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode inventory --help",
        apply_command="Render ES Content Update coverage handoff only.",
        handoff_skill="splunk-enterprise-security-config,splunk-security-essentials-setup",
        rollback_or_validation="Verify ESCU app/version, analytic-story mappings, and relevant detection inventory after remediation.",
        target_impacts={"es": -10},
        trigger={
            "any": [
                {"path": "es.security_content_update_missing", "equals": True},
                {"path": "es.security_content_update_stale", "equals": True},
                {"path": "es.analytic_story_gaps", "truthy": True},
                {"path": "es.detection_version_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ES-DETECTION-GAP",
        domain="Enterprise Security readiness",
        scope="both",
        severity="high",
        evidence="ES detection, risk, notable, or finding-readiness evidence is missing for this source.",
        source_doc=SOURCE_DOCS["es_data_sources"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode inventory --help",
        apply_command="Render ES detection/readiness handoff only.",
        handoff_skill="splunk-enterprise-security-config",
        rollback_or_validation="Validate expected detections and tstats searches after remediation.",
        target_impacts={"es": -20},
        trigger={
            "any": [
                {"path": "es.detection_data_models_missing", "truthy": True},
                {"path": "es.risk_index_missing", "equals": True},
                {"path": "es.notable_index_missing", "equals": True},
                {"path": "es.finding_readiness_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ES-PRODUCT-MISSING",
        domain="Enterprise Security readiness",
        scope="global",
        severity="medium",
        evidence="products.es.installed=false while ES readiness is being scored.",
        source_doc=SOURCE_DOCS["es_data_sources"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-install/scripts/validate.sh --help",
        apply_command="Render ES install/config handoff only.",
        handoff_skill="splunk-enterprise-security-install,splunk-enterprise-security-config",
        rollback_or_validation="Validate ES app presence, CIM, and ES data models before rerunning this doctor.",
        target_impacts={"es": -30},
        trigger={"any": [{"path": "products.es.installed", "equals": False}]},
    ),
    rule(
        rule_id="DSRD-ES-RISK-MODIFIER-GAP",
        domain="Enterprise Security readiness",
        scope="both",
        severity="high",
        evidence="es.risk_modifier_field_gaps, es.risk_object_field_gaps, es.risk_object_type_gaps, es.risk_score_gaps, or es.risk_datamodel_gaps prevents Risk Analysis and risk-based alerting from using this data correctly.",
        source_doc=SOURCE_DOCS["es_risk"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode inventory --help",
        apply_command="Render ES risk-modifier field handoff only.",
        handoff_skill="splunk-enterprise-security-config",
        rollback_or_validation="Verify risk events include risk_score, risk_object, risk_object_type and are visible in the Risk data model.",
        target_impacts={"es": -16},
        trigger={
            "any": [
                {"path": "es.risk_modifier_field_gaps", "truthy": True},
                {"path": "es.risk_object_field_gaps", "truthy": True},
                {"path": "es.risk_object_type_gaps", "truthy": True},
                {"path": "es.risk_score_gaps", "truthy": True},
                {"path": "es.risk_datamodel_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ES-THREAT-INTEL-GAP",
        domain="Enterprise Security readiness",
        scope="both",
        severity="high",
        evidence="es.threat_intel_source_gaps, es.threat_intel_lookup_empty, es.threat_intel_kvstore_gaps, es.threat_match_gaps, or es.observable_field_gaps prevents threat matching or investigation enrichment.",
        source_doc=SOURCE_DOCS["es_threat_intel"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode inventory --help",
        apply_command="Render ES threat-intelligence readiness handoff only.",
        handoff_skill="splunk-enterprise-security-config",
        rollback_or_validation="Verify threat intelligence sources, KV store collections/lookups, threat-matching searches, and observable fields.",
        target_impacts={"es": -16},
        trigger={
            "any": [
                {"path": "es.threat_intel_source_gaps", "truthy": True},
                {"path": "es.threat_intel_lookup_empty", "equals": True},
                {"path": "es.threat_intel_kvstore_gaps", "truthy": True},
                {"path": "es.threat_match_gaps", "truthy": True},
                {"path": "es.observable_field_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-FEDERATED-DATASET-GAP",
        domain="Federated and remote dataset readiness",
        scope="both",
        severity="high",
        evidence="federated provider, federated-index, mode, remote-search, role-mapping, result-shape, or Amazon Security Lake mapping evidence shows the remote dataset is not reliably searchable by ES, ITSI, ARI, or dashboards.",
        source_doc=SOURCE_DOCS["federated_search"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-federated-search-setup/scripts/setup.sh --help",
        apply_command="Render federated-provider/index and remote-dataset handoff only; no provider, role, or federated index is changed.",
        handoff_skill="splunk-federated-search-setup,splunk-enterprise-security-config",
        rollback_or_validation="Run representative federated searches, validate role mappings and provider mode, and verify returned fields satisfy ES/ITSI/ARI content before rerunning.",
        target_impacts={"es": -16, "itsi": -12, "ari": -12},
        trigger={
            "any": [
                {"path": "federated.provider_gaps", "truthy": True},
                {"path": "federated.federated_index_gaps", "truthy": True},
                {"path": "federated.mode_unsupported", "truthy": True},
                {"path": "federated.remote_search_errors", "truthy": True},
                {"path": "federated.role_mapping_gaps", "truthy": True},
                {"path": "federated.zero_results", "truthy": True},
                {"path": "federated.dataset_acceleration_gaps", "truthy": True},
                {"path": "federated.dataset_constraint_gaps", "truthy": True},
                {"path": "federated.amazon_security_lake_mapping_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-HANDOFF-COVERAGE-GAP",
        domain="Handoff and fix routing coverage",
        scope="global",
        severity="medium",
        evidence="handoffs.unrouted or handoffs.manual_only is populated for known readiness gaps.",
        source_doc=SOURCE_DOCS["registry"],
        fix_kind="manual_support",
        preview_command="Review generated handoff routing support packet.",
        apply_command="Render handoff routing packet only.",
        handoff_skill="",
        rollback_or_validation="Add a concrete owning skill or manual runbook, then rerun validation.",
        target_impacts={"es": -5, "itsi": -5, "ari": -5},
        trigger={
            "any": [
                {"path": "handoffs.unrouted", "truthy": True},
                {"path": "handoffs.manual_only", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-INDEX-SOURCETYPE-GAP",
        domain="Indexes sourcetypes and macros",
        scope="both",
        severity="critical",
        evidence="indexes.missing, indexes.unsearchable, sourcetypes.missing, or sourcetypes.unexpected is populated.",
        source_doc=SOURCE_DOCS["es_data_sources"],
        fix_kind="delegated_fix",
        preview_command="Review index/sourcetype handoff and the owning input setup skill.",
        apply_command="Render index/sourcetype handoff only; no index or input is changed.",
        handoff_skill="splunk-hec-service-setup,splunk-app-install,cisco-product-setup",
        rollback_or_validation="Run sample searches by index and sourcetype, then rerun this doctor.",
        target_impacts={"es": -30, "itsi": -25, "ari": -25},
        trigger={
            "any": [
                {"path": "indexes.missing", "truthy": True},
                {"path": "indexes.unsearchable", "truthy": True},
                {"path": "sourcetypes.missing", "truthy": True},
                {"path": "sourcetypes.unexpected", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-INGEST-PIPELINE-FLOW-GAP",
        domain="Ingest pipeline and transport flow",
        scope="both",
        severity="high",
        evidence="ingest pipeline, destination, drop, dead-letter, routing, latency, Edge Processor, Ingest Processor, or metadata-rewrite evidence shows events are not reaching expected indexes/sourcetypes intact.",
        source_doc=SOURCE_DOCS["ingest_monitoring"],
        fix_kind="delegated_fix",
        preview_command="Review generated ingest-monitoring, Edge Processor, Ingest Processor, and HEC destination evidence.",
        apply_command="Render ingest pipeline/destination/routing handoff only; no pipeline, token, destination, or route is changed.",
        handoff_skill="splunk-edge-processor-setup,splunk-hec-service-setup,splunk-cloud-data-manager-setup",
        rollback_or_validation="Verify ingest monitoring latency, destination success, route outcomes, and searchable events by expected index/sourcetype before rerunning.",
        target_impacts={"es": -18, "itsi": -18, "ari": -18},
        trigger={
            "any": [
                {"path": "ingest.pipeline_errors", "truthy": True},
                {"path": "ingest.destination_errors", "truthy": True},
                {"path": "ingest.dropped_events", "truthy": True},
                {"path": "ingest.dead_letter_queue_events", "truthy": True},
                {"path": "ingest.pipeline_inactive", "truthy": True},
                {"path": "ingest.routing_gaps", "truthy": True},
                {"path": "ingest.metadata_rewrite_gaps", "truthy": True},
                {"path": "ingest.edge_processor_errors", "truthy": True},
                {"path": "ingest.ingest_processor_errors", "truthy": True},
                {"path": "ingest.ingest_latency_minutes", "gt": 60},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ITSI-CONTENT-PACK-GAP",
        domain="ITSI readiness",
        scope="both",
        severity="high",
        evidence="itsi.content_packs_missing, itsi.dependencies_missing, or itsi.pack_validation_errors is populated.",
        source_doc=SOURCE_DOCS["itsi_packs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-itsi-config/scripts/setup.sh --help",
        apply_command="Render ITSI content-pack handoff only.",
        handoff_skill="splunk-itsi-config,splunk-itsi-setup",
        rollback_or_validation="Validate the installed content pack and rerun this doctor.",
        target_impacts={"itsi": -24},
        trigger={
            "any": [
                {"path": "itsi.content_packs_missing", "truthy": True},
                {"path": "itsi.dependencies_missing", "truthy": True},
                {"path": "itsi.pack_validation_errors", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ITSI-ENTITY-KPI-GAP",
        domain="ITSI readiness",
        scope="both",
        severity="high",
        evidence="ITSI entity discovery, macro, service import, KPI base search, or KPI data evidence is missing.",
        source_doc=SOURCE_DOCS["itsi_entity"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-itsi-config/scripts/setup.sh --help",
        apply_command="Render ITSI entity/KPI handoff only.",
        handoff_skill="splunk-itsi-config",
        rollback_or_validation="Validate entity discovery and KPI searches after remediation.",
        target_impacts={"itsi": -26},
        trigger={
            "any": [
                {"path": "itsi.entity_discovery_disabled", "truthy": True},
                {"path": "itsi.entity_discovery_zero_results", "truthy": True},
                {"path": "itsi.kpi_base_searches_missing", "truthy": True},
                {"path": "itsi.kpi_search_zero_results", "truthy": True},
                {"path": "itsi.macro_gaps", "truthy": True},
                {"path": "itsi.service_import_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ITSI-EVENT-ANALYTICS-GAP",
        domain="ITSI readiness",
        scope="both",
        severity="high",
        evidence="itsi.event_analytics_gaps, itsi.aggregation_policy_gaps, itsi.episode_split_field_gaps, itsi.episode_breaking_gaps, itsi.itsi_tracked_alerts_gaps, or itsi.episode_severity_gaps prevents ITSI Event Analytics from grouping usable episodes.",
        source_doc=SOURCE_DOCS["itsi_event_analytics"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-itsi-config/scripts/setup.sh --help",
        apply_command="Render ITSI Event Analytics aggregation-policy handoff only.",
        handoff_skill="splunk-itsi-config",
        rollback_or_validation="Verify notable events enter ITSI, match aggregation policies, split on useful fields, and form episodes with expected severity/status.",
        target_impacts={"itsi": -20},
        trigger={
            "any": [
                {"path": "itsi.event_analytics_gaps", "truthy": True},
                {"path": "itsi.aggregation_policy_gaps", "truthy": True},
                {"path": "itsi.episode_split_field_gaps", "truthy": True},
                {"path": "itsi.episode_breaking_gaps", "truthy": True},
                {"path": "itsi.itsi_tracked_alerts_gaps", "truthy": True},
                {"path": "itsi.episode_severity_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ITSI-KPI-THRESHOLD-GAP",
        domain="ITSI readiness",
        scope="both",
        severity="high",
        evidence="itsi.threshold_gaps, itsi.entity_split_field_gaps, itsi.service_template_gaps, itsi.kpi_runtime_gaps, or adaptive-threshold training gaps show KPI data is not operationally usable.",
        source_doc=SOURCE_DOCS["itsi_kpi"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-itsi-config/scripts/setup.sh --help",
        apply_command="Render ITSI KPI threshold/entity-split/runtime handoff only.",
        handoff_skill="splunk-itsi-config",
        rollback_or_validation="Validate KPI base search runtime, entity split/filter fields, threshold policies, and service-template propagation.",
        target_impacts={"itsi": -18},
        trigger={
            "any": [
                {"path": "itsi.threshold_gaps", "truthy": True},
                {"path": "itsi.entity_split_field_gaps", "truthy": True},
                {"path": "itsi.pseudo_entity_gaps", "truthy": True},
                {"path": "itsi.service_template_gaps", "truthy": True},
                {"path": "itsi.kpi_runtime_gaps", "truthy": True},
                {"path": "itsi.kpi_importance_gaps", "truthy": True},
                {"path": "itsi.adaptive_threshold_training_gaps", "truthy": True},
                {"path": "itsi.kpi_backfill_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-ITSI-SUMMARY-INDEX-GAP",
        domain="ITSI readiness",
        scope="both",
        severity="high",
        evidence="itsi summary-index, metrics-summary, service-health-score, or KPI summary evidence is missing or not searchable, so Service Analyzer and historical KPI views cannot prove usable data.",
        source_doc=SOURCE_DOCS["itsi_summary"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-itsi-config/scripts/setup.sh --help",
        apply_command="Render ITSI summary-index/KPI summary handoff only; no index, KPI, or backfill mutation is performed.",
        handoff_skill="splunk-itsi-config,splunk-itsi-setup",
        rollback_or_validation="Verify index=itsi_summary, index=itsi_summary_metrics, and service health score searches return recent records for the source.",
        target_impacts={"itsi": -18},
        trigger={
            "any": [
                {"path": "itsi.summary_index_gaps", "truthy": True},
                {"path": "itsi.summary_metrics_gaps", "truthy": True},
                {"path": "itsi.service_health_score_gaps", "truthy": True},
                {"path": "itsi.kpi_summary_zero_results", "truthy": True},
                {"path": "itsi.itsi_summary_access_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-KNOWLEDGE-ENRICHMENT-GAP",
        domain="Knowledge object enrichment",
        scope="both",
        severity="high",
        evidence="knowledge or lookup evidence shows automatic lookups, lookup definitions/tables, field aliases, calculated fields, KV Store collections, permissions, or search-time order are not enriching representative events.",
        source_doc=SOURCE_DOCS["automatic_lookups"],
        fix_kind="delegated_fix",
        preview_command="Review generated lookup, field-alias, calculated-field, KV Store, and search-time enrichment evidence.",
        apply_command="Render knowledge-object enrichment handoff only; no lookup, props, transforms, KV Store, or ACL change is made.",
        handoff_skill="splunk-enterprise-security-config,splunk-itsi-config,splunk-asset-risk-intelligence-setup,splunk-app-install",
        rollback_or_validation="Run representative searches after search-time operations and verify lookup-backed, alias-backed, calculated, and KV Store fields appear with expected values.",
        target_impacts={"es": -14, "itsi": -12, "ari": -14},
        trigger={
            "any": [
                {"path": "knowledge.automatic_lookup_gaps", "truthy": True},
                {"path": "knowledge.lookup_definition_gaps", "truthy": True},
                {"path": "knowledge.lookup_table_empty", "truthy": True},
                {"path": "knowledge.lookup_staleness_gaps", "truthy": True},
                {"path": "knowledge.lookup_permission_gaps", "truthy": True},
                {"path": "knowledge.field_alias_gaps", "truthy": True},
                {"path": "knowledge.calculated_field_errors", "truthy": True},
                {"path": "knowledge.search_time_order_gaps", "truthy": True},
                {"path": "knowledge.kvstore_collection_gaps", "truthy": True},
                {"path": "lookups.automatic_lookup_gaps", "truthy": True},
                {"path": "lookups.lookup_definition_gaps", "truthy": True},
                {"path": "lookups.lookup_table_empty", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-METRICS-READINESS-GAP",
        domain="Metrics indexes and dimensions",
        scope="both",
        severity="high",
        evidence="metrics.indexes_missing, metrics.metric_names_missing, metrics.dimensions_missing, metrics.mstats_zero_results, metrics.default_metrics_index_gaps, metrics.case_sensitivity_gaps, metrics.high_cardinality_dimensions, or metrics.field_filter_gaps prevents metrics-backed ITSI KPIs and dashboards from returning reliable data.",
        source_doc=SOURCE_DOCS["metrics_mstats"],
        fix_kind="delegated_fix",
        preview_command="Review generated mstats/mpreview evidence and the owning metrics or ITSI setup skill.",
        apply_command="Render metrics-readiness handoff only.",
        handoff_skill="splunk-itsi-config,splunk-observability-otel-collector-setup,splunk-app-install",
        rollback_or_validation="Verify mpreview/mstats return expected metric_name and dimension values from the target metrics indexes.",
        target_impacts={"itsi": -18},
        trigger={
            "any": [
                {"path": "metrics.indexes_missing", "truthy": True},
                {"path": "metrics.metric_names_missing", "truthy": True},
                {"path": "metrics.dimensions_missing", "truthy": True},
                {"path": "metrics.mstats_zero_results", "equals": True},
                {"path": "metrics.default_metrics_index_gaps", "truthy": True},
                {"path": "metrics.case_sensitivity_gaps", "truthy": True},
                {"path": "metrics.high_cardinality_dimensions", "truthy": True},
                {"path": "metrics.field_filter_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-OCSF-ADDON-GAP",
        domain="OCSF to CIM bridging",
        scope="both",
        severity="high",
        evidence="ocsf.required=true but ocsf.addon_installed=false.",
        source_doc=SOURCE_DOCS["ocsf_install"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-app-install/scripts/install_app.sh --help",
        apply_command="Render OCSF-CIM add-on install handoff for Splunkbase app 6841 only.",
        handoff_skill="splunk-app-install,splunk-enterprise-security-config",
        rollback_or_validation="Verify OCSF-CIM add-on on search heads and rerun OCSF-to-CIM sample checks.",
        target_impacts={"es": -18, "itsi": -8},
        trigger={
            "all": [
                {"path": "ocsf.required", "equals": True},
                {"path": "ocsf.addon_installed", "equals": False},
            ]
        },
    ),
    rule(
        rule_id="DSRD-OCSF-MAPPING-GAP",
        domain="OCSF to CIM bridging",
        scope="both",
        severity="high",
        evidence="ocsf.missing_transforms, ocsf.unsupported_classes, ocsf.mapping_errors, or ocsf.mapped_to_cim=false is present.",
        source_doc=SOURCE_DOCS["ocsf_overview"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode preview --help",
        apply_command="Render OCSF transform/CIM mapping handoff only.",
        handoff_skill="splunk-enterprise-security-config,splunk-app-install",
        rollback_or_validation="Verify OCSF class mappings and CIM data model visibility.",
        target_impacts={"es": -22, "itsi": -8},
        trigger={
            "any": [
                {"path": "ocsf.missing_transforms", "truthy": True},
                {"path": "ocsf.unsupported_classes", "truthy": True},
                {"path": "ocsf.mapping_errors", "truthy": True},
                {"path": "ocsf.mapped_to_cim", "equals": False},
            ]
        },
    ),
    rule(
        rule_id="DSRD-OCSF-SOURCETYPE-CONFIG-GAP",
        domain="OCSF to CIM bridging",
        scope="both",
        severity="high",
        evidence="ocsf.unprefixed_sourcetypes, ocsf.unconfigured_sourcetypes, ocsf.timestamp_extraction_gaps, ocsf.props_conf_gaps, or ocsf.conversion_failures prevents OCSF events from receiving the OCSF-CIM add-on field extractions and timestamp handling.",
        source_doc=SOURCE_DOCS["ocsf_config"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-security-config/scripts/setup.sh --mode preview --help",
        apply_command="Render OCSF sourcetype/setup/timestamp handoff only.",
        handoff_skill="splunk-enterprise-security-config,splunk-app-install",
        rollback_or_validation="Verify ocsf:-prefixed sourcetypes are configured in the OCSF-CIM add-on and produce CIM-visible fields.",
        target_impacts={"es": -20, "itsi": -8},
        trigger={
            "any": [
                {"path": "ocsf.unprefixed_sourcetypes", "truthy": True},
                {"path": "ocsf.unconfigured_sourcetypes", "truthy": True},
                {"path": "ocsf.timestamp_extraction_gaps", "truthy": True},
                {"path": "ocsf.props_conf_gaps", "truthy": True},
                {"path": "ocsf.conversion_failures", "truthy": True},
                {"path": "ocsf.application_error_events", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-PARSER-QUALITY-GAP",
        domain="Parser and event quality",
        scope="both",
        severity="medium",
        evidence="parser timestamp, line-breaking, extraction, truncation, host, source, or null-queue problems are present.",
        source_doc=SOURCE_DOCS["es_data_sources"],
        fix_kind="delegated_fix",
        preview_command="Review parser quality handoff and owning TA/product skill.",
        apply_command="Render parser quality handoff only.",
        handoff_skill="splunk-app-install,cisco-product-setup,splunk-connect-for-syslog-setup,splunk-connect-for-snmp-setup",
        rollback_or_validation="Run raw sample searches and fieldsummary after parser remediation.",
        target_impacts={"es": -12, "itsi": -10, "ari": -10},
        trigger={
            "any": [
                {"path": "parser.timestamp_skew_minutes", "gt": 10},
                {"path": "parser.line_breaking_errors", "truthy": True},
                {"path": "parser.extraction_errors", "truthy": True},
                {"path": "parser.truncation", "equals": True},
                {"path": "parser.host_source_gaps", "truthy": True},
                {"path": "parser.null_queue_drops", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-REGISTRY-CONTRACT-GAP",
        domain="Registry and source identity",
        scope="data_source",
        severity="medium",
        evidence="registry.resolved=false or registry.expected_contract_missing=true for a data source.",
        source_doc=SOURCE_DOCS["registry"],
        fix_kind="direct_fix",
        preview_command="Review app_registry.json, the owning skill, and explicit expected index/sourcetype/macro/CIM contract.",
        apply_command="Render local contract checklist only; no registry or Splunk config is changed.",
        handoff_skill="",
        rollback_or_validation="Add explicit evidence contract or registry mapping, then rerun this doctor.",
        target_impacts={"es": -8, "itsi": -8, "ari": -8},
        trigger={
            "any": [
                {"path": "registry.resolved", "equals": False},
                {"path": "registry.expected_contract_missing", "equals": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-RETENTION-LOOKBACK-GAP",
        domain="Retention and historical lookback",
        scope="both",
        severity="high",
        evidence="retention, index aging, archive/searchability, raw-history, data model summary, ITSI backfill, ARI last-detect, or dashboard lookback evidence shows historical data is shorter than product content requires.",
        source_doc=SOURCE_DOCS["index_storage"],
        fix_kind="delegated_fix",
        preview_command="Review index retention, bucket aging, data model summary range, ITSI backfill, ARI last-detect, and dashboard lookback evidence.",
        apply_command="Render retention/lookback handoff only; no index, SmartStore, archive, summary, or backfill setting is changed.",
        handoff_skill="splunk-admin-doctor,splunk-index-lifecycle-smartstore-setup,splunk-enterprise-security-config,splunk-itsi-config,splunk-asset-risk-intelligence-setup",
        rollback_or_validation="Verify source indexes retain searchable raw data for the longest required ES/ITSI/ARI/dashboard lookback and that summaries/backfills cover the same window.",
        target_impacts={"es": -14, "itsi": -14, "ari": -12},
        trigger={
            "any": [
                {"path": "retention.lookback_gaps", "truthy": True},
                {"path": "retention.raw_history_gaps", "truthy": True},
                {"path": "retention.archive_unsearchable_gaps", "truthy": True},
                {"path": "retention.frozen_time_too_short", "truthy": True},
                {"path": "retention.bucket_aging_gaps", "truthy": True},
                {"path": "indexes.retention_gaps", "truthy": True},
                {"path": "indexes.frozen_time_too_short", "truthy": True},
                {"path": "indexes.archive_unsearchable_gaps", "truthy": True},
                {"path": "data_models.summary_range_shorter_than_detection", "truthy": True},
                {"path": "itsi.backfill_period_gaps", "truthy": True},
                {"path": "ari.lastdetect_history_gaps", "truthy": True},
                {"path": "dashboards.time_range_retention_gaps", "truthy": True},
                {"path": "sample_events.history_depth_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-SAMPLE-FRESHNESS-GAP",
        domain="Sample freshness and volume",
        scope="both",
        severity="high",
        evidence="sample_events.count is zero or sample_events.latest_age_minutes/stale_minutes exceeds the readiness window.",
        source_doc=SOURCE_DOCS["es_data_sources"],
        fix_kind="delegated_fix",
        preview_command="Review sample-event collection search and owning input setup skill.",
        apply_command="Render sample freshness handoff only.",
        handoff_skill="splunk-hec-service-setup,cisco-product-setup,splunk-app-install,splunk-connect-for-syslog-setup,splunk-connect-for-snmp-setup",
        rollback_or_validation="Run the generated sample-event SPL and verify fresh events exist.",
        target_impacts={"es": -20, "itsi": -18, "ari": -18},
        trigger={
            "any": [
                {"path": "sample_events.count", "equals": 0},
                {"path": "sample_events.latest_age_minutes", "gt": 1440},
                {"path": "sample_events.stale_minutes", "gt": 1440},
            ]
        },
    ),
    rule(
        rule_id="DSRD-SAMPLE-VOLUME-BASELINE-GAP",
        domain="Sample freshness and volume",
        scope="both",
        severity="high",
        evidence="sample_events volume-baseline, expected-count, ingest-latency, late-arrival, or duplicate-rate evidence shows the source is present but not statistically usable by detections, KPIs, ARI processing, or dashboards.",
        source_doc=SOURCE_DOCS["ingest_latency"],
        fix_kind="delegated_fix",
        preview_command="Review sample distribution, ingest latency, duplicate, and baseline evidence with the owning input or collector skill.",
        apply_command="Render volume/baseline readiness handoff only; no input, index, retention, or scheduler setting is changed.",
        handoff_skill="splunk-admin-doctor,cisco-product-setup,splunk-hec-service-setup,splunk-connect-for-syslog-setup,splunk-connect-for-snmp-setup",
        rollback_or_validation="Compare 24-hour, 7-day, and detection/KPI lookback counts against expected baselines, then rerun this doctor.",
        target_impacts={"es": -16, "itsi": -16, "ari": -16},
        trigger={
            "any": [
                {"path": "sample_events.volume_below_baseline", "truthy": True},
                {"path": "sample_events.expected_count_gap", "truthy": True},
                {"path": "sample_events.ingest_latency_minutes", "gt": 60},
                {"path": "sample_events.late_arriving_events", "truthy": True},
                {"path": "sample_events.duplicate_rate_pct", "gt": 5},
            ]
        },
    ),
    rule(
        rule_id="DSRD-SCHEDULED-CONTENT-EXECUTION-GAP",
        domain="Scheduled content execution",
        scope="both",
        severity="high",
        evidence="scheduled_searches, scheduler, ES correlation, ITSI KPI, ARI event-search, or dashboard saved-search execution evidence shows skipped, failed, stale, queued, quota-blocked, or lagging product content.",
        source_doc=SOURCE_DOCS["es_correlation_scheduling"],
        fix_kind="delegated_fix",
        preview_command="Review scheduler.log, saved-search dispatch, correlation-search, KPI, ARI, and dashboard saved-search execution evidence.",
        apply_command="Render scheduled-content execution handoff only; no schedule, quota, search, or concurrency setting is changed.",
        handoff_skill="splunk-admin-doctor,splunk-enterprise-security-config,splunk-itsi-config,splunk-asset-risk-intelligence-setup",
        rollback_or_validation="Verify required scheduled content ran successfully inside its lookback window with no skipped searches or stale dashboard saved-search results, then rerun this doctor.",
        target_impacts={"es": -14, "itsi": -14, "ari": -10},
        trigger={
            "any": [
                {"path": "scheduled_searches.skipped", "truthy": True},
                {"path": "scheduled_searches.failed", "truthy": True},
                {"path": "scheduled_searches.latest_run_stale", "truthy": True},
                {"path": "scheduled_searches.runtime_exceeded", "truthy": True},
                {"path": "scheduled_searches.concurrency_queued", "truthy": True},
                {"path": "scheduled_searches.schedule_window_gaps", "truthy": True},
                {"path": "scheduler.skipped_searches", "truthy": True},
                {"path": "scheduler.dispatch_errors", "truthy": True},
                {"path": "scheduler.quota_gaps", "truthy": True},
                {"path": "es.correlation_search_skips", "truthy": True},
                {"path": "es.correlation_search_lag_gaps", "truthy": True},
                {"path": "itsi.kpi_scheduler_skips", "truthy": True},
                {"path": "ari.event_search_schedule_gaps", "truthy": True},
                {"path": "dashboards.saved_search_staleness_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="DSRD-SEARCH-RBAC-GAP",
        domain="Search access and RBAC",
        scope="both",
        severity="high",
        evidence="rbac.search_denied, rbac.missing_indexes, rbac.missing_roles, or rbac.knowledge_object_acl_gaps is present.",
        source_doc=SOURCE_DOCS["es_data_sources"],
        fix_kind="diagnose_only",
        preview_command="Review RBAC/index permission evidence and map changes to the owning platform/security workflow.",
        apply_command="No role, ACL, or user mutation in v1.",
        handoff_skill="",
        rollback_or_validation="Verify required roles can search the target indexes and knowledge objects.",
        target_impacts={"es": -18, "itsi": -18, "ari": -18},
        trigger={
            "any": [
                {"path": "rbac.search_denied", "equals": True},
                {"path": "rbac.missing_indexes", "truthy": True},
                {"path": "rbac.missing_roles", "truthy": True},
                {"path": "rbac.knowledge_object_acl_gaps", "truthy": True},
            ]
        },
    ),
]


SECRET_KEY_RE = re.compile(
    r"(^|_)(password|passwd|pass|secret|api[_-]?key|api[_-]?token|token[_-]?value|"
    r"access[_-]?token|refresh[_-]?token|bearer|authorization|session[_-]?key|"
    r"hec[_-]?token|client[_-]?secret|private[_-]?key)($|_)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(Bearer\s+[A-Za-z0-9._~+/-]+|splunkd_[A-Za-z0-9._-]+|SUPER_SECRET|"
    r"VERY_SECRET|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]+)",
    re.IGNORECASE,
)
DIRECT_DANGEROUS_RE = re.compile(
    r"\b(restart|delete|remove|rm\s+-|cluster|maintenance|offline|rotate|cert|"
    r"license\s+install|outputlookup|collect|mcollect|rebuild|enable|disable)\b",
    re.IGNORECASE,
)
LIVE_COLLECTOR_BLOCKED_SPL_RE = re.compile(
    r"\b(collect|mcollect|outputlookup|delete|sendemail|script)\b",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"\b[a-z][a-z0-9_:-]{2,}\b", re.IGNORECASE)
GENERIC_SOURCE_PACK_DOC_URLS = {
    "https://research.splunk.com/sources/",
    "https://help.splunk.com/en/splunk-enterprise-security-8/install/8.3/planning/data-source-planning-for-splunk-enterprise-security",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Splunk data-source readiness doctor.")
    parser.add_argument(
        "--phase",
        choices=("doctor", "fix-plan", "apply", "validate", "status", "source-packs", "collect", "synthesize"),
        default="doctor",
    )
    parser.add_argument("--platform", choices=("auto", "cloud", "enterprise"), default="auto")
    parser.add_argument("--targets", default=",".join(DEFAULT_TARGETS), help="Comma-separated targets: es,itsi,ari.")
    parser.add_argument("--target-search-head", default="")
    parser.add_argument("--splunk-uri", default="")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--evidence-file", default="")
    parser.add_argument("--collector-results-file", default="")
    parser.add_argument("--registry-file", default=str(DEFAULT_REGISTRY_FILE))
    parser.add_argument("--source-packs-file", default=str(DEFAULT_SOURCE_PACKS_FILE))
    parser.add_argument("--source-pack", default="", help="Optional comma-separated source-pack IDs to use.")
    parser.add_argument("--session-key-file", default="", help="Local file containing a Splunk session key for --phase collect.")
    parser.add_argument("--no-verify-tls", action="store_true", help="Disable TLS certificate verification for live collection.")
    parser.add_argument("--max-rows", type=int, default=50, help="Maximum rows requested per live collector search.")
    parser.add_argument("--max-searches", type=int, default=25, help="Maximum collector searches to execute during --phase collect.")
    parser.add_argument("--collect-timeout-seconds", type=int, default=60)
    parser.add_argument("--fixes", default="", help="Comma-separated finding IDs to packetize during --phase apply.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def die(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def json_dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def safe_rel_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return cleaned or "item"


def shell_join(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def parse_targets(value: str) -> list[str]:
    targets = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not targets:
        return list(DEFAULT_TARGETS)
    invalid = sorted(set(targets) - ALL_TARGETS)
    if invalid:
        die(f"Invalid --targets values: {', '.join(invalid)}")
    return targets


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"JSON file does not exist: {path}")
    except json.JSONDecodeError as exc:
        die(f"JSON file is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        die("JSON root must be an object.")
    return payload


def get_path(payload: dict[str, Any], dotted: str) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def normalize_status(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    return value


def compare_gt(actual: Any, threshold: Any) -> bool:
    try:
        return float(actual) > float(threshold)
    except (TypeError, ValueError):
        return False


def predicate_matches(predicate: dict[str, Any], evidence: dict[str, Any]) -> bool:
    actual = get_path(evidence, str(predicate["path"]))
    if "equals" in predicate:
        return actual == predicate["equals"]
    if "truthy" in predicate:
        return bool(actual) is bool(predicate["truthy"])
    if "gt" in predicate:
        return compare_gt(actual, predicate["gt"])
    if "in" in predicate:
        normalized = normalize_status(actual)
        expected = {normalize_status(item) for item in predicate["in"]}
        return normalized in expected
    if "not_in" in predicate:
        normalized = normalize_status(actual)
        expected = {normalize_status(item) for item in predicate["not_in"]}
        return normalized not in expected
    return False


def trigger_matches(trigger: dict[str, Any], evidence: dict[str, Any]) -> bool:
    any_predicates = trigger.get("any")
    if any_predicates:
        return any(predicate_matches(predicate, evidence) for predicate in any_predicates)
    all_predicates = trigger.get("all")
    if all_predicates:
        return all(predicate_matches(predicate, evidence) for predicate in all_predicates)
    return False


def manifest_domains() -> set[str]:
    return {entry["domain"] for entry in COVERAGE_MANIFEST}


def validate_catalog() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    domains = manifest_domains()
    seen_ids: set[str] = set()

    if [item["id"] for item in RULE_CATALOG] != sorted(item["id"] for item in RULE_CATALOG):
        errors.append("RULE_CATALOG must stay sorted by stable rule id.")

    for item in RULE_CATALOG:
        rule_id = str(item.get("id", ""))
        missing = sorted(REQUIRED_RULE_FIELDS - set(item))
        if missing:
            errors.append(f"{rule_id or '<unknown>'}: missing fields: {', '.join(missing)}")
        if rule_id in seen_ids:
            errors.append(f"duplicate rule id: {rule_id}")
        seen_ids.add(rule_id)
        if item.get("domain") not in domains:
            errors.append(f"{rule_id}: unknown domain {item.get('domain')!r}")
        if item.get("scope") not in {"global", "data_source", "both"}:
            errors.append(f"{rule_id}: invalid scope {item.get('scope')!r}")
        if item.get("severity") not in SEVERITY_RANK:
            errors.append(f"{rule_id}: invalid severity {item.get('severity')!r}")
        if item.get("fix_kind") not in FIX_KINDS:
            errors.append(f"{rule_id}: invalid fix_kind {item.get('fix_kind')!r}")
        if item.get("fix_kind") == "delegated_fix" and not str(item.get("handoff_skill", "")).strip():
            errors.append(f"{rule_id}: delegated_fix rules must declare handoff_skill")
        if item.get("fix_kind") == "direct_fix" and DIRECT_DANGEROUS_RE.search(str(item.get("apply_command", ""))):
            errors.append(f"{rule_id}: direct_fix apply_command contains a blocked disruptive action")
        if not item.get("trigger"):
            errors.append(f"{rule_id}: missing trigger")
        impacts = item.get("target_impacts", {})
        if not isinstance(impacts, dict) or not impacts:
            errors.append(f"{rule_id}: target_impacts must be a non-empty mapping")
        for target, impact in impacts.items():
            if target not in ALL_TARGETS:
                errors.append(f"{rule_id}: invalid target impact {target!r}")
            if not isinstance(impact, int) or impact > 0:
                errors.append(f"{rule_id}: target impact for {target} must be a non-positive integer")

    for manifest in COVERAGE_MANIFEST:
        domain = manifest["domain"]
        domain_rules = [item for item in RULE_CATALOG if item["domain"] == domain]
        if not domain_rules:
            errors.append(f"{domain}: no catalog rule covers this domain")
        for target in manifest["targets"]:
            if target not in ALL_TARGETS:
                errors.append(f"{domain}: invalid target {target}")
            if not any(target in item.get("target_impacts", {}) for item in domain_rules):
                errors.append(f"{domain}: no rule impacts target {target}")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "rule_count": len(RULE_CATALOG),
        "domain_count": len(COVERAGE_MANIFEST),
    }


def redact(value: Any, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            if SECRET_KEY_RE.search(str(key)):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact(child, str(key))
        return redacted
    if isinstance(value, list):
        return [redact(item, parent_key) for item in value]
    if isinstance(value, str):
        if SECRET_VALUE_RE.search(value):
            return "[REDACTED]"
        if len(value) > 48 and re.fullmatch(r"[A-Za-z0-9+/=_:.-]+", value):
            return "[REDACTED]"
    return value


def detect_platform(requested: str, evidence: dict[str, Any]) -> str:
    if requested in {"cloud", "enterprise"}:
        return requested
    declared = str(evidence.get("platform", "")).lower()
    if declared in {"cloud", "enterprise"}:
        return declared
    if evidence.get("acs") or evidence.get("subscription"):
        return "cloud"
    return "enterprise"


def token_set(values: Any) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, str):
        return {values}
    if isinstance(values, list):
        return {str(item) for item in values if str(item).strip()}
    return set()


def infer_contract_tokens(*texts: str) -> dict[str, list[str]]:
    combined = " ".join(text for text in texts if text)
    tokens = set(TOKEN_RE.findall(combined))
    index_markers = ("index", "indexes", "summary", "risk", "notable", "ari", "saa", "victorops")
    indexes = sorted(
        token
        for token in tokens
        if "_" in token and any(marker in token.lower() for marker in index_markers)
    )
    macros = sorted(
        token
        for token in tokens
        if token.endswith("_index") or token.endswith("_indexes") or token.endswith("-indexes")
    )
    sourcetypes = sorted(token for token in tokens if ":" in token)
    return {"indexes": indexes, "macros": macros, "sourcetypes": sourcetypes}


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"apps": [], "skill_topologies": [], "documentation": {"cloud_matrix_rows": []}}
    return load_json_file(path)


def json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def csv_items(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def validate_source_packs_payload(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    packs = payload.get("packs", [])
    if not isinstance(packs, list):
        errors.append("source_packs.packs must be a list")
        packs = []

    seen: set[str] = set()
    for index, pack in enumerate(packs, start=1):
        if not isinstance(pack, dict):
            errors.append(f"packs[{index}] must be an object")
            continue
        pack_id = str(pack.get("id", ""))
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", pack_id):
            errors.append(f"packs[{index}] has invalid id {pack_id!r}")
        if pack_id in seen:
            errors.append(f"duplicate source pack id: {pack_id}")
        seen.add(pack_id)
        if not pack.get("label"):
            errors.append(f"{pack_id or f'packs[{index}]'}: missing label")
        match = pack.get("match", {})
        if not isinstance(match, dict) or not any(match.get(key) for key in match):
            errors.append(f"{pack_id}: match must declare at least one non-empty matcher")
        defaults = pack.get("defaults", {})
        if not isinstance(defaults, dict) or not defaults:
            warnings.append(f"{pack_id}: no default evidence contract declared")
        if isinstance(match, dict) and isinstance(defaults, dict):
            match_sourcetypes = {str(item) for item in match.get("sourcetypes", []) if str(item).strip()}
            default_sourcetypes = {str(item) for item in defaults.get("expected_sourcetypes", []) if str(item).strip()}
            pair_sourcetypes = {
                str(item.get("sourcetype", ""))
                for item in match.get("source_sourcetype_pairs", [])
                if isinstance(item, dict) and str(item.get("sourcetype", "")).strip()
            }
            extra_match_sourcetypes = sorted(match_sourcetypes - default_sourcetypes)
            if extra_match_sourcetypes:
                errors.append(
                    f"{pack_id}: match.sourcetypes must be included in defaults.expected_sourcetypes: "
                    + ", ".join(extra_match_sourcetypes)
                )
            extra_pair_sourcetypes = sorted(pair_sourcetypes - default_sourcetypes)
            if extra_pair_sourcetypes:
                errors.append(
                    f"{pack_id}: source_sourcetype_pairs sourcetypes must be included in defaults.expected_sourcetypes: "
                    + ", ".join(extra_pair_sourcetypes)
                )
            unmatchable_defaults = sorted(default_sourcetypes - match_sourcetypes - pair_sourcetypes)
            if unmatchable_defaults:
                errors.append(
                    f"{pack_id}: defaults.expected_sourcetypes must be auto-matchable by match.sourcetypes or source_sourcetype_pairs: "
                    + ", ".join(unmatchable_defaults)
                )
            ari_profile = defaults.get("ari.processing_profile")
            if ari_profile and not defaults.get("ari.expected_processing_types"):
                errors.append(f"{pack_id}: ari.processing_profile requires ari.expected_processing_types")
            if isinstance(ari_profile, dict) and defaults.get("ari.expected_processing_types"):
                profile_types = {str(item) for item in ari_profile.get("processing_types", []) if str(item).strip()}
                expected_types = {str(item) for item in defaults.get("ari.expected_processing_types", []) if str(item).strip()}
                if profile_types != expected_types:
                    errors.append(f"{pack_id}: ari.processing_profile.processing_types must match ari.expected_processing_types")
            itsi_profile = defaults.get("itsi.content_pack_profile")
            if itsi_profile and not defaults.get("itsi.expected_content_packs"):
                errors.append(f"{pack_id}: itsi.content_pack_profile requires itsi.expected_content_packs")
        docs = pack.get("docs", [])
        if docs is not None and (
            not isinstance(docs, list)
            or any(not isinstance(item, str) or not item.startswith(("https://", "http://")) for item in docs)
        ):
            errors.append(f"{pack_id}: docs must be a list of URLs")
        if isinstance(docs, list):
            generic_docs = sorted(str(item) for item in docs if str(item) in GENERIC_SOURCE_PACK_DOC_URLS)
            if generic_docs:
                errors.append(f"{pack_id}: docs must use source-specific anchors, not generic URLs: {', '.join(generic_docs)}")
        match_pairs = match.get("source_sourcetype_pairs", []) if isinstance(match, dict) else []
        if match_pairs is not None:
            if not isinstance(match_pairs, list):
                errors.append(f"{pack_id}: source_sourcetype_pairs must be a list")
            else:
                for pair in match_pairs:
                    if (
                        not isinstance(pair, dict)
                        or not str(pair.get("source", "")).strip()
                        or not str(pair.get("sourcetype", "")).strip()
                    ):
                        errors.append(f"{pack_id}: every source_sourcetype_pairs item needs source and sourcetype")
        searches = pack.get("collection_searches", [])
        if searches is not None:
            if not isinstance(searches, list):
                errors.append(f"{pack_id}: collection_searches must be a list")
            else:
                for search in searches:
                    if not isinstance(search, dict) or not search.get("id") or not search.get("spl"):
                        errors.append(f"{pack_id}: every collection search needs id and spl")
                    elif LIVE_COLLECTOR_BLOCKED_SPL_RE.search(str(search.get("spl", ""))):
                        errors.append(f"{pack_id}: collection search {search.get('id')} contains a blocked SPL command")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "source_pack_count": len(packs),
    }


def load_source_packs(path: Path) -> dict[str, Any]:
    if not path.exists():
        die(f"Source packs file does not exist: {path}")
    payload = load_json_file(path)
    validation = validate_source_packs_payload(payload)
    if not validation["ok"]:
        die("Source pack validation failed: " + "; ".join(validation["errors"]))
    return payload


def source_pack_ids(value: str) -> set[str]:
    return {item.lower() for item in csv_items(value)}


def source_pack_index(source_packs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(pack["id"]).lower(): pack
        for pack in source_packs.get("packs", [])
        if isinstance(pack, dict) and pack.get("id")
    }


def build_registry_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for app in registry.get("apps", []):
        if not isinstance(app, dict):
            continue
        text = " ".join(
            str(app.get(key, ""))
            for key in ("label", "app_name", "skill", "cloud_config_path", "notes")
        )
        inferred = infer_contract_tokens(text)
        projection = {
            "kind": "app",
            "app_name": app.get("app_name", ""),
            "skill": app.get("skill", ""),
            "splunkbase_id": str(app.get("splunkbase_id", "")),
            "label": app.get("label", ""),
            "role_support": app.get("role_support", {}),
            "capabilities": app.get("capabilities", {}),
            "inferred_contract": inferred,
        }
        for key in (
            app.get("app_name"),
            app.get("skill"),
            app.get("label"),
            str(app.get("splunkbase_id", "")),
        ):
            if key:
                index[str(key).lower()] = projection

    for topology in registry.get("skill_topologies", []):
        if not isinstance(topology, dict):
            continue
        skill = str(topology.get("skill", ""))
        if not skill:
            continue
        index.setdefault(
            skill.lower(),
            {
                "kind": "workflow",
                "app_name": "",
                "skill": skill,
                "splunkbase_id": "N/A",
                "label": f"`{skill}`",
                "role_support": topology.get("role_support", {}),
                "capabilities": {},
                "inferred_contract": infer_contract_tokens(str(topology.get("notes", ""))),
            },
        )
    return index


CONTRACT_PATHS = (
    "expected_indexes",
    "expected_sources",
    "expected_sourcetypes",
    "expected_macros",
    "indexes.expected",
    "sources.expected",
    "sourcetypes.expected",
    "macros.expected",
    "cim.expected_models",
    "cim.required_fields",
    "itsi.expected_content_packs",
    "itsi.expected_entity_searches",
    "ari.expected_processing_types",
    "ari.expected_data_sources",
    "dashboards.expected",
)


def has_expected_contract(source: dict[str, Any], registry_projection: dict[str, Any] | None) -> bool:
    if any(bool(get_path(source, path)) for path in CONTRACT_PATHS):
        return True
    if registry_projection:
        contract = registry_projection.get("inferred_contract", {})
        return any(bool(contract.get(key)) for key in ("indexes", "sourcetypes", "macros"))
    return False


def source_lookup_keys(source: dict[str, Any]) -> list[str]:
    keys = []
    for field in ("app_name", "skill", "splunkbase_id", "product", "name"):
        value = source.get(field)
        if value:
            keys.append(str(value).lower())
    return keys


def as_lower_strings(values: Any) -> set[str]:
    return {str(item).strip().lower() for item in token_set(values) if str(item).strip()}


def source_pack_match_values(source: dict[str, Any]) -> dict[str, set[str]]:
    values = {
        "skills": as_lower_strings(source.get("skill")),
        "app_names": as_lower_strings(source.get("app_name")),
        "products": as_lower_strings(source.get("product")),
        "names": as_lower_strings(source.get("name")),
        "sources": set(),
        "sourcetypes": set(),
    }
    values["sources"].update(as_lower_strings(source.get("source")))
    values["sources"].update(as_lower_strings(source.get("expected_sources")))
    values["sources"].update(as_lower_strings(get_path(source, "sources.expected")))
    values["sourcetypes"].update(as_lower_strings(source.get("sourcetype")))
    values["sourcetypes"].update(as_lower_strings(source.get("expected_sourcetypes")))
    values["sourcetypes"].update(as_lower_strings(get_path(source, "sourcetypes.expected")))
    return values


def source_matches_pack(source: dict[str, Any], pack: dict[str, Any]) -> bool:
    match = pack.get("match", {}) if isinstance(pack.get("match"), dict) else {}
    values = source_pack_match_values(source)
    for key in ("skills", "app_names", "products", "names", "sources", "sourcetypes"):
        expected = {str(item).strip().lower() for item in match.get(key, []) if str(item).strip()}
        if expected and values.get(key, set()) & expected:
            return True
    for pair in match.get("source_sourcetype_pairs", []):
        if not isinstance(pair, dict):
            continue
        expected_source = str(pair.get("source", "")).strip().lower()
        expected_sourcetype = str(pair.get("sourcetype", "")).strip().lower()
        if expected_source and expected_sourcetype:
            if expected_source in values["sources"] and expected_sourcetype in values["sourcetypes"]:
                return True
    prefixes = [str(item).strip().lower() for item in match.get("sourcetype_prefixes", []) if str(item).strip()]
    if prefixes:
        return any(sourcetype.startswith(prefix) for sourcetype in values["sourcetypes"] for prefix in prefixes)
    return False


def find_source_pack(
    source: dict[str, Any],
    packs_by_id: dict[str, dict[str, Any]],
    requested_ids: set[str],
) -> dict[str, Any] | None:
    explicit = source.get("source_pack_id") or source.get("source_pack")
    if explicit:
        pack_id = str(explicit).lower()
        if requested_ids and pack_id not in requested_ids:
            return None
        return packs_by_id.get(pack_id)

    for pack_id, pack in packs_by_id.items():
        if requested_ids and pack_id not in requested_ids:
            continue
        if source_matches_pack(source, pack):
            return pack
    return None


def set_default_path(target: dict[str, Any], dotted: str, value: Any) -> bool:
    current: Any = target
    parts = dotted.split(".")
    for part in parts[:-1]:
        if not isinstance(current, dict):
            return False
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            return False
        current = child
    final = parts[-1]
    if not isinstance(current, dict):
        return False
    if final not in current or current[final] in (None, "", [], {}):
        current[final] = json_clone(value)
        return True
    return False


def assign_path(target: dict[str, Any], dotted: str, value: Any) -> None:
    current: Any = target
    parts = dotted.split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = json_clone(value)


def apply_source_pack_defaults(source: dict[str, Any], pack: dict[str, Any] | None) -> None:
    if not pack:
        return
    applied: list[str] = []
    defaults = pack.get("defaults", {}) if isinstance(pack.get("defaults"), dict) else {}
    for key, value in defaults.items():
        if set_default_path(source, str(key), value):
            applied.append(str(key))
    source["source_pack"] = {
        "id": pack.get("id", ""),
        "label": pack.get("label", ""),
        "docs": pack.get("docs", []),
        "handoffs": pack.get("handoffs", []),
        "applied_defaults": sorted(applied),
        "collection_searches": pack.get("collection_searches", []),
    }


def enrich_sources(
    evidence: dict[str, Any],
    registry_index: dict[str, dict[str, Any]],
    source_packs: dict[str, Any],
    requested_pack_ids: set[str],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    raw_sources = evidence.get("data_sources", [])
    if raw_sources is None:
        raw_sources = []
    if not isinstance(raw_sources, list):
        die("evidence.data_sources must be a list when present.")

    for index, source in enumerate(raw_sources, start=1):
        if not isinstance(source, dict):
            die("Each data_sources[] item must be an object.")
        item = dict(source)
        item.setdefault("name", f"data_source_{index}")
        pack = find_source_pack(item, source_pack_index(source_packs), requested_pack_ids)
        apply_source_pack_defaults(item, pack)
        registry_projection = None
        for key in source_lookup_keys(item):
            registry_projection = registry_index.get(key)
            if registry_projection:
                break
        registry_state = dict(item.get("registry", {}) if isinstance(item.get("registry"), dict) else {})
        if registry_projection:
            registry_state.setdefault("resolved", True)
            registry_state.setdefault("app_name", registry_projection.get("app_name", ""))
            registry_state.setdefault("skill", registry_projection.get("skill", ""))
            registry_state.setdefault("splunkbase_id", registry_projection.get("splunkbase_id", ""))
            registry_state.setdefault("label", registry_projection.get("label", ""))
            registry_state.setdefault("inferred_contract", registry_projection.get("inferred_contract", {}))
        else:
            registry_state.setdefault("resolved", False)
        registry_state.setdefault("expected_contract_missing", not has_expected_contract(item, registry_projection))
        item["registry"] = registry_state
        enriched.append(item)
    return enriched


def normalized_evidence(
    args: argparse.Namespace,
    registry_index: dict[str, dict[str, Any]],
    source_packs: dict[str, Any],
) -> tuple[dict[str, Any], str, list[str]]:
    evidence: dict[str, Any] = {}
    if args.evidence_file:
        evidence = load_json_file(Path(args.evidence_file).expanduser())
    platform = detect_platform(args.platform, evidence)
    targets = parse_targets(args.targets)
    if "targets" in evidence:
        target_value = evidence["targets"]
        if isinstance(target_value, list):
            targets = parse_targets(",".join(str(item) for item in target_value))
        elif isinstance(target_value, str):
            targets = parse_targets(target_value)
        else:
            die("evidence.targets must be a list or comma-separated string when present.")

    evidence = dict(evidence)
    evidence.setdefault("platform", platform)
    evidence["data_sources"] = enrich_sources(evidence, registry_index, source_packs, source_pack_ids(args.source_pack))
    evidence.setdefault("inputs", {})
    if args.target_search_head:
        evidence["inputs"]["target_search_head"] = args.target_search_head
    if args.splunk_uri:
        evidence["inputs"]["splunk_uri"] = args.splunk_uri
    evidence["inputs"]["registry_file"] = args.registry_file
    evidence["inputs"]["source_packs_file"] = args.source_packs_file
    if args.source_pack:
        evidence["inputs"]["source_pack_filter"] = sorted(source_pack_ids(args.source_pack))
    return evidence, platform, targets


def rule_scopes(rule_scope: str) -> tuple[bool, bool]:
    return (rule_scope in {"global", "both"}, rule_scope in {"data_source", "both"})


def finding_from_rule(
    item: dict[str, Any],
    *,
    source: dict[str, Any] | None,
    platform: str,
) -> dict[str, Any]:
    finding = {key: item[key] for key in REQUIRED_RULE_FIELDS}
    finding["observed_at"] = now_iso()
    finding["platform"] = platform
    finding["selected_fix_safe"] = item["fix_kind"] in {"direct_fix", "delegated_fix", "manual_support"}
    if source is not None:
        finding["data_source"] = str(source.get("name", "unnamed"))
        finding["source_identity"] = {
            "name": source.get("name", ""),
            "app_name": source.get("app_name", ""),
            "skill": source.get("skill", ""),
            "splunkbase_id": source.get("splunkbase_id", ""),
        }
    else:
        finding["data_source"] = "global"
        finding["source_identity"] = {}
    return finding


def evaluate_rules(evidence: dict[str, Any], platform: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    redacted_evidence = redact(evidence)
    sources = redacted_evidence.get("data_sources", [])
    if not isinstance(sources, list):
        sources = []

    for item in RULE_CATALOG:
        global_scope, source_scope = rule_scopes(item["scope"])
        if global_scope and trigger_matches(item["trigger"], redacted_evidence):
            findings.append(finding_from_rule(item, source=None, platform=platform))
        if source_scope:
            for source in sources:
                if isinstance(source, dict) and trigger_matches(item["trigger"], source):
                    findings.append(finding_from_rule(item, source=source, platform=platform))

    findings.sort(key=lambda item: (-SEVERITY_RANK[item["severity"]], item["id"], item["data_source"]))
    return findings


def status_for_score(score: int, target_findings: list[dict[str, Any]]) -> str:
    if any(finding["severity"] == "critical" for finding in target_findings):
        return "blocked"
    if score >= 90 and not any(SEVERITY_RANK[finding["severity"]] >= SEVERITY_RANK["high"] for finding in target_findings):
        return "ready"
    if score >= 75:
        return "usable_with_gaps"
    return "blocked"


def build_scores(findings: list[dict[str, Any]], targets: list[str]) -> dict[str, Any]:
    scores: dict[str, Any] = {}
    for target in targets:
        target_findings = [
            finding for finding in findings
            if target in finding.get("target_impacts", {})
        ]
        penalty = sum(int(finding["target_impacts"].get(target, 0)) for finding in target_findings)
        score = max(0, min(100, 100 + penalty))
        scores[target] = {
            "score": score,
            "status": status_for_score(score, target_findings),
            "penalty": penalty,
            "finding_ids": [finding["id"] for finding in target_findings],
        }
    return scores


def build_source_scores(findings: list[dict[str, Any]], targets: list[str]) -> dict[str, Any]:
    by_source: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        by_source.setdefault(finding.get("data_source", "global"), []).append(finding)
    return {
        source: build_scores(source_findings, targets)
        for source, source_findings in sorted(by_source.items())
    }


def build_coverage(findings: list[dict[str, Any]], targets: list[str]) -> dict[str, Any]:
    findings_by_domain: dict[str, list[str]] = {}
    for finding in findings:
        findings_by_domain.setdefault(finding["domain"], []).append(finding["id"])

    domains: dict[str, Any] = {}
    for manifest in COVERAGE_MANIFEST:
        domain = manifest["domain"]
        rules = [item for item in RULE_CATALOG if item["domain"] == domain]
        fix_kind = max((item["fix_kind"] for item in rules), key=lambda kind: FIX_KIND_RANK[kind])
        domains[domain] = {
            "coverage": fix_kind,
            "targets": manifest["targets"],
            "active_targets": [target for target in manifest["targets"] if target in targets],
            "rule_ids": [item["id"] for item in rules],
            "finding_ids": findings_by_domain.get(domain, []),
            "policy": manifest["policy"],
        }
    return {"targets": targets, "domains": domains}


def build_fix_plan(findings: list[dict[str, Any]]) -> dict[str, Any]:
    fixes: list[dict[str, Any]] = []
    for finding in findings:
        selectable = finding["fix_kind"] in {"direct_fix", "delegated_fix", "manual_support"}
        fixes.append(
            {
                "id": finding["id"],
                "data_source": finding["data_source"],
                "domain": finding["domain"],
                "severity": finding["severity"],
                "fix_kind": finding["fix_kind"],
                "selectable": selectable,
                "preview_command": finding["preview_command"],
                "apply_command": finding["apply_command"],
                "handoff_skill": finding["handoff_skill"],
                "rollback_or_validation": finding["rollback_or_validation"],
            }
        )
    return {
        "generated_at": now_iso(),
        "safety": {
            "requires_explicit_fixes": True,
            "dry_run_supported": True,
            "live_mutations_performed_by_doctor": False,
            "blocked_in_v1": [
                "app installation",
                "index creation or retention changes",
                "macro edits",
                "saved-search enablement",
                "data model rebuilds",
                "ARI data-source activation",
                "ITSI object import",
                "ES configuration writes",
            ],
        },
        "fixes": fixes,
    }


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def markdown_list(items: list[Any]) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- `{item}`" for item in items)


def markdown_score_table(scores: dict[str, Any]) -> str:
    lines = [
        "| Target | Score | Status | Penalty | Findings |",
        "| --- | --- | --- | --- | --- |",
    ]
    for target, item in scores.items():
        findings = ", ".join(f"`{finding}`" for finding in item["finding_ids"]) or "`none`"
        lines.append(f"| `{target}` | `{item['score']}` | `{item['status']}` | `{item['penalty']}` | {findings} |")
    return "\n".join(lines)


def render_report_markdown(report: dict[str, Any]) -> str:
    findings = report["findings"]
    lines = [
        "# Splunk Data Source Readiness Report",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Platform: `{report['platform']}`",
        f"Targets: {', '.join(f'`{target}`' for target in report['targets'])}",
        f"Data sources: `{len(report['data_sources'])}`",
        f"Findings: `{len(findings)}`",
        "",
        "## Scores",
        "",
        markdown_score_table(report["scores"]),
        "",
        "## Findings",
        "",
    ]
    if not findings:
        lines.extend(["No readiness findings triggered from the supplied evidence.", ""])
    for finding in findings:
        lines.extend(
            [
                f"### {finding['id']} - {finding['domain']}",
                "",
                f"- Data source: `{finding['data_source']}`",
                f"- Severity: `{finding['severity']}`",
                f"- Fix kind: `{finding['fix_kind']}`",
                f"- Evidence: {finding['evidence']}",
                f"- Source: {finding['source_doc']}",
                f"- Target impacts: `{finding['target_impacts']}`",
                f"- Preview: `{finding['preview_command']}`",
                f"- Apply policy: {finding['apply_command']}",
                f"- Handoff skill: `{finding['handoff_skill'] or 'none'}`",
                f"- Validate/rollback: {finding['rollback_or_validation']}",
                "",
            ]
        )

    lines.extend(["## Coverage", ""])
    for domain, item in report["coverage"]["domains"].items():
        lines.extend(
            [
                f"### {domain}",
                "",
                f"- Coverage: `{item['coverage']}`",
                f"- Targets: {', '.join(f'`{target}`' for target in item['targets'])}",
                f"- Rules: {', '.join(f'`{rule_id}`' for rule_id in item['rule_ids']) or '`none`'}",
                f"- Findings: {', '.join(f'`{rule_id}`' for rule_id in item['finding_ids']) or '`none`'}",
                f"- Policy: {item['policy']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_fix_plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# Splunk Data Source Readiness Fix Plan",
        "",
        f"Generated: `{plan['generated_at']}`",
        "",
        "The doctor does not execute live Splunk mutations. Select fixes with",
        "`--phase apply --fixes FIX_ID[,FIX_ID]`; apply renders local packets",
        "for the selected IDs.",
        "",
        "## Fixes",
        "",
    ]
    if not plan["fixes"]:
        lines.extend(["No selectable fixes were produced from current evidence.", ""])
    for fix in plan["fixes"]:
        lines.extend(
            [
                f"### {fix['id']}",
                "",
                f"- Data source: `{fix['data_source']}`",
                f"- Domain: `{fix['domain']}`",
                f"- Severity: `{fix['severity']}`",
                f"- Fix kind: `{fix['fix_kind']}`",
                f"- Selectable: `{fix['selectable']}`",
                f"- Preview: `{fix['preview_command']}`",
                f"- Apply policy: {fix['apply_command']}",
                f"- Handoff skill: `{fix['handoff_skill'] or 'none'}`",
                f"- Validate/rollback: {fix['rollback_or_validation']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def source_indexes(source: dict[str, Any]) -> list[str]:
    values = set()
    values.update(token_set(source.get("expected_indexes")))
    values.update(token_set(get_path(source, "indexes.expected")))
    values.update(token_set(get_path(source, "registry.inferred_contract.indexes")))
    return sorted(values)


def source_sourcetypes(source: dict[str, Any]) -> list[str]:
    values = set()
    values.update(token_set(source.get("expected_sourcetypes")))
    values.update(token_set(get_path(source, "sourcetypes.expected")))
    values.update(token_set(get_path(source, "registry.inferred_contract.sourcetypes")))
    return sorted(values)


def source_sources(source: dict[str, Any]) -> list[str]:
    values = set()
    values.update(token_set(source.get("expected_sources")))
    values.update(token_set(get_path(source, "sources.expected")))
    if source.get("source"):
        values.update(token_set(source.get("source")))
    return sorted(values)


def source_cim_models(source: dict[str, Any]) -> list[str]:
    values = set()
    values.update(token_set(get_path(source, "cim.expected_models")))
    values.update(token_set(get_path(source, "data_models.expected")))
    return sorted(values)


def splunk_search_clause(field: str, values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return f'{field}="{values[0]}"'
    return f"{field} IN ({', '.join(json.dumps(value) for value in values)})"


def source_base_search(source: dict[str, Any]) -> str:
    indexes = source_indexes(source)
    sources = source_sources(source)
    sourcetypes = source_sourcetypes(source)
    clauses = [
        clause
        for clause in (
            splunk_search_clause("index", indexes),
            splunk_search_clause("source", sources),
            splunk_search_clause("sourcetype", sourcetypes),
        )
        if clause
    ]
    return "search " + " ".join(clauses) if clauses else "search index=*"


def pack_searches_for_source(source: dict[str, Any], base: str) -> list[dict[str, Any]]:
    pack = source.get("source_pack", {}) if isinstance(source.get("source_pack"), dict) else {}
    searches = pack.get("collection_searches", [])
    if not isinstance(searches, list):
        return []
    rendered: list[dict[str, Any]] = []
    for search in searches:
        if not isinstance(search, dict) or not search.get("id") or not search.get("spl"):
            continue
        spl = str(search["spl"]).replace("%BASE_SEARCH%", base)
        spl = spl.replace("%SOURCE_NAME%", str(source.get("name", "unnamed")))
        rendered.append(
            {
                "id": f"pack-{safe_rel_name(str(pack.get('id', 'source')))}-{safe_rel_name(str(search['id']))}",
                "title": str(search.get("title", search["id"])),
                "category": str(search.get("category", "source-pack")),
                "source_pack": pack.get("id", ""),
                "data_source": str(source.get("name", "unnamed")),
                "spl": spl,
            }
        )
    return rendered


def build_collector_specs(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    sources = evidence.get("data_sources", [])
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            name = str(source.get("name", "unnamed"))
            safe_name = safe_rel_name(name)
            base = source_base_search(source)
            source_specs = [
                {
                    "id": f"source-{safe_name}-sample-freshness",
                    "title": f"{name}: sample freshness and distribution",
                    "category": "source-sample",
                    "data_source": name,
                    "spl": f"{base} earliest=-24h latest=now | stats count max(_time) as latest min(_time) as earliest by index sourcetype host source",
                },
                {
                    "id": f"source-{safe_name}-volume-latency-duplicates",
                    "title": f"{name}: volume baseline, ingest latency, and duplicate signal",
                    "category": "source-sample",
                    "data_source": name,
                    "spl": f"{base} earliest=-7d latest=now | eval ingest_latency_seconds=_indextime-_time | stats count as events dc(_raw) as distinct_raw max(ingest_latency_seconds) as max_latency_seconds avg(ingest_latency_seconds) as avg_latency_seconds by index sourcetype date_mday | eval duplicate_rate_pct=round((events-distinct_raw)/events*100,2)",
                },
                {
                    "id": f"source-{safe_name}-fieldsummary",
                    "title": f"{name}: parser and field coverage",
                    "category": "source-parser",
                    "data_source": name,
                    "spl": f"{base} earliest=-24h latest=now | head 200 | fieldsummary",
                },
                {
                    "id": f"source-{safe_name}-cim-tags-eventtypes",
                    "title": f"{name}: CIM tags and eventtypes",
                    "category": "source-cim",
                    "data_source": name,
                    "spl": f"{base} earliest=-24h latest=now | stats count by tag eventtype sourcetype",
                },
                {
                    "id": f"source-{safe_name}-cim-value-candidates",
                    "title": f"{name}: CIM value and dataset-constraint candidates",
                    "category": "source-cim",
                    "data_source": name,
                    "spl": f"{base} earliest=-24h latest=now | head 500 | stats values(*) as * by sourcetype",
                },
            ]
            for model in source_cim_models(source):
                source_specs.append(
                    {
                        "id": f"source-{safe_name}-datamodel-{safe_rel_name(model)}",
                        "title": f"{name}: data model sample for {model}",
                        "category": "source-datamodel",
                        "data_source": name,
                        "spl": f"| tstats count from datamodel={model} earliest=-24h latest=now by index sourcetype",
                    }
                )
            source_specs.extend(pack_searches_for_source(source, base))
            specs.extend(source_specs)

    specs.extend(
        [
            {
                "id": "global-data-model-acceleration",
                "title": "Global: data model acceleration status",
                "category": "global-datamodel",
                "data_source": "global",
                "spl": "| rest splunk_server=local count=0 /services/data/models | table title acceleration.* constraints tags_whitelist acceleration.earliest_time eai:acl.app",
            },
            {
                "id": "global-dashboard-inventory",
                "title": "Global: Dashboard Studio and Simple XML dependency inventory",
                "category": "global-dashboard",
                "data_source": "global",
                "spl": "| rest splunk_server=local count=0 /servicesNS/-/-/data/ui/views | table title label isVisible eai:acl.app eai:acl.sharing eai:data",
            },
            {
                "id": "global-saved-search-inventory",
                "title": "Global: saved-search and report inventory",
                "category": "global-dashboard",
                "data_source": "global",
                "spl": "| rest splunk_server=local count=0 /servicesNS/-/-/saved/searches | table title disabled is_scheduled cron_schedule realtime_schedule dispatch.earliest_time dispatch.latest_time search eai:acl.app eai:acl.sharing",
            },
            {
                "id": "global-macro-inventory",
                "title": "Global: macro inventory",
                "category": "global-knowledge",
                "data_source": "global",
                "spl": "| rest splunk_server=local count=0 /servicesNS/-/-/admin/macros | table title definition args iseval eai:acl.app eai:acl.sharing",
            },
            {
                "id": "global-lookup-transform-inventory",
                "title": "Global: lookup transform inventory",
                "category": "global-knowledge",
                "data_source": "global",
                "spl": "| rest splunk_server=local count=0 /servicesNS/-/-/data/transforms/lookups | table title filename external_type fields_list match_type case_sensitive_match eai:acl.app eai:acl.sharing",
            },
            {
                "id": "global-index-retention-aging",
                "title": "Global: index retention and aging inventory",
                "category": "global-retention",
                "data_source": "global",
                "spl": "| rest splunk_server=local count=0 /services/data/indexes | table title frozenTimePeriodInSecs maxTotalDataSizeMB maxGlobalDataSizeMB homePath coldPath thawedPath datatype disabled",
            },
            {
                "id": "global-scheduled-content-execution",
                "title": "Global: scheduled content execution health",
                "category": "global-scheduler",
                "data_source": "global",
                "spl": 'index=_internal source=*scheduler.log* earliest=-24h latest=now (status=skipped OR status=failed OR status=continued OR status=success OR "skipped" OR "quota" OR "lag") | stats count latest(_raw) as latest_event latest(status) as latest_status by savedsearch_name app user host reason',
            },
            {
                "id": "global-itsi-summary",
                "title": "Global: ITSI summary and Event Analytics evidence",
                "category": "global-itsi",
                "data_source": "global",
                "spl": "search (index=itsi_summary OR index=itsi_summary_metrics OR index=itsi_tracked_alerts) earliest=-24h latest=now | stats count latest(_time) as latest by index source sourcetype",
            },
            {
                "id": "global-metrics-mstats",
                "title": "Global: metrics index and mstats evidence",
                "category": "global-metrics",
                "data_source": "global",
                "spl": "| mpreview index=* earliest=-15m latest=now | stats count by index metric_name",
            },
            {
                "id": "global-hec-token-inventory",
                "title": "Global: HTTP Event Collector token inventory",
                "category": "global-collector-health",
                "data_source": "global",
                "spl": "| rest splunk_server=local count=0 /servicesNS/nobody/splunk_httpinput/data/inputs/http | table title disabled index indexes sourcetype useACK",
            },
            {
                "id": "global-hec-health-internal",
                "title": "Global: HTTP Event Collector metrics and error signal",
                "category": "global-collector-health",
                "data_source": "global",
                "spl": 'index=_internal earliest=-24h latest=now (component=HttpEventCollector OR component=HttpInputDataHandler OR "http_event_collector_token") | stats sum(data:num_of_errors) as errors sum(data:num_of_parser_errors) as parser_errors sum(data:num_of_requests_to_disabled_token) as disabled_token_requests sum(data:num_of_events) as events latest(_raw) as latest_event by host component data:token_name log_level',
            },
            {
                "id": "global-deployment-client-health",
                "title": "Global: deployment client phone-home health",
                "category": "global-collector-health",
                "data_source": "global",
                "spl": "| rest splunk_server=local count=0 /services/deployment/server/clients | table hostname ip dns utsname applications.* serverClasses lastPhoneHomeTime averagePhoneHomeInterval",
            },
            {
                "id": "global-sc4s-health",
                "title": "Global: Splunk Connect for Syslog health signal",
                "category": "global-collector-health",
                "data_source": "global",
                "spl": 'index=_internal earliest=-24h latest=now (sc4s OR "Splunk Connect for Syslog" OR sourcetype=sc4s:*) | stats count latest(_raw) as latest_event by host sourcetype log_level component',
            },
            {
                "id": "global-sc4snmp-health",
                "title": "Global: Splunk Connect for SNMP health signal",
                "category": "global-collector-health",
                "data_source": "global",
                "spl": 'index=_internal earliest=-24h latest=now (sc4snmp OR "Splunk Connect for SNMP" OR sourcetype=sc4snmp:*) | stats count latest(_raw) as latest_event by host sourcetype log_level component',
            },
            {
                "id": "global-otel-collector-health",
                "title": "Global: Splunk OpenTelemetry Collector health signal",
                "category": "global-collector-health",
                "data_source": "global",
                "spl": 'index=_internal earliest=-24h latest=now ("OpenTelemetry Collector" OR "splunk-otel-collector" OR splunk_otel_collector OR otelcol) | stats count latest(_raw) as latest_event by host sourcetype log_level component',
            },
            {
                "id": "global-data-manager-health",
                "title": "Global: Splunk Data Manager health signal",
                "category": "global-collector-health",
                "data_source": "global",
                "spl": 'index=_internal earliest=-24h latest=now ("Data Manager" OR datamanager OR "SplunkDM" OR "CloudFormation" OR "StackSet") | stats count latest(_raw) as latest_event by host sourcetype log_level component',
            },
        ]
    )
    return specs


def render_collection_searches(evidence: dict[str, Any]) -> str:
    lines = [
        "# Splunk data-source readiness collection searches",
        "# Run these from a user with search access and paste summarized JSON into --evidence-file.",
        "",
    ]
    sources = evidence.get("data_sources", [])
    if not sources:
        lines.append("# No data_sources[] were supplied; add source contracts to generate targeted searches.")
        return "\n".join(lines).rstrip() + "\n"

    for source in sources:
        if not isinstance(source, dict):
            continue
        name = safe_rel_name(str(source.get("name", "unnamed")))
        for spec in [item for item in build_collector_specs({"data_sources": [source]}) if item["data_source"] != "global"]:
            lines.extend([f"## {name}: {spec['title'].split(': ', 1)[-1]}", spec["spl"], ""])
    lines.extend(
        [
            "## Global: data model acceleration status",
            "| rest splunk_server=local count=0 /services/data/models | table title acceleration.* constraints tags_whitelist acceleration.earliest_time eai:acl.app",
            "",
            "## Global: dashboard dependency inventory",
            "| rest splunk_server=local count=0 /servicesNS/-/-/data/ui/views | table title label isVisible eai:acl.app eai:acl.sharing eai:data",
            "",
            "## Global: CIM index/tag constraint inventory",
            '| rest splunk_server=local count=0 /servicesNS/-/Splunk_SA_CIM/admin/conf-datamodels | table title acceleration.* constraints tags_whitelist acceleration.earliest_time eai:acl.app',
            "",
            "## Global: macro inventory",
            "| rest splunk_server=local count=0 /servicesNS/-/-/admin/macros | table title definition eai:acl.app eai:acl.sharing",
            "",
            "## Global: index retention and aging inventory",
            "| rest splunk_server=local count=0 /services/data/indexes | table title frozenTimePeriodInSecs maxTotalDataSizeMB maxGlobalDataSizeMB homePath coldPath thawedPath datatype disabled",
            "",
            "## Global: lookup transform inventory",
            "| rest splunk_server=local count=0 /servicesNS/-/-/data/transforms/lookups | table title filename external_type fields_list match_type case_sensitive_match eai:acl.app eai:acl.sharing",
            "",
            "## Global: automatic lookup inventory",
            "| rest splunk_server=local count=0 /servicesNS/-/-/data/props/lookups | table title stanza transform lookup.field.* eai:acl.app eai:acl.sharing",
            "",
            "## Global: field alias and calculated-field inventory",
            "| rest splunk_server=local count=0 /servicesNS/-/-/data/props/fieldaliases | table title stanza attribute value alias.* eai:acl.app eai:acl.sharing",
            "| rest splunk_server=local count=0 /servicesNS/-/-/data/props/calcfields | table title stanza attribute field.name value eai:acl.app eai:acl.sharing",
            "",
            "## Global: KV Store collection inventory",
            "| rest splunk_server=local count=0 /servicesNS/-/-/storage/collections/config | table title field.* accelerated_fields eai:acl.app eai:acl.sharing",
            "",
            "## Global: ingest latency and sourcetype throughput evidence",
            'index=_internal source=*metrics.log* group=per_sourcetype_thruput earliest=-24h latest=now | stats sum(kb) as kb sum(eps) as eps max(eps) as peak_eps by series',
            "",
            "## Global: ingest queue, destination, and drop signal",
            'index=_internal source=*metrics.log* (group=queue OR group=tcpin_connections OR blocked=true OR drop* OR "dead letter" OR "destination") earliest=-24h latest=now | stats count latest(_raw) as latest_event by host component group name series',
            "",
            "## Global: Edge/Ingest Processor operational signal",
            'index=_internal earliest=-24h latest=now ("Edge Processor" OR "Ingest Processor" OR edge_processor OR ingest_processor OR pipeline OR destination) | stats count latest(_raw) as latest_event by host component log_level',
            "",
            "## Global: federated provider inventory",
            "| rest splunk_server=local count=0 /services/data/federated/provider | table title name mode type disabled serviceAccount appContext status federated.*",
            "",
            "## Global: federated index inventory",
            "| rest splunk_server=local count=0 /services/data/federated/index | table title name disabled federated.provider federated.dataset datatype eai:acl.app eai:acl.sharing",
            "",
            "## Global: ES/SSE content activation evidence",
            '| rest splunk_server=local count=0 /servicesNS/-/-/saved/searches | search eai:acl.app IN ("SplunkEnterpriseSecuritySuite","DA-ESS-ContentUpdate","Splunk_Security_Essentials") | table title disabled cron_schedule action.notable action.risk action.correlationsearch.* eai:acl.app',
            "",
            "## Global: scheduled content execution health",
            'index=_internal source=*scheduler.log* earliest=-24h latest=now (status=skipped OR status=failed OR status=continued OR status=success OR "skipped" OR "quota" OR "lag") | stats count latest(_raw) as latest_event latest(status) as latest_status by savedsearch_name app user host reason',
            "",
            "## Global: scheduled saved-search inventory",
            "| rest splunk_server=local count=0 /servicesNS/-/-/saved/searches | search is_scheduled=1 OR action.correlationsearch.enabled=1 | table title disabled is_scheduled cron_schedule realtime_schedule schedule_window dispatch.earliest_time dispatch.latest_time alert.suppress action.correlationsearch.enabled action.notable action.risk eai:acl.app",
            "",
            "## Global: ES risk analysis evidence",
            '| from datamodel:Risk.All_Risk | stats count latest(_time) as latest values(risk_object_type) as risk_object_type by risk_object source',
            "",
            "## Global: ES threat intelligence evidence",
            '| rest splunk_server=local count=0 /servicesNS/-/SplunkEnterpriseSecuritySuite/saved/searches | search title="Threat*" OR title="*Threat*" | table title disabled cron_schedule search',
            "",
            "## Global: OCSF-CIM sourcetype setup evidence",
            '| rest splunk_server=local count=0 /servicesNS/-/ocsf_cim_addon_for_splunk/admin/conf-props | search title="ocsf:*" OR title="(?::){0}ocsf:*" | table title TIME_PREFIX TIME_FORMAT KV_MODE REPORT-* EXTRACT-*',
            "",
            "## Global: ITSI KPI base-search evidence",
            '| rest splunk_server=local count=0 /servicesNS/-/SA-ITOA/saved/searches | search title="DA-ITSI*" OR title="*KPI*" | table title disabled cron_schedule dispatch.earliest_time dispatch.latest_time search',
            "",
            "## Global: ITSI summary and Event Analytics evidence",
            'search (index=itsi_summary OR index=itsi_summary_metrics OR index=itsi_tracked_alerts) earliest=-24h latest=now | stats count latest(_time) as latest by index source sourcetype',
            "",
            "## Global: metrics index and mstats evidence",
            '| mpreview index=* earliest=-15m latest=now | stats count by index metric_name',
            '| mstats count WHERE index=* earliest=-15m latest=now BY metric_name',
            "",
            "## Global: ARI app search evidence",
            '| rest splunk_server=local count=0 /servicesNS/-/-/saved/searches | search eai:acl.app IN ("SplunkAssetRiskIntelligence","Splunk_TA_ari","Splunk_TA_ARi") | table title disabled cron_schedule search eai:acl.app',
            "",
            "## Global: HTTP Event Collector token inventory",
            "| rest splunk_server=local count=0 /servicesNS/nobody/splunk_httpinput/data/inputs/http | table title disabled index indexes sourcetype useACK",
            "",
            "## Global: HTTP Event Collector metrics and error signal",
            'index=_internal earliest=-24h latest=now (component=HttpEventCollector OR component=HttpInputDataHandler OR "http_event_collector_token") | stats sum(data:num_of_errors) as errors sum(data:num_of_parser_errors) as parser_errors sum(data:num_of_requests_to_disabled_token) as disabled_token_requests sum(data:num_of_events) as events latest(_raw) as latest_event by host component data:token_name log_level',
            "",
            "## Global: deployment client phone-home health",
            "| rest splunk_server=local count=0 /services/deployment/server/clients | table hostname ip dns utsname applications.* serverClasses lastPhoneHomeTime averagePhoneHomeInterval",
            "",
            "## Global: SC4S health signal",
            'index=_internal earliest=-24h latest=now (sc4s OR "Splunk Connect for Syslog" OR sourcetype=sc4s:*) | stats count latest(_raw) as latest_event by host sourcetype log_level component',
            "",
            "## Global: SC4SNMP health signal",
            'index=_internal earliest=-24h latest=now (sc4snmp OR "Splunk Connect for SNMP" OR sourcetype=sc4snmp:*) | stats count latest(_raw) as latest_event by host sourcetype log_level component',
            "",
            "## Global: Splunk OpenTelemetry Collector health signal",
            'index=_internal earliest=-24h latest=now ("OpenTelemetry Collector" OR "splunk-otel-collector" OR splunk_otel_collector OR otelcol) | stats count latest(_raw) as latest_event by host sourcetype log_level component',
            "",
            "## Global: Splunk Data Manager health signal",
            'index=_internal earliest=-24h latest=now ("Data Manager" OR datamanager OR "SplunkDM" OR "CloudFormation" OR "StackSet") | stats count latest(_raw) as latest_event by host sourcetype log_level component',
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_status(output_dir: Path) -> dict[str, Any]:
    report_path = output_dir / "readiness-report.json"
    if not report_path.exists():
        return {
            "ok": False,
            "status": "missing",
            "message": f"No readiness report found at {report_path}.",
        }
    report = load_json_file(report_path)
    return {
        "ok": True,
        "status": "available",
        "generated_at": report.get("generated_at"),
        "platform": report.get("platform"),
        "finding_count": len(report.get("findings", [])),
        "report_path": str(report_path),
    }


def registry_projection(registry_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    projections = []
    seen: set[tuple[str, str, str]] = set()
    for item in registry_index.values():
        key = (
            str(item.get("kind", "")),
            str(item.get("skill", "")),
            str(item.get("app_name", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        projections.append(item)
    projections.sort(key=lambda item: (str(item.get("skill", "")), str(item.get("app_name", ""))))
    return {"entries": projections, "entry_count": len(projections)}


def source_pack_catalog(source_packs: dict[str, Any], requested_ids: set[str] | None = None) -> dict[str, Any]:
    requested_ids = requested_ids or set()
    packs = []
    for pack in source_packs.get("packs", []):
        if not isinstance(pack, dict):
            continue
        pack_id = str(pack.get("id", "")).lower()
        if requested_ids and pack_id not in requested_ids:
            continue
        packs.append(
            {
                "id": pack.get("id", ""),
                "label": pack.get("label", ""),
                "docs": pack.get("docs", []),
                "match": pack.get("match", {}),
                "defaults": pack.get("defaults", {}),
                "handoffs": pack.get("handoffs", []),
                "collection_search_count": len(pack.get("collection_searches", [])),
            }
        )
    return {
        "generated_at": now_iso(),
        "source_pack_count": len(packs),
        "requested_source_packs": sorted(requested_ids),
        "packs": packs,
    }


def source_pack_report(evidence: dict[str, Any], source_packs: dict[str, Any]) -> dict[str, Any]:
    sources = []
    for source in evidence.get("data_sources", []):
        if not isinstance(source, dict):
            continue
        pack = source.get("source_pack", {}) if isinstance(source.get("source_pack"), dict) else {}
        sources.append(
            {
                "name": source.get("name", ""),
                "app_name": source.get("app_name", ""),
                "skill": source.get("skill", ""),
                "source_pack": {
                    "id": pack.get("id", ""),
                    "label": pack.get("label", ""),
                    "applied_defaults": pack.get("applied_defaults", []),
                    "handoffs": pack.get("handoffs", []),
                    "docs": pack.get("docs", []),
                },
            }
        )
    return {
        "generated_at": now_iso(),
        "catalog_source_pack_count": len(source_packs.get("packs", [])),
        "matched_source_count": sum(1 for item in sources if item["source_pack"]["id"]),
        "sources": sources,
    }


def collector_manifest(evidence: dict[str, Any]) -> dict[str, Any]:
    searches = build_collector_specs(evidence)
    return {
        "generated_at": now_iso(),
        "safety": {
            "read_only": True,
            "live_mutations_performed": False,
            "credential_policy": "Use --session-key-file only; tokens are never printed or written.",
        },
        "search_count": len(searches),
        "searches": searches,
    }


def write_base_outputs(
    output_dir: Path,
    report: dict[str, Any],
    fix_plan: dict[str, Any],
    evidence: dict[str, Any],
    registry: dict[str, Any],
    source_packs: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_file(output_dir / "readiness-report.json", json_dumps(report))
    write_file(output_dir / "readiness-report.md", render_report_markdown(report))
    write_file(output_dir / "fix-plan.json", json_dumps(fix_plan))
    write_file(output_dir / "fix-plan.md", render_fix_plan_markdown(fix_plan))
    write_file(output_dir / "coverage-report.json", json_dumps(report["coverage"]))
    write_file(output_dir / "registry-projection.json", json_dumps(registry_projection(build_registry_index(registry))))
    write_file(output_dir / "source-pack-catalog.json", json_dumps(source_pack_catalog(source_packs)))
    write_file(output_dir / "source-pack-report.json", json_dumps(source_pack_report(evidence, source_packs)))
    write_file(output_dir / "collector-manifest.json", json_dumps(collector_manifest(evidence)))
    write_file(output_dir / "collection-searches.spl", render_collection_searches(evidence))
    write_file(output_dir / "evidence" / "input-evidence.redacted.json", json_dumps(redact(evidence)))
    write_file(
        output_dir / "evidence" / "collection-notes.md",
        "# Evidence Collection Notes\n\n"
        "This doctor renders collection searches and can run read-only live export searches during `--phase collect`. "
        "It never mutates Splunk. "
        "Evidence supplied through `--evidence-file` is redacted before writing.\n",
    )


def selected_fix_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def render_handoff_packet(output_dir: Path, finding: dict[str, Any]) -> None:
    fix_id = finding["id"]
    skills = [item.strip() for item in finding["handoff_skill"].split(",") if item.strip()]
    packet = [
        f"# {fix_id} Handoff",
        "",
        f"Data source: `{finding['data_source']}`",
        f"Domain: `{finding['domain']}`",
        f"Severity: `{finding['severity']}`",
        f"Fix kind: `{finding['fix_kind']}`",
        "",
        "## Evidence",
        "",
        finding["evidence"],
        "",
        "## Source",
        "",
        finding["source_doc"],
        "",
        "## Suggested Preview",
        "",
        f"```bash\n{finding['preview_command']}\n```",
        "",
        "## Handoff Skills",
        "",
        markdown_list(skills),
        "",
        "## Validation",
        "",
        finding["rollback_or_validation"],
        "",
    ]
    write_file(output_dir / "handoffs" / f"{safe_rel_name(fix_id)}-{safe_rel_name(finding['data_source'])}.md", "\n".join(packet))


def render_support_packet(output_dir: Path, finding: dict[str, Any]) -> None:
    fix_id = finding["id"]
    packet = [
        f"# {fix_id} Support Packet",
        "",
        f"Data source: `{finding['data_source']}`",
        f"Domain: `{finding['domain']}`",
        f"Severity: `{finding['severity']}`",
        "",
        "## Evidence To Include",
        "",
        finding["evidence"],
        "",
        "## Source Anchor",
        "",
        finding["source_doc"],
        "",
        "## Operator Notes",
        "",
        finding["apply_command"],
        "",
        "## Validation",
        "",
        finding["rollback_or_validation"],
        "",
    ]
    write_file(output_dir / "support-tickets" / f"{safe_rel_name(fix_id)}-{safe_rel_name(finding['data_source'])}.md", "\n".join(packet))


def render_direct_packet(output_dir: Path, finding: dict[str, Any]) -> None:
    fix_id = finding["id"]
    packet = [
        f"# {fix_id} Local Checklist",
        "",
        f"Data source: `{finding['data_source']}`",
        f"Domain: `{finding['domain']}`",
        f"Severity: `{finding['severity']}`",
        "",
        "## Check",
        "",
        finding["preview_command"],
        "",
        "## Safe Local Action",
        "",
        finding["apply_command"],
        "",
        "## Validation",
        "",
        finding["rollback_or_validation"],
        "",
    ]
    write_file(output_dir / "handoffs" / f"{safe_rel_name(fix_id)}-{safe_rel_name(finding['data_source'])}.md", "\n".join(packet))


def apply_selected_fixes(output_dir: Path, findings: list[dict[str, Any]], fixes: list[str]) -> dict[str, Any]:
    if not fixes:
        die("--phase apply requires --fixes FIX_ID[,FIX_ID].")
    selectable_findings = [finding for finding in findings if finding["fix_kind"] != "diagnose_only"]
    by_id: dict[str, list[dict[str, Any]]] = {}
    for finding in selectable_findings:
        by_id.setdefault(finding["id"], []).append(finding)
    unknown = sorted(set(fixes) - set(by_id))
    if unknown:
        die(f"Requested fix IDs are not active selectable findings: {', '.join(unknown)}")

    applied: list[dict[str, Any]] = []
    for fix_id in fixes:
        for finding in by_id[fix_id]:
            if finding["fix_kind"] == "delegated_fix":
                render_handoff_packet(output_dir, finding)
            elif finding["fix_kind"] == "manual_support":
                render_support_packet(output_dir, finding)
            elif finding["fix_kind"] == "direct_fix":
                render_direct_packet(output_dir, finding)
            applied.append(
                {
                    "id": fix_id,
                    "data_source": finding["data_source"],
                    "fix_kind": finding["fix_kind"],
                    "live_mutation_performed": False,
                    "packet": "handoffs" if finding["fix_kind"] != "manual_support" else "support-tickets",
                }
            )
    result = {
        "generated_at": now_iso(),
        "selected_fixes": applied,
        "safety": "local packets rendered only; no Splunk mutation performed by doctor",
    }
    write_file(output_dir / "applied-fixes.json", json_dumps(result))
    return result


def normalize_splunk_uri(value: str) -> str:
    uri = value.rstrip("/")
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        die("--splunk-uri must be an http(s) URI such as https://localhost:8089")
    return uri


def read_session_key_file(path_value: str) -> str:
    path = Path(path_value).expanduser()
    if not path.exists():
        die(f"--session-key-file does not exist: {path}")
    if path.stat().st_mode & 0o077:
        die(f"--session-key-file must not be group/world readable: {path}")
    session_key = path.read_text(encoding="utf-8").strip()
    if not session_key:
        die("--session-key-file is empty")
    return session_key


def parse_export_json_lines(payload: bytes, max_rows: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = payload.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            row = parsed.get("result", parsed)
            rows.append(redact(row))
        if len(rows) >= max_rows:
            break
    if not rows:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, dict):
            result = parsed.get("results", parsed.get("result", parsed))
            if isinstance(result, list):
                return [redact(item) for item in result[:max_rows] if isinstance(item, dict)]
            if isinstance(result, dict):
                return [redact(result)]
    return rows


def execute_export_search(args: argparse.Namespace, session_key: str, spec: dict[str, Any]) -> dict[str, Any]:
    if LIVE_COLLECTOR_BLOCKED_SPL_RE.search(str(spec.get("spl", ""))):
        return {
            "ok": False,
            "id": spec["id"],
            "title": spec["title"],
            "error": "collector search contains a blocked mutating SPL command",
        }
    uri = normalize_splunk_uri(args.splunk_uri)
    data = urllib.parse.urlencode(
        {
            "search": spec["spl"],
            "output_mode": "json",
            "count": str(args.max_rows),
            "max_time": str(args.collect_timeout_seconds),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{uri}/services/search/v2/jobs/export",
        data=data,
        headers={
            "Authorization": f"Splunk {session_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    context = ssl._create_unverified_context() if args.no_verify_tls else ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=args.collect_timeout_seconds, context=context) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "id": spec["id"],
            "title": spec["title"],
            "http_status": exc.code,
            "error": redact(str(exc.reason)),
        }
    except urllib.error.URLError as exc:
        return {"ok": False, "id": spec["id"], "title": spec["title"], "error": redact(str(exc.reason))}
    except TimeoutError:
        return {"ok": False, "id": spec["id"], "title": spec["title"], "error": "timed out"}

    rows = parse_export_json_lines(body, args.max_rows)
    return {
        "ok": True,
        "id": spec["id"],
        "title": spec["title"],
        "category": spec.get("category", ""),
        "data_source": spec.get("data_source", ""),
        "row_count": len(rows),
        "rows": rows,
    }


def parse_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_epoch_seconds(value: Any) -> float | None:
    numeric = parse_number(value)
    if numeric is not None:
        return numeric / 1000 if numeric > 10_000_000_000 else numeric
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return None


def latest_age_minutes(value: Any, now: float | None = None) -> float | None:
    epoch = parse_epoch_seconds(value)
    if epoch is None:
        return None
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    return round(max(0.0, (now - epoch) / 60.0), 2)


def rows_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("rows", result.get("results", []))
    if isinstance(rows, dict):
        return [rows]
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def collector_results_list(collector_results: dict[str, Any]) -> list[dict[str, Any]]:
    results = collector_results.get("results", [])
    if isinstance(results, dict):
        return [results]
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]
    return []


def ensure_source(evidence: dict[str, Any], name: str) -> dict[str, Any]:
    sources = evidence.get("data_sources")
    if not isinstance(sources, list):
        sources = []
        evidence["data_sources"] = sources
    for source in sources:
        if isinstance(source, dict) and str(source.get("name", "")) == name:
            return source
    source = {"name": name}
    sources.append(source)
    return source


def row_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return None


def row_text(row: dict[str, Any], *names: str) -> str:
    value = row_value(row, *names)
    return "" if value is None else str(value)


def sum_field(rows: list[dict[str, Any]], *names: str) -> float:
    total = 0.0
    for row in rows:
        number = parse_number(row_value(row, *names))
        if number is not None:
            total += number
    return total


def max_field(rows: list[dict[str, Any]], *names: str) -> float | None:
    values = [number for row in rows if (number := parse_number(row_value(row, *names))) is not None]
    return max(values) if values else None


INDEX_RE = re.compile(r'(?:^|[\s(])index\s*=\s*"?([A-Za-z0-9_.*:-]+)"?', re.IGNORECASE)
SOURCETYPE_RE = re.compile(r'(?:^|[\s(])sourcetype\s*=\s*"?([A-Za-z0-9_.*:-]+)"?', re.IGNORECASE)
MACRO_RE = re.compile(r"`([A-Za-z0-9_.:-]+)(?:\([^`]*\))?`")
TOKEN_PLACEHOLDER_RE = re.compile(r"\$([A-Za-z0-9_.:-]+)\$")
SAVEDSEARCH_RE = re.compile(r'\bsavedsearch\s+"?([^"|`\n]+?)"?(?:\s|\||$)', re.IGNORECASE)
XML_SEARCH_REF_RE = re.compile(r"<search\s+[^>]*\bref=[\"']([^\"']+)[\"']", re.IGNORECASE)
LOOKUP_RE = re.compile(r"\b(?:inputlookup|lookup)\s+([A-Za-z0-9_.-]+)", re.IGNORECASE)


def extract_dependencies(text: str) -> dict[str, list[str]]:
    return {
        "indexes": sorted(set(INDEX_RE.findall(text))),
        "sourcetypes": sorted(set(SOURCETYPE_RE.findall(text))),
        "macros": sorted(set(MACRO_RE.findall(text))),
        "tokens": sorted(set(TOKEN_PLACEHOLDER_RE.findall(text))),
        "saved_searches": sorted(
            {
                item.strip()
                for pattern in (SAVEDSEARCH_RE, XML_SEARCH_REF_RE)
                for item in pattern.findall(text)
                if item.strip()
            }
        ),
        "lookups": sorted(set(LOOKUP_RE.findall(text))),
    }


def merge_dependency_sets(*dependencies: dict[str, list[str]]) -> dict[str, list[str]]:
    merged: dict[str, set[str]] = {
        "indexes": set(),
        "sourcetypes": set(),
        "macros": set(),
        "tokens": set(),
        "saved_searches": set(),
        "lookups": set(),
        "chain_extends": set(),
    }
    for dependency in dependencies:
        for key in merged:
            merged[key].update(str(item) for item in dependency.get(key, []) if str(item).strip())
    return {key: sorted(values) for key, values in merged.items()}


def parse_dashboard_json(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if not raw.startswith("{"):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def dashboard_dependencies(row: dict[str, Any]) -> dict[str, list[str]]:
    raw = row_text(row, "eai:data", "data", "definition", "source")
    base_dependencies = extract_dependencies(raw)
    parsed = parse_dashboard_json(raw)
    if not parsed:
        return base_dependencies

    structured: dict[str, list[str]] = {
        "indexes": [],
        "sourcetypes": [],
        "macros": [],
        "tokens": [],
        "saved_searches": [],
        "lookups": [],
        "chain_extends": [],
    }
    data_sources = parsed.get("dataSources", {})
    if isinstance(data_sources, dict):
        for data_source_id, data_source in data_sources.items():
            if not isinstance(data_source, dict):
                continue
            options = data_source.get("options", {})
            if not isinstance(options, dict):
                options = {}
            data_type = str(data_source.get("type", ""))
            query = str(options.get("query", ""))
            structured = merge_dependency_sets(structured, extract_dependencies(query))
            if data_type == "ds.savedSearch" and options.get("ref"):
                structured["saved_searches"].append(str(options["ref"]))
            if data_type == "ds.chain" and options.get("extend"):
                structured["chain_extends"].append(str(options["extend"]))
            if data_type == "ds.search":
                query_parameters = options.get("queryParameters", {})
                if isinstance(query_parameters, dict):
                    structured = merge_dependency_sets(structured, extract_dependencies(json.dumps(query_parameters)))
            if data_source_id:
                structured["tokens"].extend(TOKEN_PLACEHOLDER_RE.findall(str(data_source_id)))
    return merge_dependency_sets(base_dependencies, structured)


def build_dashboard_dependency_graph(collector_results: dict[str, Any]) -> dict[str, Any]:
    results_by_id = {str(result.get("id", "")): result for result in collector_results_list(collector_results)}
    macro_rows = rows_from_result(results_by_id.get("global-macro-inventory", {}))
    saved_rows = rows_from_result(results_by_id.get("global-saved-search-inventory", {}))
    lookup_rows = rows_from_result(results_by_id.get("global-lookup-transform-inventory", {}))
    dashboard_rows = rows_from_result(results_by_id.get("global-dashboard-inventory", {}))

    macro_names = {
        re.sub(r"\(.*$", "", row_text(row, "title", "name"))
        for row in macro_rows
        if row_text(row, "title", "name")
    }
    saved_names = {row_text(row, "title", "name") for row in saved_rows if row_text(row, "title", "name")}
    lookup_names = {row_text(row, "title", "name") for row in lookup_rows if row_text(row, "title", "name")}

    dashboards: list[dict[str, Any]] = []
    dependencies: list[dict[str, str]] = []
    missing_macros: set[str] = set()
    missing_saved_searches: set[str] = set()
    missing_lookups: set[str] = set()
    unresolved_chain_extends: set[str] = set()

    for row in dashboard_rows:
        title = row_text(row, "title", "label", "name") or "unnamed_dashboard"
        refs = dashboard_dependencies(row)
        dashboards.append(
            {
                "title": title,
                "label": row_text(row, "label"),
                "app": row_text(row, "eai:acl.app"),
                "sharing": row_text(row, "eai:acl.sharing"),
                "refs": refs,
            }
        )
        data_source_ids = set()
        parsed = parse_dashboard_json(row_text(row, "eai:data", "data", "definition", "source"))
        if parsed and isinstance(parsed.get("dataSources"), dict):
            data_source_ids.update(str(item) for item in parsed["dataSources"])
        dependency_type = {
            "indexes": "index",
            "sourcetypes": "sourcetype",
            "macros": "macro",
            "saved_searches": "saved_search",
            "lookups": "lookup",
        }
        for kind in ("indexes", "sourcetypes", "macros", "saved_searches", "lookups"):
            target_type = dependency_type[kind]
            for target in refs.get(kind, []):
                dependencies.append({"from_type": "dashboard", "from": title, "to_type": target_type, "to": target})
        missing_macros.update(set(refs.get("macros", [])) - macro_names)
        missing_saved_searches.update(set(refs.get("saved_searches", [])) - saved_names)
        missing_lookups.update(set(refs.get("lookups", [])) - lookup_names)
        unresolved_chain_extends.update(set(refs.get("chain_extends", [])) - data_source_ids)

    saved_searches = []
    for row in saved_rows:
        title = row_text(row, "title", "name")
        refs = extract_dependencies(row_text(row, "search"))
        saved_searches.append(
            {
                "title": title,
                "app": row_text(row, "eai:acl.app"),
                "sharing": row_text(row, "eai:acl.sharing"),
                "disabled": row_value(row, "disabled"),
                "is_scheduled": row_value(row, "is_scheduled"),
                "refs": refs,
            }
        )
        missing_macros.update(set(refs.get("macros", [])) - macro_names)
        missing_lookups.update(set(refs.get("lookups", [])) - lookup_names)

    return {
        "generated_at": now_iso(),
        "dashboards": dashboards,
        "saved_searches": saved_searches,
        "macros": sorted(macro_names),
        "lookups": sorted(lookup_names),
        "dependencies": sorted(dependencies, key=lambda item: (item["from"], item["to_type"], item["to"])),
        "missing_macros": sorted(item for item in missing_macros if item),
        "missing_saved_searches": sorted(item for item in missing_saved_searches if item),
        "missing_lookups": sorted(item for item in missing_lookups if item),
        "unresolved_chain_extends": sorted(item for item in unresolved_chain_extends if item),
    }


def synthesize_source_result(source: dict[str, Any], result: dict[str, Any]) -> None:
    result_id = str(result.get("id", ""))
    rows = rows_from_result(result)
    if not result.get("ok", True):
        failures = get_path(source, "live_collection.failed_searches") or []
        failures = failures if isinstance(failures, list) else []
        failures.append({"id": result_id, "error": result.get("error", "unknown error")})
        assign_path(source, "live_collection.failed_searches", failures)
        return

    if result_id.endswith("-sample-freshness"):
        count = int(sum_field(rows, "count", "events"))
        assign_path(source, "sample_events.count", count)
        latest = max_field(rows, "latest", "max_time", "_time")
        if latest is not None:
            assign_path(source, "sample_events.latest_age_minutes", latest_age_minutes(latest))
        observed_indexes = sorted({row_text(row, "index") for row in rows if row_text(row, "index")})
        observed_sourcetypes = sorted({row_text(row, "sourcetype") for row in rows if row_text(row, "sourcetype")})
        if observed_indexes:
            assign_path(source, "indexes.observed", observed_indexes)
        if observed_sourcetypes:
            assign_path(source, "sourcetypes.observed", observed_sourcetypes)
        expected_indexes = [item for item in source_indexes(source) if item != "*"]
        expected_sourcetypes = [item for item in source_sourcetypes(source) if item != "*"]
        if expected_indexes and observed_indexes:
            assign_path(source, "indexes.missing", sorted(set(expected_indexes) - set(observed_indexes)))
        if expected_sourcetypes and observed_sourcetypes:
            assign_path(source, "sourcetypes.missing", sorted(set(expected_sourcetypes) - set(observed_sourcetypes)))
    elif result_id.endswith("-volume-latency-duplicates"):
        events = int(sum_field(rows, "events", "count"))
        if events:
            assign_path(source, "sample_events.seven_day_event_count", events)
        duplicate_rate = max_field(rows, "duplicate_rate_pct")
        if duplicate_rate is not None:
            assign_path(source, "sample_events.duplicate_rate_pct", round(duplicate_rate, 2))
        latency_seconds = max_field(rows, "max_latency_seconds", "avg_latency_seconds")
        if latency_seconds is not None:
            assign_path(source, "sample_events.ingest_latency_minutes", round(max(0.0, latency_seconds) / 60.0, 2))
    elif result_id.endswith("-fieldsummary"):
        observed_fields = sorted({row_text(row, "field", "Field") for row in rows if row_text(row, "field", "Field")})
        if observed_fields:
            assign_path(source, "parser.observed_fields", observed_fields)
            required = token_set(get_path(source, "cim.required_fields"))
            if required:
                assign_path(source, "cim.missing_required_fields", sorted(required - set(observed_fields)))
            ari_required = set()
            for profile in token_set(get_path(source, "ari.processing_profile.key_fields")):
                ari_required.add(profile)
            if ari_required:
                assign_path(source, "ari.missing_required_fields", sorted(ari_required - set(observed_fields)))
    elif result_id.endswith("-cim-tags-eventtypes"):
        observed_tags = sorted({row_text(row, "tag") for row in rows if row_text(row, "tag")})
        observed_eventtypes = sorted({row_text(row, "eventtype") for row in rows if row_text(row, "eventtype")})
        if observed_tags:
            assign_path(source, "cim.observed_tags", observed_tags)
        if observed_eventtypes:
            assign_path(source, "cim.observed_eventtypes", observed_eventtypes)
        expected_tags = token_set(get_path(source, "cim.expected_tags"))
        expected_eventtypes = token_set(get_path(source, "cim.expected_eventtypes"))
        if expected_tags and observed_tags:
            assign_path(source, "cim.missing_tags", sorted(expected_tags - set(observed_tags)))
        if expected_eventtypes and observed_eventtypes:
            assign_path(source, "cim.missing_eventtypes", sorted(expected_eventtypes - set(observed_eventtypes)))
    elif "-datamodel-" in result_id:
        count = int(sum_field(rows, "count"))
        samples = get_path(source, "data_models.data_model_samples") or []
        samples = samples if isinstance(samples, list) else []
        samples.append({"search_id": result_id, "count": count, "row_count": len(rows)})
        assign_path(source, "data_models.data_model_samples", samples)
        existing = parse_number(get_path(source, "cim.datamodel_sample_count")) or 0
        assign_path(source, "cim.datamodel_sample_count", int(existing + count))
    elif result_id.startswith("pack-"):
        pack = source.get("source_pack")
        if not isinstance(pack, dict):
            pack = {}
            source["source_pack"] = pack
        live_checks = pack.get("live_checks")
        if not isinstance(live_checks, dict):
            live_checks = {}
            pack["live_checks"] = live_checks
        live_checks[result_id] = {
            "ok": bool(result.get("ok", True)),
            "row_count": len(rows),
            "sample_count": int(sum_field(rows, "count", "events")),
        }


def synthesize_global_result(evidence: dict[str, Any], result: dict[str, Any]) -> None:
    result_id = str(result.get("id", ""))
    rows = rows_from_result(result)
    if result_id == "global-scheduled-content-execution":
        failed = []
        skipped = []
        quota = []
        for row in rows:
            status = row_text(row, "latest_status", "status").lower()
            reason = row_text(row, "reason", "latest_event")
            name = row_text(row, "savedsearch_name", "title", "name")
            item = {"name": name, "app": row_text(row, "app"), "host": row_text(row, "host"), "reason": reason}
            if "fail" in status or "error" in reason.lower():
                failed.append(item)
            if "skip" in status or "skip" in reason.lower():
                skipped.append(item)
            if "quota" in reason.lower():
                quota.append(item)
        if failed:
            assign_path(evidence, "scheduled_searches.failed", failed)
        if skipped:
            assign_path(evidence, "scheduled_searches.skipped", skipped)
        if quota:
            assign_path(evidence, "scheduler.quota_gaps", quota)
    elif result_id == "global-data-model-acceleration":
        disabled = []
        for row in rows:
            enabled = normalize_status(row_value(row, "acceleration.enabled", "acceleration"))
            if enabled in {"0", "false", "disabled", False}:
                disabled.append(row_text(row, "title", "name"))
        if disabled:
            assign_path(evidence, "data_models.acceleration_disabled", sorted(disabled))
    elif result_id == "global-hec-token-inventory":
        disabled_tokens = [
            row_text(row, "title", "name")
            for row in rows
            if normalize_status(row_value(row, "disabled")) in {"1", "true", True}
        ]
        if disabled_tokens:
            assign_path(evidence, "ingest.hec.disabled_tokens", sorted(disabled_tokens))
            assign_path(evidence, "ingest.destination_errors", sorted(disabled_tokens))
    elif result_id == "global-hec-health-internal":
        errors = int(sum_field(rows, "errors", "parser_errors", "disabled_token_requests"))
        if errors:
            assign_path(evidence, "ingest.hec.error_count", errors)
            assign_path(evidence, "ingest.destination_errors", [f"HEC reported {errors} errors/parser errors/disabled-token requests"])
    elif result_id == "global-deployment-client-health":
        stale = []
        now = datetime.now(timezone.utc).timestamp()
        for row in rows:
            last = parse_epoch_seconds(row_value(row, "lastPhoneHomeTime"))
            interval = parse_number(row_value(row, "averagePhoneHomeInterval")) or 60
            if last and (now - last) > max(7200, interval * 5):
                stale.append(row_text(row, "hostname", "dns", "ip"))
        if stale:
            assign_path(evidence, "collector_health.deployment_clients.stale", sorted(stale))
            assign_path(evidence, "ingest.pipeline_errors", [f"Deployment clients stale: {', '.join(sorted(stale))}"])
    elif result_id in {
        "global-sc4s-health",
        "global-sc4snmp-health",
        "global-otel-collector-health",
        "global-data-manager-health",
    }:
        collector = result_id.replace("global-", "").replace("-health", "")
        error_rows = [
            row
            for row in rows
            if row_text(row, "log_level").upper() in {"ERROR", "FATAL", "CRITICAL", "WARN", "WARNING"}
            or any(token in row_text(row, "latest_event").lower() for token in ("error", "failed", "exception", "dropped"))
        ]
        if error_rows:
            assign_path(
                evidence,
                f"collector_health.{collector}.errors",
                [
                    {
                        "host": row_text(row, "host"),
                        "sourcetype": row_text(row, "sourcetype"),
                        "log_level": row_text(row, "log_level"),
                        "latest_event": row_text(row, "latest_event"),
                    }
                    for row in error_rows[:20]
                ],
            )
            assign_path(evidence, "ingest.pipeline_errors", [f"{collector} emitted warning/error health events"])


def synthesize_evidence_from_collector_results(
    collector_results: dict[str, Any],
    base_evidence: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    evidence = json_clone(base_evidence)
    results = collector_results_list(collector_results)
    for result in results:
        data_source = str(result.get("data_source", ""))
        if data_source and data_source != "global":
            synthesize_source_result(ensure_source(evidence, data_source), result)
        else:
            synthesize_global_result(evidence, result)

    graph = build_dashboard_dependency_graph(collector_results)
    if graph["dashboards"] or graph["saved_searches"]:
        assign_path(
            evidence,
            "dashboards.dependency_graph",
            {
                "dashboard_count": len(graph["dashboards"]),
                "saved_search_count": len(graph["saved_searches"]),
                "dependency_count": len(graph["dependencies"]),
            },
        )
    if graph["missing_macros"]:
        assign_path(evidence, "dashboards.missing_macros", graph["missing_macros"])
    if graph["missing_saved_searches"]:
        assign_path(evidence, "dashboards.saved_search_reference_gaps", graph["missing_saved_searches"])
    if graph["missing_lookups"]:
        assign_path(evidence, "dashboards.lookup_permission_gaps", graph["missing_lookups"])
    if graph["unresolved_chain_extends"]:
        assign_path(evidence, "dashboards.chain_search_gaps", graph["unresolved_chain_extends"])

    source_names = sorted(
        {
            str(result.get("data_source", ""))
            for result in results
            if str(result.get("data_source", "")) and str(result.get("data_source", "")) != "global"
        }
    )
    synthesis = {
        "generated_at": now_iso(),
        "collector_result_count": len(results),
        "collector_live_executed": bool(collector_results.get("live_executed", False)),
        "source_count": len(source_names),
        "sources": source_names,
        "dashboard_count": len(graph["dashboards"]),
        "saved_search_count": len(graph["saved_searches"]),
        "missing_macro_count": len(graph["missing_macros"]),
        "missing_saved_search_count": len(graph["missing_saved_searches"]),
        "missing_lookup_count": len(graph["missing_lookups"]),
    }
    evidence["live_synthesis"] = synthesis
    return evidence, graph, synthesis


def write_synthesis_outputs(
    output_dir: Path,
    synthesized_evidence: dict[str, Any],
    graph: dict[str, Any],
    synthesis_report: dict[str, Any],
) -> None:
    write_file(output_dir / "evidence" / "live-evidence.synthesized.json", json_dumps(redact(synthesized_evidence)))
    write_file(output_dir / "dashboard-dependency-graph.json", json_dumps(redact(graph)))
    write_file(output_dir / "synthesis-report.json", json_dumps(synthesis_report))


def load_collector_results(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    path = Path(args.collector_results_file).expanduser() if args.collector_results_file else output_dir / "live-collector-results.redacted.json"
    return load_json_file(path)


def run_live_collection(args: argparse.Namespace, evidence: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    manifest = collector_manifest(evidence)
    result: dict[str, Any] = {
        "generated_at": now_iso(),
        "live_executed": False,
        "ok": True,
        "search_count_available": manifest["search_count"],
        "search_count_executed": 0,
        "max_rows": args.max_rows,
        "max_searches": args.max_searches,
        "results": [],
    }
    if not args.splunk_uri or not args.session_key_file:
        result["message"] = "Live collection skipped because --splunk-uri and --session-key-file were not both supplied."
        write_file(output_dir / "live-collector-results.redacted.json", json_dumps(result))
        return result
    if args.max_rows < 1:
        die("--max-rows must be at least 1")
    if args.max_searches < 1:
        die("--max-searches must be at least 1")
    if args.collect_timeout_seconds < 1:
        die("--collect-timeout-seconds must be at least 1")

    session_key = read_session_key_file(args.session_key_file)
    specs = manifest["searches"][: args.max_searches]
    result["live_executed"] = True
    result["search_count_executed"] = len(specs)
    result["splunk_uri"] = normalize_splunk_uri(args.splunk_uri)
    result["tls_verification"] = not args.no_verify_tls
    for spec in specs:
        search_result = execute_export_search(args, session_key, spec)
        result["results"].append(search_result)
        if not search_result.get("ok", False):
            result["ok"] = False
    write_file(output_dir / "live-collector-results.redacted.json", json_dumps(result))
    return result


def build_report_payload(
    args: argparse.Namespace,
    evidence: dict[str, Any],
    registry: dict[str, Any],
    source_packs: dict[str, Any],
    platform: str,
    targets: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    findings = evaluate_rules(evidence, platform)
    scores = build_scores(findings, targets)
    source_scores = build_source_scores(findings, targets)
    coverage = build_coverage(findings, targets)
    report = {
        "skill": SKILL_NAME,
        "generated_at": now_iso(),
        "platform": platform,
        "targets": targets,
        "target_search_head": args.target_search_head,
        "splunk_uri": args.splunk_uri,
        "data_sources": [
            {
                "name": source.get("name"),
                "app_name": source.get("app_name", ""),
                "skill": source.get("skill", ""),
                "splunkbase_id": source.get("splunkbase_id", ""),
                "registry": source.get("registry", {}),
                "source_pack": {
                    key: value
                    for key, value in source.get("source_pack", {}).items()
                    if key != "collection_searches"
                }
                if isinstance(source.get("source_pack"), dict)
                else {},
            }
            for source in evidence.get("data_sources", [])
            if isinstance(source, dict)
        ],
        "findings": findings,
        "scores": scores,
        "source_scores": source_scores,
        "coverage": coverage,
        "catalog": {
            "rule_count": len(RULE_CATALOG),
            "domain_count": len(COVERAGE_MANIFEST),
            "source_pack_count": len(source_packs.get("packs", [])),
            "required_rule_fields": sorted(REQUIRED_RULE_FIELDS),
        },
    }
    fix_plan = build_fix_plan(findings)
    return report, fix_plan


def build_report(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    catalog_validation = validate_catalog()
    if not catalog_validation["ok"]:
        die("Catalog validation failed: " + "; ".join(catalog_validation["errors"]))

    registry = load_registry(Path(args.registry_file).expanduser())
    source_packs = load_source_packs(Path(args.source_packs_file).expanduser())
    registry_index = build_registry_index(registry)
    evidence, platform, targets = normalized_evidence(args, registry_index, source_packs)
    report, fix_plan = build_report_payload(args, evidence, registry, source_packs, platform, targets)
    return report, fix_plan, evidence, registry, source_packs


def text_summary(report: dict[str, Any]) -> str:
    score_parts = ", ".join(
        f"{target}={item['score']}:{item['status']}"
        for target, item in report["scores"].items()
    )
    lines = [
        f"Splunk Data Source Readiness Doctor generated {len(report['findings'])} finding(s) for {len(report['data_sources'])} data source(s).",
        f"Scores: {score_parts}",
        "Reports: readiness-report.md, readiness-report.json, fix-plan.md, fix-plan.json, coverage-report.json, source-pack-report.json, collector-manifest.json, collection-searches.spl",
    ]
    if report["findings"]:
        top = report["findings"][0]
        lines.append(f"Top finding: {top['id']} ({top['severity']}) on {top['data_source']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()

    if args.phase == "validate":
        validation = validate_catalog()
        source_pack_payload = load_json_file(Path(args.source_packs_file).expanduser())
        source_pack_validation = validate_source_packs_payload(source_pack_payload)
        validation["source_pack_count"] = source_pack_validation["source_pack_count"]
        validation["source_pack_errors"] = source_pack_validation["errors"]
        validation["source_pack_warnings"] = source_pack_validation["warnings"]
        validation["ok"] = validation["ok"] and source_pack_validation["ok"]
        if args.json:
            print(json_dumps(validation), end="")
        elif validation["ok"]:
            print(
                f"Splunk Data Source Readiness Doctor catalog OK: "
                f"{validation['rule_count']} rules, {validation['domain_count']} domains, "
                f"{validation['source_pack_count']} source packs."
            )
        else:
            print("Splunk Data Source Readiness Doctor catalog errors:", file=sys.stderr)
            for error in validation["errors"]:
                print(f"  - {error}", file=sys.stderr)
            for error in validation["source_pack_errors"]:
                print(f"  - {error}", file=sys.stderr)
        return 0 if validation["ok"] else 1

    if args.phase == "status":
        status = render_status(output_dir)
        if args.json:
            print(json_dumps(status), end="")
        else:
            print(status["message"] if not status["ok"] else f"Report available: {status['report_path']} ({status['finding_count']} findings)")
        return 0 if status["ok"] else 1

    if args.phase == "source-packs":
        source_packs = load_source_packs(Path(args.source_packs_file).expanduser())
        catalog = source_pack_catalog(source_packs, source_pack_ids(args.source_pack))
        output_dir.mkdir(parents=True, exist_ok=True)
        write_file(output_dir / "source-pack-catalog.json", json_dumps(catalog))
        if args.json:
            print(json_dumps(catalog), end="")
        else:
            print(f"Source pack catalog: {catalog['source_pack_count']} pack(s).")
            for pack in catalog["packs"]:
                print(f"- {pack['id']}: {pack['label']}")
        return 0

    report, fix_plan, evidence, registry, source_packs = build_report(args)

    synthesis_result: dict[str, Any] | None = None
    if args.phase == "synthesize":
        collector_results = load_collector_results(args, output_dir)
        synthesized_evidence, graph, synthesis_report = synthesize_evidence_from_collector_results(collector_results, evidence)
        evidence = synthesized_evidence
        report, fix_plan = build_report_payload(
            args,
            evidence,
            registry,
            source_packs,
            report["platform"],
            report["targets"],
        )
        synthesis_result = {
            "synthesis": synthesis_report,
            "dashboard_dependency_graph": graph,
            "report": report,
        }

    if args.dry_run:
        payload: Any = fix_plan if args.phase == "fix-plan" else report
        if args.phase == "apply":
            payload = {
                "dry_run": True,
                "selected_fixes": selected_fix_ids(args.fixes),
                "would_render_packets": True,
                "live_mutation_performed": False,
            }
        if args.json:
            print(json_dumps(payload), end="")
        else:
            print(text_summary(report), end="")
        return 0

    write_base_outputs(output_dir, report, fix_plan, evidence, registry, source_packs)

    result: Any = report
    if args.phase == "fix-plan":
        result = fix_plan
    elif args.phase == "apply":
        result = apply_selected_fixes(output_dir, report["findings"], selected_fix_ids(args.fixes))
    elif args.phase == "collect":
        result = run_live_collection(args, evidence, output_dir)
        synthesized_evidence, graph, synthesis_report = synthesize_evidence_from_collector_results(result, evidence)
        write_synthesis_outputs(output_dir, synthesized_evidence, graph, synthesis_report)
        result["synthesis"] = synthesis_report
    elif args.phase == "synthesize":
        assert synthesis_result is not None
        write_synthesis_outputs(
            output_dir,
            evidence,
            synthesis_result["dashboard_dependency_graph"],
            synthesis_result["synthesis"],
        )
        result = synthesis_result

    if args.json:
        print(json_dumps(result), end="")
    else:
        print(text_summary(report), end="")
        if args.phase == "apply":
            print(f"Selected fix packets written under {output_dir}.")

    if args.strict and any(SEVERITY_RANK[item["severity"]] >= SEVERITY_RANK["high"] for item in report["findings"]):
        return 2
    if args.phase == "collect" and args.strict and not result.get("ok", True):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

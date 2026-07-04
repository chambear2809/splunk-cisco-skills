#!/usr/bin/env python3
"""Render a lifecycle-aware Cisco Data Fabric coverage and delegation packet."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import Any


SKILL_NAME = "cisco-data-fabric-setup"
REPO_ROOT = Path(__file__).resolve().parents[3]
RESEARCH_VERIFIED = "2026-07-03"
SECTIONS = [
    "data-management",
    "federation",
    "storage-catalog",
    "ai-activation",
    "context-governance",
    "experience",
]
EXECUTABLE_SECTIONS = {
    "data-management",
    "federation",
    "ai-activation",
    "context-governance",
}
HANDOFF_ONLY_SECTIONS = {"storage-catalog", "experience"}
ALLOWED_REPO_STATUSES = {
    "delegated_apply",
    "delegated_render",
    "render",
    "ui_handoff",
    "validation",
    "not_applicable",
}
ALLOWED_PRODUCT_STAGES = {
    "architecture",
    "ga",
    "available",
    "controlled_availability",
    "alpha",
    "feature_preview",
    "roadmap",
    "deprecated",
    "version_dependent",
}
DIRECT_SECRET_FLAGS = {
    "--access-token",
    "--api-key",
    "--api-token",
    "--authorization",
    "--bearer-token",
    "--client-secret",
    "--password",
    "--private-key",
    "--secret",
    "--token",
}
SECRET_KEY_RE = re.compile(
    r"(^|_)(access_token|api_key|api_token|authorization|bearer_token|client_secret|password|private_key|secret|token)($|_)"
)
SECRET_KEY_ALLOW_SUFFIXES = (
    "_file",
    "_files",
    "_path",
    "_paths",
    "_ref",
    "_refs",
    "_name",
    "_names",
    "_id",
    "_ids",
    "_url",
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|splunk)\s+[A-Za-z0-9._=-]{12,}"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)://[^/@\s:]+:[^/@\s]+@"),
    re.compile(r"(?i)[?&](?:access_token|api_key|api_token|client_secret|password|secret|token)=[^&\s]{8,}"),
)

SOURCE_RECORDS = {
    "cdf_launch": {
        "title": "Cisco Data Fabric launch announcement",
        "url": "https://newsroom.cisco.com/c/r/newsroom/en/us/a/y2025/m09/cisco-data-fabric-transforms-machine-data-into-ai-ready-intelligence.html",
        "source_type": "announcement",
        "source_version": "2025-09-08",
    },
    "cdf_launch_blog": {
        "title": "Powering AI Innovation with Splunk: Meet the Cisco Data Fabric",
        "url": "https://www.splunk.com/en_us/blog/platform/powering-ai-innovation-with-splunk-meet-the-cisco-data-fabric.html",
        "source_type": "product_blog",
        "source_version": "2025-09-08",
    },
    "data_management_guide": {
        "title": "Complete Guide to Splunk Data Management",
        "url": "https://www.splunk.com/en_us/blog/platform/the-complete-guide-to-splunk-data-management.html",
        "source_type": "product_blog",
        "source_version": "2026-04-20",
    },
    "ai_data_management": {
        "title": "Accelerating Data Intelligence with AI-Powered Data Management",
        "url": "https://www.splunk.com/en_us/blog/artificial-intelligence/accelerating-data-intelligence-with-ai-powered-data-management.html",
        "source_type": "product_blog",
        "source_version": "2026-03-11",
    },
    "cisco_live_2026": {
        "title": "New Splunk Platform Innovations at Cisco Live 2026",
        "url": "https://www.splunk.com/en_us/blog/platform/new-splunk-platform-innovations-cisco-live-2026.html",
        "source_type": "product_blog",
        "source_version": "2026-06-02",
    },
    "agentic_layers": {
        "title": "Turning Cisco Data Fabric Vision into Agentic Operations Reality",
        "url": "https://www.splunk.com/en_us/blog/leadership/turning-cisco-data-fabric-vision-into-agentic-operations-reality.html",
        "source_type": "architecture_blog",
        "source_version": "2026-06-15",
    },
    "agentic_ops": {
        "title": "Splunk at Cisco Live: Trusted Agentic Operations",
        "url": "https://www.splunk.com/en_us/blog/leadership/splunk-cisco-live-agentic-operations.html",
        "source_type": "product_blog",
        "source_version": "2026-06-02",
    },
    "federated_overview": {
        "title": "Splunk Cloud 10.5 federated search options",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/welcome-to-splunk-federated-search/overview-of-the-federated-search-options-for-the-splunk-platform",
        "source_type": "product_documentation",
        "source_version": "10.5.2605",
    },
    "federated_ga": {
        "title": "General availability of Federated Search with new capabilities",
        "url": "https://www.splunk.com/en_us/blog/platform/unifying-your-data-with-federated-search.html",
        "source_type": "product_blog",
        "source_version": "2026-05-18",
    },
    "federated_s3": {
        "title": "Federated Search for Amazon S3",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/run-federated-searches-over-amazon-s3-datasets/overview-of-federated-search-for-amazon-s3",
        "source_type": "product_documentation",
        "source_version": "10.5.2605",
    },
    "federated_azure": {
        "title": "Federated Search for Microsoft Azure",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/run-federated-searches-over-microsoft-azure-datasets/about-federated-search-for-microsoft-azure",
        "source_type": "product_documentation",
        "source_version": "10.5.2605",
    },
    "federated_databricks": {
        "title": "Federated Search for Azure Databricks",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/run-federated-searches-over-azure-databricks-datasets/about-federated-search-for-azure-databricks",
        "source_type": "product_documentation",
        "source_version": "10.5.2605",
    },
    "federated_snowflake": {
        "title": "Federated Search for Snowflake",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/run-federated-searches-over-snowflake-datasets/about-federated-search-for-snowflake",
        "source_type": "product_documentation",
        "source_version": "10.5.2605",
    },
    "federated_ddss": {
        "title": "Federated Search for DDSS",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/run-federated-searches-over-ddss-datasets/about-federated-search-for-ddss",
        "source_type": "product_documentation",
        "source_version": "10.5.2605",
    },
    "federated_asl": {
        "title": "Federated Analytics for Amazon Security Lake",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/ingest-and-search-amazon-security-lake-datasets/about-federated-analytics",
        "source_type": "product_documentation",
        "source_version": "10.5.2605",
    },
    "federated_asl_ga": {
        "title": "Federated Analytics general availability",
        "url": "https://www.splunk.com/en_us/blog/security/federated-analytics-analyze-data-wherever-it-resides-for-rapid-and-holistic-security-visibility.html",
        "source_type": "product_blog",
        "source_version": "2024-11-12",
    },
    "federated_legacy": {
        "title": "Legacy Amazon S3 federated provider",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/search-data-stored-in-amazon-s3-legacy/begin-defining-an-amazon-s3-federated-provider",
        "source_type": "product_documentation",
        "source_version": "10.5.2605",
    },
    "catalog": {
        "title": "Discover data using the Catalog",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/search/discover-data-using-the-catalog/10.5.2605/discovering-data-for-your-investigations-using-the-catalog",
        "source_type": "product_documentation",
        "source_version": "10.5.2605",
    },
    "promote": {
        "title": "General availability of Promote",
        "url": "https://www.splunk.com/en_us/blog/platform/general-availability-promote-in-splunk-cloud-platform.html",
        "source_type": "product_blog",
        "source_version": "2026-01-28",
    },
    "data_inputs": {
        "title": "Data Inputs service details (formerly Data Manager)",
        "url": "https://help.splunk.com/en/data-management/ingest-data-from-cloud-sources/data-inputs-service-description/1.17/data-manager/data-inputs-service-details",
        "source_type": "product_documentation",
        "source_version": "1.17",
    },
    "ingest_monitoring": {
        "title": "Ingest Monitoring 1.2",
        "url": "https://help.splunk.com/en/data-management/monitor-and-troubleshoot/ingest-monitoring/1.2/about-ingest-monitoring",
        "source_type": "product_documentation",
        "source_version": "1.2",
    },
    "ai_toolkit": {
        "title": "AI Toolkit 5.7.4 release notes",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.4/release-notes/whats-new-in-the-ai-toolkit",
        "source_type": "product_documentation",
        "source_version": "5.7.4",
    },
    "agent_builder_preview": {
        "title": "AI Toolkit Agent Builder feature preview",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.6.4/ai-toolkit-commands-macros-and-visualizations/feature-preview-ai-toolkit-agent-builder",
        "source_type": "product_documentation",
        "source_version": "5.6.4-preview",
    },
    "cdtsm": {
        "title": "Cisco Deep Time Series Model feature preview",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.4/ai-toolkit-models/feature-preview-cisco-deep-time-series-model",
        "source_type": "product_documentation",
        "source_version": "5.7.4",
    },
    "ctsm": {
        "title": "Cisco Time Series Model 1.0 model card",
        "url": "https://huggingface.co/cisco-ai/cisco-time-series-model-1.0",
        "source_type": "model_card",
        "source_version": "1.0",
    },
    "mcp": {
        "title": "About MCP Server for Splunk Platform",
        "url": "https://help.splunk.com/en/splunk-enterprise/mcp-server-for-splunk-platform/1.1/about-mcp-server-for-splunk-platform",
        "source_type": "product_documentation",
        "source_version": "1.1",
    },
    "mcp_oauth": {
        "title": "OAuth for MCP Server",
        "url": "https://help.splunk.com/en/splunk-cloud-platform/mcp-server-for-splunk-platform/1.2/oauth-for-mcp-server",
        "source_type": "product_documentation",
        "source_version": "1.2.1",
    },
    "cloud_control": {
        "title": "Cisco Cloud Control Getting Started",
        "url": "https://cloud.cisco.com/docs/en/cisco-cloud-control-getting-started/cisco-cloud-control-getting-started.html",
        "source_type": "product_documentation",
        "source_version": "2026-07",
    },
    "cloud_control_agent_builder": {
        "title": "Announcing Cisco Cloud Control Agent Builder",
        "url": "https://blogs.cisco.com/ai/announcing-cisco-cloud-control-agent-builder",
        "source_type": "announcement",
        "source_version": "2026-06",
    },
    "cloud_control_splunk": {
        "title": "Integrating Splunk Cloud Platform with Cisco Cloud Control",
        "url": "https://lantern.splunk.com/Splunk_and_Cisco_Use_Cases/Connecting_the_Splunk_platform_to_Cisco_Cloud_Control_and_AI_Canvas/Integrating_Splunk_Cloud_Platform_with_Cisco_Cloud_Control",
        "source_type": "implementation_guidance",
        "source_version": "2026-06",
    },
    "ai_canvas": {
        "title": "Integrating Splunk Cloud Platform with AI Canvas",
        "url": "https://lantern.splunk.com/Splunk_and_Cisco_Use_Cases/Connecting_the_Splunk_platform_to_Cisco_Cloud_Control_and_AI_Canvas/Integrating_Splunk_Cloud_Platform_with_AI_Canvas",
        "source_type": "implementation_guidance",
        "source_version": "2026-07",
    },
    "sal": {
        "title": "Cisco Security Analytics and Logging",
        "url": "https://www.cisco.com/site/us/en/products/security/security-analytics/security-analytics-logging/index.html",
        "source_type": "product_page",
        "source_version": "2026",
    },
}


def capability(
    key: str,
    layer: str,
    title: str,
    stage: str,
    status: str,
    owner: str,
    platforms: str,
    source: str,
    boundary: str,
    section: str,
    flag: str = "",
    access_requirement: str = "none",
) -> dict[str, str]:
    return {
        "key": key,
        "layer": layer,
        "title": title,
        "product_stage": stage,
        "repo_status": status,
        "owner": owner,
        "platforms": platforms,
        "source": source,
        "boundary": boundary,
        "section": section,
        "flag": flag,
        "access_requirement": access_requirement,
    }


CAPABILITIES = [
    capability("cdf_architecture", "architecture", "Cisco Data Fabric architecture", "architecture", "render", SKILL_NAME, "Splunk Enterprise and Splunk Cloud", "data_management_guide", "Architecture powered by Splunk, not a standalone package, SKU, UI, or API.", "data-management"),
    capability("splunk_platform_foundation", "architecture", "Splunk Platform foundation", "available", "validation", "Splunk platform skills", "Splunk Enterprise and Splunk Cloud", "cdf_launch", "Validate the actual deployment, version, topology, and entitlements.", "data-management"),
    capability("cross_domain_operations", "architecture", "SecOps, ITOps, Engineering, and NetOps", "architecture", "render", "Cisco and Splunk domain skills", "Cross-domain", "agentic_layers", "Domains and consumers are not interchangeable Data Fabric products.", "experience"),
    capability("open_hybrid_architecture", "architecture", "Open hybrid and multicloud architecture", "architecture", "render", SKILL_NAME, "Edge, on-premises, and cloud", "cdf_launch", "No universal Cisco Data Fabric management API is claimed.", "data-management"),
    capability("source_collection", "data_management", "Machine-data collection and onboarding", "available", "delegated_render", "Cisco TAs, OTel, UF, HEC, SC4S, Data Inputs", "Source dependent", "data_management_guide", "Use the source-specific skill and validate ingest, schema, and downstream usability.", "data-management", "data_management_enabled"),
    capability("data_inputs", "data_management", "Data Inputs (formerly Data Manager)", "available", "delegated_render", "splunk-cloud-data-manager-setup", "Splunk Cloud", "data_inputs", "Cloud-source onboarding and S3 Promote are distinct from the Data Management app.", "storage-catalog", "storage_catalog_enabled"),
    capability("edge_processor", "data_management", "Edge Processor", "available", "delegated_render", "splunk-edge-processor-setup", "Customer-managed runtime with Splunk control plane", "data_management_guide", "Requires tenant activation and reviewed target settings.", "data-management", "edge_processor_enabled", access_requirement="tenant_activation"),
    capability("ingest_processor", "data_management", "Ingest Processor", "available", "delegated_render", "splunk-ingest-processor-setup", "Splunk Cloud Victoria Experience", "data_management_guide", "Do not render canned source/destination objects as customer configuration.", "data-management", "ingest_processor_enabled"),
    capability("spl2_pipelines", "data_management", "SPL2 pipelines", "version_dependent", "delegated_render", "splunk-spl2-pipeline-kit", "Execution-profile dependent", "data_management_guide", "Lint against the intended Edge, Ingest, or federated-search runtime profile.", "data-management", "spl2_enabled"),
    capability("filter_shape_route_tier", "data_management", "Filter, shape, redact, route, and tier", "available", "delegated_render", "Edge Processor, Ingest Processor, SPL2 kit", "Pipeline dependent", "cdf_launch", "Preview representative data and validate duplication, loss, privacy, and cost effects.", "data-management", "data_management_enabled"),
    capability("automated_field_extraction", "data_management", "Automated Field Extraction", "controlled_availability", "ui_handoff", "splunk-ingest-processor-setup", "Region-gated Splunk Cloud", "ai_data_management", "Review generated extractions; no private API automation.", "data-management", "afe_enabled"),
    capability("guided_onboarding_auto_schematization", "data_management", "Guided Onboarding with Auto-Schematization", "alpha", "ui_handoff", "splunk-ingest-processor-setup", "Alpha program", "ai_data_management", "Review generated schemas and mappings before production use.", "data-management", "guided_onboarding_enabled"),
    capability("ingest_monitoring", "data_management", "Ingest Monitoring 1.2", "ga", "validation", "splunk-data-source-readiness-doctor", "Splunk Cloud and Splunk Enterprise where supported", "ingest_monitoring", "Validate volume, event count, latency, no-ingestion, alerts, and investigation workflows.", "context-governance", "ingest_monitoring_enabled"),
    capability("fss2s", "federation", "Federated Search for Splunk", "available", "delegated_render", "splunk-federated-search-setup", "Splunk Enterprise and Splunk Cloud combinations", "federated_overview", "Standard and transparent modes have distinct topology and knowledge-object rules.", "federation", "federation_enabled"),
    capability("federated_s3", "federation", "Federated Search for Amazon S3", "ga", "ui_handoff", "splunk-federated-search-setup", "AWS-hosted Splunk Cloud", "federated_ga", "Use current Data Management connections/datasets, catalogs, RBAC, and DSU review.", "federation", "federation_enabled", access_requirement="sales_activation_and_scan_entitlement"),
    capability("federated_azure", "federation", "Federated Search for Microsoft Azure", "controlled_availability", "ui_handoff", "splunk-federated-search-setup", "AWS-hosted Splunk Cloud", "federated_azure", "ADLS/Blob, Entra, allowlist, catalog, role, and tenant activation requirements apply.", "federation", "federation_enabled", access_requirement="controlled_availability_enrollment_and_sales_activation"),
    capability("federated_databricks", "federation", "Federated Search for Azure Databricks", "controlled_availability", "ui_handoff", "splunk-federated-search-setup", "AWS-hosted Splunk Cloud", "federated_databricks", "Unity Catalog, Delta Sharing, runtime, role, and activation requirements apply.", "federation", "federation_enabled", access_requirement="controlled_availability_enrollment_and_sales_activation"),
    capability("federated_snowflake", "federation", "Federated Search for Snowflake", "available", "ui_handoff", "splunk-federated-search-setup", "AWS-hosted Splunk Cloud and AWS-hosted Snowflake", "federated_snowflake", "PAT, role, network policy, warehouse, database, schema, and activation requirements apply.", "federation", "federation_enabled", access_requirement="sales_activation_and_scan_entitlement"),
    capability("federated_ddss", "federation", "Federated Search for DDSS", "available", "ui_handoff", "splunk-federated-search-setup", "AWS-hosted Splunk Cloud with S3 DDSS", "federated_ddss", "No Azure/GCP DDSS federation; SQS and catalog synchronization are required.", "federation", "federation_enabled", access_requirement="sales_activation_and_scan_entitlement"),
    capability("federated_amazon_security_lake", "federation", "Federated Analytics for Amazon Security Lake", "ga", "ui_handoff", "splunk-federated-search-setup", "AWS-hosted Splunk Cloud", "federated_asl_ga", "Keep recent indexed detection and historical federated hunting paths distinct from generic S3.", "federation", "federation_enabled", access_requirement="premium_add_on_activation_and_scan_entitlement"),
    capability("aws_glue_catalog", "catalog", "AWS Glue data catalog", "available", "ui_handoff", "splunk-federated-search-setup", "Supported Amazon S3 datasets", "federated_s3", "Apply generated IAM, S3, Glue, and KMS policies through the owning cloud workflow.", "storage-catalog", "storage_catalog_enabled"),
    capability("iceberg_rest_catalog", "catalog", "Apache Iceberg REST catalog", "available", "ui_handoff", "splunk-federated-search-setup", "Supported Amazon S3 datasets", "federated_s3", "Authorization-requiring REST catalogs are not currently supported.", "storage-catalog", "storage_catalog_enabled"),
    capability("splunk_native_dataset_catalog", "catalog", "Splunk-native per-dataset catalog", "available", "ui_handoff", "splunk-federated-search-setup", "Supported external datasets", "federated_s3", "Crawler/manual schema, partitions, time fields, and synchronization require validation.", "storage-catalog", "storage_catalog_enabled"),
    capability("delta_lake_table_format", "catalog", "Delta Lake table format", "version_dependent", "ui_handoff", "splunk-federated-search-setup", "Supported catalog paths", "federated_s3", "Table format support is not a generic writable destination or independent provider.", "storage-catalog", "storage_catalog_enabled"),
    capability("iceberg_table_format", "catalog", "Apache Iceberg table format", "version_dependent", "ui_handoff", "splunk-federated-search-setup", "Supported catalog paths", "federated_s3", "Keep table format, catalog, and storage location distinct.", "storage-catalog", "storage_catalog_enabled"),
    capability("routing_plus_federation", "federation", "Data routing plus federated search", "version_dependent", "ui_handoff", "Edge Processor, Ingest Processor, Federated Search", "Documented S3 and Azure workflows", "federated_s3", "Do not project the combined workflow onto every target.", "federation", "federation_enabled"),
    capability("federated_rbac_dsu", "governance", "Federated dataset RBAC and scan entitlement", "available", "validation", "splunk-federated-search-setup", "Target dependent", "federated_overview", "Validate edit_connections/edit_datasets, per-dataset access, activation, DSU, and usage monitoring.", "context-governance", "federation_enabled", access_requirement="target_specific_roles_activation_and_scan_entitlement"),
    capability("legacy_fss3_migration", "federation", "Legacy Amazon S3 provider/index migration", "deprecated", "ui_handoff", "splunk-federated-search-setup", "Splunk Cloud 10.5", "federated_legacy", "Do not create new legacy providers; verify migrated Data Management connections and datasets.", "federation", "federation_enabled"),
    capability("splunk_index", "storage", "Splunk index real-time execution layer", "ga", "validation", "Splunk platform/index skills", "Splunk Enterprise and Splunk Cloud", "agentic_layers", "Use indexed storage for low-latency correlation, alerting, and detections.", "storage-catalog", "splunk_index_enabled"),
    capability("machine_data_lake", "storage", "Splunk Machine Data Lake", "alpha", "ui_handoff", SKILL_NAME, "Alpha/tenant dependent", "cisco_live_2026", "No public provisioning contract; verify entitlement, region, retention, security, and current UI evidence.", "storage-catalog", "machine_data_lake_enabled"),
    capability("global_catalog", "catalog", "Global Splunk Catalog discovery UI", "version_dependent", "ui_handoff", SKILL_NAME, "Splunk Cloud 10.5 gradual rollout", "catalog", "Distinguish global discovery from per-dataset catalogs and MDL cataloging.", "storage-catalog", "data_catalog_enabled"),
    capability("machine_data_lake_catalog", "catalog", "Machine Data Lake automatic cataloging and enrichment", "alpha", "ui_handoff", SKILL_NAME, "Alpha/tenant dependent", "cisco_live_2026", "Do not infer general lineage, policy-engine, or CRUD capabilities.", "storage-catalog", "machine_data_lake_enabled"),
    capability("promote_s3", "storage", "Promote historical Amazon S3 data", "ga", "delegated_render", "splunk-cloud-data-manager-setup", "Eligible Splunk Cloud Data Inputs", "promote", "Selective ingestion into indexed Splunk; not proven to be a rename of Replay S3.", "storage-catalog", "storage_catalog_enabled"),
    capability("ddss_ddaa_smartstore", "storage", "DDSS, DDAA, and SmartStore lifecycle adjacencies", "version_dependent", "render", "Federated Search, DDAA, ACS, SmartStore skills", "Product/topology dependent", "data_management_guide", "These are distinct from Machine Data Lake and from arbitrary external buckets.", "storage-catalog", "storage_catalog_enabled"),
    capability("knowledge_graph", "context", "Knowledge graph", "roadmap", "ui_handoff", "splunk-itsi-config,splunk-knowledge-objects-setup", "Architecture concept", "agentic_layers", "No independent public Cisco Data Fabric configuration surface is claimed.", "context-governance", "context_governance_enabled"),
    capability("business_context", "context", "Business and service context", "architecture", "delegated_render", "splunk-itsi-config,splunk-cim-data-model-setup,splunk-knowledge-objects-setup", "Splunk feature dependent", "agentic_layers", "Model entities, relationships, schema, ownership, and business impact explicitly.", "context-governance", "context_governance_enabled"),
    capability("ai_toolkit", "ai_action", "Splunk AI Toolkit 5.7.4 and PSC 4.3.2", "ga", "delegated_render", "splunk-ai-ml-toolkit-setup", "Search tier", "ai_toolkit", "Owning skill validates package compatibility, placement, and model permissions.", "ai-activation", "ai_toolkit_enabled"),
    capability("dsdl", "ai_action", "DSDL and external model runtimes", "available", "delegated_render", "splunk-ai-ml-toolkit-setup", "External runtime plus search tier", "ai_toolkit", "Keep runtime, image, TLS, network, GPU, and governance ownership explicit.", "ai-activation", "ai_toolkit_enabled"),
    capability("hosted_models", "ai_action", "Hosted Foundation-Sec and GPT-OSS models", "version_dependent", "delegated_render", "splunk-ai-ml-toolkit-setup", "Eligible Splunk Cloud", "ai_toolkit", "Confirm tenant/model availability and data-governance boundary.", "ai-activation", "ai_toolkit_enabled"),
    capability("cdtsm", "ai_action", "Cisco Deep Time Series Model", "feature_preview", "delegated_render", "splunk-ai-ml-toolkit-setup", "AI Toolkit feature preview/hosted beta", "cdtsm", "Do not conflate hosted CDTSM with the open Cisco Time Series Model.", "ai-activation", "ai_toolkit_enabled"),
    capability("ctsm_open_model", "ai_action", "Cisco Time Series Model 1.0 open model", "available", "render", SKILL_NAME, "Open-weight/self-hosted model", "ctsm", "Apache-2.0 model and cisco-tsm package are available; platform integration is separate.", "ai-activation", "ai_activation_enabled"),
    capability("splunk_agent_builder", "ai_action", "Splunk AI Toolkit Agent Builder", "alpha", "ui_handoff", "splunk-ai-ml-toolkit-setup", "Alpha; public GA target Fall 2026", "cisco_live_2026", "Distinct from Cloud Control Studio Agent Builder; target date is not GA evidence.", "ai-activation", "agent_builder_enabled"),
    capability("agent_builder_connections", "ai_action", "Agent Builder knowledge-base and MCP connections", "alpha", "delegated_render", "splunk-ai-ml-toolkit-setup", "Private-preview Splunk Cloud", "agent_builder_preview", "Requires preview enrollment, approved knowledge/MCP sources, edit_agent_connections permission, and secret-safe UI handling.", "ai-activation", "agent_builder_enabled"),
    capability("agent_builder_aiagent", "ai_action", "Agent Builder aiagent invocation", "alpha", "validation", "splunk-ai-ml-toolkit-setup", "Private-preview Splunk Cloud", "agent_builder_preview", "Validate run_agents permission, per-row invocation limits, timeout, agent selection, and representative non-sensitive input; do not infer availability from the public app package.", "ai-activation", "agent_builder_enabled"),
    capability("agent_builder_run_history", "governance", "Agent Builder run history", "alpha", "validation", "splunk-ai-ml-toolkit-setup", "Private-preview Splunk Cloud", "agent_builder_preview", "Review ai_agent_run_history_index retention, ACL, capacity, and sensitive content; this parent does not create the index.", "context-governance", "agent_builder_enabled"),
    capability("splunk_mcp_server", "ai_action", "Splunk MCP Server", "ga", "delegated_render", "splunk-mcp-server-setup", "Splunk Enterprise and Splunk Cloud", "mcp", "Product GA does not override the child skill's current package production-safety gate.", "ai-activation", "mcp_enabled"),
    capability("mcp_auth_tool_controls", "governance", "MCP encrypted tokens, OAuth, RBAC, tools, limits, and audit", "version_dependent", "validation", "splunk-mcp-server-setup", "Version and tenant dependent", "mcp_oauth", "Track each tool and OAuth lifecycle independently; never render credentials.", "context-governance", "mcp_enabled"),
    capability("ai_assistant_mcp_tools", "ai_action", "Splunk AI Assistant tools through MCP", "version_dependent", "delegated_render", "splunk-ai-assistant-setup,splunk-mcp-server-setup", "AI Assistant and MCP version dependent", "mcp", "AI Assistant must be installed and tool/RBAC controls validated.", "ai-activation", "ai_assistant_enabled"),
    capability("agent_observability", "governance", "AI Agent Monitoring / Agent Observability", "available", "delegated_render", "splunk-observability-ai-agent-monitoring-setup", "Tenant and instrumentation dependent", "agentic_ops", "Monitor behavior, quality, latency, cost, guardrails, and evaluation evidence.", "context-governance", "agent_observability_enabled"),
    capability("ai_canvas_splunk", "experience", "Cisco AI Canvas with Splunk", "controlled_availability", "ui_handoff", "cisco-cloud-control-setup", "Eligible US commercial AWS Splunk Cloud during CA", "ai_canvas", "Requires Cloud Control enablement, Splunk Cloud 10.5.2605.3, current AI Assistant and MCP Server, and `mcp_tool_execute` for every user.", "experience", "ai_canvas_enabled", access_requirement="cloud_control_ca_tenant_approval_identity_terms_and_admin_onboarding"),
    capability("ai_canvas_splunk_limits", "experience", "AI Canvas Splunk execution limits", "controlled_availability", "validation", "cisco-cloud-control-setup", "Eligible AI Canvas with Splunk integrations", "ai_canvas", "Results are limited to 100 rows per card; some SPL commands are forbidden and fail on refresh/run. Validate every generated search and visualization against the current allowlist.", "experience", "ai_canvas_enabled", access_requirement="same_as_ai_canvas_splunk"),
    capability("cloud_control_studio_agent_builder", "experience", "Cloud Control Studio Agent Builder", "roadmap", "ui_handoff", "cisco-cloud-control-setup", "Announced; availability not established", "cloud_control_agent_builder", "Separate announced Cisco builder from Splunk AI Toolkit Agent Builder; do not infer CA from Cloud Control's own lifecycle.", "experience", "cloud_control_enabled", access_requirement="when_and_if_available"),
    capability("rbac_audit_lineage_policy", "governance", "RBAC, audit, lineage, policy, and human approval", "architecture", "validation", "Admin, readiness, and product-owner skills", "Cross-cutting", "agentic_layers", "Production agents require access, meaning, trust, evidence, and approval paths.", "context-governance", "context_governance_enabled"),
    capability("cim_ocsf_readiness", "context", "CIM, OCSF, schema, and downstream data readiness", "available", "delegated_render", "splunk-data-source-readiness-doctor,splunk-cim-data-model-setup", "Data-source dependent", "data_management_guide", "Validate usable data, not only successful transport or package installation.", "context-governance", "context_governance_enabled"),
    capability("cisco_sal_boundary", "integration", "Cisco Security Analytics and Logging boundary", "available", "render", "cisco-product-setup", "Cisco security product", "sal", "SAL is not Machine Data Lake; no undocumented Data Fabric federation contract is inferred.", "experience", "experience_enabled"),
]


PRODUCTS = [
    ("cisco_data_fabric", "Cisco Data Fabric", "architecture", SKILL_NAME, "Architecture umbrella; no standalone installer or API."),
    ("splunk_cloud", "Splunk Cloud Platform", "available", "Splunk Cloud skills", "Core platform; external federation and emerging features are tenant dependent."),
    ("splunk_enterprise", "Splunk Enterprise", "available", "Splunk Enterprise skills", "Core platform and FSS2S; not every Cloud Data Management feature applies."),
    ("data_inputs", "Data Inputs (formerly Data Manager)", "available", "splunk-cloud-data-manager-setup", "Cloud-source onboarding and S3 Promote."),
    ("data_management_app", "Data Management app", "version_dependent", "Edge/Ingest/Federated Search skills", "Connections, datasets, pipelines, and product-specific UI workflows."),
    ("edge_processor", "Edge Processor", "available", "splunk-edge-processor-setup", "Customer-managed edge runtime."),
    ("ingest_processor", "Ingest Processor", "available", "splunk-ingest-processor-setup", "Splunk-managed Cloud ingest processing."),
    ("spl2", "SPL2", "version_dependent", "splunk-spl2-pipeline-kit", "Shared language with runtime-specific command subsets."),
    ("federated_search", "Federated Search", "version_dependent", "splunk-federated-search-setup", "FSS2S plus store-specific Cloud federation."),
    ("splunk_index", "Splunk index", "ga", "Splunk platform/index skills", "Low-latency real-time execution layer."),
    ("machine_data_lake", "Splunk Machine Data Lake", "alpha", SKILL_NAME, "Account-team/UI readiness only."),
    ("catalog", "Global Catalog", "version_dependent", SKILL_NAME, "Gradual 10.5 rollout; distinct from dataset catalogs."),
    ("ai_toolkit", "Splunk AI Toolkit", "ga", "splunk-ai-ml-toolkit-setup", "Model workflows, hosted/external connections, and preview features."),
    ("ctsm", "Cisco Time Series Model 1.0", "available", SKILL_NAME, "Open model; separate from hosted CDTSM preview."),
    ("agent_builder", "Splunk AI Toolkit Agent Builder", "alpha", "splunk-ai-ml-toolkit-setup", "Alpha with public Fall 2026 GA target."),
    ("mcp_server", "Splunk MCP Server", "ga", "splunk-mcp-server-setup", "Core product GA; child package safety findings still govern use."),
    ("ai_assistant", "Splunk AI Assistant", "version_dependent", "splunk-ai-assistant-setup", "Optional MCP tools and agentic search support."),
    ("cloud_control", "Cisco Cloud Control", "controlled_availability", "cisco-cloud-control-setup", "Operational experience/control plane, not the Data Fabric."),
    ("ai_canvas", "Cisco AI Canvas", "controlled_availability", "cisco-cloud-control-setup", "Collaborative experience layer, not a Data Fabric admin UI."),
    ("enterprise_security", "Splunk Enterprise Security", "available", "splunk-enterprise-security-config", "SecOps consumer and context producer."),
    ("itsi", "Splunk ITSI", "available", "splunk-itsi-config", "ITOps service/business-context consumer and producer."),
    ("observability", "Splunk Observability Cloud", "available", "Splunk Observability skills", "Engineering/ITOps consumer and agent-observability owner."),
    ("cisco_sal", "Cisco Security Analytics and Logging", "available", "cisco-product-setup", "Separate Cisco logging product; integration contract must be verified."),
]


FEDERATION_TARGETS = [
    ("splunk", "Splunk Cloud / Enterprise", "available", "none", "Splunk Enterprise + Cloud", "standard or transparent FSS2S", "federated_overview"),
    ("amazon-s3", "Amazon S3", "ga", "sales activation and scan entitlement", "AWS-hosted Splunk Cloud", "Data Management connection/dataset", "federated_s3"),
    ("microsoft-azure", "Microsoft Azure Blob / ADLS Gen2", "controlled_availability", "CA enrollment and sales activation", "AWS-hosted Splunk Cloud", "Data Management connection/dataset", "federated_azure"),
    ("azure-databricks", "Azure Databricks Unity Catalog", "controlled_availability", "CA enrollment and sales activation", "AWS-hosted Splunk Cloud", "Delta Sharing connection/dataset", "federated_databricks"),
    ("snowflake", "Snowflake tables and views", "available", "sales activation and scan entitlement", "AWS-hosted Splunk Cloud + AWS Snowflake", "PAT-backed connection/dataset", "federated_snowflake"),
    ("ddss", "DDSS in Amazon S3", "available", "sales activation and scan entitlement", "AWS-hosted Splunk Cloud", "DDSS dataset and Splunk-native catalog", "federated_ddss"),
    ("amazon-security-lake", "Amazon Security Lake", "ga", "premium add-on activation and scan entitlement", "AWS-hosted Splunk Cloud", "Federated Analytics detection + hunting", "federated_asl"),
]

FEDERATION_INTAKE_REQUIREMENTS = {
    "splunk": "remote deployment/version, standard or transparent mode, search-head endpoint, service account, app context, mapped datasets, knowledge objects, network/TLS, RBAC, and topology",
    "amazon-s3": "AWS account/region, bucket and prefixes, IAM trust/resource policies, SSE-S3 or KMS, catalog choice, schema/time field/partitions, formats/storage class, RBAC, DSU estimate, and representative SPL2",
    "microsoft-azure": "Entra tenant/app handoff, storage account URL, Blob or ADLS container/path, roles, network allowlists, catalog/schema/time/partitions, RBAC, scan estimate, and representative SPL2",
    "azure-databricks": "workspace and Unity Catalog identifiers, Delta Sharing credential handoff, runtime/version, schemas/tables, network, RBAC, scan estimate, and representative SPL2",
    "snowflake": "AWS-hosted account/region, warehouse/database/schema, service user and PAT handoff, USAGE grants, network/authentication policy, tables/views, RBAC, scan estimate, and representative SPL2",
    "ddss": "S3 bucket path and DDSS index, SQS queue, S3 notifications and generated policies, catalog crawler/synchronization, schema/time/partitions, RBAC, scan estimate, and representative SPL2",
    "amazon-security-lake": "same AWS region, activation, Security Lake subscriber, OCSF sources/classes, recent-data filters and retention, data lake indexes, historical federated indexes, storage class, ES detections/macros, RBAC, DSU estimate, and representative threat-hunting SPL2",
}


def reject_direct_secret_flags(args: list[str]) -> None:
    for item in args:
        flag = item.split("=", 1)[0] if item.startswith("--") else item
        if flag in DIRECT_SECRET_FLAGS:
            print(
                "ERROR: Direct secret values are not accepted. Use the owning child skill's secret-file workflow.",
                file=sys.stderr,
            )
            raise SystemExit(2)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw = list(sys.argv[1:] if argv is None else argv)
    reject_direct_secret_flags(raw)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--spec", default="")
    parser.add_argument("--execute", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(raw)


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    return value


def next_content_line(lines: list[str], start: int) -> str:
    for line in lines[start:]:
        if line.strip() and not line.lstrip().startswith("#"):
            return line
    return ""


def parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = text.splitlines()
    for index, raw_line in enumerate(lines):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise SystemExit("ERROR: Could not parse YAML indentation.")
        current = stack[-1][1]
        if stripped.startswith("- "):
            if not isinstance(current, list):
                raise SystemExit("ERROR: Could not parse YAML list item.")
            item = stripped[2:].strip()
            if ":" in item:
                key, raw_value = item.split(":", 1)
                child: dict[str, Any] = {key.strip(): parse_scalar(raw_value)}
                current.append(child)
                stack.append((indent, child))
            else:
                current.append(parse_scalar(item))
            continue
        if ":" not in stripped or not isinstance(current, dict):
            raise SystemExit("ERROR: Could not parse YAML mapping.")
        key, raw_value = stripped.split(":", 1)
        key, value = key.strip(), raw_value.strip()
        if value:
            current[key] = parse_scalar(value)
            continue
        following = next_content_line(lines, index + 1)
        following_indent = len(following) - len(following.lstrip(" ")) if following else indent
        child = [] if following and following_indent > indent and following.strip().startswith("- ") else {}
        current[key] = child
        stack.append((indent, child))
    return root


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.lower().replace("-", "_")).strip("_")


def reject_secret_like_spec_keys(node: Any, path: str = "") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            normalized = normalize_key(str(key))
            sub_path = f"{path}.{key}" if path else str(key)
            allowed = normalized.endswith(SECRET_KEY_ALLOW_SUFFIXES)
            if SECRET_KEY_RE.search(normalized) and not allowed:
                raise SystemExit(
                    f"ERROR: Spec contains raw secret-looking key at {sub_path}; use a child secret-file field instead."
                )
            reject_secret_like_spec_keys(value, sub_path)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            reject_secret_like_spec_keys(item, f"{path}[{index}]")
    elif isinstance(node, str):
        if any(pattern.search(node) for pattern in SECRET_VALUE_PATTERNS):
            raise SystemExit(
                f"ERROR: Spec contains a value matching a credential signature at {path}; use the owning child skill's secret-file workflow."
            )


def load_spec(path: str) -> dict[str, Any]:
    if not path:
        return {}
    spec_path = Path(path)
    text = spec_path.read_text(encoding="utf-8")
    if spec_path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            data = json.loads(text) if text.lstrip().startswith("{") else parse_simple_yaml(text)
        else:
            data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SystemExit("ERROR: Spec must be a mapping.")
    if data.get("api_version") not in {None, f"{SKILL_NAME}/v1"}:
        raise SystemExit(f"ERROR: Spec api_version must be {SKILL_NAME}/v1.")
    reject_secret_like_spec_keys(data)
    return data


def get_nested(spec: dict[str, Any], dotted: str, default: Any) -> Any:
    current: Any = spec
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def as_bool(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def as_list(value: Any, default: list[str]) -> list[str]:
    if value in (None, ""):
        return list(default)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def merge_config(spec: dict[str, Any]) -> dict[str, Any]:
    storage_specs = get_nested(spec, "storage_catalog.child_specs", {})
    context_specs = get_nested(spec, "context_governance.child_specs", {})
    if not isinstance(storage_specs, dict):
        storage_specs = {}
    if not isinstance(context_specs, dict):
        context_specs = {}
    return {
        "organization": str(get_nested(spec, "organization.name", "example-enterprise") or "example-enterprise"),
        "environment": str(get_nested(spec, "organization.environment", "production") or "production"),
        "owner": str(get_nested(spec, "organization.owner", "data-platform") or "data-platform"),
        "deployment": str(get_nested(spec, "platform.deployment", "splunk-cloud") or "splunk-cloud"),
        "version": str(get_nested(spec, "platform.version", "10.5.2605") or "10.5.2605"),
        "cloud_provider": str(get_nested(spec, "platform.cloud_provider", "aws") or "aws"),
        "region": str(get_nested(spec, "platform.region", "") or ""),
        "data_management_enabled": as_bool(get_nested(spec, "data_management.enabled", True), True),
        "ingest_processor_enabled": as_bool(get_nested(spec, "data_management.ingest_processor.enabled", True), True),
        "edge_processor_enabled": as_bool(get_nested(spec, "data_management.edge_processor.enabled", True), True),
        "edge_tenant_url": str(get_nested(spec, "data_management.edge_processor.tenant_url", "") or ""),
        "edge_name": str(get_nested(spec, "data_management.edge_processor.name", "data-fabric-edge") or "data-fabric-edge"),
        "spl2_enabled": as_bool(get_nested(spec, "data_management.spl2_pipeline_kit.enabled", True), True),
        "afe_enabled": as_bool(get_nested(spec, "data_management.automated_field_extraction.enabled", True), True),
        "guided_onboarding_enabled": as_bool(get_nested(spec, "data_management.guided_onboarding.enabled", True), True),
        "ingest_monitoring_enabled": as_bool(get_nested(spec, "data_management.ingest_monitoring.enabled", True), True),
        "federation_enabled": as_bool(get_nested(spec, "federation.enabled", True), True),
        "federation_targets": as_list(get_nested(spec, "federation.requested_targets", [item[0] for item in FEDERATION_TARGETS]), [item[0] for item in FEDERATION_TARGETS]),
        "federation_spec": str(get_nested(spec, "federation.child_spec", "") or ""),
        "storage_catalog_enabled": as_bool(get_nested(spec, "storage_catalog.enabled", True), True),
        "splunk_index_enabled": as_bool(get_nested(spec, "storage_catalog.splunk_index.enabled", True), True),
        "machine_data_lake_enabled": as_bool(get_nested(spec, "storage_catalog.machine_data_lake.enabled", True), True),
        "data_catalog_enabled": as_bool(get_nested(spec, "storage_catalog.built_in_data_catalog.enabled", True), True),
        "storage_specs": {str(k): str(v or "") for k, v in storage_specs.items()},
        "ai_activation_enabled": as_bool(get_nested(spec, "ai_activation.enabled", True), True),
        "ai_toolkit_enabled": as_bool(get_nested(spec, "ai_activation.ai_toolkit.enabled", True), True),
        "ai_toolkit_spec": str(get_nested(spec, "ai_activation.ai_toolkit.child_spec", "") or ""),
        "agent_builder_enabled": as_bool(get_nested(spec, "ai_activation.agent_builder.enabled", True), True),
        "mcp_enabled": as_bool(get_nested(spec, "ai_activation.mcp_server.enabled", True), True),
        "mcp_url": str(get_nested(spec, "ai_activation.mcp_server.mcp_url", "") or ""),
        "ai_assistant_enabled": as_bool(get_nested(spec, "ai_activation.ai_assistant.enabled", True), True),
        "agent_observability_enabled": as_bool(get_nested(spec, "ai_activation.agent_observability.enabled", True), True),
        "agent_observability_spec": str(get_nested(spec, "ai_activation.agent_observability.child_spec", "") or ""),
        "context_governance_enabled": as_bool(get_nested(spec, "context_governance.enabled", True), True),
        "context_specs": {str(k): str(v or "") for k, v in context_specs.items()},
        "experience_enabled": as_bool(get_nested(spec, "experience.enabled", True), True),
        "cloud_control_enabled": as_bool(get_nested(spec, "experience.cloud_control", True), True),
        "ai_canvas_enabled": as_bool(get_nested(spec, "experience.ai_canvas", True), True),
        "domains": as_list(get_nested(spec, "domains", ["secops", "itops", "engineering", "netops"]), ["secops", "itops", "engineering", "netops"]),
    }


def selected_sections(value: str) -> list[str]:
    if not value or value == "all":
        return [section for section in SECTIONS if section in EXECUTABLE_SECTIONS]
    result = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(result) - set(SECTIONS))
    if unknown:
        raise SystemExit(f"ERROR: Unknown execute section(s): {', '.join(unknown)}")
    return result


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def command(argv: list[str]) -> list[str]:
    reject_direct_secret_flags(argv)
    return argv


def child_platform(deployment: str) -> str:
    normalized = deployment.strip().lower().replace("_", "-")
    if normalized in {"cloud", "splunk-cloud", "splunk-cloud-platform"}:
        return "cloud"
    if normalized in {"enterprise", "splunk-enterprise"}:
        return "enterprise"
    return ""


def write_text(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def prepare_output_dir(output_dir: Path) -> None:
    marker = output_dir / ".cisco-data-fabric-setup"
    if output_dir.exists() and any(output_dir.iterdir()) and not marker.is_file():
        raise SystemExit(f"ERROR: Refusing unrelated non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    delegated = output_dir / "delegated"
    if delegated.exists():
        shutil.rmtree(delegated)
    write_text(marker, f"owner={SKILL_NAME}\n")


def build_commands(config: dict[str, Any], output_dir: Path) -> dict[str, list[list[str]]]:
    delegated = output_dir / "delegated"
    result: dict[str, list[list[str]]] = {section: [] for section in SECTIONS}

    if config["data_management_enabled"]:
        if config["edge_processor_enabled"] and config["edge_tenant_url"]:
            result["data-management"].append(command([
                "bash", "skills/splunk-edge-processor-setup/scripts/setup.sh",
                "--phase", "render", "--ep-tenant-url", config["edge_tenant_url"],
                "--ep-name", config["edge_name"], "--output-dir", str(delegated / "edge-processor"),
            ]))
        if config["spl2_enabled"]:
            result["data-management"].append(command([
                "bash", "skills/splunk-spl2-pipeline-kit/scripts/setup.sh",
                "--phase", "all", "--profile", "both", "--output-dir", str(delegated / "spl2-pipeline-kit"),
            ]))

    if config["federation_enabled"] and config["federation_spec"]:
        result["federation"].append(command([
            "bash", "skills/splunk-federated-search-setup/scripts/setup.sh",
            "--phase", "render", "--spec", config["federation_spec"],
            "--output-dir", str(delegated / "federated-search"),
        ]))

    if config["ai_activation_enabled"] and config["ai_toolkit_enabled"]:
        platform = child_platform(config["deployment"])
        ai_cmd = [
            "bash", "skills/splunk-ai-ml-toolkit-setup/scripts/setup.sh",
            "--render", "--validate", "--output-dir", str(delegated / "ai-ml-toolkit"),
        ]
        if platform:
            ai_cmd.extend(["--platform", platform])
        if config["version"]:
            ai_cmd.extend(["--splunk-version", config["version"]])
        if config["ai_toolkit_spec"]:
            ai_cmd.extend(["--spec", config["ai_toolkit_spec"]])
        if platform:
            result["ai-activation"].append(command(ai_cmd))
    if config["ai_activation_enabled"] and config["mcp_enabled"] and config["mcp_url"]:
        result["ai-activation"].append(command([
            "bash", "skills/splunk-mcp-server-setup/scripts/setup.sh",
            "--render-clients", "--mcp-url", config["mcp_url"],
            "--no-register-codex", "--no-configure-cursor", "--no-configure-claude",
            "--output-dir", str(delegated / "splunk-mcp"),
        ]))
    if config["ai_activation_enabled"] and config["agent_observability_enabled"] and config["agent_observability_spec"]:
        result["ai-activation"].append(command([
            "bash", "skills/splunk-observability-ai-agent-monitoring-setup/scripts/setup.sh",
            "--render", "--spec", config["agent_observability_spec"],
            "--output-dir", str(delegated / "agent-observability"),
        ]))

    if config["context_governance_enabled"]:
        readiness = config["context_specs"].get("data_source_readiness", "")
        if readiness:
            result["context-governance"].append(command([
                "bash", "skills/splunk-data-source-readiness-doctor/scripts/setup.sh",
                "--phase", "doctor", "--evidence-file", readiness,
                "--output-dir", str(delegated / "data-source-readiness"),
            ]))
        itsi = config["context_specs"].get("itsi", "")
        if itsi:
            result["context-governance"].append(command([
                "bash", "skills/splunk-itsi-config/scripts/setup.sh",
                "--workflow", "native", "--spec", itsi, "--mode", "lint",
            ]))
    return result


def flag_enabled(config: dict[str, Any], flag: str) -> bool:
    return True if not flag else bool(config.get(flag, False))


def coverage_rows(config: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in CAPABILITIES:
        if item["product_stage"] not in ALLOWED_PRODUCT_STAGES:
            raise SystemExit(f"Internal error: unsupported product stage {item['product_stage']}")
        status = item["repo_status"]
        if item["section"] == "data-management" and not config["data_management_enabled"]:
            status = "not_applicable"
        elif item["section"] == "federation" and not config["federation_enabled"]:
            status = "not_applicable"
        elif item["section"] == "storage-catalog" and not config["storage_catalog_enabled"]:
            status = "not_applicable"
        elif item["section"] == "ai-activation" and not config["ai_activation_enabled"]:
            status = "not_applicable"
        elif item["section"] == "context-governance" and not config["context_governance_enabled"]:
            status = "not_applicable"
        elif item["section"] == "experience" and not config["experience_enabled"]:
            status = "not_applicable"
        elif not flag_enabled(config, item["flag"]):
            status = "not_applicable"
        if status not in ALLOWED_REPO_STATUSES:
            raise SystemExit(f"Internal error: unsupported repo status {status}")
        source = SOURCE_RECORDS[item["source"]]
        rows.append({
            "key": item["key"],
            "layer": item["layer"],
            "title": item["title"],
            "product_stage": item["product_stage"],
            "repo_status": status,
            "owner": item["owner"],
            "platforms": item["platforms"],
            "access_requirement": item["access_requirement"],
            "source_url": source["url"],
            "source_type": source["source_type"],
            "source_version": source["source_version"],
            "retrieved_at": RESEARCH_VERIFIED,
            "boundary": item["boundary"],
        })
    keys = [row["key"] for row in rows]
    if len(keys) != len(set(keys)):
        raise SystemExit("Internal error: duplicate coverage keys")
    return rows


def product_rows() -> list[dict[str, str]]:
    rows = []
    for key, title, stage, owner, relationship in PRODUCTS:
        rows.append({
            "key": key,
            "title": title,
            "product_stage": stage,
            "owner": owner,
            "relationship": relationship,
        })
    return rows


def source_ledger() -> list[dict[str, str]]:
    return [
        {"claim_id": key, **value, "retrieved_at": RESEARCH_VERIFIED}
        for key, value in sorted(SOURCE_RECORDS.items())
    ]


def config_gaps(config: dict[str, Any]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    platform = child_platform(config["deployment"])
    if not platform:
        gaps.append({"severity": "error", "key": "platform_deployment", "message": "Set platform.deployment to splunk-cloud/cloud or splunk-enterprise/enterprise before delegating platform-specific child skills."})
    if not config["version"]:
        gaps.append({"severity": "error", "key": "platform_version", "message": "Set platform.version to the exact target stack version before compatibility or lifecycle decisions."})
    elif not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", config["version"]):
        gaps.append({"severity": "error", "key": "platform_version_precision", "message": f"Platform version '{config['version']}' is not an exact three-or-four-component stack version; supply the full stack version before production delegation."})
    if platform == "cloud" and not config["region"]:
        gaps.append({"severity": "error", "key": "platform_region", "message": "Set platform.region before deciding federation, Machine Data Lake, Catalog, AI, Cloud Control, residency, or availability support."})
    if platform == "cloud" and config["federation_enabled"] and config["cloud_provider"].lower() != "aws":
        gaps.append({"severity": "warning", "key": "federation_cloud_provider", "message": "Current external federation targets in this matrix are primarily documented for AWS-hosted Splunk Cloud; verify provider-specific support before proceeding."})
    if config["data_management_enabled"] and config["ingest_processor_enabled"]:
        gaps.append({"severity": "info", "key": "ingest_processor_intake", "message": "Ingest Processor is covered but is not invoked without reviewed source, destination, and pipeline intake; use the child skill directly."})
    if config["edge_processor_enabled"] and not config["edge_tenant_url"]:
        gaps.append({"severity": "info", "key": "edge_tenant_url", "message": "Set data_management.edge_processor.tenant_url before delegating Edge Processor render."})
    if config["federation_enabled"] and not config["federation_spec"]:
        gaps.append({"severity": "warning", "key": "federation_spec", "message": "Set federation.child_spec to delegate a provider-specific Federated Search render."})
        for target in sorted(set(config["federation_targets"]) & set(FEDERATION_INTAKE_REQUIREMENTS)):
            gaps.append({"severity": "warning", "key": f"federation_intake_{target.replace('-', '_')}", "message": f"Complete the {target} intake before calling this a production plan: {FEDERATION_INTAKE_REQUIREMENTS[target]}."})
    if config["machine_data_lake_enabled"]:
        gaps.append({"severity": "warning", "key": "machine_data_lake_alpha", "message": "Machine Data Lake is alpha; confirm current tenant access, terms, region, security, retention, and product documentation."})
    if config["data_catalog_enabled"]:
        gaps.append({"severity": "info", "key": "catalog_rollout", "message": "Confirm global Catalog rollout separately from per-dataset and Machine Data Lake catalogs."})
    if config["mcp_enabled"] and not config["mcp_url"]:
        gaps.append({"severity": "info", "key": "mcp_url", "message": "Set ai_activation.mcp_server.mcp_url only after the MCP child skill validates the server and production boundary."})
    if config["mcp_enabled"]:
        gaps.append({"severity": "warning", "key": "mcp_package_gate", "message": "Splunk MCP Server is product-GA, but the repository's current 1.2.1 package review is production-blocked; the child skill remains authoritative."})
    if config["ai_assistant_enabled"]:
        gaps.append({"severity": "warning", "key": "ai_assistant_handoff", "message": "AI Assistant is enabled in scope but has no reviewed child intake in this packet; validate the current app, context/agent-mode settings, model governance, and AI Canvas compatibility through splunk-ai-assistant-setup."})
    if config["agent_observability_enabled"] and not config["agent_observability_spec"]:
        gaps.append({"severity": "warning", "key": "agent_observability_spec", "message": "Set ai_activation.agent_observability.child_spec to render instrumentation, evaluation, quality, latency, cost, dashboard, and detector readiness."})
    if config["agent_builder_enabled"]:
        gaps.append({"severity": "warning", "key": "agent_builder_alpha", "message": "Splunk AI Toolkit Agent Builder remains alpha with a Fall 2026 GA target; keep it distinct from Cloud Control Studio Agent Builder."})
    if config["experience_enabled"] and config["cloud_control_enabled"]:
        gaps.append({"severity": "warning", "key": "cloud_control_ca", "message": "Validate Cloud Control Controlled Availability eligibility, US commercial access, tenant approval, identity/domain, and terms. Cloud Control Studio Agent Builder is separately announced/roadmap; do not infer its availability from Cloud Control CA."})
    if config["experience_enabled"] and config["ai_canvas_enabled"]:
        gaps.append({"severity": "warning", "key": "ai_canvas_ca", "message": "Validate AI Canvas CA eligibility, Cloud Control enablement, Splunk Cloud 10.5.2605.3, US commercial AWS, latest AI Assistant and MCP Server, and `mcp_tool_execute` for every user. Results are capped at 100 rows per card and some SPL commands are forbidden."})
        if platform == "cloud" and config["version"] != "10.5.2605.3":
            gaps.append({"severity": "error", "key": "ai_canvas_stack_version", "message": f"AI Canvas with Splunk currently requires Splunk Cloud 10.5.2605.3; target version is '{config['version']}'. Disable the experience lane or verify/upgrade the exact stack before production use."})
    requested = set(config["federation_targets"])
    known = {item[0] for item in FEDERATION_TARGETS}
    for target in sorted(requested - known):
        gaps.append({"severity": "error", "key": f"unknown_federation_target_{target}", "message": f"Unknown federation target: {target}."})
    storage_handoffs = {k: v for k, v in config["storage_specs"].items() if v}
    if storage_handoffs:
        gaps.append({"severity": "info", "key": "storage_child_specs", "message": "Storage child spec paths are recorded as handoffs; this parent does not apply alpha Machine Data Lake or catalog state."})
    if config["context_governance_enabled"]:
        context_requirements = {
            "data_source_readiness": "evidence file for index, sourcetype, event, macro, CIM/OCSF, dashboard, ES, ITSI, and ARI readiness",
            "cim": "CIM data-model/index/mapping specification",
            "knowledge_objects": "knowledge-object ownership, sharing, macro, lookup, eventtype, tag, and extraction specification",
            "itsi": "ITSI entity, service, KPI, dependency, template, and content-pack specification",
        }
        for key, requirement in context_requirements.items():
            if not config["context_specs"].get(key):
                gaps.append({"severity": "warning", "key": f"context_{key}_spec", "message": f"Provide the {requirement} before treating the SecOps/ITOps context lane as implemented."})
            elif key in {"cim", "knowledge_objects"}:
                gaps.append({"severity": "info", "key": f"context_{key}_handoff", "message": f"The {key} path is recorded as an operator handoff because its child CLI is object-specific and does not accept this parent spec directly; execute reviewed child objects separately."})
    return gaps


def build_apply_plan(config: dict[str, Any], commands: dict[str, list[list[str]]], selected: list[str], output_dir: Path) -> dict[str, Any]:
    owners = {
        "data-management": "Edge Processor and SPL2 child skills",
        "federation": "splunk-federated-search-setup",
        "storage-catalog": "Machine Data Lake/Catalog UI plus storage lifecycle child skills",
        "ai-activation": "AI Toolkit, MCP, AI Assistant, and Agent Observability child skills",
        "context-governance": "Readiness, CIM, knowledge objects, and ITSI child skills",
        "experience": "cisco-cloud-control-setup and Cisco AI Canvas handoff",
    }
    return {
        "api_version": f"{SKILL_NAME}/apply-plan/v1",
        "output_dir": str(output_dir),
        "selected_sections": selected,
        "secret_values_rendered": False,
        "direct_cdf_api_mutation": False,
        "sections": [
            {
                "name": section,
                "owner": owners[section],
                "commands": commands[section],
                "script": f"scripts/execute-{section}.sh",
                "handoff_only": section in HANDOFF_ONLY_SECTIONS,
                "requires_accept_execute": section in EXECUTABLE_SECTIONS,
                "child_apply_requires_separate_approval": True,
            }
            for section in SECTIONS
        ],
    }


def markdown_table(rows: list[dict[str, str]], columns: list[tuple[str, str]]) -> str:
    lines = [
        "| " + " | ".join(label for _, label in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        values = [str(row.get(key, "")).replace("|", "\\|").replace("\n", " ") for key, _ in columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def render_reports(output_dir: Path, config: dict[str, Any], rows: list[dict[str, str]], products: list[dict[str, str]], gaps: list[dict[str, str]]) -> None:
    write_json(output_dir / "coverage-report.json", {
        "api_version": f"{SKILL_NAME}/coverage/v1",
        "research_verified": RESEARCH_VERIFIED,
        "allowed_repo_statuses": sorted(ALLOWED_REPO_STATUSES),
        "allowed_product_stages": sorted(ALLOWED_PRODUCT_STAGES),
        "secret_values_rendered": False,
        "coverage": rows,
    })
    write_text(output_dir / "coverage-report.md", "# Cisco Data Fabric Coverage Report\n\n" + markdown_table(rows, [
        ("key", "Key"), ("layer", "Layer"), ("title", "Capability"),
        ("product_stage", "Product stage"), ("repo_status", "Repo status"),
        ("access_requirement", "Access requirement"), ("owner", "Owner"),
        ("boundary", "Boundary"),
    ]) + "\n")
    write_json(output_dir / "product-matrix.json", {
        "api_version": f"{SKILL_NAME}/products/v1",
        "research_verified": RESEARCH_VERIFIED,
        "products": products,
    })
    write_text(output_dir / "product-matrix.md", "# Cisco Data Fabric Product Matrix\n\n" + markdown_table(products, [
        ("key", "Key"), ("title", "Product or architecture"),
        ("product_stage", "Stage"), ("owner", "Owner"), ("relationship", "Relationship"),
    ]) + "\n")
    stage_counts: dict[str, int] = {}
    for row in rows:
        stage_counts[row["product_stage"]] = stage_counts.get(row["product_stage"], 0) + 1
    availability = [
        {"product_stage": key, "capability_count": str(value)}
        for key, value in sorted(stage_counts.items())
    ]
    write_text(output_dir / "availability-matrix.md", "# Availability Matrix\n\nAvailability is a product lifecycle field, not proof that this repository can apply the feature.\n\n" + markdown_table(availability, [("product_stage", "Stage"), ("capability_count", "Capabilities")]) + "\n")
    write_json(output_dir / "source-ledger.json", {
        "api_version": f"{SKILL_NAME}/sources/v1",
        "sources": source_ledger(),
    })
    write_json(output_dir / "gap-register.json", {
        "api_version": f"{SKILL_NAME}/gaps/v1",
        "research_verified": RESEARCH_VERIFIED,
        "blocking_error_count": sum(1 for gap in gaps if gap["severity"] == "error"),
        "gaps": gaps,
    })
    gap_lines = ["# Cisco Data Fabric Gap Register", "", f"Research verified: `{RESEARCH_VERIFIED}`", ""]
    if gaps:
        gap_lines.append(markdown_table(gaps, [("severity", "Severity"), ("key", "Key"), ("message", "Finding")]))
    else:
        gap_lines.append("No intake gaps were found. Product-stage handoffs still require owner validation.")
    write_text(output_dir / "gap-register.md", "\n".join(gap_lines) + "\n")


def rows_for(rows: list[dict[str, str]], *layers: str) -> list[dict[str, str]]:
    return [row for row in rows if row["layer"] in set(layers)]


def render_layer_assets(output_dir: Path, config: dict[str, Any], rows: list[dict[str, str]]) -> None:
    write_text(output_dir / "architecture/layer-model.md", f"""# Cisco Data Fabric Layer Model

Cisco Data Fabric is an architecture powered by Splunk, not a standalone
installer, SKU, API, or data lake.

1. Data access and management: sources, Edge Processor, Ingest Processor, SPL2.
2. Real-time execution and storage: Splunk indexes plus governed tiering.
3. Federation and catalog: search data where it resides with explicit catalog and RBAC models.
4. Context: schema, metadata, knowledge objects, service/business relationships.
5. AI and action: models, Agent Builder, MCP, assistants, and governed workflows.
6. Experience: Splunk products, Cisco Cloud Control, and AI Canvas.

- Deployment: `{config['deployment']}` `{config['version']}`
- Cloud/provider region: `{config['cloud_provider']}` / `{config['region'] or 'not supplied'}`
- Research verified: `{RESEARCH_VERIFIED}`
""")
    write_text(output_dir / "data-management/pipeline-readiness.md", "# Data Management And Pipeline Readiness\n\n" + markdown_table(rows_for(rows, "data_management"), [
        ("title", "Capability"), ("product_stage", "Stage"), ("repo_status", "Repo status"), ("access_requirement", "Access"), ("owner", "Owner"), ("boundary", "Boundary"),
    ]) + "\n\nThe parent deliberately does not call Ingest Processor with canned defaults. Use reviewed source, destination, and pipeline intake in the child skill.\n")
    requested = set(config["federation_targets"])
    federation_rows = []
    for key, title, stage, access, platforms, model, source in FEDERATION_TARGETS:
        federation_rows.append({
            "key": key,
            "target": title,
            "requested": "yes" if key in requested else "no",
            "stage": stage,
            "access_requirement": access,
            "platforms": platforms,
            "model": model,
            "source_url": SOURCE_RECORDS[source]["url"],
        })
    write_text(output_dir / "federation/target-matrix.md", "# Federation Target Matrix\n\n" + markdown_table(federation_rows, [
        ("key", "Key"), ("target", "Target"), ("requested", "Requested"),
        ("stage", "Product stage"), ("access_requirement", "Access requirement"),
        ("platforms", "Platforms"), ("model", "Configuration model"),
    ]) + "\n\nDo not route Amazon Security Lake as a generic Amazon S3 provider. Treat Cisco SAL as a separate product/integration boundary.\n")
    write_text(output_dir / "storage-catalog/tiering-and-catalog-readiness.md", "# Storage, Tiering, And Catalog Readiness\n\n" + markdown_table(rows_for(rows, "storage", "catalog"), [
        ("title", "Capability"), ("product_stage", "Stage"), ("repo_status", "Repo status"), ("owner", "Owner"), ("boundary", "Boundary"),
    ]) + "\n\nKeep the global Catalog, per-dataset catalogs, and Machine Data Lake cataloging separate. Machine Data Lake remains alpha and has no direct apply path here.\n")
    write_text(output_dir / "ai/activation-readiness.md", "# AI Activation Readiness\n\n" + markdown_table(rows_for(rows, "ai_action"), [
        ("title", "Capability"), ("product_stage", "Stage"), ("repo_status", "Repo status"), ("access_requirement", "Access"), ("owner", "Owner"), ("boundary", "Boundary"),
    ]) + "\n\nCisco Time Series Model 1.0 is an available open model; hosted Cisco Deep Time Series Model remains a separate AI Toolkit preview. Splunk Agent Builder and Cloud Control Studio Agent Builder are distinct.\n")
    write_text(output_dir / "governance/trust-readiness.md", "# Context And Trust Readiness\n\n" + markdown_table(rows_for(rows, "context", "governance"), [
        ("title", "Capability"), ("product_stage", "Stage"), ("repo_status", "Repo status"), ("owner", "Owner"), ("boundary", "Boundary"),
    ]) + "\n\nRequire access, meaning, and trust: least privilege, catalog/schema context, lineage evidence, auditability, human approval, cost controls, and downstream data-readiness validation.\n")
    experience_rows = rows_for(rows, "experience", "integration", "architecture")
    write_text(output_dir / "experience/cross-domain-handoff.md", "# Cross-Domain Experience Handoff\n\n" + markdown_table(experience_rows, [
        ("title", "Surface"), ("product_stage", "Stage"), ("repo_status", "Repo status"), ("access_requirement", "Access"), ("owner", "Owner"), ("boundary", "Boundary"),
    ]) + f"\n\nRequested domains: {', '.join(config['domains'])}. Cisco Cloud Control and AI Canvas are experience/control surfaces above the Data Fabric, not synonyms for it.\n")


def render_metadata(output_dir: Path, config: dict[str, Any], rows: list[dict[str, str]], gaps: list[dict[str, str]]) -> None:
    write_json(output_dir / "metadata.json", {
        "api_version": f"{SKILL_NAME}/v1",
        "organization": config["organization"],
        "environment": config["environment"],
        "owner": config["owner"],
        "deployment": config["deployment"],
        "version": config["version"],
        "cloud_provider": config["cloud_provider"],
        "region": config["region"],
        "research_verified": RESEARCH_VERIFIED,
        "capability_count": len(rows),
        "source_count": len(SOURCE_RECORDS),
        "gap_count": len(gaps),
        "blocking_gap_count": sum(1 for gap in gaps if gap["severity"] == "error"),
        "secret_values_rendered": False,
        "direct_cdf_api_mutation": False,
        "cdf_is_architecture": True,
    })


def render_handoff_and_doctor(output_dir: Path, config: dict[str, Any], rows: list[dict[str, str]], gaps: list[dict[str, str]], selected: list[str]) -> None:
    write_text(output_dir / "handoff.md", f"""# Cisco Data Fabric Handoff

- Organization: `{config['organization']}`
- Environment: `{config['environment']}`
- Platform: `{config['deployment']}` `{config['version']}`
- Cisco Data Fabric direct API mutation: `false`
- Secret values rendered: `false`
- Selected sections: {', '.join(f'`{item}`' for item in selected)}

## Review Order

1. Review `architecture/layer-model.md`, `product-matrix.md`, and `availability-matrix.md`.
2. Resolve `gap-register.md` and confirm product stages against `source-ledger.json`.
3. Review the data-management, federation, storage/catalog, AI, governance, and experience artifacts.
4. Execute only delegated child renders with reviewed intake.
5. Apply and validate through each child skill's own approval and secret-file gates.
""")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["product_stage"]] = counts.get(row["product_stage"], 0) + 1
    warning_count = sum(1 for gap in gaps if gap["severity"] == "warning")
    error_count = sum(1 for gap in gaps if gap["severity"] == "error")
    write_text(output_dir / "doctor-report.md", f"""# Cisco Data Fabric Doctor Report

- Capability rows: `{len(rows)}`
- Source records: `{len(SOURCE_RECORDS)}`
- Intake warnings: `{warning_count}`
- Intake errors: `{error_count}`
- Alpha capabilities: `{counts.get('alpha', 0)}`
- Controlled-availability capabilities: `{counts.get('controlled_availability', 0)}`
- Feature-preview capabilities: `{counts.get('feature_preview', 0)}`
- Roadmap capabilities: `{counts.get('roadmap', 0)}`
- Deprecated capabilities: `{counts.get('deprecated', 0)}`
- Direct Cisco Data Fabric API mutation: `false`
- Secret values rendered: `false`

## Production Gates

- Confirm actual stack version, cloud provider, region, entitlement, and release stage per capability.
- Keep Machine Data Lake alpha and Catalog rollout evidence tenant-specific.
- Use current Data Management connections/datasets; migrate legacy S3 provider/index objects.
- Validate federation target, catalog, RBAC, network, encryption, data-residency, and scan-cost constraints.
- Keep Splunk Agent Builder separate from Cloud Control Studio Agent Builder.
- Keep open CTSM separate from hosted CDTSM preview.
- Enforce the MCP child skill's production-package findings despite product GA status.
- Require data readiness, auditability, agent observability, and human approval before production actions.
""")


def script_header() -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
OUTPUT_DIR="$(cd "${{SCRIPT_DIR}}/.." && pwd)"
PROJECT_ROOT="${{PROJECT_ROOT:-{REPO_ROOT}}}"
cd "${{PROJECT_ROOT}}"
"""


def blocking_gap_guard() -> str:
    return """python3 - "${OUTPUT_DIR}/gap-register.json" <<'PY_GAPS'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
errors = [
    gap for gap in json.loads(path.read_text(encoding="utf-8")).get("gaps", [])
    if gap.get("severity") == "error"
]
if errors:
    keys = ", ".join(str(gap.get("key", "unknown")) for gap in errors)
    raise SystemExit(f"ERROR: refusing delegated execution with blocking intake gaps: {keys}")
PY_GAPS
"""


def render_command_script(section: str, commands: list[list[str]]) -> str:
    lines = [script_header()]
    if section in HANDOFF_ONLY_SECTIONS:
        lines.append(f"echo {shell_quote('ERROR: ' + section + ' is a rendered handoff, not an executable Cisco Data Fabric mutation.')} >&2\n")
        lines.append("exit 2\n")
        return "".join(lines)
    if not commands:
        lines.append(f"echo {shell_quote('ERROR: no reviewed child command is available for ' + section + '; complete the intake and rerender.')} >&2\n")
        lines.append("exit 2\n")
        return "".join(lines)
    lines.append(blocking_gap_guard())
    for argv in commands:
        lines.append("cmd=(" + " ".join(shell_quote(part) for part in argv) + ")\n")
        lines.append('"${cmd[@]}"\n')
    return "".join(lines)


def render_scripts(output_dir: Path, commands: dict[str, list[list[str]]], selected: list[str]) -> None:
    for section in SECTIONS:
        write_text(output_dir / "scripts" / f"execute-{section}.sh", render_command_script(section, commands[section]), executable=True)
    selected_lines = [script_header(), "sections=(" + " ".join(shell_quote(item) for item in selected) + ")\n"]
    unavailable = [section for section in selected if not commands[section]]
    if unavailable:
        selected_lines.append(
            "echo "
            + shell_quote(
                "ERROR: refusing before any delegated command runs because selected section(s) have no reviewed child command: "
                + ", ".join(unavailable)
                + ". Complete the intake and rerender."
            )
            + " >&2\nexit 2\n"
        )
    selected_lines.append("""for section in "${sections[@]}"; do
  case "${section}" in
    storage-catalog|experience)
      echo "ERROR: ${section} is handoff-only; refusing before any delegated command runs." >&2
      exit 2
      ;;
  esac
done
for section in "${sections[@]}"; do
  "${SCRIPT_DIR}/execute-${section}.sh"
done
""")
    write_text(output_dir / "scripts/execute-selected.sh", "".join(selected_lines), executable=True)


def render(args: argparse.Namespace) -> dict[str, Any]:
    spec = load_spec(args.spec)
    config = merge_config(spec)
    output_dir = Path(args.output_dir).expanduser().resolve()
    selected = selected_sections(args.execute)
    commands = build_commands(config, output_dir)
    plan = build_apply_plan(config, commands, selected, output_dir)
    if args.dry_run:
        return plan

    prepare_output_dir(output_dir)
    rows = coverage_rows(config)
    products = product_rows()
    gaps = config_gaps(config)
    write_json(output_dir / "apply-plan.json", plan)
    render_reports(output_dir, config, rows, products, gaps)
    render_layer_assets(output_dir, config, rows)
    render_metadata(output_dir, config, rows, gaps)
    render_handoff_and_doctor(output_dir, config, rows, gaps, selected)
    render_scripts(output_dir, commands, selected)
    return {
        "output_dir": str(output_dir),
        "coverage_report": str(output_dir / "coverage-report.json"),
        "product_matrix": str(output_dir / "product-matrix.json"),
        "source_ledger": str(output_dir / "source-ledger.json"),
        "gap_register": str(output_dir / "gap-register.md"),
        "doctor_report": str(output_dir / "doctor-report.md"),
        "apply_plan": str(output_dir / "apply-plan.json"),
        "selected_sections": selected,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = render(args)
    if args.json or args.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Rendered Cisco Data Fabric assets to {payload['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

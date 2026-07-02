#!/usr/bin/env python3
"""Render Splunk Admin Doctor reports and selected fix packets."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


SKILL_NAME = "splunk-admin-doctor"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "splunk-admin-doctor-rendered"

FIX_KINDS = {
    "direct_fix",
    "delegated_fix",
    "manual_support",
    "diagnose_only",
    "not_applicable",
}
FIX_KIND_RANK = {
    "direct_fix": 4,
    "delegated_fix": 3,
    "manual_support": 2,
    "diagnose_only": 1,
    "not_applicable": 0,
}
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
REQUIRED_RULE_FIELDS = {
    "id",
    "domain",
    "platform",
    "severity",
    "evidence",
    "source_doc",
    "fix_kind",
    "preview_command",
    "apply_command",
    "handoff_skill",
    "rollback_or_validation",
}


SOURCE_DOCS = {
    "acs": "https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual",
    "agent_management": "https://help.splunk.com/en/splunk-enterprise/administer/update-your-deployment/10.0/agent-management/about-agent-management",
    "audit": "https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.4/audit-splunk-activity/about-audit-trail-events",
    "btool": "https://help.splunk.com/en/splunk-enterprise/administer/troubleshoot/10.4/first-steps/use-btool-to-troubleshoot-configurations",
    "cloud_config_validation": "https://help.splunk.com/en/splunk-cloud-platform/administer/admin-manual/10.5.2605/configure-your-splunk-cloud-platform-deployment/validating-configurations-using-the-btool-rest-api",
    "cloud_cmc": "https://help.splunk.com/en/splunk-cloud-platform/administer/admin-manual/10.5.2605/monitor-your-splunk-cloud-platform-deployment/introduction-to-the-cloud-monitoring-console",
    "cloud_rest": "https://help.splunk.com/en/splunk-cloud-platform/leverage-rest-apis",
    "config_validation": "https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.4/administer-splunk-enterprise-with-configuration-files/validate-configuration-changes",
    "data_management": "https://help.splunk.com/en/data-management/transform-and-route-data/explore-data-management-solutions/data-management-solutions",
    "dashboard_studio": "https://help.splunk.com/en/splunk-enterprise/create-dashboards-and-reports/dashboard-studio/10.4/whats-new-in-dashboard-studio/whats-new-in-dashboard-studio",
    "ddaa": "https://help.splunk.com/en/splunk-cloud-platform/administer/admin-manual/10.5.2605/manage-your-indexes-and-data-in-splunk-cloud-platform/store-expired-splunk-cloud-platform-data-in-a-splunk-managed-archive",
    "kvstore": "https://help.splunk.com/en?resourceId=Splunk_Admin_TroubleshootKVstore",
    "cim": "https://help.splunk.com/en/splunk-enterprise/common-information-model/6.1/introduction/overview-of-the-splunk-common-information-model",
    "diag": "https://help.splunk.com/en/splunk-enterprise/administer/troubleshoot/9.1/contact-splunk-support/generate-a-diagnostic-file",
    "backup": "https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.2/administer-splunk-enterprise-with-configuration-files/back-up-configuration-information",
    "federated_search": "https://help.splunk.com/en/splunk-cloud-platform/splunk-validated-architectures/splunk-platform-indexing-and-search/federated-search-for-splunk-platform",
    "monitoring": "https://help.splunk.com/en/splunk-enterprise/administer/monitor/10.0/introduction/monitoring-splunk-enterprise-overview",
    "products": "https://www.splunk.com/en_us/products.html",
    "splunkd_health": "https://help.splunk.com/en/splunk-enterprise/administer/monitor/10.0/proactive-splunk-component-monitoring-with-the-splunkd-health-report/about-proactive-splunk-component-monitoring",
    "smartstore": "https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.4/deploy-smartstore",
    "support_policy": "https://www.splunk.com/en_us/legal/splunk-software-support-policy.html",
    "workload_cloud": "https://help.splunk.com/en/splunk-cloud-platform/administer/admin-manual/9.2.2406/manage-search-workloads-in-splunk-cloud-platform/workload-management-overview",
}


COVERAGE_MANIFEST = [
    {
        "domain": "Connectivity and credentials",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "direct_fix", "enterprise": "direct_fix"},
        "policy": "REST/ACS reachability, TLS verification, and role/capability checks. Direct output is local guidance only.",
    },
    {
        "domain": "Cloud ACS control plane",
        "platforms": ["cloud"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "not_applicable"},
        "policy": "Diagnose ACS status and route allowlists, outbound ports, private connectivity, HEC, indexes, limits, apps, users/roles, DDSS, maintenance windows, tokens, and restarts.",
    },
    {
        "domain": "Cloud Monitoring Console",
        "platforms": ["cloud"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "not_applicable"},
        "policy": "Render exact CMC panel/runbook evidence. The doctor never modifies CMC.",
    },
    {
        "domain": "Enterprise health",
        "platforms": ["enterprise"],
        "coverage_by_platform": {"cloud": "not_applicable", "enterprise": "delegated_fix"},
        "policy": "Inspect splunkd health, server info/sysinfo hints, health.log, and btool errors.",
    },
    {
        "domain": "Platform lifecycle and topology",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Assess supported versions, upgrade paths, topology, runtime, sizing, host resources, and deployment compatibility.",
    },
    {
        "domain": "Config validation",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "direct_fix", "enterprise": "diagnose_only"},
        "policy": "Use the Cloud btool REST validation API or Enterprise 10.4+ Config Validation before applying .conf assets.",
    },
    {
        "domain": "Monitoring Console",
        "platforms": ["enterprise"],
        "coverage_by_platform": {"cloud": "not_applicable", "enterprise": "delegated_fix"},
        "policy": "Route distributed or standalone Monitoring Console remediation to the mature setup skill.",
    },
    {
        "domain": "Indexes and storage",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Detect missing indexes, retention risk, datatype drift, and SmartStore hints.",
    },
    {
        "domain": "Archive and data lifecycle",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Assess DDAA, archive/restore, SmartStore lifecycle, frozen data, and restore-test readiness without deleting data.",
    },
    {
        "domain": "Ingest paths",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Route HEC, S2S, UF/HF, SC4S, SC4SNMP, Stream, and Edge Processor gaps.",
    },
    {
        "domain": "Ingest processing and routing",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Assess Ingest Processor, Edge Processor, Ingest Actions, SPL2, Data Manager, OTLP, queues, destinations, drops, and dead-letter paths.",
    },
    {
        "domain": "Agent Management and forwarders",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Detect stale or missing agents, fleet/version health, deployment-server compatibility, server classes, and app/config rollout gaps.",
    },
    {
        "domain": "Distributed search and SHC",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "manual_support", "enterprise": "delegated_fix"},
        "policy": "Diagnose peers, Cloud CMC cluster signals, SHC captain/status, replication, and deployer hints; no cluster operation is run here.",
    },
    {
        "domain": "Federated search",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Assess providers, federated indexes, connectivity, knowledge-object drift, concurrency, and Hybrid Search migration readiness.",
    },
    {
        "domain": "Indexer clustering",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "manual_support", "enterprise": "delegated_fix"},
        "policy": "Diagnose Cloud CMC cluster signals plus Enterprise manager, peers, bundle, RF/SF, searchability, and maintenance mode.",
    },
    {
        "domain": "License/subscription",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "manual_support", "enterprise": "delegated_fix"},
        "policy": "Enterprise license work delegates to license-manager automation; Cloud usage concerns render support evidence.",
    },
    {
        "domain": "Search and scheduler",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Diagnose expensive jobs, skipped searches, saved-search health, and Search API readiness.",
    },
    {
        "domain": "Workload management",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "direct_fix", "enterprise": "delegated_fix"},
        "policy": "Enterprise assets delegate to workload-management setup; Cloud sc_admin rule/pool/admission gaps render an operator checklist.",
    },
    {
        "domain": "Apps and add-ons",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Detect installed app state, update gaps, permissions, restart-required flags, and private/restricted app handoffs.",
    },
    {
        "domain": "Auth, users, roles, tokens",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "diagnose_only", "enterprise": "diagnose_only"},
        "policy": "Diagnose RBAC, SAML/SSO, LDAP, MFA, inherited capabilities, token auth, and ACS role signals. No identity is deleted.",
    },
    {
        "domain": "TLS/PKI/security hardening",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "manual_support", "enterprise": "delegated_fix"},
        "policy": "Detect default certs, weak TLS hints, public exposure posture, and token/auth risks.",
    },
    {
        "domain": "Audit and compliance",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "diagnose_only", "enterprise": "diagnose_only"},
        "policy": "Assess audit-trail availability, forwarding, retention, privileged changes, and compliance evidence without changing audit data.",
    },
    {
        "domain": "KV Store and knowledge objects",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Diagnose and route KV status/backup, collection risk, CIM/data-model acceleration, lookup health, ACLs, and knowledge-object pressure.",
    },
    {
        "domain": "Dashboards and user experience",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Assess Dashboard Studio definitions, macros, permissions, missing searches, empty panels, and Secure Gateway/mobile readiness.",
    },
    {
        "domain": "Data source and semantic readiness",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Assess index/sourcetype flow, CIM, OCSF, ES/ITSI/ARI usability, macros, dashboards, and completion-gate evidence.",
    },
    {
        "domain": "Backup, DR, support evidence",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "manual_support", "enterprise": "manual_support"},
        "policy": "Render backup, DR, and diag/support evidence. The doctor never uploads bundles.",
    },
    {
        "domain": "Restart and maintenance orchestration",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Route pending restarts, reloads, maintenance windows, and topology-aware sequencing; never restart from the doctor.",
    },
    {
        "domain": "Product and solution handoffs",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Resolve detected Splunk, Cisco, AppDynamics, WideField, and Galileo product families to precise specialist routers.",
    },
    {
        "domain": "Diagnostic evidence completeness",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "diagnose_only", "enterprise": "diagnose_only"},
        "policy": "Distinguish assessed health from supported-but-unassessed features and fail closed in complete-evidence mode.",
    },
]


PRODUCT_ROUTE_CATALOG = [
    {
        "id": "splunk-platform",
        "name": "Splunk Cloud Platform and Splunk Enterprise",
        "aliases": ["splunk cloud platform", "splunk enterprise", "splunk platform"],
        "handoff_skills": ["splunk-platform-sizing", "splunk-enterprise-host-setup", "splunk-cloud-acs-admin-setup"],
        "covered_skill_names": [],
        "covered_skill_prefixes": [],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "splunk-security",
        "name": "Splunk Security portfolio",
        "aliases": [
            "enterprise security", "splunkenterprisesecuritysuite", "security essentials",
            "splunk_security_essentials", "asset risk intelligence", "splunkassetriskintelligence",
            "attack analyzer", "splunk_app_saa", "splunk_ta_saa", "user behavior analytics",
            "splunk uba", "pci compliance", "splunk app for pci compliance", "fraud analytics",
            "infosec app", "infosec_app_for_splunk", "da-ess-contentupdate",
        ],
        "handoff_skills": ["splunk-security-portfolio-setup", "splunk-data-source-readiness-doctor"],
        "covered_skill_names": [
            "splunk-asset-risk-intelligence-setup", "splunk-attack-analyzer-setup",
            "splunk-enterprise-security-config", "splunk-enterprise-security-install",
            "splunk-fraud-analytics-setup", "splunk-infosec-app-setup",
            "splunk-pci-compliance-setup", "splunk-uba-setup",
        ],
        "covered_skill_prefixes": ["splunk-security-"],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "splunk-itsi",
        "name": "Splunk IT Service Intelligence",
        "aliases": ["itsi", "sa-itoa", "it service intelligence"],
        "handoff_skills": ["splunk-itsi-setup", "splunk-itsi-config", "splunk-data-source-readiness-doctor"],
        "covered_skill_names": ["splunk-itsi-setup", "splunk-itsi-config"],
        "covered_skill_prefixes": [],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "splunk-soar",
        "name": "Splunk SOAR",
        "aliases": ["splunk soar", "splunk_app_soar", "phantom"],
        "handoff_skills": ["splunk-soar-setup"],
        "covered_skill_names": ["splunk-soar-setup"],
        "covered_skill_prefixes": [],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "splunk-observability",
        "name": "Splunk Observability Cloud",
        "aliases": ["splunk observability", "observability cloud", "splunk_ta_sim", "splunk_ta_otel"],
        "handoff_skills": [
            "splunk-observability-cloud-integration-setup",
            "splunk-observability-deep-native-workflows",
            "splunk-observability-native-ops",
        ],
        "covered_skill_names": [],
        "covered_skill_prefixes": ["splunk-observability-"],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "splunk-oncall",
        "name": "Splunk On-Call",
        "aliases": ["splunk on-call", "splunk oncall", "victorops", "ta-splunk-add-on-for-victorops"],
        "handoff_skills": ["splunk-oncall-setup"],
        "covered_skill_names": ["splunk-oncall-setup"],
        "covered_skill_prefixes": [],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "splunk-appdynamics",
        "name": "Splunk AppDynamics",
        "aliases": ["appdynamics", "splunk_ta_appdynamics", "splunk appdynamics"],
        "handoff_skills": ["splunk-appdynamics-setup"],
        "covered_skill_names": ["cisco-appdynamics-setup"],
        "covered_skill_prefixes": ["splunk-appdynamics-"],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "splunk-data-management",
        "name": "Splunk data management and ingest processing",
        "aliases": ["ingest processor", "edge processor", "ingest actions", "data manager"],
        "handoff_skills": [
            "splunk-ingest-processor-setup", "splunk-edge-processor-setup",
            "splunk-ingest-actions-setup", "splunk-cloud-data-manager-setup",
        ],
        "covered_skill_names": [
            "splunk-cloud-data-manager-setup", "splunk-edge-processor-setup",
            "splunk-ingest-actions", "splunk-ingest-actions-setup",
            "splunk-ingest-processor-setup", "splunk-spl2-pipeline-kit",
        ],
        "covered_skill_prefixes": [],
        "source_doc": SOURCE_DOCS["data_management"],
    },
    {
        "id": "splunk-ai",
        "name": "Splunk AI and machine learning",
        "aliases": ["splunk ai assistant", "splunk_ai_assistant_cloud", "machine learning toolkit", "mltk", "ai toolkit"],
        "handoff_skills": ["splunk-ai-assistant-setup", "splunk-ai-ml-toolkit-setup"],
        "covered_skill_names": ["splunk-ai-assistant-setup", "splunk-ai-ml-toolkit-setup"],
        "covered_skill_prefixes": [],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "splunk-mcp",
        "name": "Splunk MCP Server",
        "aliases": ["splunk mcp server", "splunk_mcp_server"],
        "handoff_skills": ["splunk-mcp-server-setup"],
        "covered_skill_names": ["splunk-mcp-server-setup"],
        "covered_skill_prefixes": [],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "cisco",
        "name": "Cisco product integrations",
        "aliases": ["cisco", "thousandeyes", "meraki", "intersight", "webex", "isovalent"],
        "handoff_skills": ["cisco-product-setup"],
        "covered_skill_names": [],
        "covered_skill_prefixes": ["cisco-"],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "widefield",
        "name": "WideField Security",
        "aliases": ["widefield", "widefield security"],
        "handoff_skills": ["widefield-security-setup"],
        "covered_skill_names": [],
        "covered_skill_prefixes": ["widefield-"],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "galileo",
        "name": "Galileo",
        "aliases": ["galileo", "galileo observe", "galileo agent control"],
        "handoff_skills": ["galileo-platform-setup"],
        "covered_skill_names": [],
        "covered_skill_prefixes": ["galileo-"],
        "source_doc": SOURCE_DOCS["products"],
    },
    {
        "id": "splunk-data-integrations",
        "name": "Splunk supported add-ons and data integrations",
        "aliases": ["supported add-ons", "technology add-on", "data integration"],
        "handoff_skills": ["splunk-supported-addons-setup", "splunk-data-source-readiness-doctor"],
        "covered_skill_names": [
            "splunk-amazon-kinesis-firehose-setup", "splunk-app-install", "splunk-db-connect-setup",
            "splunk-microsoft-cloud-setup", "splunk-supported-addons-setup",
        ],
        "covered_skill_prefixes": [],
        "covered_skill_suffixes": ["-ta-setup"],
        "source_doc": SOURCE_DOCS["products"],
    },
]


CANONICAL_SKILL_ALIASES = {
    "splunk-cim-data-model": "splunk-cim-data-model-setup",
    "splunk-cloud-acs-allowlist-setup": "splunk-cloud-acs-admin-setup",
    "splunk-dashboard-studio": "splunk-dashboard-studio-setup",
    "splunk-ddaa-archive": "splunk-ddaa-archive-setup",
    "splunk-ingest-actions": "splunk-ingest-actions-setup",
    "splunk-knowledge-objects": "splunk-knowledge-objects-setup",
    "splunk-kvstore-admin": "splunk-kvstore-admin-setup",
    "splunk-secure-gateway": "splunk-secure-gateway-setup",
}


def rule(
    *,
    rule_id: str,
    domain: str,
    platform: str,
    severity: str,
    evidence: str,
    source_doc: str,
    fix_kind: str,
    preview_command: str,
    apply_command: str,
    handoff_skill: str,
    rollback_or_validation: str,
    trigger: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "domain": domain,
        "platform": platform,
        "severity": severity,
        "evidence": evidence,
        "source_doc": source_doc,
        "fix_kind": fix_kind,
        "preview_command": preview_command,
        "apply_command": apply_command,
        "handoff_skill": handoff_skill,
        "rollback_or_validation": rollback_or_validation,
        "trigger": trigger,
    }


RULE_CATALOG = [
    rule(
        rule_id="SAD-APPS-PERMISSION-GAP",
        domain="Apps and add-ons",
        platform="both",
        severity="medium",
        evidence="apps.permission_issues, apps.disabled_required, apps.deployment_errors, apps.unsupported, apps.appinspect_issues, or apps.runtime_compatibility_issues is populated.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="Review app ownership, compatibility, permissions, and completion-gate handoffs.",
        apply_command="Route package delivery to app install and configuration/data proof to the owning setup and readiness workflows.",
        handoff_skill="splunk-app-install,splunk-supported-addons-setup,splunk-data-source-readiness-doctor",
        rollback_or_validation="Rerun the owning app validation and doctor; verify permissions, compatibility, and data/dashboard evidence.",
        trigger={
            "any": [
                {"path": "apps.permission_issues", "truthy": True},
                {"path": "apps.disabled_required", "truthy": True},
                {"path": "apps.deployment_errors", "truthy": True},
                {"path": "apps.unsupported", "truthy": True},
                {"path": "apps.appinspect_issues", "truthy": True},
                {"path": "apps.runtime_compatibility_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-APPS-RESTART-REQUIRED",
        domain="Apps and add-ons",
        platform="both",
        severity="medium",
        evidence="apps.restart_required contains one or more app names.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-app-install/scripts/setup.sh --help",
        apply_command="Render an app-install handoff; restarts remain explicit ACS/support or operator actions.",
        handoff_skill="splunk-app-install,splunk-platform-restart-orchestrator",
        rollback_or_validation="Run doctor again and verify apps.restart_required is empty.",
        trigger={"any": [{"path": "apps.restart_required", "truthy": True}]},
    ),
    rule(
        rule_id="SAD-APPS-UPDATE-GAP",
        domain="Apps and add-ons",
        platform="both",
        severity="medium",
        evidence="apps.update_gaps contains one or more stale or unsupported apps.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-app-install/scripts/setup.sh --help",
        apply_command="Render an app-install handoff for package review/install/list actions.",
        handoff_skill="splunk-app-install,splunk-supported-addons-setup,splunk-data-source-readiness-doctor",
        rollback_or_validation="Run doctor again and verify apps.update_gaps is empty or acknowledged.",
        trigger={"any": [{"path": "apps.update_gaps", "truthy": True}]},
    ),
    rule(
        rule_id="SAD-AUDIT-COVERAGE-GAP",
        domain="Audit and compliance",
        platform="both",
        severity="high",
        evidence="audit.issues, audit.index_issues, audit.forwarding_issues, audit.retention_risks, or audit.privileged_change_gaps is populated.",
        source_doc=SOURCE_DOCS["audit"],
        fix_kind="diagnose_only",
        preview_command="Review _audit availability, retention, forwarding, privileged changes, and access controls.",
        apply_command="No audit event, retention, or forwarding mutation is performed by doctor.",
        handoff_skill="",
        rollback_or_validation="Rerun the audit searches and doctor after the approved compliance change.",
        trigger={
            "any": [
                {"path": "audit.issues", "truthy": True},
                {"path": "audit.index_issues", "truthy": True},
                {"path": "audit.forwarding_issues", "truthy": True},
                {"path": "audit.retention_risks", "truthy": True},
                {"path": "audit.privileged_change_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-AUTH-RBAC-GAP",
        domain="Auth, users, roles, tokens",
        platform="both",
        severity="medium",
        evidence="auth.rbac_gaps contains users, roles, inherited capabilities, or ACS RBAC gaps.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="diagnose_only",
        preview_command="Review doctor-report.md RBAC evidence and map changes to a change ticket.",
        apply_command="No direct role/user mutation in v1.",
        handoff_skill="",
        rollback_or_validation="Run doctor again and verify auth.rbac_gaps is empty or explicitly accepted.",
        trigger={"any": [{"path": "auth.rbac_gaps", "truthy": True}]},
    ),
    rule(
        rule_id="SAD-AUTH-SSO-GAP",
        domain="Auth, users, roles, tokens",
        platform="both",
        severity="high",
        evidence="auth.sso_issues, auth.saml_issues, auth.ldap_issues, auth.mfa_issues, or auth.idp_certificate_issues is populated.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="diagnose_only",
        preview_command="Review SSO/SAML, LDAP, MFA, SCIM, IdP certificate, and break-glass evidence.",
        apply_command="No authentication-provider or identity mutation is performed by doctor.",
        handoff_skill="",
        rollback_or_validation="Test approved interactive and service-account login paths, then rerun doctor.",
        trigger={
            "any": [
                {"path": "auth.sso_issues", "truthy": True},
                {"path": "auth.saml_issues", "truthy": True},
                {"path": "auth.ldap_issues", "truthy": True},
                {"path": "auth.mfa_issues", "truthy": True},
                {"path": "auth.idp_certificate_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-AUTH-TOKEN-RISK",
        domain="Auth, users, roles, tokens",
        platform="both",
        severity="medium",
        evidence="auth.weak_tokens, auth.token_risks, or auth.token_auth_without_controls is populated/true.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="diagnose_only",
        preview_command="Review token posture; rotate or disable through approved admin workflow.",
        apply_command="No token deletion, rotation, or auth change in v1.",
        handoff_skill="",
        rollback_or_validation="Run doctor again and verify weak token findings are cleared.",
        trigger={
            "any": [
                {"path": "auth.weak_tokens", "truthy": True},
                {"path": "auth.token_risks", "truthy": True},
                {"path": "auth.token_auth_without_controls", "equals": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-BACKUP-DR-GAP",
        domain="Backup, DR, support evidence",
        platform="both",
        severity="high",
        evidence="backup.dr_issues, backup.restore_test_stale, backup.rpo_rto_gaps, backup.kvstore_issues, or backup.indexed_data_issues is populated/true.",
        source_doc=SOURCE_DOCS["backup"],
        fix_kind="manual_support",
        preview_command="Review the generated backup/restore/DR readiness packet.",
        apply_command="Render a DR and restore-test packet only; no backup, restore, failover, or upload is performed.",
        handoff_skill="",
        rollback_or_validation="Complete an approved restore/failover exercise and rerun doctor with dated RPO/RTO evidence.",
        trigger={
            "any": [
                {"path": "backup.dr_issues", "truthy": True},
                {"path": "backup.restore_test_stale", "equals": True},
                {"path": "backup.rpo_rto_gaps", "truthy": True},
                {"path": "backup.kvstore_issues", "truthy": True},
                {"path": "backup.indexed_data_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-BACKUP-STALE",
        domain="Backup, DR, support evidence",
        platform="enterprise",
        severity="medium",
        evidence="backup.last_config_backup_stale is true or backup.last_config_backup_age_days is greater than 30.",
        source_doc=SOURCE_DOCS["backup"],
        fix_kind="manual_support",
        preview_command="Review backup support packet under support-tickets/.",
        apply_command="Render backup runbook packet only; no backup upload or remote copy is performed.",
        handoff_skill="",
        rollback_or_validation="Run a controlled config backup, then rerun doctor and verify backup evidence is fresh.",
        trigger={
            "any": [
                {"path": "backup.last_config_backup_stale", "equals": True},
                {"path": "backup.last_config_backup_age_days", "gt": 30},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-ACS-ADMIN-GAP",
        domain="Cloud ACS control plane",
        platform="cloud",
        severity="high",
        evidence="ACS outbound-port, private-connectivity, DDSS, limits, maintenance, app-permission, token, identity, EMEK, or retry findings are populated.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-cloud-acs-admin-setup/scripts/setup.sh --phase audit --dry-run",
        apply_command="Render an ACS administration handoff; all ACS writes remain explicitly gated in the specialist skill.",
        handoff_skill="splunk-cloud-acs-admin-setup",
        rollback_or_validation="Run the ACS audit again and rerun doctor after the approved change.",
        trigger={
            "any": [
                {"path": "acs.outbound_ports.issues", "truthy": True},
                {"path": "acs.private_connectivity.issues", "truthy": True},
                {"path": "acs.ddss.issues", "truthy": True},
                {"path": "acs.limits.issues", "truthy": True},
                {"path": "acs.maintenance_windows.issues", "truthy": True},
                {"path": "acs.app_permissions.issues", "truthy": True},
                {"path": "acs.tokens.issues", "truthy": True},
                {"path": "acs.identity.issues", "truthy": True},
                {"path": "acs.emek.issues", "truthy": True},
                {"path": "acs.failed_operations", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-ACS-ALLOWLIST-GAP",
        domain="Cloud ACS control plane",
        platform="cloud",
        severity="high",
        evidence="acs.allowlist.search_api_allowed is false or acs.allowlist.gaps is populated.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-cloud-acs-admin-setup/scripts/setup.sh --phase audit --dry-run",
        apply_command="Render an ACS allowlist handoff; actual allowlist mutation stays in the ACS skill.",
        handoff_skill="splunk-cloud-acs-admin-setup",
        rollback_or_validation="Audit ACS allowlists again and rerun doctor.",
        trigger={
            "any": [
                {"path": "acs.allowlist.search_api_allowed", "equals": False},
                {"path": "acs.allowlist.gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-ACS-DEGRADED",
        domain="Cloud ACS control plane",
        platform="cloud",
        severity="high",
        evidence="acs.reachable is false, or acs.status is degraded/error.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="manual_support",
        preview_command="Review generated Cloud support packet for ACS status, stack, and endpoint evidence.",
        apply_command="Render support packet only; no restart or maintenance action is performed.",
        handoff_skill="",
        rollback_or_validation="Run ACS status after Splunk Support or platform recovery and rerun doctor.",
        trigger={
            "any": [
                {"path": "acs.reachable", "equals": False},
                {"path": "acs.status", "in": ["degraded", "error", "failed", "red"]},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-ACS-RBAC-GAP",
        domain="Cloud ACS control plane",
        platform="cloud",
        severity="high",
        evidence="acs.rbac_issues, acs.user_issues, acs.role_issues, or acs.capability_issues is populated.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-cloud-acs-admin-setup/scripts/setup.sh --phase audit --dry-run",
        apply_command="Render an ACS identity/RBAC handoff; no user, role, or capability is changed by doctor.",
        handoff_skill="splunk-cloud-acs-admin-setup",
        rollback_or_validation="Audit ACS users, roles, capabilities, ownership, and effective access, then rerun doctor.",
        trigger={
            "any": [
                {"path": "acs.rbac_issues", "truthy": True},
                {"path": "acs.user_issues", "truthy": True},
                {"path": "acs.role_issues", "truthy": True},
                {"path": "acs.capability_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-CMC-CAPACITY",
        domain="Cloud Monitoring Console",
        platform="cloud",
        severity="high",
        evidence="cmc.capacity status is degraded or findings are populated.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="delegated_fix",
        preview_command="Review CMC capacity, usage, index/search resource, and Cloud Flex panels.",
        apply_command="Render a Cloud sizing/capacity handoff; no subscription or infrastructure is changed.",
        handoff_skill="splunk-platform-sizing",
        rollback_or_validation="Recheck CMC capacity and usage after approved sizing or workload changes.",
        trigger={
            "any": [
                {"path": "cmc.capacity.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "cmc.capacity.findings", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-CMC-DATA-QUALITY",
        domain="Cloud Monitoring Console",
        platform="cloud",
        severity="high",
        evidence="cmc.data_quality status is degraded or findings are populated.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="delegated_fix",
        preview_command="Review CMC data quality, timestamp, line-breaking, sourcetype, latency, and volume evidence.",
        apply_command="Render a data-readiness and owning-source handoff; no parsing or routing configuration is changed.",
        handoff_skill="splunk-data-source-readiness-doctor,splunk-supported-addons-setup",
        rollback_or_validation="Validate representative events, metadata, latency, and dashboards after remediation.",
        trigger={
            "any": [
                {"path": "cmc.data_quality.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "cmc.data_quality.findings", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-CMC-FORWARDER",
        domain="Cloud Monitoring Console",
        platform="cloud",
        severity="medium",
        evidence="cmc.forwarders status is degraded or findings are populated.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="delegated_fix",
        preview_command="Review CMC forwarder/agent fleet, version, connectivity, and throughput evidence.",
        apply_command="Render Agent Management and Universal Forwarder handoffs; no agent is changed.",
        handoff_skill="splunk-agent-management-setup,splunk-universal-forwarder-setup",
        rollback_or_validation="Verify agent connectivity, versions, effective configuration, and data flow.",
        trigger={
            "any": [
                {"path": "cmc.forwarders.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "cmc.forwarders.findings", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-CMC-HEC",
        domain="Cloud Monitoring Console",
        platform="cloud",
        severity="high",
        evidence="cmc.hec status is degraded or findings are populated.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="delegated_fix",
        preview_command="Review CMC HEC receive/index throughput, errors, acknowledgement, and token/index evidence.",
        apply_command="Render HEC and readiness handoffs; no token or global HEC setting is changed.",
        handoff_skill="splunk-hec-service-setup,splunk-data-source-readiness-doctor",
        rollback_or_validation="Compare sent, received, acknowledged, and indexed events after remediation.",
        trigger={
            "any": [
                {"path": "cmc.hec.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "cmc.hec.findings", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-CMC-ISSUE",
        domain="Cloud Monitoring Console",
        platform="cloud",
        severity="medium",
        evidence="cmc.findings is populated or any CMC panel status is degraded.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="manual_support",
        preview_command="Review generated CMC panel evidence and support packet.",
        apply_command="Render CMC runbook/support packet only; the doctor never modifies CMC.",
        handoff_skill="",
        rollback_or_validation="Recheck the referenced Cloud Monitoring Console panels.",
        trigger={
            "any": [
                {"path": "cmc.findings", "truthy": True},
                {"path": "cmc.ingest.status", "not_in": ["ok", "green", "healthy", None]},
                {"path": "cmc.indexing.status", "not_in": ["ok", "green", "healthy", None]},
                {"path": "cmc.search.status", "not_in": ["ok", "green", "healthy", None]},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-CMC-MAINTENANCE",
        domain="Cloud Monitoring Console",
        platform="cloud",
        severity="medium",
        evidence="cmc.maintenance status is degraded or findings/change-freeze issues are populated.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="delegated_fix",
        preview_command="Review CMC maintenance, change freeze, platform upgrade, app, and restart windows.",
        apply_command="Render ACS maintenance and restart-orchestration handoffs; no maintenance action is initiated.",
        handoff_skill="splunk-cloud-acs-admin-setup,splunk-platform-restart-orchestrator",
        rollback_or_validation="Recheck maintenance status and post-maintenance platform health.",
        trigger={
            "any": [
                {"path": "cmc.maintenance.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "cmc.maintenance.findings", "truthy": True},
                {"path": "cmc.maintenance.change_freeze_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-CONFIG-VALIDATION-GAP",
        domain="Config validation",
        platform="cloud",
        severity="info",
        evidence="Cloud 10.3.2512+ supports btool REST validation, or config_validation errors/unvalidated changes are present.",
        source_doc=SOURCE_DOCS["cloud_config_validation"],
        fix_kind="direct_fix",
        preview_command="Validate candidate .conf content with POST /services/properties/<config>?validate=true before deployment.",
        apply_command="Render the btool REST validation checklist only; doctor does not upload or apply configuration.",
        handoff_skill="",
        rollback_or_validation="Repeat validation until it returns success, then use the supported Cloud configuration path.",
        trigger={
            "any": [
                {"path": "server.version", "version_gte": "10.3.2512"},
                {"path": "config_validation.validated", "equals": False},
                {"path": "config_validation.errors", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-IDXCLUSTER-DEGRADED",
        domain="Indexer clustering",
        platform="cloud",
        severity="high",
        evidence="cmc.indexer_cluster status is degraded or findings are populated.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="manual_support",
        preview_command="Review Cloud Monitoring Console indexer-cluster panels and capture the affected stack, peers, and time window.",
        apply_command="Render a Cloud cluster support packet only; cluster configuration remains Splunk-managed.",
        handoff_skill="",
        rollback_or_validation="Recheck the CMC indexer-cluster panels after platform recovery or support action.",
        trigger={
            "any": [
                {"path": "cmc.indexer_cluster.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "cmc.indexer_cluster.findings", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-INDEX-MISSING",
        domain="Indexes and storage",
        platform="cloud",
        severity="medium",
        evidence="indexes.missing contains one or more required Cloud indexes.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-cloud-acs-admin-setup/scripts/setup.sh --phase audit --dry-run",
        apply_command="Render an ACS index handoff; the doctor does not create or modify indexes.",
        handoff_skill="splunk-cloud-acs-admin-setup",
        rollback_or_validation="Audit ACS indexes and rerun doctor after the owning data workflow validates ingestion.",
        trigger={"any": [{"path": "indexes.missing", "truthy": True}]},
    ),
    rule(
        rule_id="SAD-CLOUD-KVSTORE-DEGRADED",
        domain="KV Store and knowledge objects",
        platform="cloud",
        severity="high",
        evidence="kvstore.status is failed/degraded/red/down or kvstore.errors is populated on Cloud.",
        source_doc=SOURCE_DOCS["kvstore"],
        fix_kind="manual_support",
        preview_command="Capture Cloud KV Store status, affected apps/collections, search head, and timestamps.",
        apply_command="Render a Cloud support packet only; no KV Store repair, cleanup, or resync is performed.",
        handoff_skill="",
        rollback_or_validation="Verify Cloud KV Store recovery and affected app collections, then rerun doctor.",
        trigger={
            "any": [
                {"path": "kvstore.status", "in": ["failed", "degraded", "red", "down"]},
                {"path": "kvstore.errors", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-LIFECYCLE-RISK",
        domain="Platform lifecycle and topology",
        platform="cloud",
        severity="high",
        evidence="lifecycle.version_unsupported, lifecycle.upgrade_issues, lifecycle.maintenance_issues, lifecycle.experience_issues, or lifecycle.sidecar_issues is populated/true.",
        source_doc=SOURCE_DOCS["support_policy"],
        fix_kind="manual_support",
        preview_command="Review Cloud train, Experience, maintenance, entitlement, sidecar, and app-compatibility evidence.",
        apply_command="Render a Cloud lifecycle/support packet only; no upgrade or maintenance action is initiated.",
        handoff_skill="",
        rollback_or_validation="Confirm the supported Cloud train and maintenance outcome, then rerun doctor.",
        trigger={
            "any": [
                {"path": "lifecycle.version_unsupported", "equals": True},
                {"path": "lifecycle.upgrade_issues", "truthy": True},
                {"path": "lifecycle.maintenance_issues", "truthy": True},
                {"path": "lifecycle.experience_issues", "truthy": True},
                {"path": "lifecycle.sidecar_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-SECURITY-TLS",
        domain="TLS/PKI/security hardening",
        platform="cloud",
        severity="high",
        evidence="security.server_tls_findings, security.platform_certificate_issues, or security.weak_tls is populated/true on Cloud.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="manual_support",
        preview_command="Separate client trust-store failures from Splunk-managed server TLS and capture endpoint/cipher evidence.",
        apply_command="Render a Cloud TLS support packet only; Enterprise PKI automation is not used for Cloud endpoints.",
        handoff_skill="",
        rollback_or_validation="Verify TLS 1.2+ with trusted certificates after local trust or Splunk Support remediation.",
        trigger={
            "any": [
                {"path": "security.server_tls_findings", "truthy": True},
                {"path": "security.platform_certificate_issues", "truthy": True},
                {"path": "security.weak_tls", "equals": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CLOUD-SHC-DEGRADED",
        domain="Distributed search and SHC",
        platform="cloud",
        severity="high",
        evidence="cmc.shc status is degraded or findings are populated.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="manual_support",
        preview_command="Review Cloud Monitoring Console search-head-cluster panels and capture captain/member evidence.",
        apply_command="Render a Cloud SHC support packet only; no cluster action is performed.",
        handoff_skill="",
        rollback_or_validation="Recheck the CMC SHC panels after recovery or support action.",
        trigger={
            "any": [
                {"path": "cmc.shc.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "cmc.shc.findings", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CONNECTIVITY-REST-DENIED",
        domain="Connectivity and credentials",
        platform="both",
        severity="high",
        evidence="rest.denied is true, rest.reachable is false, REST probes fail, or rest.status_code is 401/403.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="direct_fix",
        preview_command="Review credentials file path, target URI, role capabilities, and search-api allowlist evidence.",
        apply_command="Render local credential/TLS checklist only; no secret is read from chat or argv.",
        handoff_skill="",
        rollback_or_validation="Run doctor again and verify REST reachability and authorization are green.",
        trigger={
            "any": [
                {"path": "rest.denied", "equals": True},
                {"path": "rest.reachable", "equals": False},
                {"path": "rest.status_code", "in": [401, 403]},
                {"path": "rest.probe_errors", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-CONNECTIVITY-TLS-UNVERIFIED",
        domain="Connectivity and credentials",
        platform="both",
        severity="medium",
        evidence="rest.tls_verified or acs.tls_verified is false.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="direct_fix",
        preview_command="Review CA bundle, SPLUNK_* URI scheme, and local trust store configuration.",
        apply_command="Render local TLS checklist only; no local trust-store mutation is performed.",
        handoff_skill="",
        rollback_or_validation="Run doctor again and verify TLS verification is enabled.",
        trigger={
            "any": [
                {"path": "rest.tls_verified", "equals": False},
                {"path": "acs.tls_verified", "equals": False},
            ]
        },
    ),
    rule(
        rule_id="SAD-DASHBOARD-STUDIO-GAP",
        domain="Dashboards and user experience",
        platform="both",
        severity="medium",
        evidence="dashboards.definition_issues, dashboards.permission_issues, dashboards.macro_issues, dashboards.empty_panels, or dashboards.missing_searches is populated.",
        source_doc=SOURCE_DOCS["dashboard_studio"],
        fix_kind="delegated_fix",
        preview_command="Review Dashboard Studio definition, ACL, macro, search, and panel evidence.",
        apply_command="Render Dashboard Studio and data-readiness handoffs; no view is published by doctor.",
        handoff_skill="splunk-dashboard-studio-setup,splunk-data-source-readiness-doctor",
        rollback_or_validation="Validate the view JSON/XML, ACLs, macros, searches, and populated panels, then rerun doctor.",
        trigger={
            "any": [
                {"path": "dashboards.definition_issues", "truthy": True},
                {"path": "dashboards.permission_issues", "truthy": True},
                {"path": "dashboards.macro_issues", "truthy": True},
                {"path": "dashboards.empty_panels", "truthy": True},
                {"path": "dashboards.missing_searches", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-DATA-SOURCE-READINESS-GAP",
        domain="Data source and semantic readiness",
        platform="both",
        severity="high",
        evidence="data_readiness.issues, cim.issues, ocsf.issues, data_readiness.dashboard_issues, or data_readiness.completion_gate_gaps is populated.",
        source_doc=SOURCE_DOCS["cim"],
        fix_kind="delegated_fix",
        preview_command="Run the data-source readiness doctor for index, sourcetype, CIM, OCSF, macro, and dashboard proof.",
        apply_command="Render readiness, CIM, and owning add-on handoffs; package installation alone is not considered complete.",
        handoff_skill="splunk-data-source-readiness-doctor,splunk-cim-data-model-setup,splunk-supported-addons-setup",
        rollback_or_validation="Rerun the readiness doctor and require ingest plus shipped-dashboard evidence.",
        trigger={
            "any": [
                {"path": "data_readiness.issues", "truthy": True},
                {"path": "cim.issues", "truthy": True},
                {"path": "ocsf.issues", "truthy": True},
                {"path": "data_readiness.dashboard_issues", "truthy": True},
                {"path": "data_readiness.completion_gate_gaps", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-DDAA-ARCHIVE-GAP",
        domain="Archive and data lifecycle",
        platform="cloud",
        severity="medium",
        evidence="ddaa.issues, ddaa.retention_issues, ddaa.restore_issues, ddss.issues, or archive.restore_issues is populated.",
        source_doc=SOURCE_DOCS["ddaa"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-ddaa-archive-setup/scripts/setup.sh --help",
        apply_command="Render distinct DDAA/DDSS/archive handoffs; no retention, archive, or restore operation is performed.",
        handoff_skill="splunk-ddaa-archive-setup,splunk-cloud-acs-admin-setup",
        rollback_or_validation="Audit searchable/archive retention and complete a controlled restore check, then rerun doctor.",
        trigger={
            "any": [
                {"path": "ddaa.issues", "truthy": True},
                {"path": "ddaa.retention_issues", "truthy": True},
                {"path": "ddaa.restore_issues", "truthy": True},
                {"path": "ddss.issues", "truthy": True},
                {"path": "archive.restore_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-DEPLOYMENT-CAPACITY-RISK",
        domain="Platform lifecycle and topology",
        platform="both",
        severity="high",
        evidence="capacity.issues, capacity.cpu_pressure, capacity.memory_pressure, capacity.disk_pressure, capacity.dispatch_pressure, or topology.sizing_issues is populated/true.",
        source_doc=SOURCE_DOCS["monitoring"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-platform-sizing/scripts/setup.sh --help",
        apply_command="Render a topology/sizing handoff; no infrastructure is provisioned by doctor.",
        handoff_skill="splunk-platform-sizing",
        rollback_or_validation="Re-run capacity and topology validation after approved scaling or workload changes.",
        trigger={
            "any": [
                {"path": "capacity.issues", "truthy": True},
                {"path": "capacity.cpu_pressure", "equals": True},
                {"path": "capacity.memory_pressure", "equals": True},
                {"path": "capacity.disk_pressure", "equals": True},
                {"path": "capacity.dispatch_pressure", "equals": True},
                {"path": "topology.sizing_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-DEPLOYMENT-RUNTIME-GAP",
        domain="Platform lifecycle and topology",
        platform="enterprise",
        severity="high",
        evidence="runtime.issues, topology.issues, kubernetes.issues, os_prerequisites.issues, time_sync.issues, or sidecars.issues is populated.",
        source_doc=SOURCE_DOCS["monitoring"],
        fix_kind="delegated_fix",
        preview_command="Review host, Kubernetes, sidecar, OS, DNS, and time-sync topology evidence.",
        apply_command="Render Enterprise host/Kubernetes specialist handoffs; no runtime mutation is performed.",
        handoff_skill="splunk-enterprise-host-setup,splunk-enterprise-kubernetes-setup,splunk-platform-sizing",
        rollback_or_validation="Validate the target runtime and topology after specialist remediation, then rerun doctor.",
        trigger={
            "any": [
                {"path": "runtime.issues", "truthy": True},
                {"path": "topology.issues", "truthy": True},
                {"path": "kubernetes.issues", "truthy": True},
                {"path": "os_prerequisites.issues", "truthy": True},
                {"path": "time_sync.issues", "truthy": True},
                {"path": "sidecars.issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-DEPLOYMENT-SERVER-DEGRADED",
        domain="Agent Management and forwarders",
        platform="enterprise",
        severity="high",
        evidence="agent-management health/version/config drift or deployment-server server-class/rollout/prohibited-target issues are populated.",
        source_doc=SOURCE_DOCS["agent_management"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-deployment-server-setup/scripts/setup.sh --help",
        apply_command="Render Agent Management/deployment-server handoffs; no server-class reload or client retarget is performed.",
        handoff_skill="splunk-deployment-server-setup,splunk-agent-management-setup",
        rollback_or_validation="Audit agents, server classes, checksums, rollout status, and prohibited cluster targets, then rerun doctor.",
        trigger={
            "any": [
                {"path": "agent_management.issues", "truthy": True},
                {"path": "agent_management.version_gaps", "truthy": True},
                {"path": "agent_management.configuration_drift", "truthy": True},
                {"path": "agent_management.upgrade_failures", "truthy": True},
                {"path": "deployment_server.issues", "truthy": True},
                {"path": "deployment_server.serverclass_conflicts", "truthy": True},
                {"path": "deployment_server.rollout_failures", "truthy": True},
                {"path": "deployment_server.prohibited_targets", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-DIAG-NOT-READY",
        domain="Backup, DR, support evidence",
        platform="both",
        severity="low",
        evidence="support.diag_ready is false or support.diag_blockers is populated.",
        source_doc=SOURCE_DOCS["diag"],
        fix_kind="manual_support",
        preview_command="Review support-tickets/diag-readiness.md.",
        apply_command="Render diag readiness packet only; no diag bundle is generated or uploaded.",
        handoff_skill="",
        rollback_or_validation="Generate diag through approved Splunk workflow and attach it to the support case.",
        trigger={
            "any": [
                {"path": "support.diag_ready", "equals": False},
                {"path": "support.diag_blockers", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-DISTSEARCH-PEER-DOWN",
        domain="Distributed search and SHC",
        platform="enterprise",
        severity="high",
        evidence="distributed_search.peer_errors or distributed_search.peers_down is populated.",
        source_doc=SOURCE_DOCS["splunkd_health"],
        fix_kind="diagnose_only",
        preview_command="Review distsearch peer evidence and Monitoring Console peer status.",
        apply_command="No distributed-search mutation in v1.",
        handoff_skill="",
        rollback_or_validation="Verify peers are healthy in Monitoring Console and rerun doctor.",
        trigger={
            "any": [
                {"path": "distributed_search.peer_errors", "truthy": True},
                {"path": "distributed_search.peers_down", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-ENT-BTOOL-ERRORS",
        domain="Enterprise health",
        platform="enterprise",
        severity="high",
        evidence="btool.errors contains parse, stanza, or precedence issues.",
        source_doc=SOURCE_DOCS["btool"],
        fix_kind="diagnose_only",
        preview_command="Review btool error excerpts in doctor-report.md.",
        apply_command="No automatic configuration rewrite in v1.",
        handoff_skill="",
        rollback_or_validation="Run splunk btool check --debug and rerun doctor after fixing config.",
        trigger={"any": [{"path": "btool.errors", "truthy": True}]},
    ),
    rule(
        rule_id="SAD-ENT-CONFIG-VALIDATION-104",
        domain="Config validation",
        platform="enterprise",
        severity="info",
        evidence="server.version is 10.4 or newer; run Splunk Config Validation before applying rendered .conf assets.",
        source_doc=SOURCE_DOCS["config_validation"],
        fix_kind="diagnose_only",
        preview_command="Review rendered .conf assets with Splunk Config Validation before apply.",
        apply_command="No doctor-side apply; use Splunk Config Validation in Splunk Web or CLI per Splunk documentation.",
        handoff_skill="",
        rollback_or_validation="Re-run Config Validation after changes and before restart.",
        trigger={"any": [{"path": "server.version", "version_gte": "10.4"}]},
    ),
    rule(
        rule_id="SAD-ENT-HEALTH-RED",
        domain="Enterprise health",
        platform="enterprise",
        severity="high",
        evidence="splunkd.health.status is red/yellow/degraded or splunkd.health.failures is populated.",
        source_doc=SOURCE_DOCS["splunkd_health"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-monitoring-console-setup/scripts/setup.sh --phase status --dry-run",
        apply_command="Render Monitoring Console/status handoff; no restart is performed.",
        handoff_skill="splunk-monitoring-console-setup",
        rollback_or_validation="Run doctor again and verify splunkd.health.status is green/healthy.",
        trigger={
            "any": [
                {"path": "splunkd.health.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "splunkd.health.failures", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-ENT-LIFECYCLE-RISK",
        domain="Platform lifecycle and topology",
        platform="enterprise",
        severity="critical",
        evidence="lifecycle.version_unsupported, lifecycle.eos, lifecycle.near_eos, lifecycle.upgrade_path_issues, lifecycle.app_compatibility_issues, lifecycle.kvstore_upgrade_issues, or lifecycle.forwarder_compatibility_issues is populated/true.",
        source_doc=SOURCE_DOCS["support_policy"],
        fix_kind="delegated_fix",
        preview_command="Review supported train, upgrade hops, KV Store, app, forwarder, OS, and topology compatibility.",
        apply_command="Render host, topology, app, and restart handoffs; no binary upgrade is performed by doctor.",
        handoff_skill="splunk-enterprise-host-setup,splunk-platform-sizing,splunk-app-install,splunk-platform-restart-orchestrator",
        rollback_or_validation="Complete pre/post-upgrade validation on the supported path and rerun doctor.",
        trigger={
            "any": [
                {"path": "lifecycle.version_unsupported", "equals": True},
                {"path": "lifecycle.eos", "equals": True},
                {"path": "lifecycle.near_eos", "equals": True},
                {"path": "lifecycle.upgrade_path_issues", "truthy": True},
                {"path": "lifecycle.app_compatibility_issues", "truthy": True},
                {"path": "lifecycle.kvstore_upgrade_issues", "truthy": True},
                {"path": "lifecycle.forwarder_compatibility_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-EVIDENCE-INCOMPLETE",
        domain="Diagnostic evidence completeness",
        platform="both",
        severity="medium",
        evidence="diagnostics.evidence_incomplete is true because one or more applicable rules have no supplied or collected evidence path.",
        source_doc=SOURCE_DOCS["monitoring"],
        fix_kind="diagnose_only",
        preview_command="Review coverage-report.json for unassessed_rule_ids and expected_evidence_paths.",
        apply_command="Collect the missing read-only evidence or provide an evidence snapshot; no platform mutation is required.",
        handoff_skill="",
        rollback_or_validation="Rerun doctor until every applicable domain is assessed or explicitly marked unavailable/not applicable.",
        trigger={"any": [{"path": "diagnostics.evidence_incomplete", "equals": True}]},
    ),
    rule(
        rule_id="SAD-FEDERATED-SEARCH-DEGRADED",
        domain="Federated search",
        platform="both",
        severity="high",
        evidence="federated_search.issues, provider_errors, index_mapping_issues, knowledge_object_drift, concurrency_issues, or hybrid_search_detected is populated/true.",
        source_doc=SOURCE_DOCS["federated_search"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-federated-search-setup/scripts/setup.sh --help",
        apply_command="Render Federated Search provider/index/SHC or Hybrid Search migration handoffs; no provider is changed.",
        handoff_skill="splunk-federated-search-setup",
        rollback_or_validation="Probe provider connectivity and validate federated datasets/searches after remediation.",
        trigger={
            "any": [
                {"path": "federated_search.issues", "truthy": True},
                {"path": "federated_search.provider_errors", "truthy": True},
                {"path": "federated_search.index_mapping_issues", "truthy": True},
                {"path": "federated_search.knowledge_object_drift", "truthy": True},
                {"path": "federated_search.concurrency_issues", "truthy": True},
                {"path": "federated_search.hybrid_search_detected", "equals": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-FWD-STALE",
        domain="Agent Management and forwarders",
        platform="both",
        severity="medium",
        evidence="forwarders.stale_count or forwarders.missing_count is greater than zero.",
        source_doc=SOURCE_DOCS["agent_management"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-agent-management-setup/scripts/setup.sh --phase status --dry-run",
        apply_command="Render Agent Management / Universal Forwarder handoff.",
        handoff_skill="splunk-agent-management-setup,splunk-universal-forwarder-setup,splunk-deployment-server-setup",
        rollback_or_validation="Rerun doctor and verify stale/missing forwarder counts are zero or accepted.",
        trigger={
            "any": [
                {"path": "forwarders.stale_count", "gt": 0},
                {"path": "forwarders.missing_count", "gt": 0},
                {"path": "forwarders.stale", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-IDXCLUSTER-DEGRADED",
        domain="Indexer clustering",
        platform="enterprise",
        severity="critical",
        evidence="indexer_cluster.status is degraded/red or indexer_cluster.issues is populated.",
        source_doc=SOURCE_DOCS["splunkd_health"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-indexer-cluster-setup/scripts/setup.sh --phase status --dry-run",
        apply_command="Render indexer-cluster handoff; no bundle, restart, offline, or maintenance-mode operation is run here.",
        handoff_skill="splunk-indexer-cluster-setup",
        rollback_or_validation="Rerun doctor and cluster validate/status after the specialist workflow completes.",
        trigger={
            "any": [
                {"path": "indexer_cluster.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "indexer_cluster.issues", "truthy": True},
                {"path": "indexer_cluster.rf_met", "equals": False},
                {"path": "indexer_cluster.sf_met", "equals": False},
            ]
        },
    ),
    rule(
        rule_id="SAD-INDEX-ARCHIVE-LIFECYCLE-GAP",
        domain="Archive and data lifecycle",
        platform="enterprise",
        severity="high",
        evidence="archive.issues, archive.restore_issues, archive.thaw_issues, smartstore.archive_issues, or indexes.frozen_data_issues is populated.",
        source_doc=SOURCE_DOCS["smartstore"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh --phase render --dry-run",
        apply_command="Render index lifecycle/SmartStore handoffs; no bucket, archive, thaw, or retention mutation is performed.",
        handoff_skill="splunk-index-lifecycle-smartstore-setup",
        rollback_or_validation="Validate archive/thaw and SmartStore state with a controlled restore test, then rerun doctor.",
        trigger={
            "any": [
                {"path": "archive.issues", "truthy": True},
                {"path": "archive.restore_issues", "truthy": True},
                {"path": "archive.thaw_issues", "truthy": True},
                {"path": "smartstore.archive_issues", "truthy": True},
                {"path": "indexes.frozen_data_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-INDEX-DATATYPE-DRIFT",
        domain="Indexes and storage",
        platform="both",
        severity="high",
        evidence="indexes.datatype_drift, indexes.metrics_index_issues, indexes.bucket_issues, indexes.volume_issues, or indexes.watermark_issues is populated.",
        source_doc=SOURCE_DOCS["monitoring"],
        fix_kind="delegated_fix",
        preview_command="Review index datatype, metrics/event usage, bucket/volume, and watermark evidence.",
        apply_command="Render index lifecycle and data-readiness handoffs; no index is recreated or deleted.",
        handoff_skill="splunk-index-lifecycle-smartstore-setup,splunk-data-source-readiness-doctor",
        rollback_or_validation="Validate index definitions and sample event/metric flow after remediation.",
        trigger={
            "any": [
                {"path": "indexes.datatype_drift", "truthy": True},
                {"path": "indexes.metrics_index_issues", "truthy": True},
                {"path": "indexes.bucket_issues", "truthy": True},
                {"path": "indexes.volume_issues", "truthy": True},
                {"path": "indexes.watermark_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-INDEX-MISSING",
        domain="Indexes and storage",
        platform="enterprise",
        severity="medium",
        evidence="indexes.missing contains one or more required indexes.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh --help",
        apply_command="Render an Enterprise index lifecycle handoff; no index is created or modified.",
        handoff_skill="splunk-index-lifecycle-smartstore-setup",
        rollback_or_validation="Run doctor again and verify indexes.missing is empty.",
        trigger={"any": [{"path": "indexes.missing", "truthy": True}]},
    ),
    rule(
        rule_id="SAD-INDEX-RETENTION-RISK",
        domain="Indexes and storage",
        platform="both",
        severity="medium",
        evidence="indexes.retention_risks, indexes.storage_warnings, or smartstore.issues is populated.",
        source_doc=SOURCE_DOCS["smartstore"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh --phase render --dry-run",
        apply_command="Render SmartStore/index lifecycle handoff; no index deletion or retention change is applied here.",
        handoff_skill="splunk-index-lifecycle-smartstore-setup",
        rollback_or_validation="Rerun doctor and verify index/storage warnings are cleared or accepted.",
        trigger={
            "any": [
                {"path": "indexes.retention_risks", "truthy": True},
                {"path": "indexes.storage_warnings", "truthy": True},
                {"path": "smartstore.issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-INGEST-ACTIONS-GAP",
        domain="Ingest processing and routing",
        platform="both",
        severity="high",
        evidence="ingest_actions.issues, ingest_actions.ruleset_errors, ingest_actions.destination_errors, or ingest_actions.preview_failures is populated.",
        source_doc=SOURCE_DOCS["data_management"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-ingest-actions-setup/scripts/setup.sh --help",
        apply_command="Render Ingest Actions ruleset/destination handoffs; no ingest-time rule is applied.",
        handoff_skill="splunk-ingest-actions-setup,splunk-spl2-pipeline-kit",
        rollback_or_validation="Preview and validate the ruleset against representative events, then rerun doctor.",
        trigger={
            "any": [
                {"path": "ingest_actions.issues", "truthy": True},
                {"path": "ingest_actions.ruleset_errors", "truthy": True},
                {"path": "ingest_actions.destination_errors", "truthy": True},
                {"path": "ingest_actions.preview_failures", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-INGEST-CLOUD-DATA-MANAGER-GAP",
        domain="Ingest processing and routing",
        platform="cloud",
        severity="high",
        evidence="data_manager.issues, data_manager.source_errors, data_manager.infrastructure_drift, or data_manager.hec_index_issues is populated.",
        source_doc=SOURCE_DOCS["data_management"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-cloud-data-manager-setup/scripts/setup.sh --help",
        apply_command="Render Data Manager and readiness handoffs; no generated cloud infrastructure is applied.",
        handoff_skill="splunk-cloud-data-manager-setup,splunk-data-source-readiness-doctor",
        rollback_or_validation="Validate source infrastructure, HEC/index flow, and destination data after remediation.",
        trigger={
            "any": [
                {"path": "data_manager.issues", "truthy": True},
                {"path": "data_manager.source_errors", "truthy": True},
                {"path": "data_manager.infrastructure_drift", "truthy": True},
                {"path": "data_manager.hec_index_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-INGEST-COLLECTOR-GAP",
        domain="Ingest paths",
        platform="both",
        severity="medium",
        evidence="ingest.collector_gaps, ingest.s2s_issues, ingest.sc4s_issues, ingest.sc4snmp_issues, ingest.stream_issues, or ingest.edge_processor_issues is populated.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="delegated_fix",
        preview_command="Review collector handoff commands in handoffs/.",
        apply_command="Render collector-specific handoffs only.",
        handoff_skill="splunk-connect-for-syslog-setup,splunk-connect-for-snmp-setup,splunk-stream-setup,splunk-edge-processor-setup",
        rollback_or_validation="Rerun doctor and validate the referenced collector workflow.",
        trigger={
            "any": [
                {"path": "ingest.collector_gaps", "truthy": True},
                {"path": "ingest.s2s_issues", "truthy": True},
                {"path": "ingest.sc4s_issues", "truthy": True},
                {"path": "ingest.sc4snmp_issues", "truthy": True},
                {"path": "ingest.stream_issues", "truthy": True},
                {"path": "ingest.edge_processor_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-INGEST-DBCONNECT-GAP",
        domain="Ingest processing and routing",
        platform="both",
        severity="high",
        evidence="db_connect.issues, db_connect.jdbc_issues, db_connect.input_issues, db_connect.output_issues, or db_connect.checkpoint_issues is populated.",
        source_doc=SOURCE_DOCS["data_management"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-db-connect-setup/scripts/setup.sh --help",
        apply_command="Render DB Connect topology/JDBC/input/output handoffs; no database or Splunk credential is changed.",
        handoff_skill="splunk-db-connect-setup,splunk-data-source-readiness-doctor",
        rollback_or_validation="Validate JDBC connectivity, checkpoints, ingestion/export, and destination data.",
        trigger={
            "any": [
                {"path": "db_connect.issues", "truthy": True},
                {"path": "db_connect.jdbc_issues", "truthy": True},
                {"path": "db_connect.input_issues", "truthy": True},
                {"path": "db_connect.output_issues", "truthy": True},
                {"path": "db_connect.checkpoint_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-INGEST-EDGE-PROCESSOR-GAP",
        domain="Ingest processing and routing",
        platform="both",
        severity="critical",
        evidence="edge_processor.issues, edge_processor.instance_issues, edge_processor.pipeline_errors, edge_processor.destination_errors, or edge_processor.data_loss_risks is populated.",
        source_doc=SOURCE_DOCS["data_management"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-edge-processor-setup/scripts/setup.sh --help",
        apply_command="Render Edge Processor/SPL2 handoffs; no pipeline, destination, or instance is mutated.",
        handoff_skill="splunk-edge-processor-setup,splunk-spl2-pipeline-kit",
        rollback_or_validation="Validate instances, queues, destinations, pipeline metrics, drops, and representative data.",
        trigger={
            "any": [
                {"path": "edge_processor.issues", "truthy": True},
                {"path": "edge_processor.instance_issues", "truthy": True},
                {"path": "edge_processor.pipeline_errors", "truthy": True},
                {"path": "edge_processor.destination_errors", "truthy": True},
                {"path": "edge_processor.data_loss_risks", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-INGEST-HEC-DISABLED",
        domain="Ingest paths",
        platform="both",
        severity="high",
        evidence="hec.expected_but_disabled is true or hec.issues is populated.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-hec-service-setup/scripts/setup.sh --phase status --dry-run",
        apply_command="Render HEC service handoff; token creation or modification stays in splunk-hec-service-setup.",
        handoff_skill="splunk-hec-service-setup",
        rollback_or_validation="Run HEC status and doctor again after remediation.",
        trigger={
            "any": [
                {"path": "hec.expected_but_disabled", "equals": True},
                {"path": "hec.issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-INGEST-OTLP-GAP",
        domain="Ingest processing and routing",
        platform="both",
        severity="high",
        evidence="otlp.issues, otlp.receiver_errors, otlp.hec_handoff_issues, or otlp.data_loss_risks is populated.",
        source_doc=SOURCE_DOCS["data_management"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-connect-for-otlp-setup/scripts/setup.sh --help",
        apply_command="Render Splunk Connect for OTLP and HEC handoffs; no app, sender, or token is changed.",
        handoff_skill="splunk-connect-for-otlp-setup,splunk-hec-service-setup",
        rollback_or_validation="Validate receiver/app health and representative OTLP-to-index data flow.",
        trigger={
            "any": [
                {"path": "otlp.issues", "truthy": True},
                {"path": "otlp.receiver_errors", "truthy": True},
                {"path": "otlp.hec_handoff_issues", "truthy": True},
                {"path": "otlp.data_loss_risks", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-INGEST-PROCESSOR-GAP",
        domain="Ingest processing and routing",
        platform="cloud",
        severity="critical",
        evidence="ingest_processor.issues, pipeline_errors, destination_errors, queue_issues, dlq_issues, drop_risks, or unprocessed_routing_issues is populated.",
        source_doc=SOURCE_DOCS["data_management"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-ingest-processor-setup/scripts/setup.sh --help",
        apply_command="Render Ingest Processor/SPL2/readiness handoffs; no pipeline or destination is changed.",
        handoff_skill="splunk-ingest-processor-setup,splunk-spl2-pipeline-kit,splunk-data-source-readiness-doctor",
        rollback_or_validation="Verify inbound/outbound metrics, queues, DLQ, destinations, drops, and indexed data.",
        trigger={
            "any": [
                {"path": "ingest_processor.issues", "truthy": True},
                {"path": "ingest_processor.pipeline_errors", "truthy": True},
                {"path": "ingest_processor.destination_errors", "truthy": True},
                {"path": "ingest_processor.queue_issues", "truthy": True},
                {"path": "ingest_processor.dlq_issues", "truthy": True},
                {"path": "ingest_processor.drop_risks", "truthy": True},
                {"path": "ingest_processor.unprocessed_routing_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-INGEST-QUEUE-PRESSURE",
        domain="Ingest processing and routing",
        platform="both",
        severity="critical",
        evidence="ingest.queue_issues, ingest.blocked_queues, ingest.drop_risks, ingest.destination_errors, ingest.latency_issues, or ingest.data_quality_issues is populated.",
        source_doc=SOURCE_DOCS["monitoring"],
        fix_kind="diagnose_only",
        preview_command="Review queue, throughput, latency, destination, parsing, timestamp, line-breaking, and drop evidence.",
        apply_command="No queue reset, process restart, or ingest rule mutation is performed by doctor.",
        handoff_skill="",
        rollback_or_validation="Confirm received-versus-indexed flow and representative event quality after approved remediation.",
        trigger={
            "any": [
                {"path": "ingest.queue_issues", "truthy": True},
                {"path": "ingest.blocked_queues", "truthy": True},
                {"path": "ingest.drop_risks", "truthy": True},
                {"path": "ingest.destination_errors", "truthy": True},
                {"path": "ingest.latency_issues", "truthy": True},
                {"path": "ingest.data_quality_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-KO-ACCELERATION-RISK",
        domain="KV Store and knowledge objects",
        platform="both",
        severity="medium",
        evidence="knowledge_objects.acceleration_issues, knowledge_objects.lookup_issues, or knowledge_objects.collection_size_risks is populated.",
        source_doc=SOURCE_DOCS["kvstore"],
        fix_kind="delegated_fix",
        preview_command="Review knowledge-object, CIM/data-model, lookup, collection, and ownership evidence.",
        apply_command="Render knowledge-object, CIM, and readiness handoffs; no object or acceleration is changed.",
        handoff_skill="splunk-knowledge-objects-setup,splunk-lookup-file-editing-setup,splunk-cim-data-model-setup,splunk-data-source-readiness-doctor",
        rollback_or_validation="Rerun doctor and verify the knowledge-object pressure is reduced.",
        trigger={
            "any": [
                {"path": "knowledge_objects.acceleration_issues", "truthy": True},
                {"path": "knowledge_objects.lookup_issues", "truthy": True},
                {"path": "knowledge_objects.collection_size_risks", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-KVSTORE-BACKUP-RISK",
        domain="KV Store and knowledge objects",
        platform="enterprise",
        severity="high",
        evidence="kvstore.backup_stale, kvstore.backup_issues, kvstore.replication_issues, kvstore.storage_engine_issues, or kvstore.certificate_issues is populated/true.",
        source_doc=SOURCE_DOCS["kvstore"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-kvstore-admin-setup/scripts/setup.sh --help",
        apply_command="Render KV Store backup/migration/resync handoffs; no cleanup, restore, or resync is performed.",
        handoff_skill="splunk-kvstore-admin-setup,splunk-platform-pki-setup",
        rollback_or_validation="Validate KV Store status, backup age, replication, storage engine, and TLS after remediation.",
        trigger={
            "any": [
                {"path": "kvstore.backup_stale", "equals": True},
                {"path": "kvstore.backup_issues", "truthy": True},
                {"path": "kvstore.replication_issues", "truthy": True},
                {"path": "kvstore.storage_engine_issues", "truthy": True},
                {"path": "kvstore.certificate_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-KVSTORE-FAILED",
        domain="KV Store and knowledge objects",
        platform="enterprise",
        severity="high",
        evidence="kvstore.status is failed/degraded/red or kvstore.errors is populated.",
        source_doc=SOURCE_DOCS["kvstore"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-kvstore-admin-setup/scripts/setup.sh --help",
        apply_command="Render a KV Store specialist handoff; no destructive cleanup, resync, or repair is performed.",
        handoff_skill="splunk-kvstore-admin-setup",
        rollback_or_validation="Rerun doctor and verify kvstore.status is healthy.",
        trigger={
            "any": [
                {"path": "kvstore.status", "in": ["failed", "degraded", "red", "down"]},
                {"path": "kvstore.errors", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-LICENSE-CLOUD-ENTITLEMENT",
        domain="License/subscription",
        platform="cloud",
        severity="medium",
        evidence="subscription.over_quota or subscription.usage_risk is true.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="manual_support",
        preview_command="Review generated Cloud subscription/support packet.",
        apply_command="Render Cloud entitlement support packet only.",
        handoff_skill="",
        rollback_or_validation="Confirm Cloud Monitoring Console/license panels and rerun doctor.",
        trigger={
            "any": [
                {"path": "subscription.over_quota", "equals": True},
                {"path": "subscription.usage_risk", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-LICENSE-ENTERPRISE-VIOLATION",
        domain="License/subscription",
        platform="enterprise",
        severity="high",
        evidence="license.violation_count is greater than zero or license.messages is populated.",
        source_doc=SOURCE_DOCS["splunkd_health"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-license-manager-setup/scripts/setup.sh --phase status --dry-run",
        apply_command="Render license-manager handoff; license install/peer changes stay in the dedicated skill.",
        handoff_skill="splunk-license-manager-setup",
        rollback_or_validation="Run license validate/status and rerun doctor.",
        trigger={
            "any": [
                {"path": "license.violation_count", "gt": 0},
                {"path": "license.messages", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-MC-ALERTS-DISABLED",
        domain="Monitoring Console",
        platform="enterprise",
        severity="low",
        evidence="monitoring_console.platform_alerts_enabled is false.",
        source_doc=SOURCE_DOCS["splunkd_health"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-monitoring-console-setup/scripts/setup.sh --phase render --enable-platform-alerts true --dry-run",
        apply_command="Render Monitoring Console handoff; no saved-search change is made by doctor.",
        handoff_skill="splunk-monitoring-console-setup",
        rollback_or_validation="Run Monitoring Console status and rerun doctor.",
        trigger={"any": [{"path": "monitoring_console.platform_alerts_enabled", "equals": False}]},
    ),
    rule(
        rule_id="SAD-MC-NOT-CONFIGURED",
        domain="Monitoring Console",
        platform="enterprise",
        severity="medium",
        evidence="monitoring_console.configured is false.",
        source_doc=SOURCE_DOCS["splunkd_health"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-monitoring-console-setup/scripts/setup.sh --phase render --dry-run",
        apply_command="Render Monitoring Console setup handoff.",
        handoff_skill="splunk-monitoring-console-setup",
        rollback_or_validation="Run Monitoring Console status and rerun doctor.",
        trigger={"any": [{"path": "monitoring_console.configured", "equals": False}]},
    ),
    rule(
        rule_id="SAD-PREMIUM-HANDOFFS",
        domain="Product and solution handoffs",
        platform="both",
        severity="info",
        evidence="premium_products.detected or products.detected contains a supported product/app footprint.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="delegated_fix",
        preview_command="Review premium product handoffs in handoffs/.",
        apply_command="Render product-specific skill handoffs only.",
        handoff_skill="splunk-security-portfolio-setup,splunk-itsi-setup,splunk-soar-setup,splunk-observability-cloud-integration-setup,splunk-oncall-setup,splunk-appdynamics-setup,cisco-product-setup,widefield-security-setup,galileo-platform-setup",
        rollback_or_validation="Run the routed specialist skill validation and rerun doctor.",
        trigger={
            "any": [
                {"path": "premium_products.detected", "truthy": True},
                {"path": "products.detected", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-RESTART-PENDING",
        domain="Restart and maintenance orchestration",
        platform="both",
        severity="medium",
        evidence="runtime.restart_required, maintenance.restart_required, maintenance.reload_required, maintenance.sequence_issues, or maintenance.pending is populated/true.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-platform-restart-orchestrator/scripts/setup.sh --help",
        apply_command="Render a topology-aware restart/reload plan; the doctor never restarts a Splunk component.",
        handoff_skill="splunk-platform-restart-orchestrator",
        rollback_or_validation="Run post-restart status, cluster, scheduler, ingest, and app checks, then rerun doctor.",
        trigger={
            "any": [
                {"path": "runtime.restart_required", "equals": True},
                {"path": "maintenance.restart_required", "equals": True},
                {"path": "maintenance.reload_required", "equals": True},
                {"path": "maintenance.sequence_issues", "truthy": True},
                {"path": "maintenance.pending", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-SEARCH-API-GAP",
        domain="Search and scheduler",
        platform="both",
        severity="high",
        evidence="search_api.issues, search_api.denied, search_api.allowlist_issues, or search_api.service_account_issues is populated/true.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="diagnose_only",
        preview_command="Review Search API reachability, allowlist, service account, RBAC, and concurrency evidence.",
        apply_command="No allowlist, identity, role, or search change is performed by doctor.",
        handoff_skill="",
        rollback_or_validation="Run a bounded authenticated search and confirm API results after approved remediation.",
        trigger={
            "any": [
                {"path": "search_api.issues", "truthy": True},
                {"path": "search_api.denied", "equals": True},
                {"path": "search_api.allowlist_issues", "truthy": True},
                {"path": "search_api.service_account_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-SEARCH-DISPATCH-PRESSURE",
        domain="Search and scheduler",
        platform="both",
        severity="high",
        evidence="scheduler.dispatch_pressure, scheduler.concurrency_issues, scheduler.artifact_issues, or scheduler.quota_issues is populated/true.",
        source_doc=SOURCE_DOCS["monitoring"],
        fix_kind="delegated_fix",
        preview_command="Review dispatch storage, concurrency, quotas, scheduler capacity, and workload evidence.",
        apply_command="Render workload and sizing handoffs; no job, artifact, quota, or rule is changed.",
        handoff_skill="splunk-platform-sizing",
        rollback_or_validation="Verify dispatch usage, concurrency, scheduler capacity, and skipped searches.",
        trigger={
            "any": [
                {"path": "scheduler.dispatch_pressure", "equals": True},
                {"path": "scheduler.concurrency_issues", "truthy": True},
                {"path": "scheduler.artifact_issues", "truthy": True},
                {"path": "scheduler.quota_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-SEARCH-EXPENSIVE",
        domain="Search and scheduler",
        platform="both",
        severity="medium",
        evidence="scheduler.expensive_searches is populated.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="diagnose_only",
        preview_command="Review expensive-search evidence and saved-search owners.",
        apply_command="No search disable/enable or workload mutation in v1.",
        handoff_skill="",
        rollback_or_validation="Rerun doctor and verify expensive-search evidence is reduced or accepted.",
        trigger={"any": [{"path": "scheduler.expensive_searches", "truthy": True}]},
    ),
    rule(
        rule_id="SAD-SEARCH-SAVED-SEARCH-GAP",
        domain="Search and scheduler",
        platform="both",
        severity="medium",
        evidence="saved_searches.issues, saved_searches.owner_issues, saved_searches.alert_action_issues, saved_searches.acceleration_issues, or saved_searches.summary_index_issues is populated.",
        source_doc=SOURCE_DOCS["monitoring"],
        fix_kind="delegated_fix",
        preview_command="Review saved-search ownership, failures, alert actions, acceleration, and summary indexing.",
        apply_command="Render knowledge-object/CIM handoffs; no saved search or alert action is changed.",
        handoff_skill="splunk-knowledge-objects-setup,splunk-cim-data-model-setup",
        rollback_or_validation="Validate scheduled runs, ownership, actions, acceleration, and summary data.",
        trigger={
            "any": [
                {"path": "saved_searches.issues", "truthy": True},
                {"path": "saved_searches.owner_issues", "truthy": True},
                {"path": "saved_searches.alert_action_issues", "truthy": True},
                {"path": "saved_searches.acceleration_issues", "truthy": True},
                {"path": "saved_searches.summary_index_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-SEARCH-SKIPPED",
        domain="Search and scheduler",
        platform="both",
        severity="medium",
        evidence="scheduler.skipped_count is greater than zero or scheduler.skipped_searches is populated.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="diagnose_only",
        preview_command="Review skipped-search evidence and scheduler capacity.",
        apply_command="No saved-search enable/disable in v1.",
        handoff_skill="",
        rollback_or_validation="Rerun doctor and verify skipped-search counts are zero or accepted.",
        trigger={
            "any": [
                {"path": "scheduler.skipped_count", "gt": 0},
                {"path": "scheduler.skipped_searches", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-SECURE-GATEWAY-GAP",
        domain="Dashboards and user experience",
        platform="both",
        severity="medium",
        evidence="secure_gateway.issues, secure_gateway.spacebridge_issues, secure_gateway.token_auth_issues, secure_gateway.device_issues, or secure_gateway.mdm_issues is populated.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-secure-gateway-setup/scripts/setup.sh --help",
        apply_command="Render Secure Gateway/Spacebridge/mobile handoffs; no device or gateway state is changed.",
        handoff_skill="splunk-secure-gateway-setup",
        rollback_or_validation="Validate Spacebridge egress, token auth, gateway status, and device registration.",
        trigger={
            "any": [
                {"path": "secure_gateway.issues", "truthy": True},
                {"path": "secure_gateway.spacebridge_issues", "truthy": True},
                {"path": "secure_gateway.token_auth_issues", "truthy": True},
                {"path": "secure_gateway.device_issues", "truthy": True},
                {"path": "secure_gateway.mdm_issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-SECURITY-DEFAULT-CERTS",
        domain="TLS/PKI/security hardening",
        platform="enterprise",
        severity="high",
        evidence="security.default_certs is true.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-platform-pki-setup/scripts/setup.sh --phase render --dry-run",
        apply_command="Render PKI handoff; no certificate generation, distribution, rotation, or restart is performed here.",
        handoff_skill="splunk-platform-pki-setup",
        rollback_or_validation="Run PKI validation and rerun doctor.",
        trigger={"any": [{"path": "security.default_certs", "equals": True}]},
    ),
    rule(
        rule_id="SAD-SECURITY-PUBLIC-EXPOSURE",
        domain="TLS/PKI/security hardening",
        platform="enterprise",
        severity="critical",
        evidence="security.public_exposure is true.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-enterprise-public-exposure-hardening/scripts/setup.sh --phase preflight --dry-run",
        apply_command="Render public-exposure hardening handoff; live hardening requires the dedicated skill and explicit acceptance.",
        handoff_skill="splunk-enterprise-public-exposure-hardening",
        rollback_or_validation="Run exposure validation and rerun doctor.",
        trigger={"any": [{"path": "security.public_exposure", "equals": True}]},
    ),
    rule(
        rule_id="SAD-SECURITY-WEAK-TLS",
        domain="TLS/PKI/security hardening",
        platform="enterprise",
        severity="medium",
        evidence="security.weak_tls is true or security.tls_findings is populated.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-platform-pki-setup/scripts/setup.sh --phase render --dry-run",
        apply_command="Render PKI/security hardening handoff; no TLS setting is changed here.",
        handoff_skill="splunk-platform-pki-setup",
        rollback_or_validation="Rerun doctor and verify TLS findings are clear.",
        trigger={
            "any": [
                {"path": "security.weak_tls", "equals": True},
                {"path": "security.tls_findings", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-SHC-DEGRADED",
        domain="Distributed search and SHC",
        platform="enterprise",
        severity="high",
        evidence="shc.status is degraded/red or shc.issues is populated.",
        source_doc=SOURCE_DOCS["splunkd_health"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-search-head-cluster-setup/scripts/setup.sh --help",
        apply_command="Render an SHC specialist handoff; no captain, deployer, restart, member, or resync operation is performed.",
        handoff_skill="splunk-search-head-cluster-setup",
        rollback_or_validation="Verify SHC status through supported admin workflow and rerun doctor.",
        trigger={
            "any": [
                {"path": "shc.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "shc.issues", "truthy": True},
                {"path": "shc.replication_healthy", "equals": False},
            ]
        },
    ),
    rule(
        rule_id="SAD-WLM-CLOUD-CMC-ISSUE",
        domain="Workload management",
        platform="cloud",
        severity="medium",
        evidence="cmc.workload.status is degraded or cmc.workload.findings is populated.",
        source_doc=SOURCE_DOCS["cloud_cmc"],
        fix_kind="direct_fix",
        preview_command="Review CMC and Settings > Workload Management rules, admission rules, pool assignment, order, and required capabilities.",
        apply_command="Render a Cloud sc_admin workload checklist only; doctor does not modify rules or pool assignments.",
        handoff_skill="",
        rollback_or_validation="Recheck Cloud Monitoring Console workload panels.",
        trigger={
            "any": [
                {"path": "cmc.workload.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "cmc.workload.findings", "truthy": True},
                {"path": "workload_management.guardrails_missing", "equals": True},
                {"path": "workload_management.issues", "truthy": True},
            ]
        },
    ),
    rule(
        rule_id="SAD-WLM-GUARDRAILS-MISSING",
        domain="Workload management",
        platform="enterprise",
        severity="medium",
        evidence="workload_management.guardrails_missing is true or workload_management.issues is populated.",
        source_doc=SOURCE_DOCS["splunkd_health"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-workload-management-setup/scripts/setup.sh --phase render --dry-run",
        apply_command="Render workload-management handoff; no WLM rule or pool is changed here.",
        handoff_skill="splunk-workload-management-setup",
        rollback_or_validation="Run workload-management validation and rerun doctor.",
        trigger={
            "any": [
                {"path": "workload_management.guardrails_missing", "equals": True},
                {"path": "workload_management.issues", "truthy": True},
            ]
        },
    ),
]


SECRET_KEY_RE = re.compile(
    r"^(password|passwd|pass|pwd|credential|credentials|secret|apikey|apitoken|tokenvalue|"
    r"accesstoken|refreshtoken|authtoken|bearer|authorization|sessionkey|stacktoken|"
    r"hectoken|clientsecret|sslpassword|privatekeypassword|pass4symmkey)$",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(Bearer\s+[A-Za-z0-9._~+/-]+|splunkd_[A-Za-z0-9._-]+|SUPER_SECRET|"
    r"VERY_SECRET|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]+)",
    re.IGNORECASE,
)
URI_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/@\s]+)@")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|api[_-]?token|auth[_-]?token|"
    r"access[_-]?token|refresh[_-]?token|client[_-]?secret|sslpassword|"
    r"privatekeypassword|pass4symmkey)(\s*[:=]\s*)([^\s,;&]+)"
)
DIRECT_DANGEROUS_RE = re.compile(
    r"\b(restart|delete|remove|rm\s+-|cluster|maintenance|offline|rotate|cert|license\s+install)\b",
    re.IGNORECASE,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Splunk Admin Doctor + Fixes renderer.")
    parser.add_argument("--phase", choices=("doctor", "fix-plan", "apply", "validate", "status"), default="doctor")
    parser.add_argument("--platform", choices=("auto", "cloud", "enterprise"), default="auto")
    parser.add_argument("--target-search-head", default="")
    parser.add_argument("--splunk-uri", default="")
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--evidence-file", default="")
    parser.add_argument("--fixes", default="", help="Comma-separated rule IDs to packetize during --phase apply.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--require-complete-evidence", action="store_true")
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


def normalize_secret_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def redact_string(value: str) -> str:
    redacted = URI_USERINFO_RE.sub(r"\1[REDACTED]@", value)
    redacted = SECRET_ASSIGNMENT_RE.sub(r"\1\2[REDACTED]", redacted)
    redacted = SECRET_VALUE_RE.sub("[REDACTED]", redacted)
    return redacted


def sanitize_uri(value: str) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return redact_string(value)
    if not parts.scheme or not parts.netloc:
        return redact_string(value)
    hostname = parts.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    try:
        port = parts.port
    except ValueError:
        port = None
    if port:
        netloc = f"{netloc}:{port}"
    return redact_string(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))


def shell_join(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


MISSING = object()


def lookup_path(payload: dict[str, Any], dotted: str) -> tuple[bool, Any]:
    current: Any = payload
    for part in dotted.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, MISSING
    return True, current


def get_path(payload: dict[str, Any], dotted: str) -> Any:
    exists, value = lookup_path(payload, dotted)
    return value if exists else None


def normalize_status(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    return value


def compare_gt(actual: Any, threshold: Any) -> bool:
    try:
        return float(actual) > float(threshold)
    except (TypeError, ValueError):
        return False


def version_tuple(value: Any) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(value or "")))


def compare_version_gte(actual: Any, minimum: Any) -> bool:
    actual_parts = version_tuple(actual)
    minimum_parts = version_tuple(minimum)
    if not actual_parts or not minimum_parts:
        return False
    width = max(len(actual_parts), len(minimum_parts))
    return actual_parts + (0,) * (width - len(actual_parts)) >= minimum_parts + (0,) * (width - len(minimum_parts))


def normalize_bool(value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off", ""}:
            return False
    return value


def predicate_matches(predicate: dict[str, Any], evidence: dict[str, Any]) -> bool:
    actual = get_path(evidence, str(predicate["path"]))
    if "equals" in predicate:
        expected = predicate["equals"]
        if isinstance(expected, bool):
            return normalize_bool(actual) is expected
        return actual == expected
    if "truthy" in predicate:
        return bool(normalize_bool(actual)) is bool(predicate["truthy"])
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
    if "prefix" in predicate:
        return str(actual or "").startswith(str(predicate["prefix"]))
    if "version_gte" in predicate:
        return compare_version_gte(actual, predicate["version_gte"])
    return False


def trigger_matches(trigger: dict[str, Any], evidence: dict[str, Any]) -> bool:
    any_predicates = trigger.get("any")
    if any_predicates:
        return any(predicate_matches(predicate, evidence) for predicate in any_predicates)
    all_predicates = trigger.get("all")
    if all_predicates:
        return all(predicate_matches(predicate, evidence) for predicate in all_predicates)
    return False


def platform_applies(rule_platform: str, target_platform: str) -> bool:
    return rule_platform == "both" or rule_platform == target_platform


def manifest_domains() -> set[str]:
    return {entry["domain"] for entry in COVERAGE_MANIFEST}


def trigger_predicates(trigger: dict[str, Any]) -> list[dict[str, Any]]:
    predicates = trigger.get("any") or trigger.get("all") or []
    return [item for item in predicates if isinstance(item, dict)]


def rule_evidence_paths(item: dict[str, Any]) -> list[str]:
    return sorted({str(predicate.get("path", "")) for predicate in trigger_predicates(item.get("trigger", {})) if predicate.get("path")})


def evidence_value_assessed(value: Any) -> bool:
    if value is None or value is MISSING:
        return False
    if isinstance(value, str) and value.strip().lower() in {"unknown", "unavailable", "not_assessed", "not_collected"}:
        return False
    return True


def rule_is_assessed(item: dict[str, Any], evidence: dict[str, Any]) -> bool:
    if item.get("id") == "SAD-PREMIUM-HANDOFFS":
        for inventory_path in ("premium_products.detected", "products.detected", "apps.installed"):
            exists, value = lookup_path(evidence, inventory_path)
            if exists and evidence_value_assessed(value):
                return True
    predicates = trigger_predicates(item.get("trigger", {}))
    if not predicates:
        return False
    observed = []
    for predicate in predicates:
        exists, value = lookup_path(evidence, str(predicate.get("path", "")))
        observed.append(exists and evidence_value_assessed(value))
    if item.get("trigger", {}).get("all"):
        return all(observed)
    return any(observed)


def rule_environment_applicable(item: dict[str, Any], evidence: dict[str, Any]) -> bool:
    applicability = evidence.get("applicability", {})
    if not isinstance(applicability, dict):
        return True
    domain_overrides = applicability.get("domains", {})
    if isinstance(domain_overrides, dict) and domain_overrides.get(item["domain"]) is False:
        return False
    rule_overrides = applicability.get("rules", {})
    if isinstance(rule_overrides, dict) and rule_overrides.get(item["id"]) is False:
        return False
    return True


def validate_evidence_applicability(evidence: dict[str, Any]) -> None:
    applicability = evidence.get("applicability")
    if applicability is None:
        return
    if not isinstance(applicability, dict):
        die("Evidence field 'applicability' must be a JSON object when present.")
    valid_rules = {item["id"] for item in RULE_CATALOG}
    valid_domains = manifest_domains()
    for key, valid_values in (("rules", valid_rules), ("domains", valid_domains)):
        overrides = applicability.get(key, {})
        if not isinstance(overrides, dict):
            die(f"Evidence field 'applicability.{key}' must be a JSON object when present.")
        unknown = sorted(set(overrides) - valid_values)
        if unknown:
            die(f"Evidence applicability.{key} contains unknown names: {', '.join(unknown)}")
        invalid_values = sorted(name for name, value in overrides.items() if not isinstance(value, bool))
        if invalid_values:
            die(f"Evidence applicability.{key} values must be booleans: {', '.join(invalid_values)}")


def matched_observations(item: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for predicate in trigger_predicates(item.get("trigger", {})):
        path = str(predicate.get("path", ""))
        if path and predicate_matches(predicate, evidence):
            observations[path] = get_path(evidence, path)
    return observations


def normalize_product_label(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def product_route_matches(route: dict[str, Any], value: Any) -> bool:
    normalized_value = normalize_product_label(value)
    if not normalized_value:
        return False
    for alias in route.get("aliases", []):
        normalized_alias = normalize_product_label(alias)
        if normalized_alias and (normalized_value == normalized_alias or normalized_alias in normalized_value):
            return True
    return False


def detected_product_values(evidence: dict[str, Any]) -> tuple[list[str], list[str]]:
    explicit: list[str] = []
    for path in ("premium_products.detected", "products.detected"):
        value = get_path(evidence, path)
        if isinstance(value, str):
            explicit.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    item = item.get("name") or item.get("id") or ""
                if str(item).strip():
                    explicit.append(str(item))

    inferred: list[str] = []
    installed = get_path(evidence, "apps.installed")
    if isinstance(installed, list):
        for item in installed:
            name = item.get("name", "") if isinstance(item, dict) else item
            if any(product_route_matches(route, name) for route in PRODUCT_ROUTE_CATALOG):
                inferred.append(str(name))
    return sorted(set(explicit)), sorted(set(inferred))


def build_product_coverage(evidence: dict[str, Any], platform: str) -> dict[str, Any]:
    explicit, inferred = detected_product_values(evidence)
    detected = sorted(set(explicit + inferred))
    routes: list[dict[str, Any]] = []
    matched_values: set[str] = set()
    for route in PRODUCT_ROUTE_CATALOG:
        matches = [value for value in detected if product_route_matches(route, value)]
        matched_values.update(matches)
        routes.append(
            {
                "id": route["id"],
                "name": route["name"],
                "detected": bool(matches),
                "detected_values": matches,
                "handoff_skills": route["handoff_skills"],
                "source_doc": route["source_doc"],
            }
        )
    unresolved = sorted(set(explicit) - matched_values)
    return {
        "platform": platform,
        "supported_route_count": len(routes),
        "detected_route_count": sum(1 for route in routes if route["detected"]),
        "routes": routes,
        "unresolved_detected_values": unresolved,
    }


def repository_skill_names() -> tuple[set[str], set[str]]:
    directory_skills = {
        path.name
        for path in (REPO_ROOT / "skills").iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    }
    registry_path = REPO_ROOT / "skills" / "shared" / "app_registry.json"
    registry_skills: set[str] = set()
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry_skills = {
            str(item.get("skill", ""))
            for item in registry.get("skill_topologies", [])
            if isinstance(item, dict) and item.get("skill")
        }
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return directory_skills, registry_skills


def repository_skill_dispositions() -> dict[str, Any]:
    directory_skills, registry_skills = repository_skill_names()
    direct_handoffs = {
        skill.strip()
        for item in RULE_CATALOG
        for skill in str(item.get("handoff_skill", "")).split(",")
        if skill.strip()
    }
    dispositions: dict[str, Any] = {}
    for skill in sorted(directory_skills | registry_skills):
        routes: list[str] = []
        kind = ""
        if skill == SKILL_NAME:
            kind = "direct_admin_check"
            routes = [SKILL_NAME]
        elif skill in CANONICAL_SKILL_ALIASES:
            kind = "compatibility_alias"
            routes = [CANONICAL_SKILL_ALIASES[skill]]
        elif skill in direct_handoffs:
            kind = "specialist_admin_handoff"
            routes = [skill]
        else:
            for route in PRODUCT_ROUTE_CATALOG:
                names = set(route.get("covered_skill_names", []))
                prefixes = tuple(route.get("covered_skill_prefixes", []))
                suffixes = tuple(route.get("covered_skill_suffixes", []))
                if skill in names or (prefixes and skill.startswith(prefixes)) or (suffixes and skill.endswith(suffixes)):
                    routes.append(str(route["id"]))
            if routes:
                kind = "product_or_integration_handoff"
        dispositions[skill] = {"disposition": kind or "unmapped", "routes": sorted(set(routes))}
    return {
        "directory_skill_count": len(directory_skills),
        "registry_skill_count": len(registry_skills),
        "directory_only": sorted(directory_skills - registry_skills),
        "registry_only": sorted(registry_skills - directory_skills),
        "routed_skill_count": sum(1 for item in dispositions.values() if item["disposition"] != "unmapped"),
        "unmapped_skills": sorted(skill for skill, item in dispositions.items() if item["disposition"] == "unmapped"),
        "dispositions": dispositions,
    }


def validate_catalog() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    domains = manifest_domains()
    valid_predicate_operators = {"equals", "truthy", "gt", "in", "not_in", "prefix", "version_gte"}

    if [rule["id"] for rule in RULE_CATALOG] != sorted(rule["id"] for rule in RULE_CATALOG):
        errors.append("RULE_CATALOG must stay sorted by stable rule id.")

    for item in RULE_CATALOG:
        missing = sorted(REQUIRED_RULE_FIELDS - set(item))
        if missing:
            errors.append(f"{item.get('id', '<unknown>')}: missing fields: {', '.join(missing)}")
        rule_id = str(item.get("id", ""))
        if rule_id in seen_ids:
            errors.append(f"duplicate rule id: {rule_id}")
        seen_ids.add(rule_id)
        if item.get("domain") not in domains:
            errors.append(f"{rule_id}: unknown domain {item.get('domain')!r}")
        if item.get("platform") not in {"cloud", "enterprise", "both"}:
            errors.append(f"{rule_id}: invalid platform {item.get('platform')!r}")
        if item.get("severity") not in SEVERITY_RANK:
            errors.append(f"{rule_id}: invalid severity {item.get('severity')!r}")
        if item.get("fix_kind") not in FIX_KINDS - {"not_applicable"}:
            errors.append(f"{rule_id}: invalid fix_kind {item.get('fix_kind')!r}")
        if item.get("fix_kind") == "delegated_fix" and not str(item.get("handoff_skill", "")).strip():
            errors.append(f"{rule_id}: delegated_fix rules must declare handoff_skill")
        if not str(item.get("source_doc", "")).startswith("https://"):
            errors.append(f"{rule_id}: source_doc must be an absolute HTTPS official reference")
        for field in ("evidence", "preview_command", "apply_command", "rollback_or_validation"):
            if not str(item.get(field, "")).strip():
                errors.append(f"{rule_id}: {field} must not be empty")
        if item.get("fix_kind") == "direct_fix" and DIRECT_DANGEROUS_RE.search(str(item.get("apply_command", ""))):
            errors.append(f"{rule_id}: direct_fix apply_command contains a blocked disruptive action")
        if not item.get("trigger"):
            errors.append(f"{rule_id}: missing trigger")
        predicates = trigger_predicates(item.get("trigger", {}))
        if not predicates:
            errors.append(f"{rule_id}: trigger must contain non-empty any or all predicates")
        for predicate in predicates:
            path = str(predicate.get("path", "")).strip()
            if not path:
                errors.append(f"{rule_id}: trigger predicate is missing path")
            operators = valid_predicate_operators & set(predicate)
            if len(operators) != 1:
                errors.append(f"{rule_id}: predicate {path or '<unknown>'} must have exactly one supported operator")
        for handoff in [part.strip() for part in str(item.get("handoff_skill", "")).split(",") if part.strip()]:
            if not (REPO_ROOT / "skills" / handoff / "SKILL.md").is_file():
                errors.append(f"{rule_id}: handoff skill does not exist: {handoff}")
        preview = str(item.get("preview_command", ""))
        if preview.startswith("bash skills/"):
            try:
                preview_script = shlex.split(preview)[1]
            except (ValueError, IndexError):
                errors.append(f"{rule_id}: preview command cannot be parsed")
            else:
                if not (REPO_ROOT / preview_script).is_file():
                    errors.append(f"{rule_id}: preview script does not exist: {preview_script}")

    for manifest in COVERAGE_MANIFEST:
        domain = manifest["domain"]
        coverage_by_platform = manifest.get("coverage_by_platform", {})
        if set(coverage_by_platform) != {"cloud", "enterprise"}:
            errors.append(f"{domain}: coverage_by_platform must declare cloud and enterprise")
        for platform, coverage_class in coverage_by_platform.items():
            if coverage_class not in FIX_KINDS:
                errors.append(f"{domain}: invalid {platform} coverage class {coverage_class!r}")
        if not any(item["domain"] == domain for item in RULE_CATALOG):
            errors.append(f"{domain}: no catalog rule covers this domain")
        for platform in ("cloud", "enterprise"):
            applicable = platform in manifest["platforms"]
            declared = coverage_by_platform.get(platform)
            if not applicable and declared != "not_applicable":
                errors.append(f"{domain}: {platform} must be not_applicable when omitted from platforms")
            if applicable and declared == "not_applicable":
                errors.append(f"{domain}: {platform} is applicable but declared not_applicable")
        for platform in manifest["platforms"]:
            if platform not in {"cloud", "enterprise"}:
                errors.append(f"{domain}: invalid manifest platform {platform}")
            rules_for_platform = [
                item
                for item in RULE_CATALOG
                if item["domain"] == domain and platform_applies(item["platform"], platform)
            ]
            if not rules_for_platform:
                errors.append(f"{domain}: no rule applies to platform {platform}")
                continue
            actual = max((item["fix_kind"] for item in rules_for_platform), key=lambda kind: FIX_KIND_RANK[kind])
            declared = coverage_by_platform.get(platform)
            if actual != declared:
                errors.append(f"{domain}: {platform} declares {declared} but applicable rules provide {actual}")

    seen_product_ids: set[str] = set()
    directory_skills, _registry_skills = repository_skill_names()
    for route in PRODUCT_ROUTE_CATALOG:
        route_id = str(route.get("id", ""))
        if not route_id or route_id in seen_product_ids:
            errors.append(f"duplicate or empty product route id: {route_id!r}")
        seen_product_ids.add(route_id)
        if not route.get("aliases"):
            errors.append(f"{route_id}: product route has no aliases")
        if not route.get("handoff_skills"):
            errors.append(f"{route_id}: product route has no handoff skills")
        for handoff in route.get("handoff_skills", []):
            if not (REPO_ROOT / "skills" / str(handoff) / "SKILL.md").is_file():
                errors.append(f"{route_id}: product handoff skill does not exist: {handoff}")
        for covered_skill in route.get("covered_skill_names", []):
            if str(covered_skill) not in directory_skills:
                errors.append(f"{route_id}: covered skill does not exist: {covered_skill}")
        for prefix in route.get("covered_skill_prefixes", []):
            if not any(skill.startswith(str(prefix)) for skill in directory_skills):
                errors.append(f"{route_id}: covered skill prefix matches nothing: {prefix}")
        for suffix in route.get("covered_skill_suffixes", []):
            if not any(skill.endswith(str(suffix)) for skill in directory_skills):
                errors.append(f"{route_id}: covered skill suffix matches nothing: {suffix}")

    for alias, canonical in CANONICAL_SKILL_ALIASES.items():
        if not (REPO_ROOT / "skills" / alias / "SKILL.md").is_file():
            errors.append(f"compatibility alias skill does not exist: {alias}")
        if not (REPO_ROOT / "skills" / canonical / "SKILL.md").is_file():
            errors.append(f"compatibility alias target does not exist: {canonical}")

    repository_coverage = repository_skill_dispositions()
    if repository_coverage["directory_only"]:
        errors.append("skills missing from app_registry skill_topologies: " + ", ".join(repository_coverage["directory_only"]))
    if repository_coverage["registry_only"]:
        errors.append("app_registry skill_topologies missing skill directories: " + ", ".join(repository_coverage["registry_only"]))
    if repository_coverage["unmapped_skills"]:
        errors.append("repository skills without a doctor disposition: " + ", ".join(repository_coverage["unmapped_skills"]))

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "rule_count": len(RULE_CATALOG),
        "domain_count": len(COVERAGE_MANIFEST),
        "product_route_count": len(PRODUCT_ROUTE_CATALOG),
        "repository_skill_count": repository_coverage["directory_skill_count"],
        "routed_repository_skill_count": repository_coverage["routed_skill_count"],
        "unmapped_skills": repository_coverage["unmapped_skills"],
    }


def redact(value: Any, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            if SECRET_KEY_RE.fullmatch(normalize_secret_key(str(key))):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact(child, str(key))
        return redacted
    if isinstance(value, list):
        return [redact(item, parent_key) for item in value]
    if isinstance(value, str):
        redacted_value = redact_string(value)
        if redacted_value != value:
            return redacted_value
        if len(value) > 48 and re.fullmatch(r"[A-Za-z0-9+/=_:.-]+", value) and "://" not in value:
            return "[REDACTED]"
    return value


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"Evidence file does not exist: {path}")
    except json.JSONDecodeError as exc:
        die(f"Evidence file is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        die("Evidence file root must be a JSON object.")
    return payload


def augment_lifecycle_evidence(evidence: dict[str, Any], platform: str) -> None:
    version = str(get_path(evidence, "server.version") or "").strip()
    if not version:
        return
    contract_path = REPO_ROOT / "skills" / "shared" / "references" / "splunk_platform_versions.json"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    lifecycle = evidence.setdefault("lifecycle", {})
    if not isinstance(lifecycle, dict):
        return
    parts = version_tuple(version)
    if len(parts) < 2:
        return
    minor = f"{parts[0]}.{parts[1]}"
    lifecycle.setdefault("assessed_version", version)
    if platform == "enterprise":
        supported = [str(item) for item in contract.get("enterprise_platform_versions", [])]
        cloud_only = {str(item) for item in contract.get("enterprise_cloud_only_trains", [])}
        not_public = {
            str(item)
            for item in contract.get("enterprise_not_publicly_released_trains", [])
        }
        lifecycle.setdefault("supported_minor_trains", supported)
        if minor in supported:
            lifecycle.setdefault("version_unsupported", False)
        elif minor in cloud_only:
            lifecycle.setdefault("version_unsupported", True)
            upgrade_issues = lifecycle.setdefault("upgrade_path_issues", [])
            if isinstance(upgrade_issues, list):
                upgrade_issues.append(
                    f"Splunk platform {minor} is Cloud-only and is not a Splunk Enterprise release train."
                )
        elif minor in not_public:
            lifecycle.setdefault("version_unsupported", True)
            upgrade_issues = lifecycle.setdefault("upgrade_path_issues", [])
            if isinstance(upgrade_issues, list):
                upgrade_issues.append(
                    f"Splunk Enterprise {minor} is not in the current public "
                    "Enterprise release contract; keep the verified 10.4 baseline "
                    "until public Enterprise packages and documentation are available."
                )
        else:
            supported_parts = [version_tuple(item) for item in supported]
            if supported_parts and parts[:2] < min(supported_parts):
                lifecycle.setdefault("version_unsupported", True)
                lifecycle.setdefault("eos", True)
            else:
                lifecycle.setdefault("version_unrecognized", True)
        support_end = contract.get("enterprise_support_end_dates", {}).get(minor)
        if support_end:
            try:
                end = datetime.fromisoformat(str(support_end)).replace(tzinfo=timezone.utc)
                days = (end - datetime.now(timezone.utc)).days
                lifecycle.setdefault("support_end_date", support_end)
                lifecycle.setdefault("support_days_remaining", days)
                lifecycle.setdefault("near_eos", 0 <= days <= 90)
                if days < 0:
                    lifecycle.setdefault("version_unsupported", True)
                    lifecycle.setdefault("eos", True)
            except ValueError:
                pass
    else:
        cloud_trains = [str(item) for item in contract.get("cloud_doc_trains", [])]
        lifecycle.setdefault("documented_cloud_trains", cloud_trains)
        if any(version.startswith(train) for train in cloud_trains):
            lifecycle.setdefault("version_unsupported", False)


def run_local_command(argv: list[str], timeout: int = 20) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "error": str(exc), "returncode": None}
    return {
        "argv": argv,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def collect_local_enterprise_evidence(args: argparse.Namespace) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "collection": {
            "mode": "best_effort_local",
            "notes": [],
        }
    }
    splunk_home = Path(args.splunk_home).expanduser()
    splunk_bin = splunk_home / "bin" / "splunk"
    if not splunk_bin.exists():
        evidence["collection"]["notes"].append(f"Splunk binary not found at {splunk_bin}.")
        return evidence

    evidence["collection"]["notes"].append(f"Found Splunk binary at {splunk_bin}.")
    btool_result = run_local_command([str(splunk_bin), "btool", "check", "--debug"])
    if btool_result["returncode"] not in (0, None):
        evidence["btool"] = {"errors": [btool_result.get("stderr_tail") or btool_result.get("stdout_tail")]}
    else:
        evidence["btool"] = {"errors": []}

    health_log = splunk_home / "var" / "log" / "splunk" / "health.log"
    if health_log.exists():
        text = health_log.read_text(encoding="utf-8", errors="replace")
        evidence.setdefault("splunkd", {}).setdefault("health_log_tail", text[-8000:])
    return evidence


def merge_evidence(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in secondary.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_evidence(merged[key], value)
        else:
            merged[key] = value
    return merged


def detect_platform(requested: str, evidence: dict[str, Any]) -> str:
    if requested in {"cloud", "enterprise"}:
        return requested
    declared = str(evidence.get("platform", "")).lower()
    if declared in {"cloud", "enterprise"}:
        return declared
    if "acs" in evidence or "cmc" in evidence or "subscription" in evidence:
        return "cloud"
    return "enterprise"


def load_evidence(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    evidence: dict[str, Any] = {}
    if args.evidence_file:
        evidence = load_json_file(Path(args.evidence_file).expanduser())

    platform = detect_platform(args.platform, evidence)
    declared_platform = str(evidence.get("platform", "")).lower()
    if args.platform in {"cloud", "enterprise"} and declared_platform in {"cloud", "enterprise"} and declared_platform != args.platform:
        die(f"Requested platform {args.platform!r} conflicts with evidence platform {declared_platform!r}.")
    if not args.evidence_file and platform == "enterprise":
        evidence = merge_evidence(evidence, collect_local_enterprise_evidence(args))

    evidence.setdefault("platform", platform)
    inputs = evidence.setdefault("inputs", {})
    if not isinstance(inputs, dict):
        die("Evidence field 'inputs' must be a JSON object when present.")
    if args.target_search_head:
        inputs["target_search_head"] = redact_string(args.target_search_head)
    if args.splunk_uri:
        inputs["splunk_uri"] = sanitize_uri(args.splunk_uri)
    inputs["splunk_home"] = args.splunk_home
    validate_evidence_applicability(evidence)
    return evidence, platform


def evaluate_rules(
    evidence: dict[str, Any],
    platform: str,
    product_coverage: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    redacted_evidence = redact(evidence)
    for item in RULE_CATALOG:
        if not platform_applies(item["platform"], platform):
            continue
        if not rule_environment_applicable(item, redacted_evidence):
            continue
        if not trigger_matches(item["trigger"], redacted_evidence):
            continue
        finding = {key: item[key] for key in REQUIRED_RULE_FIELDS}
        finding["observed_at"] = now_iso()
        finding["platform"] = platform
        finding["observed"] = matched_observations(item, redacted_evidence)
        if item["id"] == "SAD-PREMIUM-HANDOFFS" and product_coverage is not None:
            active_routes = [route for route in product_coverage["routes"] if route["detected"]]
            handoffs = sorted({skill for route in active_routes for skill in route["handoff_skills"]})
            if product_coverage["unresolved_detected_values"]:
                handoffs.extend(["splunk-app-install", "splunk-supported-addons-setup"])
            if handoffs:
                finding["handoff_skill"] = ",".join(sorted(set(handoffs)))
            finding["product_routes"] = active_routes
            finding["unresolved_products"] = product_coverage["unresolved_detected_values"]
        finding["selected_fix_safe"] = item["fix_kind"] in {"direct_fix", "delegated_fix", "manual_support"}
        findings.append(finding)
    findings.sort(key=lambda item: (-SEVERITY_RANK[item["severity"]], item["id"]))
    return findings


def domain_coverage_class(domain: str, platform: str, domain_rules: list[dict[str, Any]]) -> str:
    manifest = next(entry for entry in COVERAGE_MANIFEST if entry["domain"] == domain)
    if platform not in manifest["platforms"]:
        return "not_applicable"
    declared = manifest["coverage_by_platform"].get(platform)
    if declared:
        return declared
    if not domain_rules:
        return "not_applicable"
    return max((rule["fix_kind"] for rule in domain_rules), key=lambda kind: FIX_KIND_RANK[kind])


def build_coverage(
    platform: str,
    findings: list[dict[str, Any]],
    evidence: dict[str, Any],
    product_coverage: dict[str, Any],
) -> dict[str, Any]:
    findings_by_domain: dict[str, list[str]] = {}
    for finding in findings:
        findings_by_domain.setdefault(finding["domain"], []).append(finding["id"])

    domains: dict[str, Any] = {}
    for manifest in COVERAGE_MANIFEST:
        domain = manifest["domain"]
        platform_rules = [
            item
            for item in RULE_CATALOG
            if item["domain"] == domain and platform_applies(item["platform"], platform)
        ]
        rules = [item for item in platform_rules if rule_environment_applicable(item, evidence)]
        explicitly_not_applicable = [item["id"] for item in platform_rules if item not in rules]
        coverage_class = domain_coverage_class(domain, platform, platform_rules)
        assessed_rule_ids = [item["id"] for item in rules if rule_is_assessed(item, evidence)]
        unassessed_rule_ids = [item["id"] for item in rules if item["id"] not in assessed_rule_ids]
        finding_ids = findings_by_domain.get(domain, [])
        if platform not in manifest["platforms"] or not rules:
            assessment = "not_applicable"
            evidence_status = "not_applicable"
        elif finding_ids:
            assessment = "finding"
            evidence_status = "complete" if not unassessed_rule_ids else ("partial" if assessed_rule_ids else "unknown")
        elif not unassessed_rule_ids:
            assessment = "healthy"
            evidence_status = "complete"
        elif assessed_rule_ids:
            assessment = "partial"
            evidence_status = "partial"
        else:
            assessment = "unknown"
            evidence_status = "unknown"
        domains[domain] = {
            "coverage": coverage_class,
            "remediation_coverage": coverage_class,
            "assessment": assessment,
            "evidence_status": evidence_status,
            "platform_applicable": platform in manifest["platforms"],
            "environment_applicable": bool(rules) and platform in manifest["platforms"],
            "platforms": manifest["platforms"],
            "rule_ids": [item["id"] for item in platform_rules],
            "applicable_rule_ids": [item["id"] for item in rules],
            "explicitly_not_applicable_rule_ids": explicitly_not_applicable,
            "finding_ids": finding_ids,
            "assessed_rule_ids": assessed_rule_ids,
            "unassessed_rule_ids": unassessed_rule_ids,
            "expected_evidence_paths": sorted({path for item in rules for path in rule_evidence_paths(item)}),
            "policy": manifest["policy"],
        }
    assessment_counts: dict[str, int] = {}
    evidence_status_counts: dict[str, int] = {}
    for item in domains.values():
        assessment_counts[item["assessment"]] = assessment_counts.get(item["assessment"], 0) + 1
        evidence_status_counts[item["evidence_status"]] = evidence_status_counts.get(item["evidence_status"], 0) + 1
    repository_coverage = repository_skill_dispositions()
    return {
        "platform": platform,
        "assessment_summary": assessment_counts,
        "evidence_status_summary": evidence_status_counts,
        "complete": all(item["evidence_status"] in {"complete", "not_applicable"} for item in domains.values()),
        "domains": domains,
        "product_routes": product_coverage,
        "repository_skills": repository_coverage,
    }


def build_fix_plan(findings: list[dict[str, Any]]) -> dict[str, Any]:
    fixes: list[dict[str, Any]] = []
    for finding in findings:
        selectable = finding["fix_kind"] in {"direct_fix", "delegated_fix", "manual_support"}
        fixes.append(
            {
                "id": finding["id"],
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
                "automatic restarts",
                "deletions",
                "certificate rotations",
                "cluster operations",
                "user or role deletion",
                "KV Store cleanup",
            ],
        },
        "fixes": fixes,
    }


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if executable else 0)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    path.chmod(mode)


def markdown_list(items: list[Any]) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- `{item}`" for item in items)


def render_doctor_markdown(report: dict[str, Any]) -> str:
    findings = report["findings"]
    coverage = report["coverage"]["domains"]
    lines = [
        "# Splunk Admin Doctor Report",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Platform: `{report['platform']}`",
        f"Findings: `{len(findings)}`",
        f"Evidence complete: `{report['coverage']['complete']}`",
        f"Detected product routes: `{report['product_coverage']['detected_route_count']}`",
        "",
        "## Findings",
        "",
    ]
    if not findings:
        lines.extend(["No findings triggered from the supplied evidence.", ""])
    for finding in findings:
        lines.extend(
            [
                f"### {finding['id']} - {finding['domain']}",
                "",
                f"- Severity: `{finding['severity']}`",
                f"- Fix kind: `{finding['fix_kind']}`",
                f"- Evidence: {finding['evidence']}",
                f"- Observed: `{json.dumps(finding.get('observed', {}), sort_keys=True)}`",
                f"- Source: {finding['source_doc']}",
                f"- Preview: `{finding['preview_command']}`",
                f"- Apply policy: {finding['apply_command']}",
                f"- Handoff skill: `{finding['handoff_skill'] or 'none'}`",
                f"- Validate/rollback: {finding['rollback_or_validation']}",
                "",
            ]
        )

    lines.extend(["## Coverage", ""])
    for domain, item in coverage.items():
        lines.extend(
            [
                f"### {domain}",
                "",
                f"- Coverage: `{item['coverage']}`",
                f"- Assessment: `{item['assessment']}`",
                f"- Evidence status: `{item['evidence_status']}`",
                f"- Applicable: `{item['platform_applicable']}`",
                f"- Environment applicable: `{item['environment_applicable']}`",
                f"- Rules: {', '.join(f'`{rule_id}`' for rule_id in item['rule_ids']) or '`none`'}",
                f"- Explicitly not applicable: {', '.join(f'`{rule_id}`' for rule_id in item['explicitly_not_applicable_rule_ids']) or '`none`'}",
                f"- Findings: {', '.join(f'`{rule_id}`' for rule_id in item['finding_ids']) or '`none`'}",
                f"- Unassessed rules: {', '.join(f'`{rule_id}`' for rule_id in item['unassessed_rule_ids']) or '`none`'}",
                f"- Policy: {item['policy']}",
                "",
            ]
        )

    lines.extend(["## Product Routing", ""])
    for route in report["product_coverage"]["routes"]:
        status = "detected" if route["detected"] else "not detected"
        lines.append(
            f"- `{route['name']}`: {status}; handoff(s): "
            + ", ".join(f"`{skill}`" for skill in route["handoff_skills"])
        )
    unresolved = report["product_coverage"]["unresolved_detected_values"]
    lines.extend(["", f"Unresolved detected values: {', '.join(f'`{item}`' for item in unresolved) or '`none`'}", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_fix_plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# Splunk Admin Doctor Fix Plan",
        "",
        f"Generated: `{plan['generated_at']}`",
        "",
        "The doctor does not execute hidden live Splunk mutations. Select fixes with",
        "`--phase apply --fixes FIX_ID[,FIX_ID]`; apply renders local fix packets,",
        "handoffs, and support notes for the selected IDs.",
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


def render_status(output_dir: Path) -> dict[str, Any]:
    report_path = output_dir / "doctor-report.json"
    if not report_path.exists():
        return {
            "ok": False,
            "status": "missing",
            "message": f"No doctor report found at {report_path}.",
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


def write_base_outputs(
    output_dir: Path,
    report: dict[str, Any],
    fix_plan: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for packet_dir_name in ("handoffs", "support-tickets"):
        packet_dir = output_dir / packet_dir_name
        if packet_dir.is_dir():
            for stale_packet in packet_dir.glob("SAD-*.md"):
                stale_packet.unlink()
    stale_applied = output_dir / "applied-fixes.json"
    if stale_applied.is_file():
        stale_applied.unlink()
    write_file(output_dir / "doctor-report.json", json_dumps(report))
    write_file(output_dir / "doctor-report.md", render_doctor_markdown(report))
    write_file(output_dir / "fix-plan.json", json_dumps(fix_plan))
    write_file(output_dir / "fix-plan.md", render_fix_plan_markdown(fix_plan))
    write_file(output_dir / "coverage-report.json", json_dumps(report["coverage"]))
    write_file(output_dir / "evidence" / "input-evidence.redacted.json", json_dumps(redact(evidence)))
    write_file(
        output_dir / "evidence" / "collection-notes.md",
        "# Evidence Collection Notes\n\n"
        "Live REST and ACS mutations are not performed by this doctor. "
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
        f"Domain: `{finding['domain']}`",
        f"Severity: `{finding['severity']}`",
        f"Fix kind: `{finding['fix_kind']}`",
        "",
        "## Evidence",
        "",
        finding["evidence"],
        "",
        "## Observed (redacted)",
        "",
        f"```json\n{json.dumps(finding.get('observed', {}), indent=2, sort_keys=True)}\n```",
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
    write_file(output_dir / "handoffs" / f"{safe_rel_name(fix_id)}.md", "\n".join(packet))


def render_support_packet(output_dir: Path, finding: dict[str, Any]) -> None:
    fix_id = finding["id"]
    packet = [
        f"# {fix_id} Support Packet",
        "",
        f"Domain: `{finding['domain']}`",
        f"Severity: `{finding['severity']}`",
        "",
        "## Evidence To Include",
        "",
        finding["evidence"],
        "",
        "## Observed (redacted)",
        "",
        f"```json\n{json.dumps(finding.get('observed', {}), indent=2, sort_keys=True)}\n```",
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
    write_file(output_dir / "support-tickets" / f"{safe_rel_name(fix_id)}.md", "\n".join(packet))


def render_direct_packet(output_dir: Path, finding: dict[str, Any]) -> None:
    fix_id = finding["id"]
    packet = [
        f"# {fix_id} Local Checklist",
        "",
        f"Domain: `{finding['domain']}`",
        f"Severity: `{finding['severity']}`",
        "",
        "## Check",
        "",
        finding["preview_command"],
        "",
        "## Observed (redacted)",
        "",
        f"```json\n{json.dumps(finding.get('observed', {}), indent=2, sort_keys=True)}\n```",
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
    write_file(output_dir / "handoffs" / f"{safe_rel_name(fix_id)}.md", "\n".join(packet))


def apply_selected_fixes(output_dir: Path, findings: list[dict[str, Any]], fixes: list[str]) -> dict[str, Any]:
    selected = validate_selected_fixes(findings, fixes)

    applied: list[dict[str, Any]] = []
    for finding in selected:
        fix_id = finding["id"]
        if finding["fix_kind"] == "delegated_fix":
            render_handoff_packet(output_dir, finding)
        elif finding["fix_kind"] == "manual_support":
            render_support_packet(output_dir, finding)
        elif finding["fix_kind"] == "direct_fix":
            render_direct_packet(output_dir, finding)
        applied.append(
            {
                "id": fix_id,
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


def validate_selected_fixes(findings: list[dict[str, Any]], fixes: list[str]) -> list[dict[str, Any]]:
    if not fixes:
        die("--phase apply requires --fixes FIX_ID[,FIX_ID].")
    by_id = {finding["id"]: finding for finding in findings}
    unknown = sorted(set(fixes) - set(by_id))
    if unknown:
        die(f"Requested fix IDs are not active findings: {', '.join(unknown)}")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fix_id in fixes:
        if fix_id in seen:
            continue
        seen.add(fix_id)
        finding = by_id[fix_id]
        if finding["fix_kind"] == "diagnose_only":
            die(f"{fix_id} is diagnose_only and cannot be selected for apply.")
        selected.append(finding)
    return selected


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    catalog_validation = validate_catalog()
    if not catalog_validation["ok"]:
        die("Catalog validation failed: " + "; ".join(catalog_validation["errors"]))

    evidence, platform = load_evidence(args)
    augment_lifecycle_evidence(evidence, platform)
    diagnostics = evidence.setdefault("diagnostics", {})
    if not isinstance(diagnostics, dict):
        die("Evidence field 'diagnostics' must be a JSON object when present.")
    rules_for_completeness = [
        item
        for item in RULE_CATALOG
        if item["id"] != "SAD-EVIDENCE-INCOMPLETE"
        and platform_applies(item["platform"], platform)
        and rule_environment_applicable(item, evidence)
    ]
    diagnostics["unassessed_rule_ids"] = [
        item["id"] for item in rules_for_completeness if not rule_is_assessed(item, evidence)
    ]
    diagnostics["evidence_incomplete"] = bool(diagnostics["unassessed_rule_ids"])
    product_coverage = build_product_coverage(redact(evidence), platform)
    inferred_products = sorted(
        {
            value
            for route in product_coverage["routes"]
            if route["detected"]
            for value in route["detected_values"]
        }
    )
    if inferred_products:
        products = evidence.setdefault("products", {})
        if isinstance(products, dict):
            products.setdefault("detected", inferred_products)
    findings = evaluate_rules(evidence, platform, product_coverage)
    coverage = build_coverage(platform, findings, evidence, product_coverage)
    report = {
        "skill": SKILL_NAME,
        "generated_at": now_iso(),
        "platform": platform,
        "target_search_head": redact_string(args.target_search_head),
        "splunk_uri": sanitize_uri(args.splunk_uri),
        "findings": findings,
        "coverage": coverage,
        "product_coverage": product_coverage,
        "catalog": {
            "rule_count": len(RULE_CATALOG),
            "domain_count": len(COVERAGE_MANIFEST),
            "product_route_count": len(PRODUCT_ROUTE_CATALOG),
            "repository_skill_count": coverage["repository_skills"]["directory_skill_count"],
            "routed_repository_skill_count": coverage["repository_skills"]["routed_skill_count"],
            "required_rule_fields": sorted(REQUIRED_RULE_FIELDS),
        },
    }
    fix_plan = build_fix_plan(findings)
    return report, fix_plan, evidence


def text_summary(report: dict[str, Any]) -> str:
    lines = [
        f"Splunk Admin Doctor generated {len(report['findings'])} finding(s) for {report['platform']}.",
        f"Evidence complete: {report['coverage']['complete']} ({report['coverage']['evidence_status_summary']}).",
        "Reports: doctor-report.md, doctor-report.json, fix-plan.md, fix-plan.json, coverage-report.json",
    ]
    if report["findings"]:
        top = report["findings"][0]
        lines.append(f"Top finding: {top['id']} ({top['severity']})")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()

    if args.phase == "validate":
        validation = validate_catalog()
        if args.json:
            print(json_dumps(validation), end="")
        elif validation["ok"]:
            print(f"Splunk Admin Doctor catalog OK: {validation['rule_count']} rules, {validation['domain_count']} domains.")
        else:
            print("Splunk Admin Doctor catalog errors:", file=sys.stderr)
            for error in validation["errors"]:
                print(f"  - {error}", file=sys.stderr)
        return 0 if validation["ok"] else 1

    if args.phase == "status":
        status = render_status(output_dir)
        if args.json:
            print(json_dumps(status), end="")
        else:
            print(status["message"] if not status["ok"] else f"Report available: {status['report_path']} ({status['finding_count']} findings)")
        return 0 if status["ok"] else 1

    report, fix_plan, evidence = build_report(args)

    if args.dry_run:
        payload: Any = fix_plan if args.phase == "fix-plan" else report
        if args.phase == "apply":
            selected = validate_selected_fixes(report["findings"], selected_fix_ids(args.fixes))
            payload = {
                "dry_run": True,
                "selected_fixes": [item["id"] for item in selected],
                "would_render_packets": True,
                "live_mutation_performed": False,
            }
        if args.json:
            print(json_dumps(payload), end="")
        else:
            print(text_summary(report), end="")
        if args.require_complete_evidence and not report["coverage"]["complete"]:
            return 3
        if args.strict and any(SEVERITY_RANK[item["severity"]] >= SEVERITY_RANK["high"] for item in report["findings"]):
            return 2
        return 0

    write_base_outputs(output_dir, report, fix_plan, evidence)

    result: Any = report
    if args.phase == "fix-plan":
        result = fix_plan
    elif args.phase == "apply":
        result = apply_selected_fixes(output_dir, report["findings"], selected_fix_ids(args.fixes))

    if args.json:
        print(json_dumps(result), end="")
    else:
        print(text_summary(report), end="")
        if args.phase == "apply":
            print(f"Selected fix packets written under {output_dir}.")

    if args.require_complete_evidence and not report["coverage"]["complete"]:
        return 3
    if args.strict and any(SEVERITY_RANK[item["severity"]] >= SEVERITY_RANK["high"] for item in report["findings"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

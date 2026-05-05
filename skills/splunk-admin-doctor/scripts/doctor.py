#!/usr/bin/env python3
"""Render Splunk Admin Doctor reports and selected fix packets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    "cloud_rest": "https://help.splunk.com/en?resourceId=Splunk_RESTTUT_RESTandCloud&version=splunk-9_0",
    "cloud_cmc": "https://help.splunk.com/?resourceId=SplunkCloud_Admin_MonitoringIntro",
    "splunkd_health": "https://help.splunk.com/en/splunk-enterprise/administer/monitor/9.3/proactive-splunk-component-monitoring-with-the-splunkd-health-report/about-proactive-splunk-component-monitoring",
    "btool": "https://help.splunk.com/en/splunk-enterprise/administer/troubleshoot/10.2/first-steps/use-btool-to-troubleshoot-configurations",
    "kvstore": "https://help.splunk.com/en?resourceId=Splunk_Admin_TroubleshootKVstore",
    "diag": "https://help.splunk.com/en/splunk-enterprise/administer/troubleshoot/9.1/contact-splunk-support/generate-a-diagnostic-file",
    "backup": "https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.2/administer-splunk-enterprise-with-configuration-files/back-up-configuration-information",
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
        "policy": "Diagnose ACS status and route allowlists, HEC, indexes, apps, users/roles, restarts, and support-only actions.",
    },
    {
        "domain": "Cloud Monitoring Console",
        "platforms": ["cloud"],
        "coverage_by_platform": {"cloud": "manual_support", "enterprise": "not_applicable"},
        "policy": "Render exact CMC panel/runbook evidence. The doctor never modifies CMC.",
    },
    {
        "domain": "Enterprise health",
        "platforms": ["enterprise"],
        "coverage_by_platform": {"cloud": "not_applicable", "enterprise": "delegated_fix"},
        "policy": "Inspect splunkd health, server info/sysinfo hints, health.log, and btool errors.",
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
        "domain": "Ingest paths",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Route HEC, S2S, UF/HF, SC4S, SC4SNMP, Stream, and Edge Processor gaps.",
    },
    {
        "domain": "Forwarder and deployment server",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Detect stale or missing clients and route server-class/app mapping work.",
    },
    {
        "domain": "Distributed search and SHC",
        "platforms": ["enterprise"],
        "coverage_by_platform": {"cloud": "not_applicable", "enterprise": "delegated_fix"},
        "policy": "Diagnose peers, SHC captain/status, replication, and deployer hints; no cluster operation is run here.",
    },
    {
        "domain": "Indexer clustering",
        "platforms": ["enterprise"],
        "coverage_by_platform": {"cloud": "not_applicable", "enterprise": "delegated_fix"},
        "policy": "Diagnose manager, peers, bundle, RF/SF, searchability, and maintenance-mode signals.",
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
        "coverage_by_platform": {"cloud": "diagnose_only", "enterprise": "diagnose_only"},
        "policy": "Diagnose expensive jobs, skipped searches, saved-search health, and Search API readiness.",
    },
    {
        "domain": "Workload management",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "manual_support", "enterprise": "delegated_fix"},
        "policy": "Enterprise guardrail assets delegate to workload-management setup; Cloud WLM signals become CMC/support evidence.",
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
        "policy": "Diagnose RBAC, inherited capabilities, token auth, and ACS role signals. No users or roles are deleted.",
    },
    {
        "domain": "TLS/PKI/security hardening",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "manual_support", "enterprise": "delegated_fix"},
        "policy": "Detect default certs, weak TLS hints, public exposure posture, and token/auth risks.",
    },
    {
        "domain": "KV Store and knowledge objects",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "diagnose_only", "enterprise": "diagnose_only"},
        "policy": "Diagnose KV status, collection risk, data model acceleration, lookup health, and knowledge-object pressure.",
    },
    {
        "domain": "Backup, DR, support evidence",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "manual_support", "enterprise": "manual_support"},
        "policy": "Render backup, DR, and diag/support evidence. The doctor never uploads bundles.",
    },
    {
        "domain": "Premium product handoffs",
        "platforms": ["cloud", "enterprise"],
        "coverage_by_platform": {"cloud": "delegated_fix", "enterprise": "delegated_fix"},
        "policy": "Detect ES, ITSI, SOAR, Observability, On-Call, and Cisco product footprints and route to existing skills.",
    },
]


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
        rule_id="SAD-APPS-RESTART-REQUIRED",
        domain="Apps and add-ons",
        platform="both",
        severity="medium",
        evidence="apps.restart_required contains one or more app names.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-app-install/scripts/setup.sh --help",
        apply_command="Render an app-install handoff; restarts remain explicit ACS/support or operator actions.",
        handoff_skill="splunk-app-install",
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
        handoff_skill="splunk-app-install",
        rollback_or_validation="Run doctor again and verify apps.update_gaps is empty or acknowledged.",
        trigger={"any": [{"path": "apps.update_gaps", "truthy": True}]},
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
        rule_id="SAD-AUTH-TOKEN-RISK",
        domain="Auth, users, roles, tokens",
        platform="both",
        severity="medium",
        evidence="auth.weak_tokens is populated or auth.token_auth_enabled is true without compensating controls.",
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
        rule_id="SAD-CLOUD-ACS-ALLOWLIST-GAP",
        domain="Cloud ACS control plane",
        platform="cloud",
        severity="high",
        evidence="acs.allowlist.search_api_allowed is false or acs.allowlist.gaps is populated.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh --phase audit --dry-run",
        apply_command="Render an ACS allowlist handoff; actual allowlist mutation stays in the ACS skill.",
        handoff_skill="splunk-cloud-acs-allowlist-setup",
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
        rule_id="SAD-CONNECTIVITY-REST-DENIED",
        domain="Connectivity and credentials",
        platform="both",
        severity="high",
        evidence="rest.denied is true, rest.reachable is false, or rest.status_code is 401/403.",
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
        rule_id="SAD-FWD-STALE",
        domain="Forwarder and deployment server",
        platform="both",
        severity="medium",
        evidence="forwarders.stale_count or forwarders.missing_count is greater than zero.",
        source_doc=SOURCE_DOCS["splunkd_health"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-agent-management-setup/scripts/setup.sh --phase status --dry-run",
        apply_command="Render Agent Management / Universal Forwarder handoff.",
        handoff_skill="splunk-agent-management-setup,splunk-universal-forwarder-setup",
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
        rule_id="SAD-INDEX-MISSING",
        domain="Indexes and storage",
        platform="both",
        severity="medium",
        evidence="indexes.missing contains one or more required indexes.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-hec-service-setup/scripts/setup.sh --help",
        apply_command="Render index/HEC handoff. Cloud index creation stays in ACS-capable skills.",
        handoff_skill="splunk-hec-service-setup,splunk-index-lifecycle-smartstore-setup",
        rollback_or_validation="Run doctor again and verify indexes.missing is empty.",
        trigger={"any": [{"path": "indexes.missing", "truthy": True}]},
    ),
    rule(
        rule_id="SAD-INDEX-RETENTION-RISK",
        domain="Indexes and storage",
        platform="both",
        severity="medium",
        evidence="indexes.retention_risks, indexes.storage_warnings, or smartstore.issues is populated.",
        source_doc=SOURCE_DOCS["btool"],
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
        rule_id="SAD-INGEST-HEC-DISABLED",
        domain="Ingest paths",
        platform="both",
        severity="high",
        evidence="hec.enabled is false or hec.issues is populated.",
        source_doc=SOURCE_DOCS["acs"],
        fix_kind="delegated_fix",
        preview_command="bash skills/splunk-hec-service-setup/scripts/setup.sh --phase status --dry-run",
        apply_command="Render HEC service handoff; token creation or modification stays in splunk-hec-service-setup.",
        handoff_skill="splunk-hec-service-setup",
        rollback_or_validation="Run HEC status and doctor again after remediation.",
        trigger={
            "any": [
                {"path": "hec.enabled", "equals": False},
                {"path": "hec.issues", "truthy": True},
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
        fix_kind="diagnose_only",
        preview_command="Review KV/knowledge-object evidence and plan cleanup through the owning app workflow.",
        apply_command="No lookup, collection, or data model cleanup in v1.",
        handoff_skill="",
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
        rule_id="SAD-KVSTORE-FAILED",
        domain="KV Store and knowledge objects",
        platform="both",
        severity="high",
        evidence="kvstore.status is failed/degraded/red or kvstore.errors is populated.",
        source_doc=SOURCE_DOCS["kvstore"],
        fix_kind="diagnose_only",
        preview_command="Review KV Store status evidence and Splunk KV Store troubleshooting doc.",
        apply_command="No destructive KV cleanup, resync, or repair is performed in v1.",
        handoff_skill="",
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
        domain="Premium product handoffs",
        platform="both",
        severity="info",
        evidence="premium_products.detected contains ES, ITSI, SOAR, Observability, On-Call, or Cisco apps.",
        source_doc=SOURCE_DOCS["cloud_rest"],
        fix_kind="delegated_fix",
        preview_command="Review premium product handoffs in handoffs/.",
        apply_command="Render product-specific skill handoffs only.",
        handoff_skill="splunk-security-portfolio-setup,splunk-itsi-setup,splunk-soar-setup,splunk-observability-cloud-integration-setup,splunk-oncall-setup,cisco-product-setup",
        rollback_or_validation="Run the routed specialist skill validation and rerun doctor.",
        trigger={"any": [{"path": "premium_products.detected", "truthy": True}]},
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
        platform="both",
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
        fix_kind="diagnose_only",
        preview_command="Review SHC captain/status and deployer evidence.",
        apply_command="No SHC captain, deployer, rolling-restart, or resync operation in v1.",
        handoff_skill="",
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
        fix_kind="manual_support",
        preview_command="Review Cloud CMC workload panel evidence.",
        apply_command="Render support packet only; Cloud workload controls remain Splunk-managed.",
        handoff_skill="",
        rollback_or_validation="Recheck Cloud Monitoring Console workload panels.",
        trigger={
            "any": [
                {"path": "cmc.workload.status", "in": ["red", "yellow", "degraded", "failed"]},
                {"path": "cmc.workload.findings", "truthy": True},
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
    r"(^|_)(password|passwd|pass|secret|api[_-]?key|api[_-]?token|token[_-]?value|"
    r"access[_-]?token|refresh[_-]?token|"
    r"bearer|authorization|session[_-]?key|stack[_-]?token|hec[_-]?token|client[_-]?secret)($|_)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(Bearer\s+[A-Za-z0-9._~+/-]+|splunkd_[A-Za-z0-9._-]+|SUPER_SECRET|"
    r"VERY_SECRET|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]+)",
    re.IGNORECASE,
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


def platform_applies(rule_platform: str, target_platform: str) -> bool:
    return rule_platform == "both" or rule_platform == target_platform


def manifest_domains() -> set[str]:
    return {entry["domain"] for entry in COVERAGE_MANIFEST}


def validate_catalog() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    domains = manifest_domains()

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
        if item.get("fix_kind") == "direct_fix" and DIRECT_DANGEROUS_RE.search(str(item.get("apply_command", ""))):
            errors.append(f"{rule_id}: direct_fix apply_command contains a blocked disruptive action")
        if not item.get("trigger"):
            errors.append(f"{rule_id}: missing trigger")

    for manifest in COVERAGE_MANIFEST:
        domain = manifest["domain"]
        if not any(item["domain"] == domain for item in RULE_CATALOG):
            errors.append(f"{domain}: no catalog rule covers this domain")
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
    if not args.evidence_file and platform == "enterprise":
        evidence = merge_evidence(evidence, collect_local_enterprise_evidence(args))

    evidence.setdefault("platform", platform)
    evidence.setdefault("inputs", {})
    if args.target_search_head:
        evidence["inputs"]["target_search_head"] = args.target_search_head
    if args.splunk_uri:
        evidence["inputs"]["splunk_uri"] = args.splunk_uri
    evidence["inputs"]["splunk_home"] = args.splunk_home
    return evidence, platform


def evaluate_rules(evidence: dict[str, Any], platform: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    redacted_evidence = redact(evidence)
    for item in RULE_CATALOG:
        if not platform_applies(item["platform"], platform):
            continue
        if not trigger_matches(item["trigger"], redacted_evidence):
            continue
        finding = {key: item[key] for key in REQUIRED_RULE_FIELDS}
        finding["observed_at"] = now_iso()
        finding["platform"] = platform
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


def build_coverage(platform: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    findings_by_domain: dict[str, list[str]] = {}
    for finding in findings:
        findings_by_domain.setdefault(finding["domain"], []).append(finding["id"])

    domains: dict[str, Any] = {}
    for manifest in COVERAGE_MANIFEST:
        domain = manifest["domain"]
        rules = [
            item
            for item in RULE_CATALOG
            if item["domain"] == domain and platform_applies(item["platform"], platform)
        ]
        coverage_class = domain_coverage_class(domain, platform, rules)
        domains[domain] = {
            "coverage": coverage_class,
            "platform_applicable": platform in manifest["platforms"],
            "platforms": manifest["platforms"],
            "rule_ids": [item["id"] for item in rules],
            "finding_ids": findings_by_domain.get(domain, []),
            "policy": manifest["policy"],
        }
    return {"platform": platform, "domains": domains}


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
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


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
                f"- Applicable: `{item['platform_applicable']}`",
                f"- Rules: {', '.join(f'`{rule_id}`' for rule_id in item['rule_ids']) or '`none`'}",
                f"- Findings: {', '.join(f'`{rule_id}`' for rule_id in item['finding_ids']) or '`none`'}",
                f"- Policy: {item['policy']}",
                "",
            ]
        )
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
    if not fixes:
        die("--phase apply requires --fixes FIX_ID[,FIX_ID].")
    by_id = {finding["id"]: finding for finding in findings}
    unknown = sorted(set(fixes) - set(by_id))
    if unknown:
        die(f"Requested fix IDs are not active findings: {', '.join(unknown)}")

    applied: list[dict[str, Any]] = []
    for fix_id in fixes:
        finding = by_id[fix_id]
        if finding["fix_kind"] == "diagnose_only":
            die(f"{fix_id} is diagnose_only and cannot be selected for apply.")
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


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    catalog_validation = validate_catalog()
    if not catalog_validation["ok"]:
        die("Catalog validation failed: " + "; ".join(catalog_validation["errors"]))

    evidence, platform = load_evidence(args)
    findings = evaluate_rules(evidence, platform)
    coverage = build_coverage(platform, findings)
    report = {
        "skill": SKILL_NAME,
        "generated_at": now_iso(),
        "platform": platform,
        "target_search_head": args.target_search_head,
        "splunk_uri": args.splunk_uri,
        "findings": findings,
        "coverage": coverage,
        "catalog": {
            "rule_count": len(RULE_CATALOG),
            "domain_count": len(COVERAGE_MANIFEST),
            "required_rule_fields": sorted(REQUIRED_RULE_FIELDS),
        },
    }
    fix_plan = build_fix_plan(findings)
    return report, fix_plan, evidence


def text_summary(report: dict[str, Any]) -> str:
    lines = [
        f"Splunk Admin Doctor generated {len(report['findings'])} finding(s) for {report['platform']}.",
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

    if args.strict and any(SEVERITY_RANK[item["severity"]] >= SEVERITY_RANK["high"] for item in report["findings"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

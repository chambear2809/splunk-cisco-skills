#!/usr/bin/env python3
"""Render and validate the Splunk AppDynamics skill suite."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
PARENT_SKILL = "splunk-appdynamics-setup"
TAXONOMY_PATH = SKILLS_DIR / PARENT_SKILL / "references/appdynamics-taxonomy.yaml"


class NoAliasSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True

ALLOWED_STATUSES = {
    "api_apply",
    "cli_apply",
    "k8s_apply",
    "delegated_apply",
    "render_runbook",
    "validate_only",
    "not_applicable",
}

DIRECT_SECRET_RE = re.compile(
    r"^(--(?:password|pass|secret|client-secret|api-key|token|access-token|events-api-key|controller-password))(?:=.*)?$"
)

SKILL_META: dict[str, dict[str, Any]] = {
    "splunk-appdynamics-setup": {
        "title": "Splunk AppDynamics Setup",
        "target": "AppDynamics suite router and coverage doctor",
        "purpose": "Route AppDynamics requests to the right child skill and produce a machine-readable gapless coverage report, including current 26.4 SaaS, On-Premises, API, release/reference, product-announcement, security, AI, and infrastructure families.",
        "apply": "Parent does not mutate AppDynamics directly; it delegates to child skills and cisco-appdynamics-setup.",
        "validation": "Coverage taxonomy completeness plus child rendered-output validation.",
        "sources": [
            "https://help.splunk.com/appdynamics-saas",
            "https://help.splunk.com/en/appdynamics-on-premises",
            "https://help.splunk.com/en/appdynamics-saas/release-notes-and-references",
            "https://help.splunk.com/en/appdynamics-saas/product-announcements-and-alerts",
            "https://help.splunk.com/en/appdynamics-sap-agent",
        ],
        "gate": None,
    },
    "splunk-appdynamics-platform-setup": {
        "title": "Splunk AppDynamics Platform Setup",
        "target": "On-Premises, Virtual Appliance, Enterprise Console, Controller, Events Service, EUM Server, Synthetic Server",
        "purpose": "Render and validate deployment planning, platform quickstart, Controller, Events Service, EUM Server, Synthetic Server, HA, upgrade, secure-controller, release/reference, and support-gated runbooks.",
        "apply": "Enterprise Console and platform mutations require --accept-enterprise-console-mutation; support-gated operations stay runbooks.",
        "validation": "Static plan checks plus rendered planning, quickstart, controller, Enterprise Console, Events Service, EUM, Synthetic, HA, TLS, release, known-issue, and compatibility probes.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-on-premises",
            "https://help.splunk.com/en/appdynamics-on-premises/release-notes-and-references",
            "https://help.splunk.com/appdynamics-on-premises/plan-your-deployment/plan-your-deployment",
            "https://help.splunk.com/en/appdynamics-on-premises/platform-installation-quick-start/platform-installation-quick-start",
            "https://help.splunk.com/en/appdynamics-on-premises/enterprise-console/26.4.0/administer-the-enterprise-console/enterprise-console-command-line",
            "https://help.splunk.com/en/appdynamics-on-premises/controller-deployment/26.4.0/controller-deployment/install-the-controller-using-the-cli",
            "https://help.splunk.com/en/appdynamics-on-premises/controller-deployment/26.4.0/controller-deployment/controller-high-availability/prerequisites-for-high-availability",
            "https://help.splunk.com/en/appdynamics-on-premises/controller-deployment/26.4.0/controller-deployment/upgrade-the-controller-using-the-enterprise-console/before-upgrading/back-up-the-existing-controller",
            "https://help.splunk.com/en/appdynamics-on-premises/enterprise-console/25.4.0/express-install/install-the-platform-using-gui",
            "https://help.splunk.com/en/appdynamics-on-premises/enterprise-console/25.12.0/custom-install",
            "https://help.splunk.com/en/appdynamics-on-premises/platform-installation-quick-start/discovery-and-upgrade-quick-start",
            "https://help.splunk.com/en/appdynamics-on-premises/events-service-deployment",
            "https://help.splunk.com/en/appdynamics-on-premises/eum-server-deployment",
            "https://help.splunk.com/en/appdynamics-on-premises/synthetic-server-deployment/synthetic-server-deployment/installation-overview",
            "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/get-started-with-on-premises-virtual-appliance",
            "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/deploy-splunk-appdynamics-on-premises-virtual-appliance/amazon-web-services-aws",
            "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/deploy-splunk-appdynamics-on-premises-virtual-appliance/red-hat-openshift-service-in-aws-rosa",
            "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/install-splunk-appdynamics-services/standard-deployment",
            "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/install-splunk-appdynamics-services/hybrid-deployment",
            "https://help.splunk.com/en/appdynamics-on-premises/secure-the-platform/secure-the-platform",
        ],
        "gate": "enterprise_console",
    },
    "splunk-appdynamics-controller-admin-setup": {
        "title": "Splunk AppDynamics Controller Admin Setup",
        "target": "SaaS and on-prem Controller administration",
        "purpose": "Render API client, OAuth, users, groups, roles, SAML/LDAP, permissions, licensing, license-rule, sensitive-data, audit, and tenant-admin plans.",
        "apply": "Controller REST API changes are API apply where documented; UI-only gaps render runbooks.",
        "validation": "Controller API readbacks for security, access, license, audit, and sensitive-data-control state.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-saas/extend-splunk-appdynamics/26.4.0/extend-splunk-appdynamics/splunk-appdynamics-apis/platform-api-index",
            "https://help.splunk.com/en/appdynamics-saas/appdynamics-saas-administration",
            "https://help.splunk.com/appdynamics-saas/licensing",
            "https://help.splunk.com/en/appdynamics-saas/get-started/26.4.0/sensitive-data-collection-and-security",
        ],
        "gate": None,
    },
    "splunk-appdynamics-agent-management-setup": {
        "title": "Splunk AppDynamics Agent Management Setup",
        "target": "Smart Agent and Agent Management",
        "purpose": "Render Smart Agent readiness, configuration, local and remote install, upgrade, uninstall, sync, UI, smartagentctl, deployment group, auto-attach, auto-discovery, deprecated CLI, software download, checksum, signature, and agent-release compatibility plans for supported managed agent types.",
        "apply": "Remote host execution requires --accept-remote-execution; UI paths and deprecated Smart Agent CLI paths are runbook-only; otherwise the skill emits commands for review.",
        "validation": "Smart Agent service status, Controller registration, UI inventory, managed-agent status, deployment-group state, smartagentctl command shape, remote.yaml security posture, package checksum/signature, and release-compatibility readbacks.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/before-you-begin",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/get-started/install-smart-agent",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/get-started/configure-smart-agent",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/get-started/validate-smart-agent-installation",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/get-started/synchronize-smart-agent-primary-host-with-the-remote-hosts",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/upgrade-smart-agent",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/auto-attach-java-and-nodejs-agents",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/auto-discovery-of-application-process",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/auto-deploy-agents-with-deployment-groups",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-ui",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-database-agent-using-ui",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/manage-the-agents-using-smartagentctl/install-supported-agents-using-smartagentctl/ssh-configuration-for-remote-host",
            "https://help.splunk.com/en/appdynamics-on-premises/agent-management/26.4.0/smart-agent/smart-agent-command-line-utility",
            "https://help.splunk.com/en/appdynamics-on-premises/accounts/download-splunk-appdynamics-software",
            "https://help.splunk.com/en/appdynamics-on-premises/extend-appdynamics/26.4.0/extend-splunk-appdynamics/splunk-appdynamics-apis/agent-installer-platform-service-api",
        ],
        "gate": "remote_execution",
    },
    "splunk-appdynamics-apm-setup": {
        "title": "Splunk AppDynamics APM Setup",
        "target": "Business applications, tiers, nodes, transactions, service endpoints, remote services, information points, and Splunk AppDynamics for OpenTelemetry",
        "purpose": "Render APM model, application server agent snippets, serverless/development monitoring runbooks, OpenTelemetry collector and access-key runbooks, metric checks, snapshots, and topology validation.",
        "apply": "Documented Controller APIs are API apply; runtime agent install is delegated to agent-management or k8s child skills.",
        "validation": "Controller readbacks for apps, tiers, nodes, business transactions, metrics, snapshots, and OpenTelemetry trace ingestion.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-saas/application-performance-monitoring/26.4.0",
            "https://help.splunk.com/en/appdynamics-saas/application-performance-monitoring/26.4.0/install-app-server-agents/serverless-apm-for-aws-lambda/serverless-apm-in-the-controller",
            "https://help.splunk.com/en/appdynamics-saas/application-performance-monitoring/26.4.0/splunk-appdynamics-for-opentelemetry",
        ],
        "gate": None,
    },
    "splunk-appdynamics-k8s-cluster-agent-setup": {
        "title": "Splunk AppDynamics Kubernetes Cluster Agent Setup",
        "target": "Cluster Agent, Kubernetes auto-instrumentation, AppDynamics combined agents, and Splunk OTel Collector export to Splunk Observability Cloud",
        "purpose": "Render Cluster Agent values, workload instrumentation, dual-signal combined-agent environment patches, Splunk OTel Collector wiring to O11y, and rollout validation.",
        "apply": "Kubernetes resource changes require --accept-k8s-rollout; GitOps render remains the default.",
        "validation": "kubectl/oc checks for Cluster Agent, auto-instrumented workloads, combined-agent mode, OTel collector health, and Splunk Observability telemetry export.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-saas/infrastructure-visibility/26.4.0/monitor-kubernetes-with-the-cluster-agent/use-the-cluster-agent",
            "https://help.splunk.com/en/appdynamics-saas/infrastructure-visibility/26.4.0/monitor-kubernetes-with-the-cluster-agent/permissions-required-for-cluster-agent-and-infrastructure-visibility",
            "https://help.splunk.com/en/appdynamics-saas/infrastructure-visibility/26.4.0/monitor-kubernetes-with-the-cluster-agent/installation-overview/cluster-agent-and-the-operator-compatibility-matrix",
            "https://help.splunk.com/en/appdynamics-on-premises/infrastructure-visibility/26.4.0/monitor-kubernetes-with-the-cluster-agent/installation-overview/install-splunk-otel-collector-using-cluster-agent",
            "https://help.splunk.com/en/appdynamics-saas/application-performance-monitoring/26.4.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/monitor-applications-and-infrastructure-with-combined-agent",
            "https://help.splunk.com/en/appdynamics-saas/application-performance-monitoring/26.4.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/enable-opentelemetry-in-the-java-agent/enable-dual-signal-mode",
            "https://help.splunk.com/en/appdynamics-saas/application-performance-monitoring/26.4.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/enable-opentelemetry-in-the-.net-agent/enable-the-combined-mode-for-.net-agent",
            "https://help.splunk.com/en/appdynamics-on-premises/application-performance-monitoring/26.3.0/splunk-appdynamics-for-opentelemetry/instrument-applications-with-splunk-appdynamics-for-opentelemetry/enable-opentelemetry-in-the-node.js-agent/dual-signal-mode-for-node.js-combined-agent",
            "https://help.splunk.com/en/appdynamics-saas/infrastructure-visibility/26.4.0/machine-agent/combined-agent-for-infrastructure-visibility",
        ],
        "gate": "k8s_rollout",
    },
    "splunk-appdynamics-infrastructure-visibility-setup": {
        "title": "Splunk AppDynamics Infrastructure Visibility Setup",
        "target": "Machine Agent, Server Visibility, Network Visibility, Docker/container visibility, service availability, GPU Monitoring, and Prometheus extensions",
        "purpose": "Render Machine Agent, network visibility, service availability, server-tag, GPU Monitoring, Prometheus extension, and infrastructure health-rule plans.",
        "apply": "Agent and host changes are CLI/rendered apply; Controller health rules use documented APIs where available.",
        "validation": "Controller server, container, network, GPU, Prometheus, service availability, tag, and health-rule readbacks.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-saas/infrastructure-visibility/26.4.0/infrastructure-visibility",
            "https://help.splunk.com/en/appdynamics-saas/infrastructure-visibility/26.4.0/gpu-monitoring",
            "https://help.splunk.com/en/appdynamics-saas/infrastructure-visibility/26.4.0/gpu-monitoring/gpu-monitoring-supported-environments",
            "https://help.splunk.com/en/appdynamics-on-premises/infrastructure-visibility/25.12.0/prometheus-extension-for-machine-agent",
        ],
        "gate": None,
    },
    "splunk-appdynamics-database-visibility-setup": {
        "title": "Splunk AppDynamics Database Visibility Setup",
        "target": "Database Agent and Database Visibility API collectors",
        "purpose": "Render collector CRUD payloads with file-backed secrets, DB server/node validation, and event checks.",
        "apply": "Database Visibility API apply uses password-file references and redacted rendered payloads.",
        "validation": "Collector list/readback plus DB server, node, metric, and event checks.",
        "sources": ["https://help.splunk.com/en/appdynamics-on-premises/extend-appdynamics/26.4.0/extend-splunk-appdynamics/splunk-appdynamics-apis/database-visibility-api"],
        "gate": None,
    },
    "splunk-appdynamics-analytics-setup": {
        "title": "Splunk AppDynamics Analytics Setup",
        "target": "Transaction, Log, Browser, Mobile, Synthetic, IoT, and Connected Devices Analytics",
        "purpose": "Render ADQL, schema, Analytics Events API publish/query plans, IoT/Connected Device readbacks, Business Journeys, XLM, and Events API header handling.",
        "apply": "Custom event publishing requires --accept-analytics-event-publish; query and schema validation are read-only.",
        "validation": "ADQL query/readback and optional Events API publish probe.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-saas/analytics/26.4.0",
            "https://help.splunk.com/en/appdynamics-saas/analytics/26.4.0/analytics/using-analytics-data/business-journeys",
            "https://help.splunk.com/en/appdynamics-saas/analytics/26.4.0/analytics/using-analytics-data/business-journeys/experience-level-management",
            "https://help.splunk.com/en/appdynamics-saas/end-user-monitoring/25.4.0/end-user-monitoring/iot-monitoring/iot-analytics",
        ],
        "gate": "analytics_event_publish",
    },
    "splunk-appdynamics-eum-setup": {
        "title": "Splunk AppDynamics EUM Setup",
        "target": "Browser RUM, Mobile RUM, IoT RUM, Session Replay, source maps, and app keys",
        "purpose": "Render browser injection, mobile SDK snippets, app-key inventory, Session Replay, mapping, and source-upload runbooks.",
        "apply": "Local source edits require --accept-eum-source-edit; otherwise snippets and upload commands are rendered only.",
        "validation": "EUM app key checks, beacon validation, source-map inventory, and session replay readiness checks.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-saas/end-user-monitoring/26.4.0/end-user-monitoring/browser-monitoring/browser-real-user-monitoring/overview-of-the-controller-ui-for-browser-rum/configure-the-controller-ui-for-browser-rum",
            "https://help.splunk.com/en/appdynamics-saas/end-user-monitoring/26.4.0/end-user-monitoring/browser-monitoring/browser-real-user-monitoring/overview-of-the-controller-ui-for-browser-rum/session-replay-for-browser-rum/enable-session-replay",
            "https://help.splunk.com/en/appdynamics-saas/end-user-monitoring/25.9.0/end-user-monitoring/mobile-real-user-monitoring/overview-of-the-controller-ui-for-mobile-rum/session-replay-for-mobile-rum",
        ],
        "gate": "eum_source_edit",
    },
    "splunk-appdynamics-synthetic-monitoring-setup": {
        "title": "Splunk AppDynamics Synthetic Monitoring Setup",
        "target": "Browser Synthetic, Synthetic API Monitoring, Hosted and Private Synthetic Agents",
        "purpose": "Render synthetic jobs, private synthetic agent Docker/Kubernetes/Minikube assets, Shepherd URL checks, and run validation.",
        "apply": "Synthetic job API apply is documented where available; private agent rollout emits reviewed container or Kubernetes plans.",
        "validation": "Synthetic job, run, location, PSA health, and Shepherd connectivity checks.",
        "sources": ["https://help.splunk.com/en/appdynamics-saas/end-user-monitoring/26.4.0/end-user-monitoring/synthetic-monitoring"],
        "gate": None,
    },
    "splunk-appdynamics-log-observer-connect-setup": {
        "title": "Splunk AppDynamics Log Observer Connect Setup",
        "target": "Splunk Log Observer Connect for Splunk AppDynamics",
        "purpose": "Render new LOC configuration, legacy Splunk integration detection, service-account handoffs, and deep-link validation.",
        "apply": "Cloud/Enterprise Splunk service-account and allow-list actions are delegated to Splunk Platform skills.",
        "validation": "Controller LOC state, Splunk service account readiness, legacy integration disabled state, and deep-link checks.",
        "sources": ["https://help.splunk.com/en/appdynamics-saas/unified-observability-experience-with-the-splunk-platform/26.4.0/splunk-log-observer-connect-for-splunk-appdynamics"],
        "gate": None,
    },
    "splunk-appdynamics-alerting-content-setup": {
        "title": "Splunk AppDynamics Alerting Content Setup",
        "target": "Health rules, schedules, policies, actions, digests, suppression, anomaly detection, RCA, and AIML baselines",
        "purpose": "Render alerting content import/export, rollback, health rule, schedule, policy, action, digest, suppression, anomaly detection, RCA, dynamic baseline, and automated transaction diagnostics plans.",
        "apply": "Documented Controller APIs are API apply; unsupported UI-only content stays as runbooks.",
        "validation": "Readbacks for health rules, policies, actions, schedules, suppressions, exported content snapshots, baseline behavior, and AIML diagnostics.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-saas/get-started/26.4.0/alert-and-respond/health-rules/how-to-set-up-health-rules",
            "https://help.splunk.com/en/appdynamics-saas/get-started/26.4.0/alert-and-respond/policies/policy-actions",
            "https://help.splunk.com/en/appdynamics-saas/get-started/26.4.0/alert-and-respond/anomaly-detection",
            "https://help.splunk.com/en/appdynamics-saas/get-started/26.4.0/aiml",
        ],
        "gate": None,
    },
    "splunk-appdynamics-dashboards-reports-setup": {
        "title": "Splunk AppDynamics Dashboards Reports Setup",
        "target": "Custom dashboards, Dash Studio, reports, scheduled reports, and War Rooms",
        "purpose": "Render dashboard/report inventories, scheduled-report runbooks, Dash Studio handoffs, ThousandEyes dashboard integration handoffs, and War Room validation.",
        "apply": "API-backed dashboard actions are API apply; UI-only report and War Room operations render runbooks.",
        "validation": "Dashboard, report, schedule, ThousandEyes query/widget, and War Room existence checks.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-saas/get-started/26.4.0/dashboards-and-reports",
            "https://help.splunk.com/en/appdynamics-on-premises/get-started/26.4.0/dashboards-and-reports/custom-dashboards/create-custom-dashboards",
            "https://help.splunk.com/en/appdynamics-saas/get-started/26.4.0/dashboards-and-reports/custom-dashboards/virtual-war-rooms/war-room-templates",
            "https://help.splunk.com/en/appdynamics-saas/get-started/26.4.0/dashboards-and-reports/dash-studio/thousandeyes-integration-with-appdynamics",
        ],
        "gate": None,
    },
    "splunk-appdynamics-tags-extensions-setup": {
        "title": "Splunk AppDynamics Tags Extensions Setup",
        "target": "Custom Tags, Integration Modules, extensions, Machine Agent custom metrics, ServiceNow, Jira, Scalyr, ACC, Log Auto-Discovery",
        "purpose": "Render tag API plans, extension runbooks, custom metric examples, and external integration handoffs.",
        "apply": "Tag APIs are API apply; extensions and third-party connectors render runbooks unless their owner API is explicit.",
        "validation": "Tag readbacks, extension file checks, custom metric visibility, and connector readiness checks.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-saas/tag-management/26.4.0",
            "https://help.splunk.com/en/appdynamics-saas/application-performance-monitoring/26.4.0/overview-of-application-monitoring/tags/filter-entities-with-custom-tags",
            "https://help.splunk.com/en/appdynamics-on-premises/extend-appdynamics/26.4.0/extend-splunk-appdynamics/integration-modules",
        ],
        "gate": None,
    },
    "splunk-appdynamics-security-ai-setup": {
        "title": "Splunk AppDynamics Security AI Setup",
        "target": "Application Security Monitoring, Secure Application, Secure Application policies, Secure Application APIs, and Observability for AI",
        "purpose": "Render Application Security Monitoring, Secure Application policy, OTel Java security, Secure Application API, Observability for AI, GenAI framework, GPU, and Cisco AI Pod handoffs.",
        "apply": "Security and AI platform enablement is validate/runbook-first with handoffs to owning skills.",
        "validation": "Secure Application dashboard, runtime policy, API, OTel Java, GenAI framework, GPU, and AI Pod readiness checks.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-saas/application-security-monitoring/26.4.0/application-security-monitoring",
            "https://help.splunk.com/en/appdynamics-saas/application-security-monitoring/26.4.0/application-security-monitoring/secure-application-policies",
            "https://help.splunk.com/en/appdynamics-saas/application-security-monitoring/26.4.0/application-security-monitoring/secure-application-for-opentelemetry",
            "https://help.splunk.com/en/appdynamics-saas/extend-splunk-appdynamics/26.4.0/extend-splunk-appdynamics/splunk-appdynamics-apis/secure-application-apis",
            "https://help.splunk.com/en/appdynamics-saas/observability-for-ai/26.4.0/splunk-appdynamics-observability-for-ai/supported-ai-components",
        ],
        "gate": None,
    },
    "splunk-appdynamics-sap-agent-setup": {
        "title": "Splunk AppDynamics SAP Agent Setup",
        "target": "SAP Agent, ABAP Agent, HTTP SDK, SNP CrystalBridge Monitoring, BiQ Collector, and NetWeaver transports",
        "purpose": "Render SAP agent install, transport, authorization, SDK, CrystalBridge, BiQ collector, release-note, compatibility, and validation runbooks.",
        "apply": "SAP transports and authorization changes are runbook-only; agent commands are rendered for controlled execution.",
        "validation": "SAP-side authorization and transport checklist plus release-note, component-version, Controller node, and metric readbacks.",
        "sources": [
            "https://help.splunk.com/en/appdynamics-sap-agent",
            "https://help.splunk.com/en/appdynamics-sap-agent/release-notes",
        ],
        "gate": None,
    },
}

GATE_FLAGS = {
    "remote_execution": "--accept-remote-execution",
    "enterprise_console": "--accept-enterprise-console-mutation",
    "k8s_rollout": "--accept-k8s-rollout",
    "eum_source_edit": "--accept-eum-source-edit",
    "analytics_event_publish": "--accept-analytics-event-publish",
}


def reject_direct_secrets(argv: list[str]) -> None:
    for arg in argv:
        match = DIRECT_SECRET_RE.match(arg)
        if match:
            raise SystemExit(
                "Refusing direct-secret flag. Use file-backed credentials such as "
                "--token-file, --password-file, --client-secret-file, or --events-api-key-file."
            )


def load_yaml_or_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def load_taxonomy() -> list[dict[str, Any]]:
    data = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8")) or {}
    features = data.get("features", [])
    if not isinstance(features, list):
        raise ValueError("AppDynamics taxonomy must contain features list")
    return [row for row in features if isinstance(row, dict)]


def coverage_for_skill(skill: str) -> list[dict[str, Any]]:
    rows = load_taxonomy()
    if skill == PARENT_SKILL:
        return rows
    return [row for row in rows if row.get("owner") == skill]


def validate_coverage(rows: list[dict[str, Any]]) -> list[str]:
    required = {
        "id",
        "family",
        "feature",
        "owner",
        "source_url",
        "status",
        "validation_method",
        "apply_boundary",
    }
    errors: list[str] = []
    for index, row in enumerate(rows):
        missing = sorted(field for field in required if not row.get(field))
        if missing:
            errors.append(f"coverage[{index}] missing {', '.join(missing)}")
        if row.get("status") not in ALLOWED_STATUSES:
            errors.append(f"{row.get('id', f'coverage[{index}]')}: invalid status {row.get('status')!r}")
    return errors


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("password", "secret", "token", "api_key", "apikey", "key_file")):
                result[key] = "<redacted:file-reference-required>" if not str(key).endswith("_file") else str(item)
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def dump_yaml(payload: Any) -> str:
    return yaml.dump(payload, Dumper=NoAliasSafeDumper, sort_keys=False)


def render_overview(skill: str, spec: dict[str, Any], coverage: list[dict[str, Any]]) -> str:
    meta = SKILL_META[skill]
    rows = "\n".join(
        f"- `{row['id']}`: {row['feature']} ({row['status']})"
        for row in coverage[:12]
    )
    if len(coverage) > 12:
        rows += f"\n- ... {len(coverage) - 12} more rows in coverage-report.json"
    requested = spec.get("sections") or spec.get("features") or ["all"]
    return f"""# {meta['title']}

Target: {meta['target']}

Purpose: {meta['purpose']}

Requested sections: {requested}

## Coverage

{rows or '- No taxonomy rows found for this child skill.'}

## Apply Boundary

{meta['apply']}

## Validation

{meta['validation']}
"""


def render_apply_plan(skill: str, coverage: list[dict[str, Any]]) -> str:
    if skill == "splunk-appdynamics-platform-setup":
        return render_platform_apply_plan(coverage)
    meta = SKILL_META[skill]
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f"# Reviewed apply plan for {skill}.",
        f"# Boundary: {meta['apply']}",
        "# This generated plan is intentionally conservative; inspect each block before running.",
        "",
    ]
    for row in coverage:
        status = row["status"]
        lines.append(f"# {row['id']}: {row['feature']} [{status}]")
        if status in {"render_runbook", "validate_only", "not_applicable", "delegated_apply"}:
            lines.append(f"echo 'HANDOFF: {row['feature']} - {row['apply_boundary']}'")
        elif status == "k8s_apply":
            lines.append("echo 'K8S APPLY: review manifests, then run kubectl apply from this rendered tree.'")
        else:
            lines.append("echo 'API/CLI APPLY: review generated payloads and run the documented child command.'")
        lines.append("")
    return "\n".join(lines)


def render_common_artifacts(skill: str, out: Path, spec: dict[str, Any], coverage: list[dict[str, Any]]) -> None:
    meta = SKILL_META[skill]
    write(out / "01-overview.md", render_overview(skill, spec, coverage))
    write(out / "02-apply-boundary.md", f"# Apply Boundary\n\n{meta['apply']}\n")
    write(out / "03-validation.md", f"# Validation Plan\n\n{meta['validation']}\n")
    write(out / "04-runbook.md", render_runbook(skill, spec, coverage))
    write(out / "apply-plan.sh", render_apply_plan(skill, coverage))
    os.chmod(out / "apply-plan.sh", stat.S_IMODE((out / "apply-plan.sh").stat().st_mode) | stat.S_IXUSR)
    write_json(
        out / "coverage-report.json",
        {
            "skill": skill,
            "coverage_rows": len(coverage),
            "features": coverage,
            "sources": meta["sources"],
        },
    )
    write_json(out / "redacted-spec.json", redact(spec))


def render_runbook(skill: str, spec: dict[str, Any], coverage: list[dict[str, Any]]) -> str:
    meta = SKILL_META[skill]
    source_lines = "\n".join(f"- {url}" for url in meta["sources"])
    feature_lines = "\n".join(
        f"- {row['feature']}: validate with {row['validation_method']}; apply boundary: {row['apply_boundary']}"
        for row in coverage
    )
    return f"""# {meta['title']} Runbook

## Sources

{source_lines}

## Feature Checklist

{feature_lines}

## Secret Handling

Keep controller passwords, OAuth client secrets, Events API keys, Splunk tokens,
database passwords, and SAP credentials in chmod-600 files. Do not put secret
values in YAML specs, shell arguments, rendered payloads, or chat.
"""


PLATFORM_REQUIRED_ARTIFACTS = {
    "platform-topology-inventory.yaml",
    "deployment-method-selector.yaml",
    "deployment-method-matrix.md",
    "enterprise-console-hosts.txt",
    "enterprise-console-command-plan.sh",
    "classic-onprem-deployment-runbook.md",
    "controller-install-upgrade-runbook.md",
    "component-deployment-runbook.md",
    "virtual-appliance-deployment-runbook.md",
    "platform-ha-backup-runbook.md",
    "platform-security-checklist.md",
    "platform-validation-probes.sh",
}


CLASSIC_DEPLOYMENT_METHODS: list[dict[str, Any]] = [
    {
        "id": "classic_gui_express",
        "family": "classic_on_premises",
        "interface": "enterprise_console_gui",
        "best_for": "Demo, evaluation, or smallest-friction single-host Controller plus embedded Events Service.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/enterprise-console/25.4.0/express-install/install-the-platform-using-gui",
        "validation": "Enterprise Console Jobs page, Controller URL, and platform-validation-probes.sh.",
        "frictionless_next_step": "Open Enterprise Console on port 9191 and choose Express Install.",
    },
    {
        "id": "classic_gui_custom",
        "family": "classic_on_premises",
        "interface": "enterprise_console_gui",
        "best_for": "Fresh production, distributed Controller, Controller HA, or scaled Events Service.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/enterprise-console/25.12.0/custom-install",
        "validation": "Enterprise Console Jobs page, Controller health, Events URL, and HA checks when enabled.",
        "frictionless_next_step": "Open Enterprise Console on port 9191 and choose Custom Install.",
    },
    {
        "id": "classic_cli_custom",
        "family": "classic_on_premises",
        "interface": "enterprise_console_cli",
        "best_for": "Script-reviewed Linux deployments where the operator wants CLI repeatability.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/controller-deployment/26.4.0/controller-deployment/install-the-controller-using-the-cli",
        "validation": "platform-admin list-jobs, diagnosis job, Controller URL, and platform-validation-probes.sh.",
        "frictionless_next_step": "Review enterprise-console-command-plan.sh, then run from an approved authenticated CLI session.",
    },
    {
        "id": "classic_discover_upgrade_gui",
        "family": "classic_on_premises",
        "interface": "enterprise_console_gui",
        "best_for": "Existing Controller or Events Service environments that need Enterprise Console onboarding.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/platform-installation-quick-start/discovery-and-upgrade-quick-start",
        "validation": "Discovery wizard verification summary, Controller version, and post-upgrade health checks.",
        "frictionless_next_step": "Use the Discovery or Custom Install Discover and Upgrade wizard.",
    },
    {
        "id": "classic_discover_upgrade_cli",
        "family": "classic_on_premises",
        "interface": "enterprise_console_cli",
        "best_for": "Existing environments that need a reviewed discover-upgrade command path.",
        "source": "https://help.splunk.com/appdynamics-on-premises/upgrade-platform-components/discover-existing-components",
        "validation": "platform-admin discover-upgrade job status, Controller version, and rollback readiness.",
        "frictionless_next_step": "Create platform, add credentials/hosts, then submit the discover-upgrade job with local secret handling.",
    },
    {
        "id": "classic_aws_aurora_upgrade_cli",
        "family": "classic_on_premises",
        "interface": "enterprise_console_cli",
        "best_for": "AWS Controller deployments using Aurora where the docs require CLI upgrade or move operations.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/plan-your-deployment/aws-controller-deployment-guide/upgrade-or-move-the-controller-on-aws",
        "validation": "Aurora backup, EC2 sizing, discover/upgrade job status, and Controller post-upgrade checks.",
        "frictionless_next_step": "Use the AWS Aurora branch only when databaseType=aurora is explicit in the spec.",
    },
]


COMPONENT_DEPLOYMENT_METHODS: list[dict[str, Any]] = [
    {
        "id": "events_linux_gui_cli",
        "family": "classic_component",
        "interface": "enterprise_console_gui_or_cli",
        "best_for": "Linux Events Service single-node, 3+ node cluster, or embedded-to-scaled deployment.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/events-service-deployment/events-service-deployment/install-the-events-service-on-linux",
        "validation": "Events Service URL, Controller event service settings, load balancer VIP, and node status.",
        "frictionless_next_step": "Use Custom Install or the Events Service page for GUI; use platform-admin for CLI.",
    },
    {
        "id": "events_windows_manual",
        "family": "classic_component",
        "interface": "manual_windows",
        "best_for": "Windows Events Service deployments where Enterprise Console remote operations are not supported.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/events-service-deployment/events-service-deployment/install-the-events-service-on-windows",
        "validation": "Windows service state, Controller event service URL/key settings, and cluster config files.",
        "frictionless_next_step": "Render a manual checklist; do not try to remote-install Windows Events Service through Enterprise Console.",
    },
    {
        "id": "eum_installer_gui_console_silent",
        "family": "classic_component",
        "interface": "package_installer",
        "best_for": "EUM Server demo or production install using GUI, console, or silent varfile modes.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/eum-server-deployment/eum-server-deployment/run-the-eum-server-installer",
        "validation": "EUM ports, reverse proxy, Controller integration, Events Service integration, and beacon test.",
        "frictionless_next_step": "Generate a mode-specific response-file checklist and reverse-proxy/TLS validation.",
    },
    {
        "id": "synthetic_server_sequence",
        "family": "classic_component",
        "interface": "package_and_agent_runbook",
        "best_for": "On-prem Synthetic Server after Controller, Events Service, and EUM Server are ready.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/synthetic-server-deployment/synthetic-server-deployment/installation-overview",
        "validation": "Synthetic Server endpoints, EUM connectivity, Controller integration, and Synthetic Agent checks.",
        "frictionless_next_step": "Render dependency gates before any Synthetic install steps.",
    },
]


VIRTUAL_APPLIANCE_DEPLOYMENT_METHODS: list[dict[str, Any]] = [
    {
        "id": "va_vmware_vsphere_ova",
        "family": "virtual_appliance_infra",
        "interface": "vmware_vsphere",
        "best_for": "vSphere environments deploying three VMs from OVA/OVF properties.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/deploy-splunk-appdynamics-on-premises-virtual-appliance/vmware-vsphere",
        "validation": "Three VMs, VMware Tools OVF properties, appdctl show boot, and cluster status.",
        "frictionless_next_step": "Use the OVA and collect DNS, gateway, three host IPs, domain, and profile up front.",
    },
    {
        "id": "va_vmware_esxi_ova",
        "family": "virtual_appliance_infra",
        "interface": "vmware_esxi",
        "best_for": "Standalone ESXi environments deploying three VMs from the OVA.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/deploy-splunk-appdynamics-on-premises-virtual-appliance/vmware-esxi",
        "validation": "Three VMs, network properties, appdctl show boot, and cluster status.",
        "frictionless_next_step": "Use the ESXi Create/Register VM flow and capture the same network fields for each node.",
    },
    {
        "id": "va_azure_vhd",
        "family": "virtual_appliance_infra",
        "interface": "azure_portal_or_cli",
        "best_for": "Azure deployments using the VHD image and reference scripts.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.7.0/deploy-splunk-appdynamics-on-premises-virtual-appliance/microsoft-azure",
        "validation": "Resource group, NSG, VNet, storage/image gallery, three VMs, and appdctl show boot.",
        "frictionless_next_step": "Render the ordered Azure resource checklist and config.cfg fields before running reference scripts.",
    },
    {
        "id": "va_aws_ami",
        "family": "virtual_appliance_infra",
        "interface": "aws_console_or_cli",
        "best_for": "AWS deployments using AMI import, m5a.4xlarge instances, and reference scripts.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/deploy-splunk-appdynamics-on-premises-virtual-appliance/amazon-web-services-aws",
        "validation": "VPC, S3, IAM import role, AMI ID, three EC2 instances, host init, and appdctl show boot.",
        "frictionless_next_step": "Render the AWS import/run-instances checklist and require explicit profile/region/subnet inputs.",
    },
    {
        "id": "va_kvm_qcow2",
        "family": "virtual_appliance_infra",
        "interface": "kvm_reference_scripts",
        "best_for": "KVM deployments using QCOW2 and three KVM hypervisors.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.4.0/deploy-cisco-appdynamics-on-premises-virtual-appliance/deploy-and-configure-virtual-appliance-in-kvm",
        "validation": "NTP, kvm-ok, bridge, config.cfg, run-cluster, cluster-status, and appdctl show boot.",
        "frictionless_next_step": "Render config.cfg placeholders and preflight host virtualization checks.",
    },
    {
        "id": "va_rosa_qcow2",
        "family": "virtual_appliance_infra",
        "interface": "rosa_openshift_virtualization",
        "best_for": "ROSA HCP with OpenShift Virtualization using QCOW2-backed VMs.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/deploy-splunk-appdynamics-on-premises-virtual-appliance/red-hat-openshift-service-in-aws-rosa",
        "validation": "ROSA HCP, active OpenShift Virtualization operator, PVC boot disks, NLB/firewall, and appdctl show boot.",
        "frictionless_next_step": "Render virtctl image-upload commands and VM template checks with UEFI non-secure boot.",
    },
    {
        "id": "va_services_standard",
        "family": "virtual_appliance_services",
        "interface": "appdcli",
        "best_for": "Virtual Appliance installs infrastructure plus Controller, Events, EUM, Synthetic, and optional services in Kubernetes.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/install-splunk-appdynamics-services/standard-deployment",
        "validation": "globals.yaml.gotmpl, secrets.yaml, license.lic, appdcli ping, and kubectl namespace checks.",
        "frictionless_next_step": "Render profile-matched appdcli start commands and DNS/SAN checks.",
    },
    {
        "id": "va_services_hybrid",
        "family": "virtual_appliance_services",
        "interface": "appdcli",
        "best_for": "Hybrid VA services attached to an existing classic Controller, Events Service, and EUM Server.",
        "source": "https://help.splunk.com/en/appdynamics-on-premises/virtual-appliance-self-hosted/25.10.0/install-splunk-appdynamics-services/hybrid-deployment",
        "validation": "Hybrid Controller connectivity, DNS, certs, appdcli ping, Controller restart, and agent download checks.",
        "frictionless_next_step": "Render hybrid Controller/EUM/Events connection intake before service start.",
    },
]


ALL_PLATFORM_DEPLOYMENT_METHODS = (
    CLASSIC_DEPLOYMENT_METHODS + COMPONENT_DEPLOYMENT_METHODS + VIRTUAL_APPLIANCE_DEPLOYMENT_METHODS
)


def render_platform_apply_plan(coverage: list[dict[str, Any]]) -> str:
    feature_lines = "\n".join(
        f"# - {row['id']}: {row['status']} - {row['apply_boundary']}"
        for row in coverage
    )
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Reviewed apply plan for splunk-appdynamics-platform-setup.
# Boundary: Enterprise Console and platform mutations require --accept-enterprise-console-mutation.
# The renderer emits concrete command/runbook artifacts but does not execute live platform mutation.

{feature_lines}

echo "Review platform-topology-inventory.yaml"
echo "Review enterprise-console-command-plan.sh"
echo "Run enterprise-console-command-plan.sh only from an approved Enterprise Console CLI session"
echo "Use controller-install-upgrade-runbook.md for Controller install/upgrade steps that require password arguments"
echo "Use platform-ha-backup-runbook.md for HA, backup, restore, and failover operations"
echo "Use platform-security-checklist.md for TLS and hardening changes"
"""


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def shell_quote(value: Any) -> str:
    return shlex.quote(str(value))

def render_appd_curl_helper() -> str:
    return r"""APPD_CURL_TLS_ARGS=()
APPD_INSECURE_TLS_WARNED=0

appd_prepare_curl_tls_args() {
  APPD_CURL_TLS_ARGS=()

  if [[ -n "${APPD_CA_CERT:-}" ]]; then
    if [[ ! -f "${APPD_CA_CERT}" ]]; then
      echo "FAIL: APPD_CA_CERT does not exist: ${APPD_CA_CERT}" >&2
      return 2
    fi
    APPD_CURL_TLS_ARGS=(--cacert "${APPD_CA_CERT}")
    return 0
  fi

  case "${APPD_VERIFY_SSL:-true}" in
    false|False|FALSE|0|no|No|NO|off|Off|OFF)
      if [[ "${APPD_INSECURE_TLS_WARNED}" != "1" ]]; then
        echo "WARN: TLS verification is disabled for AppDynamics API probes (APPD_VERIFY_SSL=false). Prefer APPD_CA_CERT=/path/to/ca.pem for self-signed lab controllers." >&2
        APPD_INSECURE_TLS_WARNED=1
      fi
      APPD_CURL_TLS_ARGS=(-k)
      ;;
    true|True|TRUE|1|yes|Yes|YES|on|On|ON|"")
      ;;
    *)
      echo "FAIL: APPD_VERIFY_SSL must be true or false; got '${APPD_VERIFY_SSL}'" >&2
      return 2
      ;;
  esac
}

appd_curl() {
  appd_prepare_curl_tls_args || return $?
  curl "${APPD_CURL_TLS_ARGS[@]}" "$@"
}
"""


def host_records_from_platform_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    ec = as_dict(spec.get("enterprise_console"))
    controller = as_dict(spec.get("controller"))
    events = as_dict(spec.get("events_service"))
    eum = as_dict(spec.get("eum_server"))
    synthetic = as_dict(spec.get("synthetic_server"))
    records: list[dict[str, Any]] = []

    def add(host: Any, component: str, **extra: Any) -> None:
        if host:
            record = {"host": str(host), "component": component}
            record.update({key: value for key, value in extra.items() if value not in (None, "", [])})
            records.append(record)

    add(ec.get("host"), "enterprise_console", port=ec.get("port"), install_dir=ec.get("install_dir"))
    add(controller.get("primary_host"), "controller_primary", http_port=controller.get("http_port"), https_port=controller.get("https_port"))
    add(controller.get("secondary_host"), "controller_secondary", replication_port=as_dict(spec.get("ha")).get("replication_port"))
    for node in as_list(events.get("nodes")):
        node_dict = as_dict(node)
        add(node_dict.get("host"), "events_service", roles=node_dict.get("roles"), data_dir=node_dict.get("data_dir"))
    add(eum.get("host"), "eum_server", mode=eum.get("mode"), http_port=eum.get("http_port"), https_port=eum.get("https_port"))
    add(synthetic.get("host"), "synthetic_server", http_ports=synthetic.get("http_ports"), https_ports=synthetic.get("https_ports"))

    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        key = (record["host"], record["component"])
        if key not in seen:
            unique.append(record)
            seen.add(key)
    return unique


def method_by_id(method_id: str) -> dict[str, Any]:
    for method in ALL_PLATFORM_DEPLOYMENT_METHODS:
        if method["id"] == method_id:
            return method
    return {}


def normalize_deployment_model(value: Any) -> str:
    normalized = str(value or "on_premises").strip().lower().replace("-", "_")
    aliases = {
        "classic": "on_premises",
        "classic_on_premises": "on_premises",
        "onprem": "on_premises",
        "on_prem": "on_premises",
        "self_hosted_virtual_appliance": "virtual_appliance",
        "va": "virtual_appliance",
        "appliance": "virtual_appliance",
    }
    return aliases.get(normalized, normalized)


def selected_platform_method_ids(spec: dict[str, Any]) -> list[str]:
    platform = as_dict(spec.get("platform"))
    deployment = as_dict(spec.get("deployment"))
    va = as_dict(spec.get("virtual_appliance"))
    events = as_dict(spec.get("events_service"))
    eum = as_dict(spec.get("eum_server"))
    synthetic = as_dict(spec.get("synthetic_server"))

    deployment_model = normalize_deployment_model(
        deployment.get("model") or spec.get("deployment_model") or platform.get("deployment_model")
    )
    selected: list[str] = []
    if deployment_model == "virtual_appliance":
        infra = str(va.get("infrastructure_platform") or deployment.get("infrastructure_platform") or "vmware_vsphere")
        infra = infra.strip().lower().replace("-", "_")
        infra_aliases = {
            "vsphere": "vmware_vsphere",
            "vcenter": "vmware_vsphere",
            "esxi": "vmware_esxi",
            "azure": "azure",
            "microsoft_azure": "azure",
            "aws": "aws",
            "amazon_web_services": "aws",
            "kvm": "kvm",
            "rosa": "rosa",
            "openshift_rosa": "rosa",
        }
        infra = infra_aliases.get(infra, infra)
        selected.append(
            {
                "vmware_vsphere": "va_vmware_vsphere_ova",
                "vmware_esxi": "va_vmware_esxi_ova",
                "azure": "va_azure_vhd",
                "aws": "va_aws_ami",
                "kvm": "va_kvm_qcow2",
                "rosa": "va_rosa_qcow2",
            }.get(infra, "va_vmware_vsphere_ova")
        )
        service_mode = str(va.get("service_deployment") or deployment.get("service_deployment") or "standard")
        service_mode = service_mode.strip().lower().replace("-", "_")
        selected.append("va_services_hybrid" if service_mode == "hybrid" else "va_services_standard")
        return selected

    install_mode = str(platform.get("install_mode") or deployment.get("install_mode") or "custom")
    install_mode = install_mode.strip().lower().replace("-", "_")
    operator_interface = str(deployment.get("operator_interface") or platform.get("operator_interface") or "cli")
    operator_interface = operator_interface.strip().lower().replace("-", "_")
    if install_mode == "express":
        selected.append("classic_gui_express")
    elif install_mode in {"discover", "discover_upgrade", "discovery_upgrade"}:
        selected.append("classic_discover_upgrade_cli" if operator_interface == "cli" else "classic_discover_upgrade_gui")
    elif operator_interface == "gui":
        selected.append("classic_gui_custom")
    else:
        selected.append("classic_cli_custom")

    controller = as_dict(spec.get("controller"))
    if "aurora" in str(controller.get("database_type", "")).strip().lower():
        selected.append("classic_aws_aurora_upgrade_cli")
    if bool(events.get("enabled", False)):
        if str(events.get("os_family", platform.get("os_family", "linux"))).lower() == "windows":
            selected.append("events_windows_manual")
        else:
            selected.append("events_linux_gui_cli")
    if bool(eum.get("enabled", False)):
        selected.append("eum_installer_gui_console_silent")
    if bool(synthetic.get("enabled", False)):
        selected.append("synthetic_server_sequence")
    return selected


def render_deployment_method_selector(spec: dict[str, Any]) -> str:
    deployment = as_dict(spec.get("deployment"))
    va = as_dict(spec.get("virtual_appliance"))
    selected_ids = selected_platform_method_ids(spec)
    payload = {
        "deployment_model": normalize_deployment_model(
            deployment.get("model") or spec.get("deployment_model") or as_dict(spec.get("platform")).get("deployment_model")
        ),
        "recommended_methods": selected_ids,
        "recommended_next_steps": [
            method_by_id(method_id).get("frictionless_next_step", "Review the rendered runbook.")
            for method_id in selected_ids
        ],
        "required_decisions": [
            "Choose classic on-premises software or Virtual Appliance.",
            "Choose GUI-first, CLI-reviewed, or discover/upgrade for classic on-premises.",
            "For Virtual Appliance, choose infrastructure target: vmware_vsphere, vmware_esxi, azure, aws, kvm, or rosa.",
            "For Virtual Appliance, choose service deployment: standard or hybrid.",
            "Choose profile and node count before rendering final host, disk, DNS, and certificate checks.",
        ],
        "virtual_appliance_defaults": {
            "infrastructure_platform": va.get("infrastructure_platform", "vmware_vsphere"),
            "service_deployment": va.get("service_deployment", "standard"),
            "profile": va.get("profile", as_dict(spec.get("platform")).get("controller_profile", "small")),
            "node_count": va.get("node_count", 3),
        },
        "supported_methods": [
            {
                "id": method["id"],
                "family": method["family"],
                "interface": method["interface"],
                "source": method["source"],
            }
            for method in ALL_PLATFORM_DEPLOYMENT_METHODS
        ],
    }
    return dump_yaml(payload)


def render_deployment_method_matrix(spec: dict[str, Any]) -> str:
    selected = set(selected_platform_method_ids(spec))
    rows = [
        "| Method | Selected | Interface | Best for | Validation |",
        "|---|---:|---|---|---|",
    ]
    for method in ALL_PLATFORM_DEPLOYMENT_METHODS:
        rows.append(
            "| `{id}` | {selected} | {interface} | {best_for} | {validation} |".format(
                id=method["id"],
                selected="yes" if method["id"] in selected else "",
                interface=method["interface"],
                best_for=method["best_for"],
                validation=method["validation"],
            )
        )
    sources = "\n".join(f"- {method['source']}" for method in ALL_PLATFORM_DEPLOYMENT_METHODS)
    return "# Deployment Method Matrix\n\n" + "\n".join(rows) + "\n\n## Sources\n\n" + sources + "\n"


def render_platform_topology(spec: dict[str, Any]) -> str:
    platform = as_dict(spec.get("platform"))
    ec = as_dict(spec.get("enterprise_console"))
    controller = as_dict(spec.get("controller"))
    events = as_dict(spec.get("events_service"))
    eum = as_dict(spec.get("eum_server"))
    synthetic = as_dict(spec.get("synthetic_server"))
    ha = as_dict(spec.get("ha"))
    security = as_dict(spec.get("security"))
    payload = {
        "doc_version": spec.get("doc_version", "26.4.0"),
        "deployment_model": spec.get("deployment_model", "on_premises"),
        "platform": {
            "name": platform.get("name", "prod-platform"),
            "target_version": platform.get("target_version", spec.get("doc_version", "26.4.0")),
            "installation_dir": platform.get("installation_dir", "/opt/appdynamics/platform"),
            "install_mode": platform.get("install_mode", "custom"),
            "controller_profile": platform.get("controller_profile", "medium"),
        },
        "enterprise_console": {
            "host": ec.get("host", "ec.example.com"),
            "bin_dir": ec.get("bin_dir", "/opt/appdynamics/enterpriseconsole/platform-admin/bin"),
            "credential_name": ec.get("credential_name", "EC-appd"),
            "remote_user": ec.get("remote_user", "appduser"),
            "ssh_key_file": ec.get("ssh_key_file", "/secure/appdynamics/ec-id_rsa.pem"),
        },
        "controller": {
            "url": spec.get("controller_url", "https://controller.example.com:8090"),
            "primary_host": controller.get("primary_host", "controller-1.example.com"),
            "secondary_host": controller.get("secondary_host"),
            "profile": platform.get("controller_profile", "medium"),
            "backup_location": controller.get("backup_location") or ha.get("backup_location"),
        },
        "events_service": {
            "enabled": bool(events.get("enabled", False)),
            "vip_url": events.get("vip_url"),
            "nodes": as_list(events.get("nodes")),
        },
        "eum_server": {
            "enabled": bool(eum.get("enabled", False)),
            "host": eum.get("host"),
            "mode": eum.get("mode", "production"),
        },
        "synthetic_server": {
            "enabled": bool(synthetic.get("enabled", False)),
            "host": synthetic.get("host"),
        },
        "ha": {
            "enabled": bool(ha.get("enabled", False)),
            "load_balancer_vip": ha.get("load_balancer_vip"),
            "replication_port": ha.get("replication_port"),
            "io_latency_ms_max": ha.get("io_latency_ms_max"),
            "secondary_license_ready": bool(ha.get("secondary_license_ready", False)),
        },
        "security": {
            "tls_profile": security.get("tls_profile", "enterprise"),
            "controller_ca_cert_file": security.get("controller_ca_cert_file"),
            "controller_cert_file": security.get("controller_cert_file"),
            "controller_key_file": security.get("controller_key_file"),
            "reverse_proxy_tls": bool(security.get("reverse_proxy_tls", False)),
            "disable_untrusted_http": bool(security.get("disable_untrusted_http", False)),
            "hsts_enabled": bool(security.get("hsts_enabled", False)),
        },
        "hosts": host_records_from_platform_spec(spec),
    }
    return dump_yaml(payload)


def render_enterprise_console_command_plan(spec: dict[str, Any]) -> str:
    platform = as_dict(spec.get("platform"))
    ec = as_dict(spec.get("enterprise_console"))
    controller = as_dict(spec.get("controller"))
    platform_name = platform.get("name", "prod-platform")
    install_dir = platform.get("installation_dir", "/opt/appdynamics/platform")
    bin_dir = ec.get("bin_dir", "/opt/appdynamics/enterpriseconsole/platform-admin/bin")
    credential = ec.get("credential_name", "EC-appd")
    remote_user = ec.get("remote_user", "appduser")
    ssh_key_file = ec.get("ssh_key_file", "/secure/appdynamics/ec-id_rsa.pem")
    controller_host = controller.get("primary_host", "controller-1.example.com")
    controller_profile = platform.get("controller_profile", "medium")
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Reviewed Enterprise Console 26.4 command plan.
# Requires --accept-enterprise-console-mutation before this skill enters apply mode.
# This script never passes Controller, MySQL, or Enterprise Console passwords as shell arguments.
# Authenticate to the Enterprise Console CLI in an approved interactive/session wrapper first.

PLATFORM_ADMIN="${{APPD_PLATFORM_ADMIN:-{bin_dir.rstrip('/')}/platform-admin.sh}}"
PLATFORM_NAME={shell_quote(platform_name)}
PLATFORM_INSTALL_DIR={shell_quote(install_dir)}
CREDENTIAL_NAME={shell_quote(credential)}
REMOTE_USER={shell_quote(remote_user)}
SSH_KEY_FILE={shell_quote(ssh_key_file)}
HOST_FILE="${{APPD_EC_HOST_FILE:-$(dirname "$0")/enterprise-console-hosts.txt}}"
CONTROLLER_PRIMARY_HOST={shell_quote(controller_host)}
CONTROLLER_PROFILE={shell_quote(controller_profile)}

echo "Checking Enterprise Console CLI and available jobs"
"${{PLATFORM_ADMIN}}" -h
"${{PLATFORM_ADMIN}}" show-platform-admin-version
"${{PLATFORM_ADMIN}}" list-jobs --service controller
"${{PLATFORM_ADMIN}}" list-jobs --service events-service || true

echo "Rendering platform bootstrap commands"
"${{PLATFORM_ADMIN}}" create-platform --name "${{PLATFORM_NAME}}" --installation-dir "${{PLATFORM_INSTALL_DIR}}"
"${{PLATFORM_ADMIN}}" add-credential --credential-name "${{CREDENTIAL_NAME}}" --type ssh --user-name "${{REMOTE_USER}}" --ssh-key-file "${{SSH_KEY_FILE}}"
"${{PLATFORM_ADMIN}}" add-hosts --host-file "${{HOST_FILE}}" --credential "${{CREDENTIAL_NAME}}"

echo "Inspect job parameters before Controller install because password arguments are intentionally omitted"
"${{PLATFORM_ADMIN}}" list-job-parameters --service controller --job install
echo "Controller install requires a local approved credential wrapper for controllerAdminPassword, controllerRootUserPassword, mysqlRootPassword, and newDatabaseUserPassword."
echo "Expected non-secret args: controllerPrimaryHost=${{CONTROLLER_PRIMARY_HOST}} controllerProfile=${{CONTROLLER_PROFILE}}"

echo "Controller diagnosis command"
"${{PLATFORM_ADMIN}}" submit-job --platform-name "${{PLATFORM_NAME}}" --service controller --job diagnosis

echo "Version discovery after install or upgrade"
"${{PLATFORM_ADMIN}}" get-available-versions --platform-name "${{PLATFORM_NAME}}" --service controller
"${{PLATFORM_ADMIN}}" get-available-versions --platform-name "${{PLATFORM_NAME}}" --service events-service || true
"""


def render_classic_onprem_deployment_runbook(spec: dict[str, Any]) -> str:
    platform = as_dict(spec.get("platform"))
    deployment = as_dict(spec.get("deployment"))
    selected = [method_by_id(method_id) for method_id in selected_platform_method_ids(spec)]
    selected = [method for method in selected if method.get("family") == "classic_on_premises"]
    selected_lines = "\n".join(
        f"- `{method['id']}`: {method['frictionless_next_step']}"
        for method in selected
    ) or "- No classic on-premises method selected; see `virtual-appliance-deployment-runbook.md`."
    return f"""# Classic On-Premises Deployment Runbook

## Current Selection

- Install mode: `{platform.get('install_mode', deployment.get('install_mode', 'custom'))}`
- Operator interface: `{deployment.get('operator_interface', platform.get('operator_interface', 'cli'))}`
- OS family: `{platform.get('os_family', 'linux')}`
- Platform installation directory: `{platform.get('installation_dir', '/opt/appdynamics/platform')}`

## Recommended Path

{selected_lines}

## Supported Classic Paths

- Express GUI: fastest first-run path for a single-host Controller and embedded Events Service.
- Custom GUI: production path for distributed hosts, HA Controller, and scaled Events Service.
- Enterprise Console CLI: reviewed repeatable path for Linux operators; this skill renders command plans but omits direct password arguments.
- Discover and Upgrade GUI or CLI: onboarding path for existing Controllers and Events Service instances.
- AWS Aurora Controller upgrade or move: CLI-only branch when the existing Controller database is Aurora.

## Frictionless Intake

Ask only these fields first: deployment model, install mode, operator interface, target version, Controller profile, Enterprise Console host, Controller primary host, and whether Events/EUM/Synthetic are in scope. Defer advanced ports, HA, certificates, and component-specific fields until the selected path requires them.

## Guardrails

- Enterprise Console is required for Controller and Events Service lifecycle.
- For Windows Controller targets, Enterprise Console must run on the same Windows machine because remote Windows operations are not supported through Enterprise Console.
- Use PEM-format SSH keys for Enterprise Console remote host credentials.
- Keep Controller, MySQL, Enterprise Console, and Events credentials file-backed; the renderer does not put password values in shell arguments.
"""


def render_controller_install_upgrade_runbook(spec: dict[str, Any]) -> str:
    platform = as_dict(spec.get("platform"))
    controller = as_dict(spec.get("controller"))
    events = as_dict(spec.get("events_service"))
    doc_version = spec.get("doc_version", "26.4.0")
    return f"""# Controller Install And Upgrade Runbook

Documentation baseline: AppDynamics On-Premises {doc_version}.

## Install Inputs

- Platform: `{platform.get('name', 'prod-platform')}`
- Controller primary host: `{controller.get('primary_host', 'controller-1.example.com')}`
- Controller secondary host: `{controller.get('secondary_host', 'not configured')}`
- Controller profile: `{platform.get('controller_profile', 'medium')}`
- Controller URL: `{spec.get('controller_url', 'https://controller.example.com:8090')}`
- Backup location: `{controller.get('backup_location', as_dict(spec.get('ha')).get('backup_location', 'not configured'))}`

## Required File-Backed Secrets

- Controller admin password file: `{controller.get('admin_password_file', 'missing')}`
- Controller root password file: `{controller.get('root_password_file', 'missing')}`
- MySQL root password file: `{controller.get('mysql_root_password_file', 'missing')}`
- Controller database user password file: `{controller.get('database_user_password_file', 'missing')}`

## Operator Steps

1. Verify Enterprise Console is installed and `platform-admin.sh show-platform-admin-version` reports the expected {doc_version} family.
2. Review `enterprise-console-hosts.txt`; every Controller and Events Service host must be reachable from the Enterprise Console host.
3. Run `enterprise-console-command-plan.sh` only after an authenticated Enterprise Console CLI session exists.
4. Use `list-job-parameters --service controller --job install` before constructing the local install command.
5. Construct the Controller install job outside this rendered tree because the 26.4 CLI requires password arguments for Controller install.
6. After install, run `platform-validation-probes.sh`; then verify Controller startup, Controller login, and database health.

## Upgrade Guardrails

- Back up the Controller before any upgrade.
- Confirm the current and target Enterprise Console and Controller versions.
- For HA, validate secondary license readiness and HA replication before starting.
- Events Service enabled: `{bool(events.get('enabled', False))}`. Validate Events Service health before and after Controller upgrades.
- Recheck retained Controller configuration changes after upgrade.
"""


def render_component_deployment_runbook(spec: dict[str, Any]) -> str:
    events = as_dict(spec.get("events_service"))
    eum = as_dict(spec.get("eum_server"))
    synthetic = as_dict(spec.get("synthetic_server"))
    selected = [method_by_id(method_id) for method_id in selected_platform_method_ids(spec)]
    selected = [method for method in selected if method.get("family") == "classic_component"]
    selected_lines = "\n".join(
        f"- `{method['id']}`: {method['frictionless_next_step']}"
        for method in selected
    ) or "- No classic component installers selected in the current spec."
    return f"""# Component Deployment Runbook

## Current Selection

- Events Service enabled: `{bool(events.get('enabled', False))}`
- Events Service nodes: `{len(as_list(events.get('nodes')))}`
- Events Service OS family: `{events.get('os_family', 'linux')}`
- EUM Server enabled: `{bool(eum.get('enabled', False))}`
- EUM mode: `{eum.get('mode', 'production')}`
- EUM reverse proxy: `{bool(eum.get('reverse_proxy', False))}`
- Synthetic Server enabled: `{bool(synthetic.get('enabled', False))}`

## Recommended Component Paths

{selected_lines}

## Events Service

- Linux: Enterprise Console supports GUI or CLI install, embedded-to-scaled conversion, and 1-node or 3+ node deployments.
- Windows: use a manual Events Service runbook. Enterprise Console does not support remote Windows operations, so do not render a remote-install flow.
- Clustered Events Service should use internal DNS/IPs, a load balancer VIP, open node ports, and host tuning before install.

## EUM Server

- EUM Server is not installed by Enterprise Console.
- Supported installer modes are GUI, console, and silent mode with a varfile.
- Demo mode shares the Controller host and MySQL; production mode uses a separate host and its own MySQL instance.
- Production should normally terminate HTTPS at a reverse proxy.

## Synthetic Server

- Gate Synthetic work behind Controller, Events Service, and EUM readiness.
- Validate Synthetic Server to EUM and Controller connectivity before adding Synthetic Agents.
- Keep Synthetic endpoint, certificate, and agent rollout checks in a separate maintenance step.
"""


def render_platform_ha_backup_runbook(spec: dict[str, Any]) -> str:
    ha = as_dict(spec.get("ha"))
    controller = as_dict(spec.get("controller"))
    return f"""# Platform HA Backup Restore Runbook

## HA Inputs

- HA enabled: `{bool(ha.get('enabled', False))}`
- Controller primary: `{controller.get('primary_host', 'controller-1.example.com')}`
- Controller secondary: `{controller.get('secondary_host', 'not configured')}`
- Load balancer VIP: `{ha.get('load_balancer_vip', 'not configured')}`
- Replication port: `{ha.get('replication_port', 'not configured')}`
- Maximum planned IO latency: `{ha.get('io_latency_ms_max', 'not configured')}` ms
- Secondary license ready: `{bool(ha.get('secondary_license_ready', False))}`
- Backup location: `{ha.get('backup_location', controller.get('backup_location', 'not configured'))}`

## Checks

- Confirm the primary and secondary hosts meet the HA prerequisites before pairing.
- Confirm backup artifacts exist and are restorable before upgrade or failover.
- Confirm the load balancer health check targets the active Controller only.
- Confirm failover, rollback, and DNS/LB ownership are assigned to named operators.
- Restore and HA cutover steps remain operator-run runbooks; this skill does not automate failover.
"""


def render_platform_security_checklist(spec: dict[str, Any]) -> str:
    security = as_dict(spec.get("security"))
    controller = as_dict(spec.get("controller"))
    return f"""# Platform Security Checklist

- TLS profile: `{security.get('tls_profile', 'enterprise')}`
- Controller CA certificate file: `{security.get('controller_ca_cert_file', 'missing')}`
- Controller certificate file: `{security.get('controller_cert_file', 'missing')}`
- Controller key file: `{security.get('controller_key_file', 'missing')}`
- Reverse proxy TLS: `{bool(security.get('reverse_proxy_tls', False))}`
- Disable untrusted HTTP: `{bool(security.get('disable_untrusted_http', False))}`
- HSTS enabled: `{bool(security.get('hsts_enabled', False))}`
- Controller HTTPS port: `{controller.get('https_port', 'not configured')}`

## Required Review

- Certificate files must be chmod 600 or otherwise restricted to the AppDynamics runtime owner.
- Controller admin, root, database, and Enterprise Console passwords must stay in file-backed secret stores.
- Confirm LDAP/SAML and Controller admin hardening with `splunk-appdynamics-controller-admin-setup`.
- Re-run `platform-validation-probes.sh` after TLS, proxy, or secure setting changes.
"""


def render_virtual_appliance_deployment_runbook(spec: dict[str, Any]) -> str:
    va = as_dict(spec.get("virtual_appliance"))
    platform = as_dict(spec.get("platform"))
    selected = [method_by_id(method_id) for method_id in selected_platform_method_ids(spec)]
    selected = [method for method in selected if str(method.get("family", "")).startswith("virtual_appliance")]
    selected_lines = "\n".join(
        f"- `{method['id']}`: {method['frictionless_next_step']}"
        for method in selected
    ) or "- No Virtual Appliance method selected; see `classic-onprem-deployment-runbook.md`."
    profile = va.get("profile", platform.get("controller_profile", "small"))
    return f"""# Virtual Appliance Deployment Runbook

## Current Selection

- Infrastructure platform: `{va.get('infrastructure_platform', 'vmware_vsphere')}`
- Service deployment: `{va.get('service_deployment', 'standard')}`
- Profile: `{profile}`
- Node count: `{va.get('node_count', 3)}`
- Image file: `{va.get('image_file', 'download from Virtual Appliance tab')}`
- DNS domain: `{va.get('dns_domain', 'not configured')}`

## Recommended Path

{selected_lines}

## Infrastructure Targets

- VMware vSphere: deploy three VMs from OVA/OVF, set OVF properties, enable VMware Tools, then run `appdctl show boot` on every node.
- VMware ESXi: deploy three VMs from the OVA, configure datastore/network/host fields, then verify boot status.
- Azure: use the VHD image, create or reuse resource group, NSG, VNet, storage, disk, image gallery, image version, then create three VMs.
- AWS: use the AMI import path, VPC, S3 image bucket, IAM import role, snapshot/register steps, then create three m5a.4xlarge instances unless sizing guidance changes.
- KVM: use QCOW2 and reference scripts; preflight NTP, `/dev/kvm`, bridge, storage pool, and config.cfg.
- ROSA: use ROSA HCP with OpenShift Virtualization, upload QCOW2 to PVCs with `virtctl`, create three RHEL-template VMs, and configure firewall/NLB.

## Service Deployment

- Standard: install infrastructure and Splunk AppDynamics services in the appliance Kubernetes cluster.
- Hybrid: connect to existing classic Controller, Events Service, and EUM components, then install add-on services in the appliance cluster.
- Match `appdcli start <service> <profile>` to the VM profile selected during infrastructure deployment.
- Validate with `appdctl show boot`, `appdctl show cluster`, `microk8s status`, `appdcli ping`, and `kubectl get pods -A`.

## Frictionless Intake

For Virtual Appliance, ask for platform, standard vs hybrid, profile, DNS domain, three node IPs, gateway, DNS server, image format/file, certificate preference, and license file readiness. Only ask cloud-specific fields after the user chooses Azure, AWS, KVM, vSphere, ESXi, or ROSA.
"""


def render_platform_validation_probes(spec: dict[str, Any]) -> str:
    controller = as_dict(spec.get("controller"))
    events = as_dict(spec.get("events_service"))
    eum = as_dict(spec.get("eum_server"))
    synthetic = as_dict(spec.get("synthetic_server"))
    ec = as_dict(spec.get("enterprise_console"))
    platform = as_dict(spec.get("platform"))
    controller_url = spec.get("controller_url", "https://controller.example.com:8090")
    events_url = events.get("vip_url", "")
    return f"""#!/usr/bin/env bash
set -euo pipefail

{render_appd_curl_helper()}

LIVE="${{APPD_PLATFORM_LIVE:-0}}"
PLATFORM_ADMIN="${{APPD_PLATFORM_ADMIN:-{ec.get('bin_dir', '/opt/appdynamics/enterpriseconsole/platform-admin/bin').rstrip('/')}/platform-admin.sh}}"
CONTROLLER_URL={shell_quote(controller_url)}
CONTROLLER_PRIMARY={shell_quote(controller.get('primary_host', 'controller-1.example.com'))}
PLATFORM_NAME={shell_quote(platform.get('name', 'prod-platform'))}
EVENTS_URL={shell_quote(events_url)}
EUM_HOST={shell_quote(eum.get('host', ''))}
SYNTHETIC_HOST={shell_quote(synthetic.get('host', ''))}

test -f "${{PLATFORM_ADMIN}}" || echo "WARN: platform-admin.sh not found at ${{PLATFORM_ADMIN}}"
test -n "${{CONTROLLER_PRIMARY}}" || {{ echo "FAIL: controller primary host missing"; exit 1; }}
test -n "${{PLATFORM_NAME}}" || {{ echo "FAIL: platform name missing"; exit 1; }}

if [[ "${{LIVE}}" != "1" ]]; then
  echo "Static validation complete. Set APPD_PLATFORM_LIVE=1 to run network probes."
  exit 0
fi

appd_curl --fail --silent --show-error --max-time 10 "${{CONTROLLER_URL}}/" >/dev/null
"${{PLATFORM_ADMIN}}" show-platform-admin-version
"${{PLATFORM_ADMIN}}" get-available-versions --platform-name "${{PLATFORM_NAME}}" --service controller
if [[ -n "${{EVENTS_URL}}" ]]; then
  appd_curl --fail --silent --show-error --max-time 10 "${{EVENTS_URL}}/" >/dev/null || echo "WARN: Events Service URL probe failed"
fi
if [[ -n "${{EUM_HOST}}" ]]; then
  echo "Probe EUM host reachability: ${{EUM_HOST}}"
fi
if [[ -n "${{SYNTHETIC_HOST}}" ]]; then
  echo "Probe Synthetic host reachability: ${{SYNTHETIC_HOST}}"
fi
"""


def render_platform_artifacts(out: Path, spec: dict[str, Any]) -> None:
    write(out / "platform-topology-inventory.yaml", render_platform_topology(spec))
    write(out / "deployment-method-selector.yaml", render_deployment_method_selector(spec))
    write(out / "deployment-method-matrix.md", render_deployment_method_matrix(spec))
    hosts = sorted({record["host"] for record in host_records_from_platform_spec(spec)})
    write(out / "enterprise-console-hosts.txt", "\n".join(hosts) + ("\n" if hosts else ""))
    write(out / "enterprise-console-command-plan.sh", render_enterprise_console_command_plan(spec))
    os.chmod(out / "enterprise-console-command-plan.sh", stat.S_IMODE((out / "enterprise-console-command-plan.sh").stat().st_mode) | stat.S_IXUSR)
    write(out / "classic-onprem-deployment-runbook.md", render_classic_onprem_deployment_runbook(spec))
    write(out / "controller-install-upgrade-runbook.md", render_controller_install_upgrade_runbook(spec))
    write(out / "component-deployment-runbook.md", render_component_deployment_runbook(spec))
    write(out / "virtual-appliance-deployment-runbook.md", render_virtual_appliance_deployment_runbook(spec))
    write(out / "platform-ha-backup-runbook.md", render_platform_ha_backup_runbook(spec))
    write(out / "platform-security-checklist.md", render_platform_security_checklist(spec))
    write(out / "platform-validation-probes.sh", render_platform_validation_probes(spec))
    os.chmod(out / "platform-validation-probes.sh", stat.S_IMODE((out / "platform-validation-probes.sh").stat().st_mode) | stat.S_IXUSR)


REQUIRED_SKILL_ARTIFACTS = {
    "splunk-appdynamics-platform-setup": PLATFORM_REQUIRED_ARTIFACTS,
    "splunk-appdynamics-controller-admin-setup": {
        "api-client-oauth-payload.redacted.json",
        "controller-admin-api-plan.sh",
        "rbac-access-plan.json",
        "saml-ldap-runbook.md",
        "sensitive-data-controls-runbook.md",
        "licensing-validation-plan.sh",
    },
    "splunk-appdynamics-agent-management-setup": {
        "agent-management-decision-guide.md",
        "smart-agent-readiness.yaml",
        "smart-agent-config.ini.template",
        "smart-agent-inventory.yaml",
        "remote.yaml.template",
        "smart-agent-remote-command-plan.sh",
        "smartagentctl-lifecycle-plan.sh",
        "agent-management-ui-runbook.md",
        "deployment-groups-runbook.md",
        "auto-attach-and-discovery-runbook.md",
        "smart-agent-cli-deprecation-runbook.md",
        "appdynamics-download-verification-runbook.md",
        "smart-agent-validation-probes.sh",
    },
    "splunk-appdynamics-apm-setup": {
        "apm-application-model.json",
        "apm-controller-api-plan.sh",
        "app-server-agent-snippets.md",
        "serverless-development-monitoring-runbook.md",
        "opentelemetry-apm-runbook.md",
        "apm-validation-probes.sh",
    },
    "splunk-appdynamics-k8s-cluster-agent-setup": {
        "cluster-agent-values.yaml",
        "splunk-otel-collector-values.yaml",
        "splunk-otel-secret-template.yaml",
        "workload-instrumentation-patches.yaml",
        "dual-signal-workload-env.yaml",
        "combined-agent-o11y-runbook.md",
        "cluster-agent-rollout-plan.sh",
        "cluster-agent-rbac-review.md",
        "cluster-agent-validation-probes.sh",
        "o11y-export-validation.sh",
    },
    "splunk-appdynamics-infrastructure-visibility-setup": {
        "machine-agent-command-plan.sh",
        "infrastructure-health-rules.json",
        "server-tags-payload.json",
        "network-visibility-runbook.md",
        "gpu-monitoring-runbook.md",
        "prometheus-extension-runbook.md",
        "infrastructure-validation-probes.sh",
    },
    "splunk-appdynamics-database-visibility-setup": {
        "database-collector-payloads.redacted.json",
        "database-agent-command-plan.sh",
        "database-validation-probes.sh",
    },
    "splunk-appdynamics-analytics-setup": {
        "analytics-events-headers.redacted.json",
        "analytics-publish-plan.sh",
        "analytics-schema-plan.json",
        "business-journeys-xlm-runbook.md",
        "analytics-adql-validation.sh",
    },
    "splunk-appdynamics-eum-setup": {
        "eum-app-key-inventory.json",
        "browser-rum-snippet.html",
        "mobile-sdk-snippets.md",
        "session-replay-config.js",
        "mobile-session-replay-runbook.md",
        "source-map-upload-plan.sh",
        "eum-validation-probes.sh",
    },
    "splunk-appdynamics-synthetic-monitoring-setup": {
        "browser-synthetic-jobs.json",
        "synthetic-api-monitor.json",
        "private-synthetic-agent-values.yaml",
        "private-synthetic-agent-docker-compose.yaml",
        "synthetic-validation-probes.sh",
    },
    "splunk-appdynamics-log-observer-connect-setup": {
        "splunk-platform-handoff.sh",
        "loc-readiness-plan.json",
        "legacy-splunk-integration-runbook.md",
        "loc-deeplink-validation.sh",
    },
    "splunk-appdynamics-alerting-content-setup": {
        "alerting-content-payloads.json",
        "alerting-export-rollback-plan.sh",
        "anomaly-detection-rca-runbook.md",
        "aiml-baseline-diagnostics-runbook.md",
        "alerting-validation-probes.sh",
    },
    "splunk-appdynamics-dashboards-reports-setup": {
        "dashboard-payloads.json",
        "dashboard-report-runbook.md",
        "dashboard-validation-probes.sh",
        "thousandeyes-dashboard-integration-runbook.md",
        "war-room-runbook.md",
    },
    "splunk-appdynamics-tags-extensions-setup": {
        "custom-tags-payload.json",
        "extensions-runbook.md",
        "custom-metrics-example.sh",
        "integrations-handoff.md",
    },
    "splunk-appdynamics-security-ai-setup": {
        "security-ai-readiness.yaml",
        "secure-application-validation.sh",
        "secure-application-policy-runbook.md",
        "otel-secure-application-snippet.md",
        "observability-ai-handoffs.md",
    },
    "splunk-appdynamics-sap-agent-setup": {
        "sap-agent-runbook.md",
        "sap-authorization-checklist.md",
        "sap-validation-probes.sh",
    },
}


def chmod_exec(path: Path) -> None:
    os.chmod(path, stat.S_IMODE(path.stat().st_mode) | stat.S_IXUSR)


def render_controller_admin_artifacts(out: Path, spec: dict[str, Any]) -> None:
    account = spec.get("account_name", "customer1")
    client = as_dict(spec.get("api_client"))
    write_json(
        out / "api-client-oauth-payload.redacted.json",
        {
            "client_name": client.get("name", "automation-client"),
            "client_secret_file": client.get("client_secret_file", "/secure/appd/client_secret"),
            "oauth_token_endpoint": "/auth/v1/oauth/token",
            "client_id_format": "{api_client_name}@{account_name}",
            "account_name": account,
            "client_secret": "<redacted:file-backed>",
        },
    )
    write_json(
        out / "rbac-access-plan.json",
        {
            "users": as_dict(spec.get("rbac")).get("users", []),
            "groups": as_dict(spec.get("rbac")).get("groups", []),
            "roles": as_dict(spec.get("rbac")).get("roles", []),
            "account_permissions": as_dict(spec.get("rbac")).get("account_permissions", []),
        },
    )
    plan = out / "controller-admin-api-plan.sh"
    write(
        plan,
        f"""#!/usr/bin/env bash
set -euo pipefail

{render_appd_curl_helper()}

: "${{APPD_CONTROLLER_URL:={spec.get('controller_url', 'https://example.saas.appdynamics.com')}}}"
: "${{APPD_ACCOUNT_NAME:={account}}}"
: "${{APPD_OAUTH_TOKEN_FILE:?set APPD_OAUTH_TOKEN_FILE}}"
AUTH_HEADER="Authorization: Bearer $(<"${{APPD_OAUTH_TOKEN_FILE}}")"
appd_curl --fail --silent --show-error -H "${{AUTH_HEADER}}" "${{APPD_CONTROLLER_URL}}/controller/api/rbac/v1/users" >/dev/null
appd_curl --fail --silent --show-error -H "${{AUTH_HEADER}}" "${{APPD_CONTROLLER_URL}}/controller/api/rbac/v1/groups" >/dev/null
appd_curl --fail --silent --show-error -H "${{AUTH_HEADER}}" "${{APPD_CONTROLLER_URL}}/controller/api/rbac/v1/roles" >/dev/null
""",
    )
    chmod_exec(plan)
    write(out / "saml-ldap-runbook.md", "# SAML LDAP Runbook\n\n- Validate IdP metadata, group mappings, and role assignment.\n- IdP changes stay outside this skill.\n- Re-run RBAC readbacks after SAML or LDAP changes.\n")
    write(
        out / "sensitive-data-controls-runbook.md",
        "# Sensitive Data Controls Runbook\n\n"
        "- Review Prevent Sensitive Data Collection controls for SaaS and on-premises deployments.\n"
        "- Validate role-based access control, raw SQL suppression, query literal hiding, error-log exclusions, Log Analytics masking, environment-variable filters, and Data Collector disablement.\n"
        "- Validate the Data Privacy Policy dialog and Data Collection Dashboard after any Controller, agent, analytics, or database monitoring change.\n"
        "- Runtime agent, database, and analytics-side edits delegate to the owning child skills.\n",
    )
    licensing = out / "licensing-validation-plan.sh"
    write(licensing, "#!/usr/bin/env bash\nset -euo pipefail\n: \"${APPD_CONTROLLER_URL:?set APPD_CONTROLLER_URL}\"\necho 'Validate license usage, subscriptions, and license rules through documented Controller/account APIs.'\n")
    chmod_exec(licensing)


SMART_AGENT_SUPPORTED_AGENTS: list[dict[str, Any]] = [
    {
        "name": "Apache Web Server",
        "key": "apache",
        "smartagentctl_type": None,
        "platforms": ["CentOS 8/9", "RHEL 8/9", "Ubuntu 20.04/22.04"],
        "service_user": "root",
        "interface": "Agent Management UI or deployment group",
    },
    {
        "name": "Database Agent",
        "key": "db",
        "smartagentctl_type": "db",
        "platforms": ["CentOS 8/9", "RHEL 8/9", "Ubuntu 20.04/22.04", "Windows with version gates"],
        "service_user": "anyUser",
        "interface": "Agent Management UI or smartagentctl",
    },
    {
        "name": "Java Agent",
        "key": "java",
        "smartagentctl_type": "java",
        "platforms": ["CentOS 8/9", "RHEL 8/9", "Ubuntu 20.04/22.04", "Windows 2016/2019/2022"],
        "service_user": "anyUser",
        "interface": "Agent Management UI, deployment group, smartagentctl, or auto-attach",
    },
    {
        "name": "Machine Agent",
        "key": "machine",
        "smartagentctl_type": "machine",
        "platforms": ["CentOS 8/9", "RHEL 8/9", "Ubuntu 20.04/22.04", "Windows 2016/2019/2022"],
        "service_user": "root",
        "interface": "Agent Management UI or smartagentctl",
    },
    {
        "name": "Node.js Agent",
        "key": "node",
        "smartagentctl_type": "node",
        "platforms": ["RHEL 8/9", "Ubuntu 20.04/22.04", "Debian 10/11/12"],
        "service_user": "anyUser",
        "interface": "Agent Management UI, deployment group, smartagentctl, or auto-attach",
    },
    {
        "name": "PHP Agent",
        "key": "php",
        "smartagentctl_type": None,
        "platforms": ["Ubuntu 20.04/22.04"],
        "service_user": "root",
        "interface": "Agent Management UI or deployment group",
    },
    {
        "name": "Python Agent",
        "key": "python",
        "smartagentctl_type": None,
        "platforms": ["CentOS 8/9", "Ubuntu 20.04/22.04", "Alpine"],
        "service_user": "root",
        "interface": "Agent Management UI, deployment group, or process discovery routing",
    },
    {
        "name": ".NET MSI Agent",
        "key": "dotnet_msi",
        "smartagentctl_type": "dotnet_msi",
        "platforms": ["Windows 2016/2019/2022"],
        "service_user": "Administrator",
        "interface": "Agent Management UI or smartagentctl",
    },
]


SMARTAGENTCTL_TYPE_ALIASES = {
    "dotnet": "dotnet_msi",
    ".net": "dotnet_msi",
    ".net msi": "dotnet_msi",
    "database": "db",
    "nodejs": "node",
    "node.js": "node",
}


def normalize_agent_type(value: Any) -> str:
    lowered = str(value).strip().lower().replace("-", "_")
    return SMARTAGENTCTL_TYPE_ALIASES.get(lowered, lowered)


def agent_targets(spec: dict[str, Any]) -> list[dict[str, Any]]:
    targets = as_list(spec.get("targets")) or [{"host": "app01.example.com", "os_family": "linux", "agent_types": ["java", "machine"], "install_dir": "/opt/appdynamics"}]
    normalized: list[dict[str, Any]] = []
    for index, target in enumerate(targets, start=1):
        target_dict = as_dict(target)
        agent_types = [normalize_agent_type(item) for item in as_list(target_dict.get("agent_types")) or ["java", "machine"]]
        normalized.append(
            {
                "host": target_dict.get("host", f"app{index:02d}.example.com"),
                "os_family": str(target_dict.get("os_family", "linux")).lower(),
                "agent_types": agent_types,
                "install_dir": target_dict.get("install_dir", "/opt/appdynamics"),
                "remote_dir": target_dict.get("remote_dir"),
                "smart_agent_id": target_dict.get("smart_agent_id"),
            }
        )
    return normalized


def render_agent_management_decision_guide(spec: dict[str, Any]) -> str:
    smart_agent = as_dict(spec.get("smart_agent"))
    remote = as_dict(smart_agent.get("remote"))
    deployment_groups = as_dict(spec.get("deployment_groups"))
    auto_attach = as_dict(spec.get("auto_attach"))
    auto_discovery = as_dict(spec.get("auto_discovery"))
    return f"""# Agent Management Decision Guide

Use this first. It keeps intake to the smallest set of decisions needed to pick
the right Smart Agent workflow.

## Current Selection

- Controller: `{spec.get('controller_url', 'https://example.saas.appdynamics.com')}`
- Account: `{spec.get('account_name', 'customer1')}`
- Operator mode: `{spec.get('operator_mode', 'render')}`
- Package source: `{smart_agent.get('package_source', 'download_portal')}`
- Remote install enabled: `{bool(remote.get('enabled', smart_agent.get('remote_execution', False)))}`
- Remote execution accepted: `{bool(smart_agent.get('remote_execution', False))}`
- Deployment groups enabled: `{bool(deployment_groups.get('enabled', False))}`
- Auto-attach enabled: `{bool(auto_attach.get('enabled', smart_agent.get('enable_auto_attach', False)))}`
- Auto-discovery enabled: `{bool(auto_discovery.get('enabled', smart_agent.get('run_auto_discovery', True)))}`

## Pick The Path

1. Use the Agent Management UI when the user wants guided install, upgrade, or
   rollback and Smart Agent is already registered on the target hosts.
2. Use `smartagentctl` when the user needs repeatable reviewed commands, remote
   host operations, local-directory packages, custom HTTP sources, or service vs
   process control.
3. Use deployment groups when the user needs the same agent configuration across
   many Smart Agent hosts.
4. Use auto-attach only for Java and Node.js runtimes. Treat it as an app owner
   change because process restart and naming rules affect runtime behavior.
5. Use auto-discovery to find Java, .NET, Node.js, and Python processes before
   selecting an install action.
6. Use the deprecated standalone Smart Agent CLI only to maintain a legacy
   build-time workflow; new work should prefer Smart Agent UI or `smartagentctl`.

## Next Files

- `smart-agent-readiness.yaml`
- `smart-agent-config.ini.template`
- `remote.yaml.template`
- `agent-management-ui-runbook.md`
- `smartagentctl-lifecycle-plan.sh`
- `deployment-groups-runbook.md`
- `auto-attach-and-discovery-runbook.md`
"""


def render_smart_agent_readiness(spec: dict[str, Any]) -> str:
    smart_agent = as_dict(spec.get("smart_agent"))
    targets = agent_targets(spec)
    payload = {
        "doc_version": spec.get("doc_version", "26.4.0"),
        "controller": {
            "url": spec.get("controller_url", "https://example.saas.appdynamics.com"),
            "minimum_version": "24.7.0",
            "target_version": smart_agent.get("controller_version", spec.get("doc_version", "26.4.0")),
            "account_name": spec.get("account_name", "customer1"),
            "access_key_file": smart_agent.get("access_key_file", "/secure/appdynamics/account_access_key"),
        },
        "resource_requirements": {
            "memory_idle_mb": "10-15",
            "memory_install_upgrade_rollback_mb": 100,
            "disk_mb": 500,
        },
        "supported_smart_agent_platforms": [
            "CentOS Stream 8.x/9.x",
            "RedHat 8.x/9.x",
            "Ubuntu 20.04/22.04/23.10",
            "Windows",
        ],
        "permissions": {
            "service_install": "sudo/root/admin required",
            "process_mode": "non-root allowed when supported by the agent type",
            "service_user": smart_agent.get("run_user", "appdynamics"),
            "service_group": smart_agent.get("run_group", "appdynamics"),
        },
        "supported_agents": SMART_AGENT_SUPPORTED_AGENTS,
        "targets": targets,
        "validation": [
            "systemctl status smartagent.service on Linux or Appdsmartagent service in Windows Services",
            "Home > Agent Management > Manage Agents > Smart Agents registration",
            "Managed-agent inventory after install, upgrade, rollback, or deployment-group action",
        ],
    }
    return dump_yaml(payload)


def render_smart_agent_config_template(spec: dict[str, Any]) -> str:
    smart_agent = as_dict(spec.get("smart_agent"))
    config = as_dict(smart_agent.get("config"))
    auto_discovery = as_dict(spec.get("auto_discovery"))
    exclude_labels = ",".join(str(item) for item in as_list(auto_discovery.get("exclude_labels")) or ["process.cpu.usage", "process.memory.usage"])
    exclude_processes = ",".join(str(item) for item in as_list(auto_discovery.get("exclude_processes")))
    exclude_users = ",".join(str(item) for item in as_list(auto_discovery.get("exclude_users")))
    return f"""# Smart Agent config.ini template. Inject AccountAccessKey from APPD_ACCOUNT_ACCESS_KEY_FILE at deploy time.
ControllerURL    = {spec.get('controller_url', 'https://example.saas.appdynamics.com')}
ControllerPort   = {config.get('controller_port', 443)}
FMServicePort    = {config.get('fm_service_port', 443)}
AgentType        =
AccountAccessKey = <redacted:file-backed>
AccountName      = {spec.get('account_name', 'customer1')}
EnableSSL        = {str(config.get('enable_ssl', True)).lower()}

[Telemetry]
LogLevel  = {config.get('log_level', 'info')}
LogFile   = {config.get('log_file', 'log.log')}

[CommonConfig]
PollingIntervalInSec  = {config.get('polling_interval_seconds', 300)}
ScanningIntervalInSec = {config.get('scanning_interval_seconds', 300)}

[Storage]
Directory = {config.get('storage_dir', smart_agent.get('install_dir', '/opt/appdynamics/appdsmartagent') + '/storage')}

[TLSClientSetting]
Insecure           = {str(config.get('insecure', False)).lower()}
InsecureSkipVerify = {str(config.get('insecure_skip_verify', False)).lower()}
AgentHTTPProxy     = {config.get('agent_http_proxy', '')}
AgentHTTPSProxy    = {config.get('agent_https_proxy', '')}
AgentNoProxy       = {config.get('agent_no_proxy', '')}

[TLSSetting]
CAFile     = {config.get('ca_file', '')}
CAPem      =
CertFile   = {config.get('cert_file', '')}
CertPem    =
KeyFile    = {config.get('key_file', '')}
KeyPem     =
MinVersion = {config.get('tls_min_version', 'TLS 1.2')}
MaxVersion = {config.get('tls_max_version', 'TLS 1.3')}
IncludeSystemCACertsPool = {str(config.get('include_system_ca_certs_pool', True)).lower()}

[AutoDiscovery]
RunAutoDiscovery = {str(auto_discovery.get('enabled', smart_agent.get('run_auto_discovery', True))).lower()}
ExcludeLabels = {exclude_labels}
ExcludeProcesses = {exclude_processes}
ExcludeUsers = {exclude_users}
AutoDiscoveryTimeInterval = {auto_discovery.get('interval', '4h')}
"""


def render_remote_yaml_template(spec: dict[str, Any]) -> str:
    smart_agent = as_dict(spec.get("smart_agent"))
    remote = as_dict(smart_agent.get("remote"))
    targets = agent_targets(spec)
    linux_hosts = [target for target in targets if target["os_family"] != "windows"]
    windows_hosts = [target for target in targets if target["os_family"] == "windows"]
    payload = {
        "max_concurrency": remote.get("max_concurrency", 5),
        "remote_dir": remote.get("remote_dir", smart_agent.get("install_dir", "/opt/appdynamics/appdsmartagent")),
        "protocol": {
            "type": "ssh",
            "auth": {
                "username": remote.get("ssh_user", "appdynamics"),
                "type": "private_key",
                "private_key_path": remote.get("ssh_private_key_file", "/secure/appdynamics/id_rsa"),
                "password_env_var": remote.get("ssh_password_env_var", "SSH_PASSWORD"),
                "privileged": bool(remote.get("privileged", False)),
                "known_hosts_path": remote.get("ssh_known_hosts_file", "/secure/appdynamics/known_hosts"),
            },
            "proxy": as_dict(remote.get("ssh_proxy")),
        },
        "hosts": [
            {
                "host": target["host"],
                "remote_dir": target.get("remote_dir") or remote.get("remote_dir", target.get("install_dir")),
            }
            for target in linux_hosts
        ],
        "windows_example": {
            "protocol": {
                "type": "winrm",
                "auth": {
                    "type": remote.get("winrm_auth", "certificate"),
                    "cert_path": remote.get("winrm_cert_file", "/secure/appdynamics/winrm-cert.pem"),
                    "key_path": remote.get("winrm_key_file", "/secure/appdynamics/winrm-key.pem"),
                },
            },
            "hosts": [
                {
                    "host": target["host"],
                    "remote_dir": target.get("remote_dir") or target.get("install_dir"),
                }
                for target in windows_hosts
            ],
        },
        "notes": [
            "Use password_env_var or file/certificate references; do not put password values in remote.yaml.",
            "For remote supported-agent install, the primary Smart Agent host must run on the same platform family as the remote host.",
            "SSH supports password auth and HTTP or SOCKS5 proxy routing when represented in the remote.yaml protocol block.",
        ],
    }
    return dump_yaml(payload)


def render_smart_agent_remote_command_plan(spec: dict[str, Any]) -> str:
    smart_agent = as_dict(spec.get("smart_agent"))
    remote = as_dict(smart_agent.get("remote"))
    targets = agent_targets(spec)
    install_dir = smart_agent.get("install_dir", "/opt/appdynamics/appdsmartagent")
    service_mode = str(smart_agent.get("service_mode", "service")).lower()
    user = smart_agent.get("run_user", "appdynamics")
    group = smart_agent.get("run_group", "appdynamics")
    auto_attach_flag = " --enable-auto-attach" if smart_agent.get("enable_auto_attach", False) else ""
    service_flag = " --service" if service_mode == "service" else ""
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Reviewed Smart Agent host command plan.",
        "# This script prints commands. It does not execute remote operations.",
        "# Requires --accept-remote-execution before this skill may execute host-scoped remote commands.",
        f"SMART_AGENT_DIR={shell_quote(install_dir)}",
        f"PACKAGE_SOURCE={shell_quote(smart_agent.get('package_source_url', smart_agent.get('package_source', 'reviewed-package-url')))}",
        'ACCOUNT_ACCESS_KEY_FILE="${APPD_ACCOUNT_ACCESS_KEY_FILE:-/secure/appdynamics/account_access_key}"',
        "",
        "cat <<'PLAN'",
        "1. Unzip the Smart Agent package into the approved Smart Agent directory.",
        "2. Render config.ini from smart-agent-config.ini.template and inject AccountAccessKey from APPD_ACCOUNT_ACCESS_KEY_FILE.",
        "3. Start Smart Agent locally before using Agent Management UI or smartagentctl remote operations.",
        "PLAN",
        "",
        f"printf '%s\\n' {shell_quote(f'cd {install_dir} && sudo ./smartagentctl start{auto_attach_flag}{service_flag} --user {user} --group {group}')}",
        "printf '%s\\n' 'systemctl status smartagent.service || true'",
        "",
    ]
    if remote.get("enabled", smart_agent.get("remote_execution", False)):
        lines.extend(
            [
                "cat <<'REMOTE_PLAN'",
                "Remote Smart Agent install requires remote.yaml.template review.",
                "Linux uses SSH; Windows uses WinRM. Proxy settings belong in remote.yaml, not in command arguments.",
                "REMOTE_PLAN",
                "printf '%s\\n' 'sudo ./smartagentctl start --remote'",
                "printf '%s\\n' 'sudo ./smartagentctl stop --remote # use before primary-to-remote sync restart'",
                "",
            ]
        )
    for target in targets:
        host = target["host"]
        agent_types = ",".join(target["agent_types"])
        lines.append(f"echo {shell_quote(f'Target {host}: plan Smart Agent lifecycle for agent types [{agent_types}]')}")
    return "\n".join(lines) + "\n"


def render_smartagentctl_lifecycle_plan(spec: dict[str, Any]) -> str:
    targets = agent_targets(spec)
    managed_agents = as_dict(spec.get("managed_agents"))
    download_validation = as_dict(spec.get("download_validation"))
    commands: list[str] = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Reviewed smartagentctl lifecycle plan.",
        "# Commands are echoed for operator review. Remote execution is gated separately.",
        "MODE=${APPD_AGENT_LIFECYCLE_MODE:-install} # install, upgrade, uninstall, rollback",
        "DOWNLOAD_PROTOCOL=${APPD_AGENT_DOWNLOAD_PROTOCOL:-portal} # portal, local, custom_http",
        "LOCAL_DOWNLOAD_DIR=${APPD_AGENT_LOCAL_DOWNLOAD_DIR:-$(pwd)}",
        "",
        "case \"${MODE}\" in install|upgrade|uninstall|rollback) ;; *) echo \"Unsupported mode: ${MODE}\" >&2; exit 2 ;; esac",
        "",
    ]
    for target in targets:
        remote_flag = " --remote" if as_dict(as_dict(spec.get("smart_agent")).get("remote")).get("enabled", False) else ""
        host = target["host"]
        for agent_type in target["agent_types"]:
            normalized = normalize_agent_type(agent_type)
            if normalized not in {"dotnet_msi", "db", "java", "machine", "node"}:
                message = f"{host} {normalized}: use Agent Management UI or deployment-group runbook; no direct smartagentctl type is assumed."
                commands.append(f"echo {shell_quote(message)}")
                continue
            agent_config = as_dict(managed_agents.get(normalized))
            option_notes = []
            if normalized == "machine" and agent_config.get("install_as_service", True):
                option_notes.append("--service")
            if normalized == "java" and agent_config.get("application_name"):
                option_notes.append(f"--application_name {agent_config['application_name']}")
            if normalized == "node" and agent_config.get("application_name"):
                option_notes.append(f"--application_name {agent_config['application_name']}")
            if normalized == "db" and agent_config.get("jvm_args"):
                option_notes.append("--jvm_args <reviewed-jvm-args>")
            options = " ".join(option_notes + ["<agent-specific-options>"])
            command_text = f"{host} {normalized}: sudo ./smartagentctl ${{MODE}} {normalized} {options}{remote_flag}"
            commands.append(f"echo {shell_quote(command_text)}")
    commands.extend(
        [
            "",
            "cat <<'GUARDRAILS'",
            "Upgrade sources: Splunk AppDynamics Download Portal, custom HTTP host, or local host directory.",
            "For local downloads, place the agent zip in the Smart Agent directory and use --download_protocol local with --download_uri.",
            "For UI rollback, rollback is available only after the agent has been upgraded through the UI at least once.",
            "For Database Agent rollback, JVM arguments from the rolled-back version are retained.",
            f"Download checksum required: {bool(download_validation.get('require_checksum', True))}",
            f"Signature verification required where published: {bool(download_validation.get('require_signature_if_published', True))}",
            "GUARDRAILS",
        ]
    )
    return "\n".join(commands) + "\n"


def render_agent_management_ui_runbook(spec: dict[str, Any]) -> str:
    targets = agent_targets(spec)
    target_lines = "\n".join(
        f"- `{target['host']}` ({target['os_family']}): {', '.join(target['agent_types'])}"
        for target in targets
    )
    return f"""# Agent Management UI Runbook

## Target Hosts

{target_lines}

## Smart Agent Inventory

1. Navigate to Home > Agent Management > Manage Agents.
2. Use the Smart Agents tab to confirm every target host is registered.
3. Select one or more Smart Agent hosts before clicking Install Agent when you
   want the install page to preselect those hosts.

## App Server And Machine Agent Install

1. Click Install Agent.
2. Select the agent type.
3. Choose Select from List for registered Smart Agent hosts or Import from CSV
   when host selection must be bulk-loaded.
4. Confirm the install directory, package source, and custom configuration.
5. For Machine Agent on SELinux, review the SELinux permissive-mode note before
   install.

## Upgrade

- Stop Machine Agent extension processes before upgrading Machine Agent.
- Keep enough free space: Java or Machine Agent upgrade paths may require temp
  and current directories sized relative to the agent zip.
- For older Smart Agent managed Java installs, place `java.zip` or
  `machine.zip` in the agent directory when the zip is not already present.

## Rollback

- UI rollback is available only after the agent has been upgraded through the
  UI at least once.
- Rollback returns only to the last used version.

## Database Agent

- Database Agent can be managed through UI only when Smart Agent is installed
  on the same machine.
- Database Agent high availability is not supported through Agent Management.
- Windows Database Agent management requires Controller 25.10.0, Database Agent
  25.9.0, and Smart Agent 25.10.0 or later.
- Database Agent rollback retains JVM arguments from the rolled-back version.
"""


def render_deployment_groups_runbook(spec: dict[str, Any]) -> str:
    deployment_groups = as_dict(spec.get("deployment_groups"))
    groups = as_list(deployment_groups.get("groups")) or [{"name": "default-agent-group", "agent_types": ["java", "machine"], "hosts": ["app01.example.com"], "auto_attach": True}]
    rows = [
        "| Group | Agents | Hosts | Auto-Attach |",
        "|---|---|---|---:|",
    ]
    for group in groups:
        group_dict = as_dict(group)
        rows.append(
            "| `{}` | {} | {} | {} |".format(
                group_dict.get("name", "default-agent-group"),
                ", ".join(str(item) for item in as_list(group_dict.get("agent_types"))),
                ", ".join(str(item) for item in as_list(group_dict.get("hosts"))),
                "yes" if group_dict.get("auto_attach", False) else "",
            )
        )
    return """# Deployment Groups Runbook

Deployment groups are the lowest-friction path for repeatable large-scale
agent rollout. They define deployment, configuration, and Java/Node.js
auto-attach from one location, then apply that configuration to selected Smart
Agent hosts.

{}

## Operations

- Create: define enabled agents, per-agent configuration, optional auto-attach,
  and the target Smart Agent hosts.
- Update hosts: change only the selected host set when configuration should
  stay stable.
- Edit: change agent versions, configuration, or auto-attach settings.
- Duplicate: create a staged variant before modifying production settings.
- Delete: remove only after confirming there are no hosts that still depend on
  the group template.
- View: use this as the validation path before and after rollout.

## Guardrails

- Keep one deployment group per coherent application/runtime pattern.
- Do not mix Windows-only .NET targets with Linux-only Apache/PHP/Python targets
  in the same group unless the UI explicitly supports the resulting host set.
- Use canary Smart Agent hosts before broad assignment.
""".format("\n".join(rows))


def render_auto_attach_and_discovery_runbook(spec: dict[str, Any]) -> str:
    auto_attach = as_dict(spec.get("auto_attach"))
    auto_discovery = as_dict(spec.get("auto_discovery"))
    java_path = auto_attach.get("java_agent_path", "/opt/appdynamics/java/javaagent.jar")
    node_path = auto_attach.get("node_agent_path", "/opt/appdynamics/node")
    return f"""# Auto-Attach And Auto-Discovery Runbook

## Auto-Attach

- Scope: Java and Node.js only.
- Java runtimes and frameworks: Tomcat, WebLogic, Spring Boot, JBoss,
  GlassFish, and plain Java applications.
- Node.js is supported for auto-attach on documented supported platforms.
- Default file: `<SmartAgent directory>/lib/ld_preload.json`.
- Java agent path: `{java_path}`.
- Node.js agent path: `{node_path}`.
- Use custom `ld_preload.json` filters when an app owner wants to exclude
  processes, bind a specific Java Agent path to a service, or generate
  application, tier, and node names from environment variables.

## Auto-Discovery

- Smart Agent 24.4 or later can report supported application processes.
- Discovered process coverage: Java on Windows/Linux, .NET on Windows, Node.js
  on Linux, and Python on Linux.
- RunAutoDiscovery: `{bool(auto_discovery.get('enabled', True))}`.
- Excluded labels: `{as_list(auto_discovery.get('exclude_labels')) or ['process.cpu.usage', 'process.memory.usage']}`.
- Excluded processes: `{as_list(auto_discovery.get('exclude_processes'))}`.
- Excluded users: `{as_list(auto_discovery.get('exclude_users'))}`.

## Validation

1. Confirm discovered processes appear in the Controller process inventory.
2. Confirm selected process routing maps to the intended agent type.
3. For auto-attach, restart only within an app owner approved window.
4. Confirm Controller node registration, naming, tier placement, and metrics.
"""


def render_smart_agent_cli_deprecation_runbook() -> str:
    return """# Deprecated Smart Agent CLI Runbook

The standalone Smart Agent CLI is deprecated in the 26.4 documentation and has
a documented end-of-support date of February 2, 2026. Treat it as legacy-only;
new work should use the Agent Management UI or `smartagentctl`.

Use this path only for legacy build-time workflows that already depend on the
standalone CLI.

## Compatibility Notes

- The deprecated CLI can manage remote or local nodes through a standalone
  service.
- It does not support Database Agent.
- Multiple-node Smart Agent install through this CLI requires Python 3.10 or
  later.
- Existing automation should be migrated toward `smartagentctl` command plans
  and `remote.yaml` templates.

## Legacy Examples

```bash
./appd install smartagent --install-agent-from ARTIFACT_PATH --inventory HOSTS --connection ssh --auto-start
appd configure smartagent --attach-configure-file PATH_TO_LD_PRELOAD_JSON
```
"""


def render_download_verification_runbook(spec: dict[str, Any]) -> str:
    download_validation = as_dict(spec.get("download_validation"))
    return f"""# AppDynamics Download Verification Runbook

## Scope

- Download portal packages are entitlement and permission dependent.
- Use filters by type, version, operating system, and Compatible With Controller
  for agent packages.
- Use cURL automation only with download-scoped OAuth and file-backed local
  handling. Do not place download passwords or tokens in specs, shell history,
  rendered artifacts, or chat.
- Validate digital signatures wherever Splunk AppDynamics publishes them for a
  package family.

## Required Checks

- Binary transfer mode: `{download_validation.get('transfer_mode', 'binary')}`.
- Require checksum: `{bool(download_validation.get('require_checksum', True))}`.
- Require signature where published: `{bool(download_validation.get('require_signature_if_published', True))}`.
- Require release note link: `{bool(download_validation.get('release_notes_required', True))}`.
- Require rollback package: `{bool(download_validation.get('rollback_package_required', True))}`.

## Validation

1. Record package name, version, operating system, compatible Controller version,
   source URL, and release-note link.
2. Compare MD5 and SHA256 checksums after download.
3. Verify digital signatures and code signatures for .NET Agent and Windows MSI packages where
   published.
4. Verify PGP signatures for Java Agent, Machine Agent, Machine Agent RPM, and
   Python Agent pip package where published.
5. Confirm rollback packages are available before upgrade.
"""


def render_agent_validation_probes(spec: dict[str, Any]) -> str:
    controller_url = spec.get("controller_url", "https://example.saas.appdynamics.com")
    targets = agent_targets(spec)
    target_checks = "\n".join(
        f"echo 'Check {target['host']} Smart Agent registration and managed agents: {', '.join(target['agent_types'])}'"
        for target in targets
    )
    return f"""#!/usr/bin/env bash
set -euo pipefail

{render_appd_curl_helper()}

LIVE="${{APPD_AGENT_MANAGEMENT_LIVE:-0}}"
CONTROLLER_URL={shell_quote(controller_url)}

echo "Static Smart Agent validation"
test -f smart-agent-readiness.yaml
test -f smart-agent-config.ini.template
test -f remote.yaml.template
test -f smartagentctl-lifecycle-plan.sh
{target_checks}

if [[ "${{LIVE}}" != "1" ]]; then
  echo "Set APPD_AGENT_MANAGEMENT_LIVE=1 to run host or Controller probes from an approved workstation."
  exit 0
fi

appd_curl --fail --silent --show-error --max-time 10 "${{CONTROLLER_URL}}/" >/dev/null
echo "Controller reachable. Continue with UI Smart Agents tab and managed-agent inventory readback."
"""


def render_agent_management_artifacts(out: Path, spec: dict[str, Any]) -> None:
    targets = agent_targets(spec)
    smart_agent = as_dict(spec.get("smart_agent"))
    write(out / "agent-management-decision-guide.md", render_agent_management_decision_guide(spec))
    write(out / "smart-agent-readiness.yaml", render_smart_agent_readiness(spec))
    write(out / "smart-agent-config.ini.template", render_smart_agent_config_template(spec))
    write(out / "smart-agent-inventory.yaml", dump_yaml({"targets": targets, "smart_agent": redact(smart_agent), "supported_agents": SMART_AGENT_SUPPORTED_AGENTS}))
    write(out / "remote.yaml.template", render_remote_yaml_template(spec))
    plan = out / "smart-agent-remote-command-plan.sh"
    write(plan, render_smart_agent_remote_command_plan(spec))
    chmod_exec(plan)
    lifecycle = out / "smartagentctl-lifecycle-plan.sh"
    write(lifecycle, render_smartagentctl_lifecycle_plan(spec))
    chmod_exec(lifecycle)
    write(out / "agent-management-ui-runbook.md", render_agent_management_ui_runbook(spec))
    write(out / "deployment-groups-runbook.md", render_deployment_groups_runbook(spec))
    write(out / "auto-attach-and-discovery-runbook.md", render_auto_attach_and_discovery_runbook(spec))
    write(out / "smart-agent-cli-deprecation-runbook.md", render_smart_agent_cli_deprecation_runbook())
    write(out / "appdynamics-download-verification-runbook.md", render_download_verification_runbook(spec))
    probes = out / "smart-agent-validation-probes.sh"
    write(probes, render_agent_validation_probes(spec))
    chmod_exec(probes)


def render_apm_artifacts(out: Path, spec: dict[str, Any]) -> None:
    applications = as_list(spec.get("applications")) or [{"name": "checkout", "tiers": ["web", "api", "worker"]}]
    write_json(out / "apm-application-model.json", {"applications": applications, "business_transactions": as_dict(spec.get("business_transactions")), "service_endpoints": as_dict(spec.get("service_endpoints"))})
    plan = out / "apm-controller-api-plan.sh"
    write(plan, "#!/usr/bin/env bash\nset -euo pipefail\n: \"${APPD_CONTROLLER_URL:?set APPD_CONTROLLER_URL}\"\necho 'Read back applications, tiers, nodes, business transactions, service endpoints, metrics, and snapshots.'\n")
    chmod_exec(plan)
    languages = as_dict(spec.get("agent_snippets")).get("languages", ["java", "dotnet", "nodejs", "python", "php"])
    write(out / "app-server-agent-snippets.md", "# App Server Agent Snippets\n\n" + "\n".join(f"- `{language}`: render startup/config snippet; runtime edits delegate to agent-management or k8s skills." for language in languages) + "\n")
    write(
        out / "serverless-development-monitoring-runbook.md",
        "# Serverless APM And Development Monitoring Runbook\n\n"
        "- Serverless APM for AWS Lambda requires subscription and tracer rollout review.\n"
        "- Validate serverless tiers/functions in flow maps, dashboards, metric browser, and health rules.\n"
        "- Development Level Monitoring increases retained call graph and SQL detail for selected originating node and business transaction combinations.\n"
        "- Review Controller limits before enabling development monitoring and validate that it automatically disables if thresholds are exceeded.\n",
    )
    write(
        out / "opentelemetry-apm-runbook.md",
        "# Splunk AppDynamics For OpenTelemetry Runbook\n\n"
        "- Confirm Splunk AppDynamics for OpenTelemetry entitlement and generate or retrieve the Controller OTel access key through the Controller UI.\n"
        "- Choose the Splunk AppDynamics Distribution for OpenTelemetry Collector, MSI collector, or upstream OpenTelemetry Collector, then render collector config with file-backed access-key references only.\n"
        "- Validate OTLP trace export, service/resource attribute mapping, backend language support, regional endpoint selection, and trace visibility in the Controller UI.\n"
        "- Deep collector deployment and tuning can hand off to the Splunk Observability OTel Collector skill when the same estate also exports to Splunk Observability Cloud.\n",
    )
    probes = out / "apm-validation-probes.sh"
    write(probes, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Validate APM model, snapshots, and metric hierarchy readbacks.'\n")
    chmod_exec(probes)


def to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def normalize_k8s_language(value: Any) -> str:
    lowered = str(value or "java").strip().lower().replace("_", "-")
    aliases = {
        ".net": "dotnet-core-linux",
        "dotnet": "dotnet-core-linux",
        "dotnet-core": "dotnet-core-linux",
        "dotnet-linux": "dotnet-core-linux",
        "node": "nodejs",
        "node.js": "nodejs",
        "machine": "machine-agent",
        "machineagent": "machine-agent",
    }
    return aliases.get(lowered, lowered)


def normalize_combined_mode(value: Any) -> str:
    lowered = str(value or "dual").strip().lower().replace("_", "-")
    aliases = {
        "dual-signal": "dual",
        "combined": "dual",
        "hybrid": "dual",
        "o11y-only": "otel",
        "splunk-only": "otel",
        "otel-only": "otel",
        "appd": "appd-only",
        "controller-only": "appd-only",
    }
    return aliases.get(lowered, lowered)


def k8s_workload_parts(workload: Any) -> tuple[str, str, str, str]:
    raw = str(workload or "deployment/checkout-api").strip()
    kind_part, name = raw.split("/", 1) if "/" in raw else ("deployment", raw)
    normalized = kind_part.strip().lower()
    kind_map = {
        "deploy": ("apps/v1", "Deployment", "deployment"),
        "deployment": ("apps/v1", "Deployment", "deployment"),
        "statefulset": ("apps/v1", "StatefulSet", "statefulset"),
        "sts": ("apps/v1", "StatefulSet", "statefulset"),
        "daemonset": ("apps/v1", "DaemonSet", "daemonset"),
        "ds": ("apps/v1", "DaemonSet", "daemonset"),
    }
    return kind_map.get(normalized, ("apps/v1", kind_part[:1].upper() + kind_part[1:], normalized)) + (name,)


def k8s_collector_config(spec: dict[str, Any]) -> dict[str, Any]:
    collector = as_dict(spec.get("splunk_otel_collector"))
    o11y = as_dict(spec.get("splunk_observability"))
    realm = collector.get("realm") or o11y.get("realm") or spec.get("realm") or "us1"
    environment = collector.get("environment") or o11y.get("environment") or spec.get("environment") or "prod"
    cluster_name = collector.get("cluster_name") or spec.get("cluster_name") or "appd-k8s-cluster"
    token_file = (
        collector.get("access_token_file")
        or o11y.get("access_token_file")
        or spec.get("splunk_o11y_token_file")
        or "/secure/splunk/o11y_access_token"
    )
    token_env = collector.get("access_token_env") or o11y.get("access_token_env") or "SPLUNK_O11Y_ACCESS_TOKEN"
    namespace = collector.get("namespace") or spec.get("namespace") or "appdynamics"
    secret_name = collector.get("secret_name") or "appd-splunk-otel-secret"
    endpoint = (
        collector.get("otlp_endpoint")
        or collector.get("endpoint")
        or f"http://splunk-otel-collector-agent.{namespace}.svc.cluster.local:4318"
    )
    return {
        "enabled": to_bool(collector.get("enabled"), True),
        "install": to_bool(collector.get("install"), True),
        "mode": collector.get("mode", "cluster-agent-managed"),
        "realm": realm,
        "environment": environment,
        "cluster_name": cluster_name,
        "namespace": namespace,
        "secret_name": secret_name,
        "token_file": token_file,
        "token_env": token_env,
        "endpoint": endpoint,
        "api_url": collector.get("api_url") or f"https://api.{realm}.signalfx.com",
        "ingest_url": collector.get("ingest_url") or f"https://ingest.{realm}.signalfx.com",
        "profiling_enabled": to_bool(collector.get("profiling_enabled"), False),
        "logs_enabled": to_bool(collector.get("logs_enabled"), True),
        "metrics_enabled": to_bool(collector.get("metrics_enabled"), True),
        "traces_enabled": to_bool(collector.get("traces_enabled"), True),
    }


def k8s_targets(spec: dict[str, Any], languages: list[str], collector: dict[str, Any]) -> list[dict[str, Any]]:
    raw_targets = as_list(spec.get("targets")) or [
        {
            "namespace": "checkout",
            "workload": "deployment/checkout-api",
            "container": "checkout-api",
            "language": languages[0] if languages else "java",
        }
    ]
    instrumentation = as_dict(spec.get("instrumentation"))
    app_name = instrumentation.get("application_name") or spec.get("application_name") or collector["cluster_name"]
    normalized: list[dict[str, Any]] = []
    for index, target in enumerate(raw_targets, start=1):
        target_dict = as_dict(target)
        api_version, kind, kubectl_kind, name = k8s_workload_parts(target_dict.get("workload"))
        language = normalize_k8s_language(target_dict.get("language") or (languages[(index - 1) % len(languages)] if languages else "java"))
        service_name = target_dict.get("service_name") or name
        service_namespace = target_dict.get("service_namespace") or target_dict.get("application_name") or app_name
        deployment_environment = (
            target_dict.get("deployment_environment")
            or target_dict.get("environment")
            or collector["environment"]
        )
        normalized.append(
            {
                "namespace": target_dict.get("namespace", "checkout"),
                "workload": f"{kubectl_kind}/{name}",
                "api_version": api_version,
                "kind": kind,
                "kubectl_kind": kubectl_kind,
                "name": name,
                "container": target_dict.get("container") or name,
                "language": language,
                "mode": normalize_combined_mode(target_dict.get("mode") or instrumentation.get("mode") or spec.get("mode") or "dual"),
                "o11y_export": target_dict.get("o11y_export") or instrumentation.get("o11y_export") or "collector",
                "service_name": service_name,
                "service_namespace": service_namespace,
                "deployment_environment": deployment_environment,
                "resource_attributes": target_dict.get("resource_attributes", {}),
            }
        )
    return normalized


def env_entry(name: str, value: Any) -> dict[str, Any]:
    return {"name": name, "value": str(value)}


def combined_agent_env(target: dict[str, Any], collector: dict[str, Any]) -> list[dict[str, Any]]:
    resource_attributes = {
        "service.name": target["service_name"],
        "service.namespace": target["service_namespace"],
        "deployment.environment.name": target["deployment_environment"],
        "k8s.namespace.name": target["namespace"],
        "k8s.workload.name": target["name"],
    }
    resource_attributes.update(as_dict(target.get("resource_attributes")))
    attributes_value = ",".join(f"{key}={value}" for key, value in resource_attributes.items())
    export_to_collector = str(target.get("o11y_export", "collector")).lower() != "direct"
    env: list[dict[str, Any]] = [
        env_entry("AGENT_DEPLOYMENT_MODE", target["mode"]),
        env_entry("OTEL_SERVICE_NAME", target["service_name"]),
        env_entry("OTEL_RESOURCE_ATTRIBUTES", attributes_value),
        env_entry("OTEL_TRACES_EXPORTER", "otlp" if collector["traces_enabled"] else "none"),
        env_entry("OTEL_METRICS_EXPORTER", "otlp" if collector["metrics_enabled"] else "none"),
        env_entry("OTEL_LOGS_EXPORTER", "otlp" if collector["logs_enabled"] else "none"),
        env_entry("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"),
        env_entry("OTEL_EXPORTER_OTLP_ENDPOINT", collector["endpoint"] if export_to_collector else collector["ingest_url"]),
    ]
    if not export_to_collector:
        env.extend(
            [
                {
                    "name": "SPLUNK_ACCESS_TOKEN",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": collector["secret_name"],
                            "key": "splunk_observability_access_token",
                        }
                    },
                },
                env_entry("SPLUNK_REALM", collector["realm"]),
            ]
        )
    language = target["language"]
    if language == "dotnet-core-linux":
        env.extend(
            [
                env_entry("DOTNET_ADDITIONAL_DEPS", "/opt/appdynamics/dotnet/additionalDeps"),
                env_entry("DOTNET_SHARED_STORE", "/opt/appdynamics/dotnet/store"),
                env_entry("DOTNET_STARTUP_HOOKS", "/opt/appdynamics/dotnet/startupHook/AppDynamics.AgentProfiler.dll"),
            ]
        )
    elif language == "nodejs":
        env.append(env_entry("NODE_OPTIONS", "--require appdynamics"))
    elif language == "machine-agent":
        env.append(env_entry("APPD_MACHINE_AGENT_COMBINED_MODE", "true"))
    return env


def render_cluster_agent_values(spec: dict[str, Any], languages: list[str], targets: list[dict[str, Any]], collector: dict[str, Any]) -> str:
    cluster_agent = as_dict(spec.get("cluster_agent"))
    instrumentation = as_dict(spec.get("instrumentation"))
    controller_secret_name = spec.get("secret_name", "appdynamics-controller-secret")
    payload: dict[str, Any] = {
        "installClusterAgent": True,
        "installSplunkOtelCollector": collector["enabled"] and collector["install"],
        "controllerInfo": {
            "url": spec.get("controller_url", "https://example.saas.appdynamics.com"),
            "account": spec.get("account_name", "customer1"),
            "username": spec.get("controller_username", "<controller-user>"),
            "password": "${APPD_CONTROLLER_PASSWORD}",
            "accessKey": "${APPD_CONTROLLER_ACCESS_KEY}",
            "secretName": controller_secret_name,
        },
        "clusterAgent": {
            "enabled": True,
            "clusterName": collector["cluster_name"],
            "appName": cluster_agent.get("app_name", collector["cluster_name"]),
            "nsToMonitorRegex": cluster_agent.get("namespace_regex", spec.get("namespace_regex", ".*")),
            "logLevel": cluster_agent.get("log_level", "INFO"),
            "disableClusterAgentMonitoring": to_bool(cluster_agent.get("disable_cluster_agent_monitoring"), False),
            "eventUploadInterval": cluster_agent.get("event_upload_interval", "10"),
            "metricsSyncInterval": cluster_agent.get("metrics_sync_interval", "30"),
        },
        "instrumentation": {
            "enabled": to_bool(instrumentation.get("enabled"), True),
            "mode": normalize_combined_mode(instrumentation.get("mode", "dual")),
            "languages": languages,
            "targets": [
                {
                    "namespace": target["namespace"],
                    "workload": target["workload"],
                    "container": target["container"],
                    "language": target["language"],
                    "o11y_export": target["o11y_export"],
                }
                for target in targets
            ],
        },
    }
    if collector["enabled"]:
        payload["splunk-otel-collector"] = {
            "enabled": True,
            "clusterName": collector["cluster_name"],
            "environment": collector["environment"],
            "secret": {
                "create": False,
                "name": collector["secret_name"],
            },
            "splunkObservability": {
                "realm": collector["realm"],
                "accessToken": f"${{{collector['token_env']}}}",
                "profilingEnabled": collector["profiling_enabled"],
                "logsEnabled": collector["logs_enabled"],
                "metricsEnabled": collector["metrics_enabled"],
                "tracesEnabled": collector["traces_enabled"],
            },
            "agent": {
                "enabled": True,
                "ports": {
                    "otlp": {"containerPort": 4317, "protocol": "TCP"},
                    "otlp-http": {"containerPort": 4318, "protocol": "TCP"},
                },
            },
        }
        payload["splunkOtelCollector"] = {
            "enabled": True,
            "mode": collector["mode"],
            "realm": collector["realm"],
            "endpoint": collector["endpoint"],
        }
    return dump_yaml(payload)


def render_splunk_otel_values(collector: dict[str, Any]) -> str:
    return dump_yaml(
        {
            "clusterName": collector["cluster_name"],
            "environment": collector["environment"],
            "splunkObservability": {
                "realm": collector["realm"],
                "accessToken": f"${{{collector['token_env']}}}",
                "profilingEnabled": collector["profiling_enabled"],
                "logsEnabled": collector["logs_enabled"],
                "metricsEnabled": collector["metrics_enabled"],
                "tracesEnabled": collector["traces_enabled"],
            },
            "secret": {
                "create": False,
                "name": collector["secret_name"],
            },
            "agent": {
                "enabled": True,
                "ports": {
                    "otlp": {"containerPort": 4317, "protocol": "TCP"},
                    "otlp-http": {"containerPort": 4318, "protocol": "TCP"},
                },
            },
            "gateway": {
                "enabled": True,
            },
        }
    )


def render_splunk_otel_secret_template(collector: dict[str, Any]) -> str:
    return dump_yaml(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": collector["secret_name"],
                "namespace": collector["namespace"],
            },
            "type": "Opaque",
            "stringData": {
                "splunk_observability_access_token": f"${{{collector['token_env']}}}",
            },
        }
    )


def render_workload_patches(targets: list[dict[str, Any]], collector: dict[str, Any]) -> str:
    patches = []
    for target in targets:
        patches.append(
            {
                "target": {
                    "apiVersion": target["api_version"],
                    "kind": target["kind"],
                    "name": target["name"],
                    "namespace": target["namespace"],
                },
                "patch": {
                    "apiVersion": target["api_version"],
                    "kind": target["kind"],
                    "metadata": {
                        "name": target["name"],
                        "namespace": target["namespace"],
                    },
                    "spec": {
                        "template": {
                            "metadata": {
                                "annotations": {
                                    "appdynamics.com/instrumentation": "enabled",
                                    "appdynamics.com/instrumentation-language": target["language"],
                                    "appdynamics.com/combined-agent-mode": target["mode"],
                                }
                            },
                            "spec": {
                                "containers": [
                                    {
                                        "name": target["container"],
                                        "env": combined_agent_env(target, collector),
                                    }
                                ]
                            },
                        }
                    },
                },
            }
        )
    return dump_yaml({"patches": patches})


def render_dual_signal_workload_env(targets: list[dict[str, Any]], collector: dict[str, Any]) -> str:
    return dump_yaml(
        {
            "defaults": {
                "mode": "dual",
                "o11y_export": "collector",
                "collector_endpoint": collector["endpoint"],
                "splunk_realm": collector["realm"],
                "secret_name": collector["secret_name"],
                "secret_key": "splunk_observability_access_token",
            },
            "targets": [
                {
                    "namespace": target["namespace"],
                    "workload": target["workload"],
                    "container": target["container"],
                    "language": target["language"],
                    "mode": target["mode"],
                    "env": combined_agent_env(target, collector),
                }
                for target in targets
            ],
        }
    )


def render_k8s_rollout_plan(targets: list[dict[str, Any]], collector: dict[str, Any]) -> str:
    patch_commands: list[str] = []
    for target in targets:
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "appdynamics.com/instrumentation": "enabled",
                            "appdynamics.com/instrumentation-language": target["language"],
                            "appdynamics.com/combined-agent-mode": target["mode"],
                        }
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": target["container"],
                                "env": combined_agent_env(target, collector),
                            }
                        ]
                    },
                }
            }
        }
        patch_commands.append(
            "kubectl -n {namespace} patch {kind} {name} --type merge -p {patch}".format(
                namespace=shell_quote(target["namespace"]),
                kind=shell_quote(target["kubectl_kind"]),
                name=shell_quote(target["name"]),
                patch=shell_quote(json.dumps(patch, separators=(",", ":"))),
            )
        )
    patch_block = "\n".join(patch_commands) or "echo 'No workload targets rendered.'"
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Kubernetes mutation remains gated by --accept-k8s-rollout in the skill entrypoint.
# Review cluster-agent-values.yaml, splunk-otel-secret-template.yaml, and workload-instrumentation-patches.yaml first.
# This plan defaults to dry-run. Set K8S_APPLY=1 only inside an approved maintenance window.

: "${{APPD_NAMESPACE:={collector['namespace']}}}"
: "${{APPD_CLUSTER_AGENT_RELEASE:=appdynamics-cluster-agent}}"
: "${{SPLUNK_O11Y_ACCESS_TOKEN_FILE:={collector['token_file']}}}"
: "${{SPLUNK_OTEL_SECRET_NAME:={collector['secret_name']}}}"

test -f "${{SPLUNK_O11Y_ACCESS_TOKEN_FILE}}" || {{ echo "Missing ${{SPLUNK_O11Y_ACCESS_TOKEN_FILE}}"; exit 1; }}
if [[ "${{K8S_APPLY:-0}}" == "1" ]]; then
  kubectl get namespace "${{APPD_NAMESPACE}}" >/dev/null 2>&1 || kubectl create namespace "${{APPD_NAMESPACE}}"

  kubectl -n "${{APPD_NAMESPACE}}" create secret generic "${{SPLUNK_OTEL_SECRET_NAME}}" \\
    --from-file=splunk_observability_access_token="${{SPLUNK_O11Y_ACCESS_TOKEN_FILE}}" \\
    --dry-run=client -o yaml | kubectl apply -f -
  HELM_DRY_RUN=()
else
  kubectl create namespace "${{APPD_NAMESPACE}}" --dry-run=client -o yaml >/dev/null
  kubectl -n "${{APPD_NAMESPACE}}" create secret generic "${{SPLUNK_OTEL_SECRET_NAME}}" \\
    --from-file=splunk_observability_access_token="${{SPLUNK_O11Y_ACCESS_TOKEN_FILE}}" \\
    --dry-run=client -o yaml >/dev/null
  HELM_DRY_RUN=(--dry-run)
fi

helm repo add appdynamics-cloud-helmcharts https://appdynamics.jfrog.io/artifactory/appdynamics-cloud-helmcharts/
helm repo update appdynamics-cloud-helmcharts
helm upgrade --install "${{APPD_CLUSTER_AGENT_RELEASE}}" appdynamics-cloud-helmcharts/cluster-agent \\
  --namespace "${{APPD_NAMESPACE}}" \\
  --values "$(dirname "$0")/cluster-agent-values.yaml" \\
  --set splunk-otel-collector.secret.create=false \\
  --set splunk-otel-collector.secret.name="${{SPLUNK_OTEL_SECRET_NAME}}" \\
  --set-file splunk-otel-collector.splunkObservability.accessToken="${{SPLUNK_O11Y_ACCESS_TOKEN_FILE}}" \\
  "${{HELM_DRY_RUN[@]}}"

if [[ "${{K8S_APPLY:-0}}" != "1" ]]; then
  echo "Dry run complete. Set K8S_APPLY=1 to apply the Helm release and workload patches."
  cat <<'PATCH_COMMANDS'
{patch_block}
PATCH_COMMANDS
  exit 0
fi

{patch_block}

kubectl -n "${{APPD_NAMESPACE}}" rollout status deployment/"${{APPD_CLUSTER_AGENT_RELEASE}}" --timeout=180s || true
"""


def render_k8s_rbac_review() -> str:
    return """# Cluster Agent RBAC Review

- Confirm Operator, Cluster Agent, and Infrastructure Visibility RBAC from the 26.4 permissions page.
- Confirm OpenShift SCC requirements before deploying on OpenShift.
- Confirm Cluster Agent and Operator compatibility matrix versions before rollout.
- If `installSplunkOtelCollector` is enabled, confirm the collector service account can list/watch Kubernetes metadata and write its secret-backed O11y token reference.
- If workload auto-instrumentation is enabled, confirm the Cluster Agent may patch selected workloads only in the approved namespaces.
- Do not grant broad namespace mutation unless the spec uses namespace scoping or explicit workload targets.
"""


def render_combined_agent_runbook(targets: list[dict[str, Any]], collector: dict[str, Any], languages: list[str]) -> str:
    target_lines = "\n".join(
        f"- `{target['namespace']}/{target['workload']}`: `{target['language']}` in `{target['mode']}` mode, exporting `{target['o11y_export']}` to `{collector['endpoint'] if target['o11y_export'] != 'direct' else collector['ingest_url']}`."
        for target in targets
    )
    return f"""# Combined Agent And O11y Export Runbook

## Rendered Coverage

- Cluster Agent deploys through the AppDynamics Helm chart with `installSplunkOtelCollector` set from the spec.
- Splunk OTel Collector is configured for realm `{collector['realm']}`, environment `{collector['environment']}`, and cluster `{collector['cluster_name']}`.
- O11y access tokens stay file-backed. Runtime apply uses `--set-file` or a Kubernetes Secret generated from `SPLUNK_O11Y_ACCESS_TOKEN_FILE`.
- Dual-signal workload plans cover: {", ".join(languages)}.

## Workloads

{target_lines}

## Mode Guidance

- `dual`: keep AppDynamics Controller visibility and emit OpenTelemetry signals toward Splunk Observability Cloud.
- `otel`: emit OpenTelemetry signals only when Controller-side AppDynamics agent telemetry is not wanted.
- `appd-only`: keep Controller telemetry and skip O11y export for that workload.
- `collector` export is the default because it centralizes O11y token use in the collector.
- `direct` export is available for constrained environments, but it mounts the O11y token into the workload through a Kubernetes Secret.

## Language Notes

- Java combined agent: use `AGENT_DEPLOYMENT_MODE=dual` with OTLP exporter variables and service/resource attributes.
- .NET Core Linux combined mode is rendered with the startup hook variables required by the combined .NET agent path.
- Node.js combined mode uses `AGENT_DEPLOYMENT_MODE=dual` plus OTLP exporter variables; application packaging must include the AppDynamics Node.js agent runtime.
- Machine Agent combined mode is acknowledged for infrastructure use cases; broad host/node rollout belongs in `splunk-appdynamics-infrastructure-visibility-setup`.

## Handoffs

- Deep Splunk OTel Collector tuning, gateway sizing, processors, and enterprise O11y dashboards can delegate to `splunk-observability-otel-collector-setup`.
- APM model ownership remains in `splunk-appdynamics-apm-setup`.
"""


def render_k8s_validation_probes(targets: list[dict[str, Any]], collector: dict[str, Any]) -> str:
    rollout_checks = "\n".join(
        f"kubectl -n {shell_quote(target['namespace'])} rollout status {shell_quote(target['kubectl_kind'])}/{shell_quote(target['name'])} --timeout=180s || true\n"
        f"kubectl -n {shell_quote(target['namespace'])} get {shell_quote(target['kubectl_kind'])} {shell_quote(target['name'])} -o jsonpath='{{.spec.template.metadata.annotations}}' | grep -E 'appdynamics.com/(instrumentation|combined-agent-mode)' || true\n"
        f"kubectl -n {shell_quote(target['namespace'])} get pod -l app -o jsonpath='{{range .items[*]}}{{.metadata.name}}{{\"\\n\"}}{{end}}' | head -5 || true"
        for target in targets
    )
    return f"""#!/usr/bin/env bash
set -euo pipefail

: "${{APPD_NAMESPACE:={collector['namespace']}}}"

kubectl -n "${{APPD_NAMESPACE}}" get deploy,ds,sts,pods,secret | grep -E 'appd|cluster-agent|otel|splunk' || true
kubectl get pods -A | grep -E 'appd|cluster-agent|splunk-otel|otel-collector' || true
kubectl get svc -A | grep -E '4317|4318|splunk-otel|otel-collector' || true

{rollout_checks}

echo "Controller validation: confirm the cluster appears in the AppDynamics Controller and that injected workloads create nodes/tiers as expected."
echo "O11y validation: run o11y-export-validation.sh and confirm APM services, traces, metrics, and Kubernetes metadata in Splunk Observability Cloud."
"""


def render_o11y_export_validation(collector: dict[str, Any], targets: list[dict[str, Any]]) -> str:
    services = " ".join(shell_quote(target["service_name"]) for target in targets)
    return f"""#!/usr/bin/env bash
set -euo pipefail

: "${{SPLUNK_REALM:={collector['realm']}}}"
: "${{SPLUNK_O11Y_ACCESS_TOKEN_FILE:={collector['token_file']}}}"
: "${{SPLUNK_O11Y_API_URL:={collector['api_url']}}}"
: "${{APPD_NAMESPACE:={collector['namespace']}}}"

if [[ -f "${{SPLUNK_O11Y_ACCESS_TOKEN_FILE}}" ]]; then
  curl --fail --silent --show-error \\
    -H "X-SF-Token: $(<"${{SPLUNK_O11Y_ACCESS_TOKEN_FILE}}")" \\
    "${{SPLUNK_O11Y_API_URL}}/v2/organization" >/dev/null || echo "WARN: O11y API token probe failed"
else
  echo "WARN: SPLUNK_O11Y_ACCESS_TOKEN_FILE is missing; skipping O11y API token probe"
fi

kubectl -n "${{APPD_NAMESPACE}}" logs -l app.kubernetes.io/name=splunk-otel-collector --tail=200 2>/dev/null | grep -Ei 'signalfx|splunk|otlp|exporter|error' || true
kubectl get pods -A | grep -E 'splunk-otel|otel-collector|cluster-agent|appd' || true

echo "Expected O11y services: {services}"
echo "Confirm these dimensions in Splunk Observability Cloud: k8s.cluster.name={collector['cluster_name']}, deployment.environment.name={collector['environment']}, service.name, service.namespace."
"""


def render_k8s_artifacts(out: Path, spec: dict[str, Any]) -> None:
    collector = k8s_collector_config(spec)
    languages = [normalize_k8s_language(item) for item in as_list(spec.get("languages"))] or [
        "java",
        "dotnet-core-linux",
        "nodejs",
    ]
    targets = k8s_targets(spec, languages, collector)
    write(out / "cluster-agent-values.yaml", render_cluster_agent_values(spec, languages, targets, collector))
    write(out / "splunk-otel-collector-values.yaml", render_splunk_otel_values(collector))
    write(out / "splunk-otel-secret-template.yaml", render_splunk_otel_secret_template(collector))
    write(out / "workload-instrumentation-patches.yaml", render_workload_patches(targets, collector))
    write(out / "dual-signal-workload-env.yaml", render_dual_signal_workload_env(targets, collector))
    write(out / "combined-agent-o11y-runbook.md", render_combined_agent_runbook(targets, collector, languages))
    rollout = out / "cluster-agent-rollout-plan.sh"
    write(rollout, render_k8s_rollout_plan(targets, collector))
    chmod_exec(rollout)
    write(out / "cluster-agent-rbac-review.md", render_k8s_rbac_review())
    probes = out / "cluster-agent-validation-probes.sh"
    write(probes, render_k8s_validation_probes(targets, collector))
    chmod_exec(probes)
    o11y = out / "o11y-export-validation.sh"
    write(o11y, render_o11y_export_validation(collector, targets))
    chmod_exec(o11y)


def render_infrastructure_artifacts(out: Path, spec: dict[str, Any]) -> None:
    hosts = as_dict(spec.get("machine_agent")).get("hosts", ["host01.example.com"])
    plan = out / "machine-agent-command-plan.sh"
    write(plan, "#!/usr/bin/env bash\nset -euo pipefail\n" + "\n".join(f"echo 'Render Machine Agent install/service validation for {host}'" for host in hosts) + "\n")
    chmod_exec(plan)
    write_json(out / "infrastructure-health-rules.json", {"service_availability": as_dict(spec.get("service_availability")).get("probes", []), "server_visibility": spec.get("server_visibility", True), "network_visibility": spec.get("network_visibility", "validate_only")})
    write_json(out / "server-tags-payload.json", {"server_tags": as_dict(spec.get("server_tags"))})
    write(out / "network-visibility-runbook.md", "# Network Visibility Runbook\n\n- Packet and flow agents require privileged host changes.\n- Validate process state, flow metrics, and Controller Network Visibility views.\n")
    write(
        out / "gpu-monitoring-runbook.md",
        "# GPU Monitoring Runbook\n\n"
        "- Validate supported environments: Machine Agent, Cluster Agent, Controller, Ubuntu, NVIDIA driver, and Kubernetes versions before enabling GPU monitoring.\n"
        "- For node-level monitoring, render NVIDIA-SMI or DCGM Exporter collection through Machine Agent; for cluster-wide metrics, render Cluster Agent GPU settings and Kubernetes service locality checks.\n"
        "- Validate `sim.cluster.gpu.enabled=true`, Cluster Agent `gpuMonitoringEnabled: true`, Machine Agent environment variables, DCGM DNS resolution, and GPU metrics in Controller dashboards.\n"
        "- GPU platform deployment can hand off to NVIDIA GPU or Cisco AI Pod observability skills when the same cluster needs broader GPU telemetry.\n",
    )
    write(
        out / "prometheus-extension-runbook.md",
        "# Prometheus Extension Runbook\n\n"
        "- Render Machine Agent Prometheus extension configuration with reviewed exporter endpoints, scrape intervals, filters, and metric mappings.\n"
        "- Validate exporter reachability, Machine Agent extension logs, max metric count, scrape timeout, and Controller metric paths before adding health rules.\n"
        "- Use this path for infrastructure exporters such as DCGM, node exporter, cAdvisor, Kafka, MongoDB, or custom Prometheus endpoints when AppDynamics ownership is required.\n",
    )
    probes = out / "infrastructure-validation-probes.sh"
    write(probes, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Validate Machine Agent, Server Visibility, container metrics, GPU metrics, Prometheus extension metrics, service availability, and server tags.'\n")
    chmod_exec(probes)


def render_database_artifacts(out: Path, spec: dict[str, Any]) -> None:
    collectors = spec.get("collectors") or [{"name": "orders-postgres", "type": "POSTGRESQL", "hostname": "db.example.com", "port": 5432, "username": "appd_monitor", "password_file": "/secure/appd/db_password"}]
    payloads = []
    for collector in collectors:
        payload = dict(collector)
        if "password" in payload:
            payload["password"] = "<redacted:use password_file>"
        payload.setdefault("password_file", "/secure/appd/db_password")
        payload["password"] = "<redacted:file-backed>"
        payloads.append(payload)
    write_json(out / "database-collector-payloads.redacted.json", {"collectors": payloads})
    agent = out / "database-agent-command-plan.sh"
    write(agent, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Render Database Agent install/start/rollback commands for the reviewed host.'\n")
    chmod_exec(agent)
    probes = out / "database-validation-probes.sh"
    write(probes, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Validate /controller/rest/databases/collectors, servers, nodes, and _dbmon events.'\n")
    chmod_exec(probes)


def render_analytics_artifacts(out: Path, spec: dict[str, Any]) -> None:
    write_json(out / "analytics-events-headers.redacted.json", {"X-Events-API-AccountName": spec.get("global_account_name", "customer1_abcdef"), "X-Events-API-Key": "<redacted:events_api_key_file>", "Content-Type": "application/vnd.appd.events+json;v=2"})
    write_json(out / "analytics-schema-plan.json", {"schemas": [as_dict(spec.get("custom_events")).get("schema", "appd_custom_events")], "adql": spec.get("adql", ["SELECT * FROM transactions LIMIT 10"])})
    write(
        out / "business-journeys-xlm-runbook.md",
        "# Business Journeys And XLM Runbook\n\n"
        "- Inventory journey steps across transaction, log, EUM, synthetic, and custom event sources.\n"
        "- Define Experience Level Management properties, compliance targets, daily thresholds, periods, time zone, and exclusion periods.\n"
        "- Validate XLM reporting output, CSV export, dashboard widgets, and scheduled report handoff.\n"
        "- Business Journey and XLM configuration is rendered for UI/operator review.\n",
    )
    publish = out / "analytics-publish-plan.sh"
    write(publish, "#!/usr/bin/env bash\nset -euo pipefail\n: \"${APPD_EVENTS_API_KEY_FILE:?set APPD_EVENTS_API_KEY_FILE}\"\necho 'Publishing is gated by --accept-analytics-event-publish.'\n")
    chmod_exec(publish)
    adql = out / "analytics-adql-validation.sh"
    write(adql, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Run ADQL validation for transaction, log, browser, mobile, synthetic, IoT, and Connected Device Data event types.'\n")
    chmod_exec(adql)


def render_eum_artifacts(out: Path, spec: dict[str, Any]) -> None:
    app_key = spec.get("browser_app_key", "APPD_BROWSER_APP_KEY")
    write_json(out / "eum-app-key-inventory.json", {"browser_app_key": app_key, "mobile_app_keys": as_dict(spec.get("mobile_app_keys")), "session_replay": as_dict(spec.get("session_replay"))})
    write(out / "browser-rum-snippet.html", f"""<script charset="UTF-8">
window["adrum-start-time"] = new Date().getTime();
(function(config) {{
  config.appKey = "{app_key}";
  config.adrumExtUrlHttp = "http://cdn.appdynamics.com";
  config.adrumExtUrlHttps = "https://cdn.appdynamics.com";
  config.beaconUrlHttp = "http://col.eum-appdynamics.com";
  config.beaconUrlHttps = "https://col.eum-appdynamics.com";
}})(window["adrum-config"] || (window["adrum-config"] = {{}}));
</script>
<script src="//cdn.appdynamics.com/adrum/adrum-latest.js"></script>
""")
    write(
        out / "mobile-sdk-snippets.md",
        "# Mobile SDK Snippets\n\n"
        "- iOS: use the configured iOS app key, collector URL, screenshot URL, and Session Replay blob URL when Mobile Session Replay is approved.\n"
        "- Android: use the configured Android app key, collector URL, `.withSessionReplayEnabled(true)`, and blob service URL when Mobile Session Replay is approved.\n"
        "- React Native: include `sessionReplayURL` and the Android session-recording dependency for React Native Android applications when replay is in scope.\n"
        "- Flutter and .NET MAUI: render framework-specific initialization, symbol upload, and privacy-review steps in the app build pipeline.\n"
        "- Source edits remain operator-controlled and require `--accept-eum-source-edit`.\n",
    )
    write(out / "session-replay-config.js", "window['adrum-config'] = window['adrum-config'] || {};\nwindow['adrum-config'].sessionReplay = { enabled: false, sessionReplayUrlHttps: 'https://col.eum-appdynamics.com' };\n")
    write(
        out / "mobile-session-replay-runbook.md",
        "# Mobile Session Replay Runbook\n\n"
        "- Confirm Session Replay licensing and platform prerequisites before source changes: Controller 25.7+ for SaaS GA paths, Controller/EUM Server 25.10+ for on-premises paths, and iOS/Android agents 25.9+ unless the target release notes require newer builds.\n"
        "- For on-premises EUM, enable the account property `session.replay.enabled=true` in the administration console before application rollout.\n"
        "- iOS: set app key, collector URL, screenshot URL, and session replay blob URL; keep privacy masking enabled for text and input fields by default.\n"
        "- Android: enable Session Replay in the agent builder, set the blob service URL, and choose native or wireframe rendering based on privacy requirements.\n"
        "- React Native: pass `sessionReplayURL` in initialization and add the Android session-recording dependency only for React Native Android builds.\n"
        "- Controller UI: administrators enable Session Replay under the selected mobile app's Configuration > Mobile App Group Configuration > Session Replay tab.\n"
        "- Validate that the Mobile Apps view shows replay availability, active session segments, and Video/Wireframe playback without exposing sensitive fields.\n",
    )
    source_map = out / "source-map-upload-plan.sh"
    write(source_map, "#!/usr/bin/env bash\nset -euo pipefail\n: \"${APPD_EUM_TOKEN_FILE:?set APPD_EUM_TOKEN_FILE}\"\necho 'Upload source maps or mobile symbols from CI after reviewing app key, release, and mapping path.'\n")
    chmod_exec(source_map)
    probes = out / "eum-validation-probes.sh"
    write(probes, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Validate app keys, beacon delivery, browser/mobile/IoT analytics, source-map and symbol inventory, browser Session Replay, and Mobile Session Replay readiness.'\n")
    chmod_exec(probes)


def render_synthetic_artifacts(out: Path, spec: dict[str, Any]) -> None:
    browser_jobs = as_list(spec.get("browser_jobs")) or [{"name": "checkout-homepage", "url": "https://example.com"}]
    api_monitors = as_list(spec.get("api_monitors")) or [{"name": "checkout-api", "url": "https://example.com/health"}]
    psa = as_dict(spec.get("private_synthetic_agent"))
    write_json(out / "browser-synthetic-jobs.json", {"jobs": browser_jobs, "locations": spec.get("locations", ["hosted"])})
    write_json(out / "synthetic-api-monitor.json", {"monitors": api_monitors, "assertions": spec.get("assertions", [{"type": "status_code", "equals": 200}] )})
    write(out / "private-synthetic-agent-values.yaml", dump_yaml({"privateSyntheticAgent": {"enabled": bool(psa.get("enabled", True)), "controllerUrl": spec.get("controller_url", "https://example.saas.appdynamics.com"), "shepherdUrl": psa.get("shepherd_url", spec.get("shepherd_url", "https://synthetic.api.appdynamics.com")), "secretName": psa.get("secret_name", "appdynamics-synthetic-agent-secret")}}))
    write(out / "private-synthetic-agent-docker-compose.yaml", dump_yaml({"services": {"private-synthetic-agent": {"image": "appdynamics/private-synthetic-agent:reviewed-version", "environment": {"APPDYNAMICS_CONTROLLER_URL": spec.get("controller_url", "https://example.saas.appdynamics.com"), "APPDYNAMICS_SECRET_FILE": "/run/secrets/appdynamics"}}}}))
    probes = out / "synthetic-validation-probes.sh"
    write(probes, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Validate synthetic jobs, API monitors, latest runs, waterfall artifacts, locations, and PSA Shepherd connectivity.'\n")
    chmod_exec(probes)


def render_log_observer_connect_artifacts(out: Path, spec: dict[str, Any]) -> None:
    write_json(out / "loc-readiness-plan.json", {"controller_url": spec.get("controller_url", "https://example.saas.appdynamics.com"), "splunk_platform": as_dict(spec.get("splunk_platform")), "deep_links": as_dict(spec.get("deep_links")), "legacy_integration": as_dict(spec.get("legacy_integration"))})
    handoff = out / "splunk-platform-handoff.sh"
    write(handoff, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Hand off Splunk service-account, allow-list, and LOC validation to Splunk Platform skills.'\n")
    chmod_exec(handoff)
    write(out / "legacy-splunk-integration-runbook.md", "# Legacy Splunk Integration Runbook\n\n- Detect old Settings > Administration > Integration > Splunk configuration.\n- Confirm replacement LOC path is ready before disablement.\n- Disablement is never blind or automatic.\n")
    deeplink = out / "loc-deeplink-validation.sh"
    write(deeplink, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Validate LOC deep links from application, tier, node, business transaction, and transaction snapshot views.'\n")
    chmod_exec(deeplink)


def render_alerting_artifacts(out: Path, spec: dict[str, Any]) -> None:
    write_json(out / "alerting-content-payloads.json", {"health_rules": spec.get("health_rules", []), "policies": spec.get("policies", []), "actions": spec.get("actions", []), "schedules": spec.get("schedules", []), "email_digests": spec.get("email_digests", []), "suppression": spec.get("suppression", []), "anomaly_detection": spec.get("anomaly_detection", {"render_runbook": True})})
    write(
        out / "anomaly-detection-rca-runbook.md",
        "# Anomaly Detection And RCA Runbook\n\n"
        "- Validate anomaly detection enablement for application servers, business transactions, browser base pages, databases, and mobile network requests.\n"
        "- Confirm model training status before relying on anomaly alerts.\n"
        "- Review anomaly filters, state transitions, event types, and policy linkage.\n"
        "- For Automated Root Cause Analysis, validate suspected causes, deviating metrics, snapshots, logs, traces, infrastructure context, and AI-generated summaries where available.\n",
    )
    write(
        out / "aiml-baseline-diagnostics-runbook.md",
        "# AIML Baseline And Diagnostics Runbook\n\n"
        "- Validate Dynamic Baseline behavior for metrics that use historical time-of-day and seasonal patterns.\n"
        "- Confirm Anomaly Detection and Automated Root Cause Analysis coverage for business transactions, application servers, browser base pages, databases, and mobile network requests.\n"
        "- Validate Automated Transaction Diagnostics by reviewing anomalous transaction capture and suspected causes across slow methods, slow databases, and remote service calls.\n"
        "- Treat AI-generated recommendations as advisory; require operator verification before remediation actions or policy changes.\n",
    )
    rollback = out / "alerting-export-rollback-plan.sh"
    write(rollback, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Export health rules, policies, actions, schedules, and suppressions before apply; render rollback from exported snapshots.'\n")
    chmod_exec(rollback)
    probes = out / "alerting-validation-probes.sh"
    write(probes, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Validate health-rule readback, policy/action binding, schedules, suppressions, and sample notification path.'\n")
    chmod_exec(probes)


def render_dashboards_reports_artifacts(out: Path, spec: dict[str, Any]) -> None:
    write_json(out / "dashboard-payloads.json", {"dashboards": spec.get("dashboards", []), "dash_studio": as_dict(spec.get("dash_studio"))})
    write(out / "dashboard-report-runbook.md", "# Dashboard Report Runbook\n\n- Review custom dashboard widgets and permissions.\n- Reports and scheduled delivery are UI/runbook-first.\n- Dash Studio migration remains a handoff when not API-backed.\n")
    write(
        out / "thousandeyes-dashboard-integration-runbook.md",
        "# ThousandEyes Dashboard Integration Runbook\n\n"
        "- Validate that the AppDynamics tenant has the ThousandEyes integration available and that the operator has AppDynamics admin privileges.\n"
        "- Configure the ThousandEyes bearer token through Administration > Integrations > ThousandEyes using a secret-file handoff; never render the token value.\n"
        "- Validate Dash Studio widgets that use the ThousandEyes query for supported widget types, account groups, tests, labels, metric categories, and time ranges.\n"
        "- Delegate ThousandEyes-side tests, labels, stream configuration, dashboards, and detectors to the existing ThousandEyes skills.\n",
    )
    write(out / "war-room-runbook.md", "# War Room Runbook\n\n- Validate War Room templates, participants, save/sync behavior, and archive expectations.\n- War Room operations stay UI/runbook-only unless documented API support is available.\n")
    probes = out / "dashboard-validation-probes.sh"
    write(probes, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Validate dashboard inventory, widget counts, report schedules, delivery, and War Room access.'\n")
    chmod_exec(probes)


def render_tags_extensions_artifacts(out: Path, spec: dict[str, Any]) -> None:
    write_json(out / "custom-tags-payload.json", {"tags": spec.get("tags", []), "permissions": ["VIEW_TAGS", "MANAGE_TAGS"]})
    write(out / "extensions-runbook.md", "# Extensions Runbook\n\n- Validate Integration Modules and extension placement.\n- Machine Agent extension installation and restarts are operator-run.\n- Review ServiceNow, Jira, Scalyr, Agent Command Center, and Log Auto-Discovery ownership before apply.\n")
    custom_metrics = out / "custom-metrics-example.sh"
    write(custom_metrics, "#!/usr/bin/env bash\nset -euo pipefail\necho 'name=Custom Metrics|Example,value=1' # Send through Machine Agent custom metric extension path after review.\n")
    chmod_exec(custom_metrics)
    write(out / "integrations-handoff.md", "# Integration Handoffs\n\n- ServiceNow, Jira, Scalyr, Agent Command Center, and Log Auto-Discovery mutate external systems and remain delegated/runbook-first.\n")


def render_security_ai_artifacts(out: Path, spec: dict[str, Any]) -> None:
    write(out / "security-ai-readiness.yaml", dump_yaml({"secure_application": as_dict(spec.get("secure_application")), "otel_java": as_dict(spec.get("otel_java")), "observability_for_ai": as_dict(spec.get("observability_for_ai")), "gpu": as_dict(spec.get("gpu")), "cisco_ai_pod": as_dict(spec.get("cisco_ai_pod"))}))
    secure = out / "secure-application-validation.sh"
    write(secure, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Validate Secure Application entitlement, supported agents, node security status, vulnerabilities, attacks, libraries, business risk, and policyConfigs APIs.'\n")
    chmod_exec(secure)
    write(
        out / "secure-application-policy-runbook.md",
        "# Secure Application Policy Runbook\n\n"
        "- Validate Application Security Monitoring entitlement and Security Health widget visibility for APM-managed applications.\n"
        "- Review runtime policy coverage for command execution, filesystem access, HTTP response headers, web transactions, and network/socket access.\n"
        "- Use Secure Application APIs for readback of applications, tiers, nodes, vulnerabilities, libraries, attacks, business risks, and `policyConfigs` inventory/detail endpoints.\n"
        "- Treat `policyConfigs` create, update, and delete calls as high-risk mutations: require owner approval, action/status review, rollback notes, and OAuth token files.\n"
        "- Keep API probes rate-limited and paginated; inventory scripts should filter by application, tier, node, severity, and policy status rather than pulling unbounded datasets.\n"
        "- Policy create/update/delete remains review-first; block or patch actions require application owner approval and rollback notes.\n",
    )
    write(out / "otel-secure-application-snippet.md", "# Secure Application OTel Snippet\n\n- Java: enable secure application settings on supported AppDynamics/OTel Java paths.\n- Validate runtime compatibility before restart.\n")
    write(out / "observability-ai-handoffs.md", "# Observability For AI Handoffs\n\n- OpenAI, LangChain, and Bedrock framework checks route through Observability for AI.\n- GPU work delegates to `splunk-observability-nvidia-gpu-integration`.\n- Cisco AI Pod work delegates to `splunk-observability-cisco-ai-pod-integration`.\n")


def render_sap_artifacts(out: Path, spec: dict[str, Any]) -> None:
    write(
        out / "sap-agent-runbook.md",
        "# SAP Agent Runbook\n\n"
        "- Verify supported SAP NetWeaver release, SAP NetWeaver transport requirements, support package, application-server OS, Controller compatibility, SAP Agent release notes, and rollback transports before import.\n"
        "- Confirm SAP authorizations for SAP Basis, ABAP Agent administration, SNP CrystalBridge, BiQ Collector, HTTP SDK, and runtime validation users before install.\n"
        "- Import ABAP Agent transport requests in the documented dependency order from the release bundle readme; schedule production imports outside peak load because standard SAP objects may be recompiled.\n"
        "- Deploy HTTP SDK locally on supported SAP application-server operating systems, or deploy a nearby 64-bit Linux gateway/proxy host for unsupported or mixed operating systems.\n"
        "- For on-premises Controllers with HTTPS, install the custom SSL certificate for the local or remote HTTP SDK path before enabling production traffic.\n"
        "- Install Machine Agent on SAP application servers for OS metrics; use HTTP SDK instead of the Machine Agent HTTP Listener for application event reporting when that path is selected.\n"
        "- Validate ABAP Agent business transactions, HTTP SDK/C++ SDK Controller connectivity, SNP CrystalBridge metrics/events, BiQ business-process data, Controller node registration, and SAP dashboards.\n",
    )
    write(
        out / "sap-authorization-checklist.md",
        "# SAP Authorization Checklist\n\n"
        "- Confirm SAP Basis transport owner, target clients, import windows, release-bundle readme ordering, and emergency rollback contacts.\n"
        "- Confirm SNP CrystalBridge Monitoring administrator access through `/DVD/MON_ADMIN` and ABAP Agent administration access through `/DVD/APPD_ADMIN`.\n"
        "- Review legacy `/DVD/APPD_USER` usage and newer elementary/composite roles for monitored users, technical RFC users, HTTP SDK control, traces, local file access, and Gateway instrumentation.\n"
        "- Confirm HTTP SDK local or gateway ports, SDK Manager reachability, hostnames, IPv4, Java 8 or newer for gateway management, disk/log space, and latency placement.\n"
        "- Confirm BiQ Collector status: for SAP Agent 23.2.0+ it is included in ABAP Agent CORE and 740 transports, so do not plan a separate BiQ transport unless release notes require it.\n"
        "- Confirm SNP CrystalBridge Monitoring version compatibility before overwriting any newer installed SNP components.\n",
    )
    probes = out / "sap-validation-probes.sh"
    write(probes, "#!/usr/bin/env bash\nset -euo pipefail\necho 'Validate SAP Agent process, Controller registration, ABAP transport status, HTTP SDK or gateway connectivity, SNP CrystalBridge metrics/events, BiQ Collector business-process data, and SAP dashboards.'\n")
    chmod_exec(probes)


def render_skill_specific(skill: str, out: Path, spec: dict[str, Any]) -> None:
    if skill == PARENT_SKILL:
        children = sorted(name for name in SKILL_META if name != PARENT_SKILL)
        write(
            out / "child-orchestration-plan.md",
            "# Child Orchestration Plan\n\n"
            + "\n".join(f"- `{child}`: bash skills/{child}/scripts/setup.sh --render --spec skills/{child}/template.example" for child in children)
            + "\n\n- `cisco-appdynamics-setup`: delegated owner for Splunk_TA_AppDynamics inputs and dashboards.\n",
        )
        write(out / "doctor-summary.md", "# Doctor Summary\n\nRun each child validate.sh after rendering or applying its plan.\n")
        return

    if skill == "splunk-appdynamics-platform-setup":
        render_platform_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-controller-admin-setup":
        render_controller_admin_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-agent-management-setup":
        render_agent_management_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-apm-setup":
        render_apm_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-k8s-cluster-agent-setup":
        render_k8s_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-infrastructure-visibility-setup":
        render_infrastructure_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-database-visibility-setup":
        render_database_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-analytics-setup":
        render_analytics_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-eum-setup":
        render_eum_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-synthetic-monitoring-setup":
        render_synthetic_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-log-observer-connect-setup":
        render_log_observer_connect_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-alerting-content-setup":
        render_alerting_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-dashboards-reports-setup":
        render_dashboards_reports_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-tags-extensions-setup":
        render_tags_extensions_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-security-ai-setup":
        render_security_ai_artifacts(out, spec)
        return

    if skill == "splunk-appdynamics-sap-agent-setup":
        render_sap_artifacts(out, spec)


def render(skill: str, spec_path: Path, out: Path, json_output: bool) -> int:
    if skill not in SKILL_META:
        raise SystemExit(f"Unknown AppDynamics skill: {skill}")
    spec = load_yaml_or_json(spec_path)
    coverage = coverage_for_skill(skill)
    errors = validate_coverage(coverage)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    render_common_artifacts(skill, out, spec, coverage)
    render_skill_specific(skill, out, spec)
    result = {"status": "rendered", "skill": skill, "output_dir": str(out), "coverage_rows": len(coverage)}
    if json_output:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"Rendered {skill} to {out}")
    return 0


def validate_output(skill: str, out: Path, live: bool, json_output: bool) -> int:
    errors: list[str] = []
    notes: list[str] = []
    coverage_path = out / "coverage-report.json"
    if not coverage_path.exists():
        errors.append(f"missing {coverage_path}")
    else:
        payload = json.loads(coverage_path.read_text(encoding="utf-8"))
        errors.extend(validate_coverage(payload.get("features", [])))
        if payload.get("skill") != skill:
            errors.append(f"coverage-report skill mismatch: {payload.get('skill')} != {skill}")
    required_artifacts = REQUIRED_SKILL_ARTIFACTS.get(skill, set())
    if required_artifacts:
        missing = sorted(name for name in required_artifacts if not (out / name).exists())
        errors.extend(f"missing {skill} artifact {name}" for name in missing)
    if skill == "splunk-appdynamics-platform-setup":
        topology_path = out / "platform-topology-inventory.yaml"
        if topology_path.exists():
            topology = yaml.safe_load(topology_path.read_text(encoding="utf-8")) or {}
            if not as_dict(topology.get("platform")).get("name"):
                errors.append("platform topology missing platform.name")
            if not topology.get("hosts"):
                errors.append("platform topology missing host inventory")
        selector_path = out / "deployment-method-selector.yaml"
        if selector_path.exists():
            selector = yaml.safe_load(selector_path.read_text(encoding="utf-8")) or {}
            recommended = as_list(selector.get("recommended_methods"))
            supported = as_list(selector.get("supported_methods"))
            if not recommended:
                errors.append("deployment method selector missing recommended_methods")
            if len(supported) < len(ALL_PLATFORM_DEPLOYMENT_METHODS):
                errors.append("deployment method selector missing supported method coverage")
        if (out / "enterprise-console-command-plan.sh").exists():
            plan_text = (out / "enterprise-console-command-plan.sh").read_text(encoding="utf-8")
            if "controllerAdminPassword=" in plan_text or "mysqlRootPassword=" in plan_text:
                errors.append("Enterprise Console command plan must not render password arguments")
        if live:
            notes.append(f"run live platform probes with APPD_PLATFORM_LIVE=1 bash {out / 'platform-validation-probes.sh'}")
    elif skill == "splunk-appdynamics-k8s-cluster-agent-setup":
        values_path = out / "cluster-agent-values.yaml"
        if values_path.exists():
            values = yaml.safe_load(values_path.read_text(encoding="utf-8")) or {}
            if values.get("installSplunkOtelCollector") and "splunk-otel-collector" not in values:
                errors.append("cluster-agent-values.yaml enables installSplunkOtelCollector without splunk-otel-collector values")
            collector_values = as_dict(values.get("splunk-otel-collector"))
            splunk_observability = as_dict(collector_values.get("splunkObservability"))
            access_token = str(splunk_observability.get("accessToken", ""))
            if access_token and not access_token.startswith("${"):
                errors.append("splunk-otel-collector accessToken must be an env placeholder; use --set-file at apply time")
            if not as_dict(values.get("instrumentation")).get("languages"):
                errors.append("cluster-agent-values.yaml missing instrumentation.languages")
        env_path = out / "dual-signal-workload-env.yaml"
        if env_path.exists():
            env_text = env_path.read_text(encoding="utf-8")
            for marker in ("AGENT_DEPLOYMENT_MODE", "OTEL_EXPORTER_OTLP_ENDPOINT", "SPLUNK_REALM"):
                if marker == "SPLUNK_REALM" and "o11y_export: collector" in env_text:
                    continue
                if marker not in env_text:
                    errors.append(f"dual-signal-workload-env.yaml missing {marker}")
        rollout_path = out / "cluster-agent-rollout-plan.sh"
        if rollout_path.exists():
            rollout_text = rollout_path.read_text(encoding="utf-8")
            if "--set-file splunk-otel-collector.splunkObservability.accessToken" not in rollout_text:
                errors.append("cluster-agent-rollout-plan.sh must use --set-file for the O11y access token")
            if "K8S_APPLY=1" not in rollout_text:
                errors.append("cluster-agent-rollout-plan.sh must default to dry-run and require K8S_APPLY=1")
        if live:
            notes.append(f"run live Kubernetes probes with bash {out / 'cluster-agent-validation-probes.sh'}")
            notes.append(f"run live O11y probes with bash {out / 'o11y-export-validation.sh'}")
    elif live:
        errors.append("live validation is not implemented in the generic renderer; use child runbook probes")
    status = "pass" if not errors else "fail"
    result = {"status": status, "skill": skill, "output_dir": str(out), "errors": errors, "notes": notes}
    if json_output:
        print(json.dumps(result, sort_keys=True))
    else:
        if errors:
            for error in errors:
                print(f"FAIL: {error}", file=sys.stderr)
        else:
            print(f"PASS: {skill} rendered output validated at {out}")
            for note in notes:
                print(f"NOTE: {note}")
    return 0 if not errors else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    reject_direct_secrets(argv)
    parser = argparse.ArgumentParser(description="Splunk AppDynamics suite renderer")
    parser.add_argument("--skill", required=True, choices=sorted(SKILL_META))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--render", action="store_true")
    mode.add_argument("--apply", nargs="?", const="all", metavar="SECTIONS")
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--doctor", action="store_true")
    mode.add_argument("--quickstart", action="store_true")
    mode.add_argument("--rollback", nargs="?", const="all", metavar="SECTIONS")
    parser.add_argument("--spec", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--accept-remote-execution", action="store_true")
    parser.add_argument("--accept-enterprise-console-mutation", action="store_true")
    parser.add_argument("--accept-k8s-rollout", action="store_true")
    parser.add_argument("--accept-eum-source-edit", action="store_true")
    parser.add_argument("--accept-analytics-event-publish", action="store_true")
    return parser.parse_args(argv)


def gate_accepted(args: argparse.Namespace) -> bool:
    gate = SKILL_META[args.skill].get("gate")
    if gate is None:
        return True
    attr = GATE_FLAGS[gate].removeprefix("--").replace("-", "_")
    return bool(getattr(args, attr))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    skill_dir = SKILLS_DIR / args.skill
    spec = Path(args.spec) if args.spec else skill_dir / "template.example"
    out = Path(args.output_dir) if args.output_dir else REPO_ROOT / f"{args.skill}-rendered"

    if args.validate:
        return validate_output(args.skill, out, args.live, args.json)
    if args.doctor:
        result = {
            "status": "doctor",
            "skill": args.skill,
            "coverage_rows": len(coverage_for_skill(args.skill)),
            "apply_boundary": SKILL_META[args.skill]["apply"],
        }
        print(json.dumps(result, sort_keys=True) if args.json else f"{args.skill}: doctor OK; render and validate child output.")
        return 0
    if args.apply is not None:
        if not gate_accepted(args):
            gate = SKILL_META[args.skill]["gate"]
            print(f"FAIL: {args.skill} apply requires {GATE_FLAGS[gate]}", file=sys.stderr)
            return 2
        rc = render(args.skill, spec, out, args.json)
        if rc == 0 and not args.json:
            print("Apply mode rendered a reviewed apply plan; no live mutation was executed by the generic suite.")
        return rc
    if args.rollback is not None:
        coverage = coverage_for_skill(args.skill)
        out.mkdir(parents=True, exist_ok=True)
        write(out / "rollback-plan.sh", render_apply_plan(args.skill, coverage).replace("APPLY", "ROLLBACK"))
        print(json.dumps({"status": "rollback-rendered", "skill": args.skill, "output_dir": str(out)}, sort_keys=True) if args.json else f"Rendered rollback plan to {out}")
        return 0
    if args.quickstart:
        rc = render(args.skill, spec, out, args.json)
        if rc == 0 and not args.json:
            print(f"Next: bash skills/{args.skill}/scripts/validate.sh --output-dir {out}")
        return rc
    return render(args.skill, spec, out, args.json)


if __name__ == "__main__":
    raise SystemExit(main())

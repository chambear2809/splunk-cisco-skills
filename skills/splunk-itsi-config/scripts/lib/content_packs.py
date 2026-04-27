from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import tempfile
import time
from typing import Any
from copy import deepcopy
from urllib.parse import urlparse

from .common import (
    ValidationError,
    bool_from_any,
    ensure_dir,
    extract_indexes_from_expression,
    infer_platform,
    listify,
    looks_like_metrics_index,
    macro_mentions_indexes,
    semver_key,
    timestamp_slug,
    write_text,
)
from .native import NativeResult, NativeWorkflow
from .topology import (
    ServiceTopologyWorkflow,
    TopologyResult,
    _pack_contexts_by_profile,
    _title_candidates,
    compile_topology,
    validate_topology_pack_references,
)

ITSI_APP = "SA-ITOA"
ITSI_APP_ID = "1841"
CONTENT_LIBRARY_APP = "DA-ITSI-ContentLibrary"
CONTENT_LIBRARY_APP_ID = "5391"
DEFAULT_APP_INSTALL_SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "skills"
    / "splunk-app-install"
    / "scripts"
    / "install_app.sh"
)
SUPPORTED_CONFIGURED_OUTCOME_KEYS = {
    "native",
    "macros",
    "macro_updates",
    "saved_searches",
    "entity_discovery_searches",
}
DOCUMENTED_MANUAL_OUTCOME_HINTS = {
    "lookup_updates": "lookup updates",
    "lookups": "lookup updates",
    "data_model_accelerations": "data model acceleration",
    "data_models": "data model acceleration",
    "kpi_backfills": "KPI backfill",
    "backfills": "KPI backfill",
    "correlation_searches": "correlation-search or alert enablement",
    "alert_integrations": "alert integration",
    "service_imports": "service import",
    "service_discovery": "service discovery",
    "sandbox_publish": "sandbox publish",
    "navigation_updates": "navigation update",
    "dashboards": "dashboard tuning",
}

ITSI_HEALTH_APPS: list[dict[str, str]] = [
    {
        "app": ITSI_APP,
        "label": "SA-ITOA",
        "status": "error",
        "message": "SA-ITOA is not installed. ITSI core REST endpoints are unavailable.",
    },
    {
        "app": "itsi",
        "label": "itsi",
        "status": "error",
        "message": "itsi is not installed. The ITSI UI bundle is incomplete on this search head.",
    },
    {
        "app": "SA-UserAccess",
        "label": "SA-UserAccess",
        "status": "warn",
        "message": "SA-UserAccess is not installed. Some supporting ITSI sharing and access workflows may be unavailable.",
    },
    {
        "app": "SA-ITSI-Licensechecker",
        "label": "SA-ITSI-Licensechecker",
        "status": "warn",
        "message": "SA-ITSI-Licensechecker is not installed. ITSI licensing checks may be degraded.",
    },
]

ITSI_KVSTORE_COLLECTIONS = [
    "itsi_services",
    "itsi_kpi_template",
    "itsi_notable_event_group",
]


GENERIC_PROFILE_KEYS = {"catalog", "generic", "custom"}


GENERIC_CONTENT_PACK_STEPS = [
    "Review the content-pack preview object list before enabling searches, services, or dashboards.",
    "Complete any Data Integrations module steps exposed by the installed content pack.",
    "Validate required add-ons, indexes, macros, entity discovery searches, and saved-search enablement for this pack.",
    "Review service-template links, KPI thresholds, alerting behavior, and dashboard navigation before production use.",
]


def _catalog_profile(
    title: str,
    *,
    catalog_titles: list[str] | None = None,
    pack_app_candidates: list[str] | None = None,
    required_apps: list[dict[str, Any]] | None = None,
    alternative_app_groups: list[dict[str, Any]] | None = None,
    companion_app_checks: list[dict[str, Any]] | None = None,
    macro_checks: list[dict[str, Any]] | None = None,
    required_inputs: list[dict[str, Any]] | None = None,
    post_install_steps: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "catalog_titles": catalog_titles or [title],
        "pack_app_candidates": pack_app_candidates or [],
        "required_apps": required_apps or [],
        "alternative_app_groups": alternative_app_groups or [],
        "companion_app_checks": companion_app_checks or [],
        "macro_checks": macro_checks or [],
        "required_inputs": required_inputs or [],
        "post_install_steps": post_install_steps or GENERIC_CONTENT_PACK_STEPS,
        "automation_scope": "catalog_install_validate_with_guided_followup",
        "generic_catalog_profile": True,
    }


PACK_PROFILES: dict[str, dict[str, Any]] = {
    "aws": {
        "title": "Amazon Web Services Dashboards and Reports",
        "catalog_titles": ["Amazon Web Services Dashboards and Reports", "AWS Dashboards and Reports"],
        "pack_app_candidates": ["DA-ITSI-CP-aws-dashboards", "DA-ITSI-CP-aws"],
        "required_apps": [{"label": "Splunk Add-on for AWS", "candidates": ["Splunk_TA_aws"]}],
        "macro_checks": [
            {"macro": "aws-account-summary", "static_indexes_key": "summary_indexes", "default_indexes": ["summary"]},
            {"macro": "aws-sourcetype-index-summary", "static_indexes_key": "summary_indexes", "default_indexes": ["summary"]},
        ],
        "post_install_steps": [
            "Create or confirm the AWS summary indexes and run the Addon Synchronization saved search.",
            "Enable the AWS entity searches for EC2 Instance, EBS Volume, Lambda Function, and ELB Instance.",
            "Enable data model acceleration for the AWS dashboards you plan to use.",
            "On Splunk Enterprise, install PSC 1.2 only if you need EC2 insight recommendations.",
            "Optionally configure billing tags and any custom account or input summary index macros.",
        ],
    },
    "cisco_data_center": {
        "title": "Cisco Data Center",
        "pack_app_candidates": ["DA-ITSI-CP-cisco-data-center"],
        "required_apps": [
            {
                "label": "Cisco DC Networking App for Splunk",
                "candidates": ["cisco_dc_networking_app_for_splunk"],
            }
        ],
        "required_inputs": [
            {"app": "cisco_dc_networking_app_for_splunk", "pattern": "advisories", "label": "ND advisories input"},
            {"app": "cisco_dc_networking_app_for_splunk", "pattern": "anomalies", "label": "ND anomalies input"},
            {"app": "cisco_dc_networking_app_for_splunk", "pattern": "fabrics", "label": "ND fabrics input"},
            {"app": "cisco_dc_networking_app_for_splunk", "pattern": "switches", "label": "ND switches input"},
        ],
        "post_install_steps": [
            "Import Cisco Nexus Dashboard services from the service import module.",
            "Publish the Cisco Nexus Dashboard sandbox after the pre-check passes.",
            "Enable Cisco Nexus Dashboard services either in the sandbox or after publish.",
            "Enable the Nexus Dashboard entity discovery search.",
            "Configure Nexus Dashboard alerts integration for ITSI.",
            "Review KPI thresholds and configure KPI alerting.",
        ],
    },
    "cisco_enterprise_networks": {
        "title": "Cisco Enterprise Networks",
        "pack_app_candidates": ["DA-ITSI-CP-enterprise-networking"],
        "required_apps": [
            {"label": "Cisco Catalyst Add-on for Splunk", "candidates": ["TA_cisco_catalyst"]},
            {"label": "Cisco Meraki Add-on for Splunk", "candidates": ["Splunk_TA_cisco_meraki"]},
        ],
        "required_inputs": [
            {"app": "TA_cisco_catalyst", "pattern": "cisco_catalyst_dnac_issue://", "label": "Catalyst issues input"},
            {"app": "TA_cisco_catalyst", "pattern": "cisco_catalyst_dnac_networkhealth://", "label": "Catalyst network health input"},
            {"app": "TA_cisco_catalyst", "pattern": "cisco_catalyst_dnac_securityadvisory://", "label": "Catalyst advisory input"},
            {"app": "Splunk_TA_cisco_meraki", "pattern": "cisco_meraki_assurance_alerts://", "label": "Meraki assurance alerts input"},
            {"app": "Splunk_TA_cisco_meraki", "pattern": "cisco_meraki_devices://", "label": "Meraki devices input"},
            {"app": "Splunk_TA_cisco_meraki", "pattern": "cisco_meraki_organizations://", "label": "Meraki organizations input"},
        ],
        "macro_checks": [
            {"macro": "itsi_cp_catalyst_center_index", "source_app": "TA_cisco_catalyst", "source_fields": ["index"]},
            {
                "macro": "meraki_index",
                "app": "Splunk_TA_cisco_meraki",
                "source_app": "Splunk_TA_cisco_meraki",
                "source_fields": ["index"],
            },
        ],
        "post_install_steps": [
            "Import services from Cisco Catalyst Center and Cisco Meraki.",
            "Publish the Catalyst Center and Meraki services from the sandbox.",
            "Enable the Catalyst Center and Meraki services if they remain disabled.",
            "Enable the Catalyst Center and Meraki entity discovery searches.",
            "Configure Catalyst Center and Meraki alerts integration for ITSI.",
            "Review KPI thresholds and KPI alerting.",
        ],
    },
    "cisco_thousandeyes": {
        "title": "Cisco ThousandEyes",
        "pack_app_candidates": ["DA-ITSI-CP-thousandeyes", "DA-ITSI-CP-cisco-thousandeyes"],
        "required_apps": [{"label": "Cisco ThousandEyes App for Splunk", "candidates": ["ta_cisco_thousandeyes"]}],
        "required_inputs": [
            {"app": "ta_cisco_thousandeyes", "pattern": "event", "label": "ThousandEyes events input"},
        ],
        "macro_discovery": {"contains": ["index", "thousandeyes"]},
        "post_install_steps": [
            "Enable the Cisco ThousandEyes services after import if they remain disabled.",
            "Enable the Cisco ThousandEyes entity discovery searches.",
            "Review KPI thresholds and KPI alerting.",
        ],
    },
    "linux": {
        "title": "Monitoring Unix and Linux",
        "pack_app_candidates": ["DA-ITSI-CP-nix", "DA-ITSI-CP-linux"],
        "companion_app_checks": [
            {
                "label": "Unix and Linux dashboards companion app",
                "candidates": ["DA-ITSI-CP-unix-dashboards"],
            }
        ],
        "required_apps": [{"label": "Splunk Add-on for Unix and Linux", "candidates": ["Splunk_TA_nix"]}],
        "macro_checks": [
            {"macro": "itsi-cp-nix-indexes", "static_indexes_key": "event_indexes", "default_indexes": ["os"]},
        ],
        "post_install_steps": [
            "Update the itsi_os_module_indexes macro if you use the ITSI Operating System module dashboards.",
            "Update the itsi-cp-nix-indexes macro if your Unix and Linux event data does not use the default os index.",
            "If you ingest events or mixed-mode data, update the monitoring_unix_* wrapper macros to match the ingestion mode.",
            "Enable recurring entity discovery for Unix and Linux hosts.",
            "Create a new service from the Unix and Linux server health template or link the template to existing services.",
            "Tune the KPI base searches and threshold levels for your environment.",
        ],
    },
    "splunk_appdynamics": {
        "title": "Splunk AppDynamics",
        "pack_app_candidates": ["DA-ITSI-CP-appdynamics", "DA-ITSI-CP-APPDYNAMICS"],
        "required_apps": [{"label": "Splunk Add-on for AppDynamics", "candidates": ["Splunk_TA_AppDynamics"]}],
        "required_inputs": [
            {"app": "Splunk_TA_AppDynamics", "pattern": "appdynamics_status", "label": "AppDynamics status input"},
        ],
        "macro_checks": [
            {
                "macro": "itsi_cp_appdynamics_index",
                "source_app": "Splunk_TA_AppDynamics",
                "source_conf": {"name": "splunk_ta_appdynamics_settings", "stanza": "additional_parameters", "field": "index"},
                "source_fields": ["index"],
            }
        ],
        "post_install_steps": [
            "Use the Splunk AppDynamics Import Applications dashboard to import services.",
            "Publish the imported AppDynamics sandbox.",
            "Enable the AppDynamics entity searches.",
            "Review KPI thresholds and KPI alerting.",
        ],
    },
    "splunk_observability_cloud": {
        "title": "Splunk Observability Cloud",
        "pack_app_candidates": ["DA-ITSI-CP-splunk-observability"],
        "required_apps": [
            {
                "label": "Splunk Infrastructure Monitoring Add-on",
                "candidates": ["splunk_ta_sim", "Splunk_TA_sim", "Splunk_TA_SIM"],
            }
        ],
        "required_inputs": [],
        "macro_checks": [{"macro": "itsi-cp-observability-indexes", "static_indexes_key": "metrics_indexes"}],
        "post_install_steps": [
            "Enable the Splunk Observability Cloud entity discovery searches.",
            "Optionally enable the saved searches used for Splunk APM Business Workflows.",
            "Review KPI thresholds and KPI alerting.",
            "If you use a custom Observability Cloud subdomain, update the entity navigation links manually.",
        ],
    },
    "vmware": {
        "title": "VMware Monitoring",
        "pack_app_candidates": ["DA-ITSI-CP-vmware", "DA-ITSI-CP-vmware-monitoring"],
        "companion_app_checks": [
            {
                "label": "VMware dashboards companion app",
                "candidates": ["DA-ITSI-CP-vmware-dashboards"],
            }
        ],
        "required_apps": [
            {
                "label": "Splunk Add-on for VMware Metrics",
                "candidates": ["Splunk_TA_vmware_inframon", "Splunk_TA_VMware_inframon", "SA-Hydra-inframon", "SA-VMWIndex-inframon"],
            }
        ],
        "macro_checks": [
            {
                "macro": "cp_vmware_perf_metrics_index",
                "static_indexes_key": "metrics_indexes",
                "default_indexes": ["vmware-perf-metrics"],
            }
        ],
        "post_install_steps": [
            "Review and tune the VMware KPI base searches to match your data collection cadence and indexes.",
            "Tune the service-template thresholds for ESXi, virtual machines, vCenter, and datastores.",
            "Use the packaged service templates as the starting point for your VMware services.",
            "Expand the simple sample topology into a deployment-specific service tree, often by CSV imports and template linking.",
        ],
    },
    "windows": {
        "title": "Monitoring Microsoft Windows",
        "pack_app_candidates": ["DA-ITSI-CP-windows"],
        "companion_app_checks": [
            {
                "label": "Windows dashboards companion app",
                "candidates": ["DA-ITSI-CP-windows-dashboards"],
            }
        ],
        "required_apps": [{"label": "Splunk Add-on for Windows", "candidates": ["Splunk_TA_windows"]}],
        "macro_checks": [
            {
                "macro": "itsi-cp-windows-indexes",
                "static_indexes_key": "event_indexes",
                "default_indexes": ["windows", "perfmon"],
            },
            {
                "macro": "itsi-cp-windows-metrics-indexes",
                "static_indexes_key": "metrics_indexes",
                "default_indexes": ["itsi_im_metrics"],
            },
        ],
        "post_install_steps": [
            "Update the Windows event and metrics index macros if you use non-default indexes.",
            "If you do not use the recommended metrics ingestion mode, update the monitoring_windows_* wrapper macros accordingly.",
            "Enable recurring entity discovery for Windows hosts.",
            "Create a new service from the Windows server health template or link the template to existing services.",
            "Tune the KPI base searches and threshold levels for your environment.",
        ],
    },
    "example_glass_tables": _catalog_profile(
        "Example Glass Tables",
        pack_app_candidates=["DA-ITSI-CP-example-glass-tables"],
        post_install_steps=[
            "Review the example glass tables and clone only the layouts that match your use case.",
            "Replace static example data sources with production service, KPI, or search-backed tokens.",
        ],
    ),
    "ite_work_alert_routing": _catalog_profile(
        "ITE Work Alert Routing",
        pack_app_candidates=["DA-ITSI-CP-ite-work-alert-routing"],
        companion_app_checks=[
            {"label": "Splunk On-Call", "candidates": ["splunk_app_on_call", "victorops_app_for_splunk"]},
            {"label": "Splunk Add-on for ServiceNow", "candidates": ["Splunk_TA_snow", "Splunk_TA_servicenow"]},
        ],
        post_install_steps=[
            "Confirm this ITE Work-focused pack is appropriate for the target environment before enabling alert actions.",
            "Configure optional Splunk On-Call or ServiceNow routing integrations if those actions are required.",
            "Review and enable only the saved searches and actions needed for alert routing.",
        ],
    ),
    "itsi_monitoring_and_alerting": _catalog_profile(
        "ITSI Monitoring and Alerting",
        pack_app_candidates=["DA-ITSI-CP-itsi-monitoring-and-alerting"],
        companion_app_checks=[
            {"label": "Lookup File Editor", "candidates": ["lookup_editor", "splunk_app_lookup_editor"]},
            {"label": "Punchcard Visualization", "candidates": ["punchcard_app", "punchcard_custom_viz"]},
        ],
        post_install_steps=[
            "Review the included alerting lookup files and populate local ownership, routing, and enrichment values.",
            "Install optional dashboard dependencies such as Lookup File Editor or Punchcard visualization when needed.",
            "Enable and tune the monitoring saved searches for your ITSI service and episode volumes.",
        ],
    ),
    "microsoft_365": _catalog_profile(
        "Microsoft 365",
        pack_app_candidates=["DA-ITSI-CP-microsoft-365", "DA-ITSI-CP-o365"],
        required_apps=[
            {
                "label": "Splunk Add-on for Microsoft Office 365",
                "candidates": ["splunk_ta_o365", "Splunk_TA_o365", "Splunk_TA_microsoft-cloudservices", "Splunk_TA_MS_O365"],
            }
        ],
        macro_checks=[
            {"macro": "itsi-cp-microsoft-365-indexes", "static_indexes_key": "event_indexes", "optional": True},
            {"macro": "itsi-cp-o365-indexes", "static_indexes_key": "event_indexes", "optional": True},
        ],
        post_install_steps=[
            "Confirm Microsoft 365 data is ingested by the Splunk Add-on for Microsoft Office 365.",
            "Align the content-pack macros with your Microsoft 365 event indexes.",
            "Enable entity discovery, service templates, and saved searches only after validating data freshness.",
        ],
    ),
    "microsoft_exchange": _catalog_profile(
        "Microsoft Exchange",
        pack_app_candidates=["DA-ITSI-CP-microsoft-exchange"],
        required_apps=[
            {
                "label": "Splunk Add-on for Microsoft Exchange",
                "candidates": ["Splunk_TA_microsoft_exchange", "Splunk_TA_windows_exchange", "TA-Exchange-Mailbox"],
            }
        ],
        macro_checks=[
            {"macro": "itsi-cp-microsoft-exchange-indexes", "static_indexes_key": "event_indexes", "optional": True},
            {"macro": "itsi-cp-exchange-indexes", "static_indexes_key": "event_indexes", "optional": True},
        ],
        post_install_steps=[
            "Confirm Exchange data is ingested by the Splunk Add-on for Microsoft Exchange.",
            "Align the Exchange macros with your mailbox, transport, and host indexes.",
            "Review service templates, entity discovery, and thresholds before enabling alerting.",
        ],
    ),
    "citrix": _catalog_profile(
        "Monitoring Citrix",
        pack_app_candidates=["DA-ITSI-CP-citrix"],
        required_apps=[
            {"label": "Add-on for the Content Pack for Monitoring Citrix", "candidates": ["Splunk_TA_citrix", "TA-citrix-cp", "DA-ITSI-TA-citrix"]},
            {"label": "Splunk Add-on for Microsoft IIS", "candidates": ["Splunk_TA_microsoft-iis", "Splunk_TA_iis"]},
            {"label": "Template for Citrix XenDesktop 7", "candidates": ["Splunk_TA_xendesktop7", "TA-XD7", "TA-Citrix-XenDesktop7"]},
            {"label": "Splunk Add-on for Citrix NetScaler", "candidates": ["Splunk_TA_citrix_netscaler", "TA-NetScaler"]},
        ],
        post_install_steps=[
            "Confirm Citrix, IIS, XenDesktop, and NetScaler prerequisite data sources are present where used.",
            "Align macros and service templates with the Citrix components deployed in this environment.",
            "Review KPI base searches and thresholds before enabling Citrix services.",
        ],
    ),
    "pivotal_cloud_foundry": _catalog_profile(
        "Monitoring Pivotal Cloud Foundry",
        pack_app_candidates=["DA-ITSI-CP-pivotal-cloud-foundry", "DA-ITSI-CP-pcf"],
        companion_app_checks=[
            {"label": "Splunk Firehose Nozzle for PCF", "candidates": ["splunk-firehose-nozzle", "Splunk_TA_pcf", "TA-pivotal-cloud-foundry"]},
        ],
        post_install_steps=[
            "Confirm Pivotal Cloud Foundry events and metrics are ingested from the firehose nozzle.",
            "Align indexes and macros with your PCF foundation naming and ingestion mode.",
            "Review entity discovery, service templates, and saved searches before enabling services.",
        ],
    ),
    "splunk_as_a_service": _catalog_profile(
        "Monitoring Splunk as a Service",
        pack_app_candidates=["DA-ITSI-CP-splunk-as-a-service"],
        macro_checks=[
            {"macro": "itsi-cp-splunk-as-a-service-indexes", "static_indexes_key": "event_indexes", "default_indexes": ["_internal"], "optional": True},
        ],
        post_install_steps=[
            "Review the Splunk service monitoring searches against your deployment topology and indexes.",
            "Tune thresholds for search head, indexer, forwarder, and platform-health services.",
            "Enable saved searches progressively and validate episode noise before production use.",
        ],
    ),
    "netapp_data_ontap_dashboards_reports": _catalog_profile(
        "NetApp Data ONTAP Dashboards and Reports",
        pack_app_candidates=["DA-ITSI-CP-netapp-data-ontap-dashboards", "DA-ITSI-CP-netapp"],
        required_apps=[
            {"label": "Splunk Add-on for NetApp Data ONTAP", "candidates": ["Splunk_TA_ontap", "Splunk_TA_netapp"]},
            {"label": "Splunk Add-on for NetApp Data ONTAP Indexes", "candidates": ["Splunk_TA_ontap_indexes", "SA-ontap-indexes"]},
            {"label": "Splunk Add-on for NetApp Data ONTAP Extractions", "candidates": ["Splunk_TA_ontap_extractions", "TA-ontap-extractions"]},
        ],
        post_install_steps=[
            "Confirm the NetApp Data ONTAP add-ons and index packages are installed where data is collected.",
            "Review NetApp dashboard macros and saved searches after the automatically installed dashboard pack is visible.",
            "Tune storage thresholds and dashboard navigation for the monitored arrays.",
        ],
    ),
    "servicenow": _catalog_profile(
        "ServiceNow",
        pack_app_candidates=["DA-ITSI-CP-servicenow"],
        required_apps=[
            {"label": "Splunk Add-on for ServiceNow", "candidates": ["Splunk_TA_snow", "Splunk_TA_servicenow"]},
        ],
        companion_app_checks=[
            {"label": "Dendrogram Viz", "candidates": ["dendrogram-viz", "dendrogram_app", "DA-ITSI-DendrogramViz"]},
        ],
        post_install_steps=[
            "Confirm ServiceNow data is ingested by the Splunk Add-on for ServiceNow.",
            "Install optional visualization dependencies, such as Dendrogram Viz, when dashboard panels require them.",
            "Review ServiceNow service templates, ticketing links, and thresholds before enabling actions.",
        ],
    ),
    "shared_it_infrastructure": _catalog_profile(
        "Shared IT Infrastructure Components",
        pack_app_candidates=["DA-ITSI-CP-shared-it-infrastructure-components", "DA-ITSI-CP-shared-it-infrastructure"],
        post_install_steps=[
            "Review the shared infrastructure dependency model and adapt it to local service ownership.",
            "Map packaged infrastructure components to production services before enabling dependency edges.",
            "Validate any _internal searches against retention and access requirements.",
        ],
    ),
    "soar_system_logs": _catalog_profile(
        "SOAR System Logs",
        pack_app_candidates=["DA-ITSI-CP-soar-system-logs"],
        required_apps=[
            {"label": "Splunk Add-on for Unix and Linux", "candidates": ["Splunk_TA_nix"]},
            {"label": "Splunk App for SOAR", "candidates": ["phantom", "Splunk_SA_Scientific_Python_linux_x86_64", "splunk_app_soar"]},
        ],
        post_install_steps=[
            "Confirm SOAR and Unix/Linux log data is ingested into the expected indexes.",
            "Align SOAR log macros, service templates, and entity discovery with the monitored SOAR deployment.",
            "Review saved searches and KPI thresholds before enabling alerting.",
        ],
    ),
    "splunk_synthetic_monitoring": _catalog_profile(
        "Splunk Synthetic Monitoring",
        pack_app_candidates=["DA-ITSI-CP-splunk-synthetic-monitoring", "DA-ITSI-CP-synthetic-monitoring"],
        required_apps=[
            {
                "label": "Splunk Synthetic Monitoring Add-on",
                "candidates": ["Splunk_TA_synthetic_monitoring", "splunk_ta_synthetic_monitoring", "Splunk_TA_synthetics"],
            }
        ],
        macro_checks=[
            {"macro": "itsi-cp-synthetic-monitoring-indexes", "static_indexes_key": "metrics_indexes", "optional": True},
        ],
        post_install_steps=[
            "Confirm the Splunk Synthetic Monitoring Add-on is collecting synthetic checks.",
            "Align metrics indexes and macros with the Synthetic Monitoring ingestion path.",
            "Review service templates, entity links, and KPI thresholds before enabling services.",
        ],
    ),
    "third_party_apm": _catalog_profile(
        "Third-Party APM",
        pack_app_candidates=["DA-ITSI-CP-third-party-apm"],
        alternative_app_groups=[
            {
                "label": "Dynatrace or New Relic add-on",
                "apps": [
                    {"label": "Dynatrace Add-on for Splunk", "candidates": ["TA-Dynatrace", "Splunk_TA_dynatrace"]},
                    {"label": "Splunk Add-on for New Relic", "candidates": ["Splunk_TA_new_relic", "TA-New-Relic"]},
                ],
            }
        ],
        macro_checks=[
            {"macro": "itsi-cp-third-party-apm-indexes", "static_indexes_key": "event_indexes", "optional": True},
        ],
        post_install_steps=[
            "Confirm Dynatrace or New Relic add-on data is present for the monitored applications.",
            "Align third-party APM macros with the event indexes used by those add-ons.",
            "Review service templates and KPI thresholds before enabling APM services.",
        ],
    ),
    "unix_dashboards_reports": _catalog_profile(
        "Unix Dashboards and Reports",
        pack_app_candidates=["DA-ITSI-CP-unix-dashboards"],
        required_apps=[{"label": "Splunk Add-on for Unix and Linux", "candidates": ["Splunk_TA_nix"]}],
        post_install_steps=[
            "Confirm the Unix and Linux dashboard companion pack is visible after content-library install.",
            "Align dashboard and OS-module macros with your Unix and Linux indexes.",
            "Review dashboard saved searches and panels before using them as operational views.",
        ],
    ),
    "vmware_dashboards_reports": _catalog_profile(
        "VMware Dashboards and Reports",
        pack_app_candidates=["DA-ITSI-CP-vmware-dashboards"],
        required_apps=[
            {
                "label": "Splunk Add-on for VMware Metrics",
                "candidates": ["Splunk_TA_vmware_inframon", "Splunk_TA_VMware_inframon", "SA-Hydra-inframon", "SA-VMWIndex-inframon"],
            }
        ],
        post_install_steps=[
            "Confirm the VMware dashboard companion pack is visible after content-library install.",
            "Align VMware dashboard macros with your VMware metrics and event indexes.",
            "Review dashboard saved searches and panels before using them as operational views.",
        ],
    ),
    "windows_dashboards_reports": _catalog_profile(
        "Windows Dashboards and Reports",
        pack_app_candidates=["DA-ITSI-CP-windows-dashboards"],
        required_apps=[{"label": "Splunk Add-on for Windows", "candidates": ["Splunk_TA_windows"]}],
        companion_app_checks=[
            {"label": "Splunk Supporting Add-on for Active Directory", "candidates": ["SA-ldapsearch", "Splunk_SA_LDAPSearch", "TA-DomainController-2012R2"]},
        ],
        post_install_steps=[
            "Confirm the Windows dashboard companion pack is visible after content-library install.",
            "Align Windows and Active Directory dashboard macros with your event and metrics indexes.",
            "Review dashboard saved searches and panels before using them as operational views.",
        ],
    ),
}


@dataclass
class PackRun:
    profile: str
    title: str
    pack_id: str | None
    version: str | None
    findings: list[dict[str, str]]
    preview_summary: dict[str, Any] | None
    install_payload: dict[str, Any] | None
    install_result: Any = None
    installed: bool = False
    automation_scope: str = "profile_install_validate_with_guided_followup"
    follow_up_required: bool = True
    follow_up_steps: list[str] = field(default_factory=list)
    pack_status: dict[str, Any] | None = None
    pack_detail: dict[str, Any] | None = None
    configured_outcome: dict[str, Any] | None = None


def _safe_tar_extract_shell_command() -> str:
    return r'''python3 - "$archive" "$workdir" <<'PY'
import os
from pathlib import PurePosixPath
import sys
import tarfile


def fail(message):
    print(f"ERROR: Unsafe archive member: {message}", file=sys.stderr)
    sys.exit(1)


def safe_relative_path(value):
    normalized = str(value or "").replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    return bool(normalized) and not path.is_absolute() and ".." not in path.parts


archive_path, destination = sys.argv[1], sys.argv[2]
destination = os.path.abspath(destination)
with tarfile.open(archive_path, "r:*") as archive:
    members = archive.getmembers()
    for member in members:
        if not safe_relative_path(member.name):
            fail(member.name)
        target = os.path.abspath(os.path.join(destination, member.name))
        if os.path.commonpath([destination, target]) != destination:
            fail(member.name)
        if member.isdev() or member.isfifo():
            fail(f"{member.name} uses a special file type")
        if member.issym() or member.islnk():
            if not safe_relative_path(member.linkname):
                fail(f"{member.name} -> {member.linkname}")
            link_target = os.path.abspath(os.path.join(os.path.dirname(target), member.linkname))
            if os.path.commonpath([destination, link_target]) != destination:
                fail(f"{member.name} -> {member.linkname}")
    try:
        archive.extractall(destination, members=members, filter="data")
    except TypeError:
        archive.extractall(destination, members=members)
PY
'''


class ShellContentLibraryInstaller:
    def __init__(
        self,
        script_path: str | Path | None = None,
        runner: Any | None = None,
        *,
        spec_key: str = "content_library",
        app_name: str = CONTENT_LIBRARY_APP,
        default_app_id: str = CONTENT_LIBRARY_APP_ID,
        display_name: str = "Splunk App for Content Packs",
    ):
        self.script_path = Path(script_path) if script_path else DEFAULT_APP_INSTALL_SCRIPT
        self.runner = runner or subprocess.run
        self.spec_key = spec_key
        self.app_name = app_name
        self.default_app_id = default_app_id
        self.display_name = display_name

    def _build_env(self, spec: dict[str, Any], client: Any) -> dict[str, str]:
        env = os.environ.copy()
        connection = spec.get("connection", {})
        base_url = str(connection.get("base_url") or env.get("SPLUNK_SEARCH_API_URI") or env.get("SPLUNK_URI") or "").strip()
        if base_url:
            env["SPLUNK_SEARCH_API_URI"] = base_url
            env["SPLUNK_URI"] = base_url
        verify_ssl_source = connection.get("verify_ssl")
        if verify_ssl_source is None:
            verify_ssl_source = env.get("SPLUNK_VERIFY_SSL")
        verify_ssl = bool_from_any(verify_ssl_source, default=True)
        env["SPLUNK_VERIFY_SSL"] = "true" if verify_ssl else "false"
        username = getattr(getattr(client, "config", None), "username", None)
        password = getattr(getattr(client, "config", None), "password", None)
        session_key = getattr(getattr(client, "config", None), "session_key", None)
        if username:
            env["SPLUNK_USERNAME"] = str(username)
            env["SPLUNK_USER"] = str(username)
        if password:
            env["SPLUNK_PASSWORD"] = str(password)
            env["SPLUNK_PASS"] = str(password)
        if session_key:
            env["SPLUNK_SESSION_KEY"] = str(session_key)
        credentials_file = str(spec.get(self.spec_key, {}).get("credentials_file") or "").strip()
        if credentials_file:
            env["SPLUNK_CREDENTIALS_FILE"] = credentials_file
        return env

    def _run_command(self, command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
        except OSError as exc:
            raise ValidationError(f"Failed to execute {' '.join(command[:2])}: {exc}") from exc

    @staticmethod
    def _without_secret_env(env: dict[str, str]) -> dict[str, str]:
        safe_env = dict(env)
        for key in (
            "SPLUNK_PASSWORD",
            "SPLUNK_PASS",
            "SPLUNK_SESSION_KEY",
            "SPLUNK_SSH_PASS",
            "SPLUNK_MCP_TOKEN",
        ):
            safe_env.pop(key, None)
        return safe_env

    def _write_secret_file(self, *values: str) -> Path:
        fd, raw_path = tempfile.mkstemp(prefix="codex-splunk-secret.")
        path = Path(raw_path)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for value in values:
                    handle.write(str(value))
                    handle.write("\n")
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            path.unlink(missing_ok=True)
            raise
        return path

    def _bundle_extract_install_command(
        self,
        archive_path: str,
        *,
        splunk_bin: str,
        auth_file: str,
        cleanup_archive: bool,
        cleanup_auth_file: bool,
        background_restart: bool = False,
    ) -> str:
        apps_dir = str(Path(splunk_bin).parent.parent / "etc" / "apps")
        cleanup_steps = ['rm -rf "$workdir"']
        if cleanup_archive:
            cleanup_steps.append('rm -f "$archive"')
        if cleanup_auth_file:
            cleanup_steps.append('rm -f "$auth_file"')
        cleanup_body = "; ".join(cleanup_steps)
        restart_credentials = (
            'auth_user=$(sed -n "1p" "$auth_file"); '
            'auth_pass=$(sed -n "2p" "$auth_file"); '
            'rm -f "$auth_file"; '
        )
        restart_command = restart_credentials + 'printf \'%s\\n%s\\n\' "$auth_user" "$auth_pass" | "$splunk_bin" restart'
        if background_restart:
            restart_command = (
                'restart_log=/tmp/codex-splunk-restart.log; '
                + restart_credentials
                + 'printf \'%s\\n%s\\n\' "$auth_user" "$auth_pass" | nohup "$splunk_bin" restart >"$restart_log" 2>&1 & '
                'echo "Triggered Splunk restart in background: $restart_log"; '
                'sleep 2'
            )
        return (
            "set -e\n"
            f"archive={shlex.quote(archive_path)}\n"
            f"apps_dir={shlex.quote(apps_dir)}\n"
            f"splunk_bin={shlex.quote(splunk_bin)}\n"
            f"auth_file={shlex.quote(auth_file)}\n"
            'chmod 600 "$auth_file" 2>/dev/null || true\n'
            "workdir=$(mktemp -d /tmp/codex-bundle.XXXXXX)\n"
            f"cleanup() {{ {cleanup_body}; }}\n"
            "trap cleanup EXIT\n"
            'mkdir -p "$apps_dir"\n'
            f"{_safe_tar_extract_shell_command()}\n"
            "found=0\n"
            "installed=0\n"
            'for app_dir in "$workdir"/*; do\n'
            '  [ -d "$app_dir" ] || continue\n'
            "  found=1\n"
            '  app_name=$(basename "$app_dir")\n'
            '  dest="$apps_dir/$app_name"\n'
            '  if [ -e "$dest" ]; then\n'
            '    echo "Skipping existing extracted app $app_name"\n'
            "    continue\n"
            "  fi\n"
            '  cp -R "$app_dir" "$dest"\n'
            '  echo "Installed extracted app $app_name"\n'
            "  installed=$((installed+1))\n"
            "done\n"
            'if [ "$found" -ne 1 ]; then\n'
            '  echo "No app directories found in bundle archive." >&2\n'
            "  exit 1\n"
            "fi\n"
            'if [ "$installed" -eq 0 ]; then\n'
            '  echo "No new apps were extracted from bundle archive." >&2\n'
            "  exit 1\n"
            "fi\n"
            f"{restart_command}\n"
        )

    def _cli_install_bundle(self, local_file: Path, spec: dict[str, Any], client: Any, env: dict[str, str]) -> dict[str, Any]:
        base_url = str(env.get("SPLUNK_SEARCH_API_URI") or env.get("SPLUNK_URI") or "").strip()
        username = env.get("SPLUNK_USERNAME") or getattr(getattr(client, "config", None), "username", None)
        password = env.get("SPLUNK_PASSWORD") or getattr(getattr(client, "config", None), "password", None)
        if not base_url:
            raise ValidationError(f"Automatic {self.display_name.lower()} bundle fallback requires a Splunk base URL.")
        auth = f"{username}:{password}" if username and password else ""
        if not auth:
            raise ValidationError(
                f"Automatic {self.display_name.lower()} bundle fallback requires Splunk username/password credentials."
            )

        section = spec.get(self.spec_key, {})
        splunk_bin = str(section.get("remote_splunk_bin") or "/opt/splunk/bin/splunk")
        auth_file = self._write_secret_file(str(username), str(password))

        if _is_local_target(base_url):
            try:
                install_process = self._run_command(
                    [
                        "bash",
                        "-lc",
                        self._bundle_extract_install_command(
                            str(local_file),
                            splunk_bin=splunk_bin,
                            auth_file=str(auth_file),
                            cleanup_archive=False,
                            cleanup_auth_file=True,
                        ),
                    ],
                    self._without_secret_env(env),
                )
            finally:
                auth_file.unlink(missing_ok=True)
            if install_process.returncode != 0:
                raise ValidationError(
                    f"Automatic {self.display_name.lower()} bundle fallback failed: "
                    + _summarize_command_output(install_process.stdout, install_process.stderr)
                )
            return {
                "attempted": True,
                "installed": True,
                "source": "local-extract",
                "message": _summarize_command_output(install_process.stdout, install_process.stderr),
            }

        ssh_host = str(env.get("SPLUNK_SSH_HOST") or _target_host(base_url)).strip()
        ssh_port = str(env.get("SPLUNK_SSH_PORT") or "22").strip() or "22"
        ssh_user = str(env.get("SPLUNK_SSH_USER") or username or "splunk").strip() or "splunk"
        ssh_pass = str(env.get("SPLUNK_SSH_PASS") or password or "").strip()
        if not ssh_host or not ssh_pass:
            auth_file.unlink(missing_ok=True)
            raise ValidationError(
                f"Automatic {self.display_name.lower()} bundle fallback requires SSH credentials. Set SPLUNK_SSH_HOST/SPLUNK_SSH_USER/SPLUNK_SSH_PASS or provide matching Splunk credentials."
            )

        remote_tmp = f"/tmp/{local_file.stem}.{os.getpid()}.{self.default_app_id}{local_file.suffix}"
        remote_auth_file = f"/tmp/{local_file.stem}.{os.getpid()}.{self.default_app_id}.auth"
        try:
            ssh_pass_file = self._write_secret_file(ssh_pass)
        except Exception:
            auth_file.unlink(missing_ok=True)
            raise
        ssh_env = self._without_secret_env(env)
        remote_cleanup_needed = False
        ssh_process: subprocess.CompletedProcess[str] | None = None
        try:
            scp_process = self._run_command(
                [
                    "sshpass",
                    "-f",
                    str(ssh_pass_file),
                    "scp",
                    "-P",
                    ssh_port,
                    "-o",
                    "ConnectTimeout=15",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-o",
                    "PubkeyAuthentication=no",
                    "-o",
                    "PreferredAuthentications=password",
                    "-q",
                    str(local_file),
                    f"{ssh_user}@{ssh_host}:{remote_tmp}",
                ],
                ssh_env,
            )
            if scp_process.returncode != 0:
                raise ValidationError(
                    f"Automatic {self.display_name.lower()} SSH staging failed: "
                    + _summarize_command_output(scp_process.stdout, scp_process.stderr)
                )
            remote_cleanup_needed = True

            scp_auth_process = self._run_command(
                [
                    "sshpass",
                    "-f",
                    str(ssh_pass_file),
                    "scp",
                    "-P",
                    ssh_port,
                    "-o",
                    "ConnectTimeout=15",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-o",
                    "PubkeyAuthentication=no",
                    "-o",
                    "PreferredAuthentications=password",
                    "-q",
                    str(auth_file),
                    f"{ssh_user}@{ssh_host}:{remote_auth_file}",
                ],
                ssh_env,
            )
            if scp_auth_process.returncode != 0:
                raise ValidationError(
                    f"Automatic {self.display_name.lower()} SSH credential staging failed: "
                    + _summarize_command_output(scp_auth_process.stdout, scp_auth_process.stderr)
                )

            remote_command = self._bundle_extract_install_command(
                remote_tmp,
                splunk_bin=splunk_bin,
                auth_file=remote_auth_file,
                cleanup_archive=True,
                cleanup_auth_file=True,
                background_restart=True,
            )
            ssh_process = self._run_command(
                [
                    "sshpass",
                    "-f",
                    str(ssh_pass_file),
                    "ssh",
                    "-p",
                    ssh_port,
                    "-o",
                    "ConnectTimeout=15",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-o",
                    "PubkeyAuthentication=no",
                    "-o",
                    "PreferredAuthentications=password",
                    f"{ssh_user}@{ssh_host}",
                    remote_command,
                ],
                ssh_env,
            )
        finally:
            if remote_cleanup_needed and (ssh_process is None or ssh_process.returncode != 0):
                cleanup_command = f"rm -f {shlex.quote(remote_tmp)} {shlex.quote(remote_auth_file)}"
                try:
                    self._run_command(
                        [
                            "sshpass",
                            "-f",
                            str(ssh_pass_file),
                            "ssh",
                            "-p",
                            ssh_port,
                            "-o",
                            "ConnectTimeout=15",
                            "-o",
                            "StrictHostKeyChecking=accept-new",
                            "-o",
                            "PubkeyAuthentication=no",
                            "-o",
                            "PreferredAuthentications=password",
                            f"{ssh_user}@{ssh_host}",
                            cleanup_command,
                        ],
                        ssh_env,
                    )
                except ValidationError:
                    pass
            auth_file.unlink(missing_ok=True)
            ssh_pass_file.unlink(missing_ok=True)
        if ssh_process.returncode != 0:
            raise ValidationError(
                f"Automatic {self.display_name.lower()} bundle fallback failed after SSH staging: "
                + _summarize_command_output(ssh_process.stdout, ssh_process.stderr)
            )
        return {
            "attempted": True,
            "installed": True,
            "source": "ssh-extract",
            "message": _summarize_command_output(ssh_process.stdout, ssh_process.stderr),
        }

    def install(self, spec: dict[str, Any], client: Any) -> dict[str, Any]:
        script_path = self.script_path
        if not script_path.is_file():
            raise ValidationError(
                f"Automatic {self.display_name.lower()} bootstrap requires installer script '{script_path}', but it was not found."
            )

        section = spec.get(self.spec_key, {})
        source = str(section.get("source") or "splunkbase").strip().lower()
        app_id = str(section.get("app_id") or self.default_app_id).strip() or self.default_app_id

        command = ["bash", str(script_path), "--source", source, "--no-update"]
        if source == "splunkbase":
            command.extend(["--app-id", app_id])
            app_version = str(section.get("app_version") or "").strip()
            if app_version:
                command.extend(["--app-version", app_version])
        elif source == "local":
            local_file = str(section.get("local_file") or "").strip()
            if not local_file:
                raise ValidationError(f"{self.spec_key}.local_file is required when {self.spec_key}.source=local.")
            command.extend(["--file", local_file])
        else:
            raise ValidationError(f"Unsupported {self.spec_key} source '{source}'. Expected 'splunkbase' or 'local'.")

        env = self._build_env(spec, client)
        if source == "local":
            bundle_path = Path(local_file)
            if _archive_has_multiple_top_level_dirs(bundle_path):
                cli_result = self._cli_install_bundle(bundle_path, spec, client, env)
                cli_result["app_id"] = None
                cli_result["installer_script"] = str(script_path)
                return cli_result

        process = self._run_command(command, env)
        process_summary = _summarize_command_output(process.stdout, process.stderr)
        if process.returncode != 0:
            bundle_path = _extract_downloaded_file_path(process_summary)
            if bundle_path and bundle_path.is_file() and _archive_has_multiple_top_level_dirs(bundle_path):
                cli_result = self._cli_install_bundle(bundle_path, spec, client, env)
                cli_result["app_id"] = app_id if source == "splunkbase" else None
                cli_result["installer_script"] = str(script_path)
                return cli_result
            raise ValidationError(
                f"Automatic {self.display_name.lower()} bootstrap failed: "
                + process_summary
            )
        return {
            "attempted": True,
            "installed": True,
            "source": source,
            "app_id": app_id if source == "splunkbase" else None,
            "installer_script": str(script_path),
            "message": process_summary,
        }


class ShellItsiInstaller(ShellContentLibraryInstaller):
    def __init__(self, script_path: str | Path | None = None, runner: Any | None = None):
        super().__init__(
            script_path=script_path,
            runner=runner,
            spec_key="itsi",
            app_name=ITSI_APP,
            default_app_id=ITSI_APP_ID,
            display_name="Splunk IT Service Intelligence",
        )


def _finding(status: str, check: str, message: str) -> dict[str, str]:
    return {"status": status, "check": check, "message": message}


def _has_error(findings: list[dict[str, str]]) -> bool:
    return any(finding["status"] == "error" for finding in findings)


def _summarize_command_output(stdout: str, stderr: str, *, line_limit: int = 12) -> str:
    lines: list[str] = []
    for stream in (stdout, stderr):
        if not stream:
            continue
        lines.extend(line.strip() for line in stream.splitlines() if line.strip())
    if not lines:
        return "installer did not produce any output."
    return " | ".join(lines[-line_limit:])


def _extract_downloaded_file_path(output: str) -> Path | None:
    match = re.search(r"(?:Downloaded to|Existing package found):\s*(?P<path>/\S+)", output)
    if not match:
        return None
    return Path(match.group("path"))


def _archive_has_multiple_top_level_dirs(path: str | Path) -> bool:
    try:
        with tarfile.open(path, "r:*") as archive:
            top_levels = {
                member.name.lstrip("./").split("/", 1)[0]
                for member in archive.getmembers()
                if member.name.lstrip("./")
            }
    except (tarfile.TarError, OSError):
        return False
    return len(top_levels) > 1


def _target_host(base_url: str) -> str:
    return (urlparse(base_url).hostname or "").strip()


def _is_local_target(base_url: str) -> bool:
    return _target_host(base_url) in {"localhost", "127.0.0.1"}


def _wait_for_app_visibility(client: Any, app_name: str, *, timeout_seconds: int = 180, interval_seconds: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if client.app_exists(app_name):
                return True
        except Exception:
            pass
        time.sleep(interval_seconds)
    return False


def resolve_catalog_entry(
    catalog: list[dict[str, Any]],
    title: str | list[str] | tuple[str, ...] | None,
    version: str | None = None,
    *,
    pack_id: str | None = None,
) -> dict[str, Any]:
    exact_titles = [str(item).strip() for item in listify(title) if str(item).strip()]
    exact_ids = [str(item).strip() for item in listify(pack_id) if str(item).strip()]
    if not catalog:
        raise ValidationError(
            "The live ITSI content-pack catalog is empty. Confirm DA-ITSI-ContentLibrary discovery completed and the packaged content-pack apps are installed."
        )
    exact_matches = [
        entry
        for entry in catalog
        if str(entry.get("id", "")).strip() in exact_ids
        or str(entry.get("title", "")).strip() in exact_titles
    ]
    if not exact_matches:
        requested = ", ".join(exact_titles + exact_ids) or str(title or pack_id)
        raise ValidationError(f"Content pack '{requested}' was not found in the live ITSI content library catalog.")
    if version:
        for entry in exact_matches:
            if str(entry.get("version")) == version:
                return entry
        requested = ", ".join(exact_titles + exact_ids) or str(title or pack_id)
        raise ValidationError(f"Content pack '{requested}' is available, but version '{version}' was not found.")
    return sorted(exact_matches, key=lambda item: semver_key(str(item.get("version", ""))), reverse=True)[0]


def _normalize_required_apps(value: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in listify(value):
        if isinstance(item, str):
            app_name = item.strip()
            if app_name:
                normalized.append({"label": app_name, "candidates": [app_name]})
            continue
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("app") or item.get("name") or "").strip()
            candidates = _candidate_list(item.get("candidates") or item.get("candidate") or item.get("app") or item.get("name"))
            if label or candidates:
                normalized.append({"label": label or candidates[0], "candidates": candidates or [label]})
            continue
        raise ValidationError("packs.required_apps entries must be strings or mappings.")
    return normalized


def _generic_pack_profile(pack_spec: dict[str, Any], profile_key: str) -> dict[str, Any]:
    title = str(
        pack_spec.get("catalog_title")
        or pack_spec.get("title")
        or pack_spec.get("pack_title")
        or pack_spec.get("pack_id")
        or pack_spec.get("id")
        or profile_key
    ).strip()
    if not title:
        raise ValidationError("Generic content-pack entries must define title, catalog_title, pack_id, or id.")
    steps = _candidate_list(pack_spec.get("follow_up_steps") or pack_spec.get("post_install_steps"))
    app_candidates = _candidate_list(
        pack_spec.get("pack_app_candidates")
        or pack_spec.get("app_candidates")
        or pack_spec.get("pack_app")
    )
    return _catalog_profile(
        title,
        catalog_titles=_candidate_list(pack_spec.get("catalog_titles") or pack_spec.get("catalog_title") or pack_spec.get("title") or pack_spec.get("pack_title")),
        pack_app_candidates=app_candidates,
        required_apps=_normalize_required_apps(pack_spec.get("required_apps")),
        companion_app_checks=listify(pack_spec.get("companion_app_checks")),
        post_install_steps=steps or GENERIC_CONTENT_PACK_STEPS,
    )


def resolve_pack_definition(pack_spec: dict[str, Any], index: int = 0) -> tuple[str, dict[str, Any]]:
    if not isinstance(pack_spec, dict):
        raise ValidationError("Each packs entry must be a mapping.")
    profile_key = str(pack_spec.get("profile") or "").strip()
    if profile_key in PACK_PROFILES:
        return profile_key, PACK_PROFILES[profile_key]
    has_catalog_identity = any(
        str(pack_spec.get(key) or "").strip()
        for key in ("title", "catalog_title", "pack_title", "pack_id", "id")
    )
    if profile_key in GENERIC_PROFILE_KEYS or (not profile_key and has_catalog_identity) or (profile_key and has_catalog_identity):
        resolved_profile = profile_key or f"catalog_pack_{index + 1}"
        return resolved_profile, _generic_pack_profile(pack_spec, resolved_profile)
    if not profile_key:
        raise ValidationError("Each content-pack entry must define profile, title, catalog_title, pack_id, or id.")
    raise ValidationError(f"Unsupported content-pack profile '{profile_key}'.")


def resolve_pack_catalog_entry(catalog: list[dict[str, Any]], pack_spec: dict[str, Any], profile_meta: dict[str, Any]) -> dict[str, Any]:
    catalog_titles = (
        _candidate_list(pack_spec.get("catalog_titles"))
        or _candidate_list(pack_spec.get("catalog_title"))
        or _candidate_list(pack_spec.get("title") or pack_spec.get("pack_title"))
        or _candidate_list(profile_meta.get("catalog_titles"))
        or [str(profile_meta["title"])]
    )
    pack_id = str(pack_spec.get("pack_id") or pack_spec.get("id") or "").strip() or None
    return resolve_catalog_entry(catalog, catalog_titles, pack_spec.get("version"), pack_id=pack_id)


def build_install_payload(pack_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": deepcopy(pack_spec.get("content") or {}),
        "resolution": pack_spec.get("resolution", "skip"),
        "enabled": bool_from_any(pack_spec.get("enabled"), default=False),
        "saved_search_action": pack_spec.get("saved_search_action", "disable"),
        "install_all": bool_from_any(pack_spec.get("install_all"), default=True),
        "backfill": bool_from_any(pack_spec.get("backfill"), default=False),
        "prefix": pack_spec.get("prefix", ""),
    }


def _preview_summary(preview_payload: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"object_counts": {}, "saved_searches": {}}
    if isinstance(preview_payload, list):
        summary["object_counts"]["items"] = len(preview_payload)
        return summary
    if not isinstance(preview_payload, dict):
        return summary
    for key, value in preview_payload.items():
        if isinstance(value, list):
            summary["object_counts"][key] = len(value)
        elif isinstance(value, dict):
            if "has_saved_searches" in value or "has_consistent_status" in value:
                summary["saved_searches"][key] = value
            else:
                summary["object_counts"][key] = len(value)
    return summary


def _installed_versions(entry: dict[str, Any]) -> list[str]:
    raw = entry.get("installed_versions")
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if raw:
        return [str(raw)]
    return []


def _state_has_error(state: dict[str, Any]) -> bool:
    return any(check.get("status") == "error" for check in state.get("checks", []))


def _run_itsi_health_checks(client: Any) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for app_meta in ITSI_HEALTH_APPS:
        try:
            version = client.get_app_version(app_meta["app"])
        except ValidationError as exc:
            checks.append(_finding("warn", "app", f"Could not inspect {app_meta['label']}: {exc}"))
            continue
        if version:
            checks.append(_finding("pass", "app", f"{app_meta['label']} is installed (version: {version})."))
        else:
            checks.append(_finding(app_meta["status"], "app", app_meta["message"]))

    try:
        kvstore_status = client.kvstore_status()
    except ValidationError as exc:
        checks.append(_finding("warn", "kvstore", f"Could not inspect KVStore status: {exc}"))
        kvstore_status = None
    if kvstore_status == "ready":
        checks.append(_finding("pass", "kvstore", "KVStore status is ready."))
    elif kvstore_status:
        checks.append(_finding("warn", "kvstore", f"KVStore status is {kvstore_status}. ITSI requires a healthy KVStore."))
    else:
        checks.append(_finding("warn", "kvstore", "KVStore status could not be determined."))

    for collection_name in ITSI_KVSTORE_COLLECTIONS:
        health = client.kvstore_collection_health(ITSI_APP, collection_name)
        status = str(health.get("status") or "").strip()
        message = str(health.get("message") or "").strip()
        if status == "ok":
            checks.append(_finding("pass", "kvstore", f"KVStore collection '{collection_name}' is accessible."))
        elif status == "missing":
            checks.append(
                _finding(
                    "warn",
                    "kvstore",
                    f"KVStore collection '{collection_name}' was not found. It may initialize after first use.",
                )
            )
        else:
            detail = f": {message}" if message else ""
            checks.append(_finding("warn", "kvstore", f"KVStore collection '{collection_name}' could not be validated{detail}"))
    return checks


def _candidate_list(values: Any) -> list[str]:
    return [str(item).strip() for item in listify(values) if str(item).strip()]


def resolve_pack_app_name(client: Any, profile_meta: dict[str, Any], catalog_pack_id: str | None) -> str:
    candidates = _candidate_list(profile_meta.get("pack_app_candidates"))
    if catalog_pack_id and catalog_pack_id not in candidates:
        candidates.append(catalog_pack_id)
    installed = client.first_installed_app(candidates)
    if installed:
        return installed
    if candidates:
        return candidates[0]
    return str(catalog_pack_id or "").strip()


def _check_pack_bundle_visibility(
    client: Any,
    findings: list[dict[str, str]],
    profile_meta: dict[str, Any],
    *,
    pack_app_name: str,
) -> None:
    if client.app_exists(pack_app_name):
        findings.append(_finding("pass", "pack_app", f"Primary content-pack app is installed as {pack_app_name}."))
    else:
        checked = ", ".join(_candidate_list(profile_meta.get("pack_app_candidates")) or [pack_app_name])
        findings.append(_finding("error", "pack_app", f"Primary content-pack app is not installed. Checked: {checked}."))
    for companion in profile_meta.get("companion_app_checks", []):
        installed = client.first_installed_app(_candidate_list(companion.get("candidates")))
        if installed:
            findings.append(_finding("pass", "pack_app", f"{companion['label']} is installed as {installed}."))
        else:
            checked = ", ".join(_candidate_list(companion.get("candidates")))
            findings.append(_finding("warn", "pack_app", f"{companion['label']} is not installed. Checked: {checked}."))


def _ensure_managed_app(
    client: Any,
    *,
    mode: str,
    spec: dict[str, Any],
    spec_key: str,
    app_name: str,
    app_id: str,
    display_name: str,
    installer: Any,
    disabled_message: str,
    missing_message: str | None = None,
) -> dict[str, Any]:
    section = spec.get(spec_key, {})
    require_present = bool_from_any(section.get("require_present"), default=True)
    install_if_missing = bool_from_any(section.get("install_if_missing"), default=True)
    state = {
        "required": require_present,
        "present_before": False,
        "installed_in_this_run": False,
        "source": None,
        "app_id": None,
        "checks": [],
        "message": f"{display_name} presence checks are disabled.",
    }
    if not require_present:
        return state

    if client.app_exists(app_name):
        state["present_before"] = True
        state["message"] = f"{display_name} is already installed."
        return state

    if missing_message:
        raise ValidationError(missing_message)

    if mode != "apply":
        if install_if_missing:
            raise ValidationError(
                f"{display_name} is not installed. Rerun with --apply to bootstrap Splunkbase app {app_id} automatically, or install it manually first."
            )
        raise ValidationError(disabled_message)

    if not install_if_missing:
        raise ValidationError(disabled_message)

    install_result = installer.install(spec, client)
    if not _wait_for_app_visibility(client, app_name):
        raise ValidationError(
            f"Attempted to install {display_name}, but app {app_name} is still not visible through the Splunk REST API."
        )
    state["installed_in_this_run"] = True
    state["source"] = install_result.get("source")
    state["app_id"] = install_result.get("app_id")
    state["message"] = str(install_result.get("message") or f"Installed {display_name}.")
    return state


def _ensure_itsi(
    client: Any,
    *,
    mode: str,
    spec: dict[str, Any],
    installer: Any,
) -> dict[str, Any]:
    state = _ensure_managed_app(
        client,
        mode=mode,
        spec=spec,
        spec_key="itsi",
        app_name=ITSI_APP,
        app_id=ITSI_APP_ID,
        display_name="Splunk IT Service Intelligence",
        installer=installer,
        disabled_message=(
            "Splunk IT Service Intelligence is not installed. Automatic bootstrap is disabled. "
            "Set itsi.install_if_missing=true or install Splunkbase app 1841 before using content-pack automation."
        ),
    )
    if state.get("required"):
        state["checks"] = _run_itsi_health_checks(client)
    return state


def _ensure_content_library(
    client: Any,
    *,
    platform: str,
    mode: str,
    spec: dict[str, Any],
    installer: Any,
) -> dict[str, Any]:
    missing_message = None
    if platform == "cloud":
        missing_message = (
            "Splunk App for Content Packs is not installed. On Splunk Cloud, open a Splunk Support / Cloud App Request for app 5391."
        )
    return _ensure_managed_app(
        client,
        mode=mode,
        spec=spec,
        spec_key="content_library",
        app_name=CONTENT_LIBRARY_APP,
        app_id=CONTENT_LIBRARY_APP_ID,
        display_name="Splunk App for Content Packs",
        installer=installer,
        disabled_message=(
            "Splunk App for Content Packs is not installed. Automatic bootstrap is disabled. "
            "Set content_library.install_if_missing=true or install Splunkbase app 5391 before using content-pack automation."
        ),
        missing_message=missing_message,
    )


def _is_enabled_input(entry: dict[str, Any]) -> bool:
    value = entry.get("disabled", False)
    if isinstance(value, str):
        return value not in {"1", "true", "True"}
    return not bool(value)


def _enabled_input_entries(client: Any, app_name: str) -> list[dict[str, Any]]:
    return [entry for entry in client.list_inputs(app_name) if _is_enabled_input(entry)]


def _input_label(entry: dict[str, Any]) -> str:
    for field_name in ("title", "name", "eai:type", "eai:location", "id"):
        value = str(entry.get(field_name) or "").strip()
        if value:
            return value
    return "<unnamed input>"


def _input_titles(client: Any, app_name: str) -> list[str]:
    return [_input_label(entry) for entry in _enabled_input_entries(client, app_name)]


def _input_indexes(client: Any, app_name: str, fields: list[str]) -> list[str]:
    indexes: set[str] = set()
    for entry in client.list_inputs(app_name):
        if not _is_enabled_input(entry):
            continue
        for field_name in fields:
            value = entry.get(field_name)
            if not value:
                continue
            if isinstance(value, str):
                indexes.update(token.strip() for token in value.split(",") if token.strip())
    return sorted(indexes)


def _discover_macro(client: Any, app_name: str, contains: list[str]) -> dict[str, Any] | None:
    candidates = []
    for macro in client.list_macros(app_name):
        name = str(macro.get("name") or macro.get("title") or "").lower()
        if all(token.lower() in name for token in contains):
            candidates.append(macro)
    return candidates[0] if len(candidates) == 1 else None


def _check_required_apps(client: Any, findings: list[dict[str, str]], profile_meta: dict[str, Any]) -> dict[str, str]:
    installed_apps: dict[str, str] = {}
    for app_requirement in profile_meta.get("required_apps", []):
        installed = client.first_installed_app(app_requirement["candidates"])
        if installed:
            installed_apps[app_requirement["label"]] = installed
            findings.append(_finding("pass", "app", f"{app_requirement['label']} is installed as {installed}."))
        else:
            findings.append(_finding("error", "app", f"{app_requirement['label']} is not installed."))
    for app_group in profile_meta.get("alternative_app_groups", []):
        installed_choice: tuple[str, str] | None = None
        checked: list[str] = []
        for app_requirement in listify(app_group.get("apps")):
            candidates = _candidate_list(app_requirement.get("candidates"))
            checked.extend(candidates)
            installed = client.first_installed_app(candidates)
            if installed:
                installed_choice = (str(app_requirement.get("label") or app_group.get("label") or installed), installed)
                break
        group_label = str(app_group.get("label") or "One of the required add-ons")
        if installed_choice:
            installed_apps[group_label] = installed_choice[1]
            findings.append(_finding("pass", "app", f"{group_label} is satisfied by {installed_choice[0]} installed as {installed_choice[1]}."))
        else:
            checked_text = ", ".join(checked) if checked else "no candidates declared"
            findings.append(_finding("error", "app", f"{group_label} is not installed. Checked: {checked_text}."))
    return installed_apps


def _input_pattern_variants(pattern: str) -> list[str]:
    normalized = pattern.lower().strip()
    variants = [normalized]
    slash_form = normalized.replace("://", "/")
    if slash_form not in variants:
        variants.append(slash_form)
    collapsed = normalized.replace("://", "")
    if collapsed not in variants:
        variants.append(collapsed)
    trimmed = collapsed.rstrip(":/")
    if trimmed and trimmed not in variants:
        variants.append(trimmed)
    return [variant for variant in variants if variant]


def _input_matches_requirement(entry: dict[str, Any], pattern: str) -> bool:
    candidates = [
        str(entry.get(field) or "").lower()
        for field in ("title", "name", "eai:type", "eai:location", "id")
        if entry.get(field)
    ]
    if not candidates:
        return False
    for variant in _input_pattern_variants(pattern):
        if any(variant in candidate for candidate in candidates):
            return True
    return False

def _check_required_inputs(client: Any, findings: list[dict[str, str]], profile_meta: dict[str, Any]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for requirement in profile_meta.get("required_inputs", []):
        matches = [
            entry
            for entry in client.list_inputs(requirement["app"])
            if _is_enabled_input(entry) and _input_matches_requirement(entry, requirement["pattern"])
        ]
        if matches:
            findings.append(_finding("pass", "input", f"{requirement['label']} is enabled."))
        else:
            findings.append(_finding("error", "input", f"{requirement['label']} is missing or disabled."))
            missing.append(requirement)
    return missing


def _check_cisco_data_center(client: Any, findings: list[dict[str, str]], missing_requirements: list[dict[str, Any]]) -> None:
    if not any(requirement["label"].startswith("ND ") for requirement in missing_requirements):
        return
    accounts = client.list_endpoint_entries("cisco_dc_networking_app_for_splunk", "cisco_dc_networking_app_for_splunk_nd_account")
    if accounts:
        labels = ", ".join(str(account.get("name") or account.get("title") or "").strip() for account in accounts[:3] if account)
        if labels:
            findings.append(_finding("pass", "account", f"Nexus Dashboard account is configured: {labels}."))
        else:
            findings.append(_finding("pass", "account", "Nexus Dashboard account is configured."))
        return
    findings.append(
        _finding(
            "error",
            "account",
            "Nexus Dashboard account is not configured in Cisco DC Networking App for Splunk. Configure it before enabling the Cisco Data Center content pack inputs.",
        )
    )


def _check_cisco_enterprise_networks(client: Any, findings: list[dict[str, str]], missing_requirements: list[dict[str, Any]]) -> None:
    if any(requirement["app"] == "TA_cisco_catalyst" for requirement in missing_requirements):
        accounts = client.list_endpoint_entries("TA_cisco_catalyst", "TA_cisco_catalyst_account")
        if accounts:
            labels = ", ".join(str(account.get("name") or account.get("title") or "").strip() for account in accounts[:3] if account)
            if labels:
                findings.append(_finding("pass", "account", f"Catalyst Center account is configured: {labels}."))
            else:
                findings.append(_finding("pass", "account", "Catalyst Center account is configured."))
        else:
            findings.append(
                _finding(
                    "error",
                    "account",
                    "Catalyst Center account is not configured in Cisco Catalyst Add-on for Splunk. Configure it before enabling the Cisco Enterprise Networks content pack inputs.",
                )
            )
    if any(requirement["app"] == "Splunk_TA_cisco_meraki" for requirement in missing_requirements):
        accounts = client.list_endpoint_entries("Splunk_TA_cisco_meraki", "Splunk_TA_cisco_meraki_account")
        if accounts:
            labels = ", ".join(str(account.get("name") or account.get("title") or "").strip() for account in accounts[:3] if account)
            if labels:
                findings.append(_finding("pass", "account", f"Meraki account is configured: {labels}."))
            else:
                findings.append(_finding("pass", "account", "Meraki account is configured."))
        else:
            findings.append(
                _finding(
                    "error",
                    "account",
                    "Meraki account is not configured in Splunk Add-on for Cisco Meraki. Configure it before enabling the Cisco Enterprise Networks content pack inputs.",
                )
            )


def _check_macro_alignment(
    client: Any,
    findings: list[dict[str, str]],
    pack_spec: dict[str, Any],
    profile_meta: dict[str, Any],
    pack_app_name: str,
) -> None:
    for macro_check in profile_meta.get("macro_checks", []):
        macro_name = macro_check["macro"]
        macro_app_name = macro_check.get("app", pack_app_name)
        macro = client.get_macro(macro_app_name, macro_name)
        if not macro:
            if macro_app_name == pack_app_name and not client.app_exists(macro_app_name):
                findings.append(
                    _finding(
                        "warn",
                        "macro",
                        f"Macro '{macro_name}' cannot be validated until content-pack app {macro_app_name} is installed.",
                    )
                )
            elif bool_from_any(macro_check.get("optional")):
                findings.append(_finding("warn", "macro", f"Optional macro '{macro_name}' was not found in app {macro_app_name}."))
            else:
                findings.append(_finding("error", "macro", f"Macro '{macro_name}' was not found in app {macro_app_name}."))
            continue
        definition = str(macro.get("definition") or "")
        expected_indexes: list[str] = []
        static_indexes_key = macro_check.get("static_indexes_key")
        if static_indexes_key:
            expected_indexes = list(pack_spec.get(static_indexes_key) or [])
            if not expected_indexes:
                expected_indexes = list(macro_check.get("default_indexes") or [])
            if not expected_indexes and macro_name == "itsi-cp-observability-indexes":
                expected_indexes = ["sim_metrics"]
        if macro_check.get("source_conf"):
            conf_meta = macro_check["source_conf"]
            stanza = client.get_conf_stanza(macro_check["source_app"], conf_meta["name"], conf_meta["stanza"])
            if stanza and stanza.get(conf_meta["field"]):
                expected_indexes.append(str(stanza[conf_meta["field"]]))
        source_fields = macro_check.get("source_fields", [])
        if source_fields:
            expected_indexes.extend(_input_indexes(client, macro_check["source_app"], source_fields))
        expected_indexes = sorted(set(index_name for index_name in expected_indexes if index_name))
        if not expected_indexes:
            if source_fields:
                findings.append(
                    _finding(
                        "warn",
                        "macro",
                        f"Could not infer expected indexes for macro '{macro_name}' because no enabled source inputs were discovered in app {macro_check['source_app']}.",
                    )
                )
            else:
                findings.append(_finding("warn", "macro", f"Could not infer expected indexes for macro '{macro_name}'."))
            continue
        if macro_mentions_indexes(definition, expected_indexes):
            findings.append(_finding("pass", "macro", f"Macro '{macro_name}' aligns with indexes: {', '.join(expected_indexes)}."))
        elif bool_from_any(macro_check.get("optional")):
            findings.append(
                _finding(
                    "warn",
                    "macro",
                    f"Optional macro '{macro_name}' does not align with expected indexes {', '.join(expected_indexes)}. Current definition: {definition}",
                )
            )
        else:
            findings.append(
                _finding(
                    "error",
                    "macro",
                    f"Macro '{macro_name}' does not align with expected indexes {', '.join(expected_indexes)}. Current definition: {definition}",
                )
            )


def _check_local_inputs(
    client: Any,
    findings: list[dict[str, str]],
    app_name: str,
    label: str,
    *,
    missing_is_warning: bool = True,
) -> list[dict[str, Any]]:
    entries = _enabled_input_entries(client, app_name)
    if entries:
        labels = [_input_label(entry) for entry in entries[:4]]
        findings.append(_finding("pass", "input", f"Observed enabled {label} inputs on the search head: {', '.join(labels)}."))
        return entries
    status = "warn" if missing_is_warning else "error"
    message = f"No enabled {label} inputs were detected on the search head."
    if missing_is_warning:
        message += " This can be expected if collection runs on forwarders or dedicated collection nodes."
    findings.append(_finding(status, "input", message))
    return entries


def _check_aws(client: Any, findings: list[dict[str, str]], aws_app_name: str) -> None:
    _check_local_inputs(client, findings, aws_app_name, "AWS", missing_is_warning=True)
    if client.app_exists("SplunkAppForAWS"):
        findings.append(
            _finding(
                "warn",
                "app",
                "The legacy Splunk App for AWS appears to be installed on this search head. The AWS content-pack docs warn about knowledge-object conflicts.",
            )
        )


def _check_thousandeyes(
    client: Any,
    findings: list[dict[str, str]],
    pack_spec: dict[str, Any],
    profile_meta: dict[str, Any],
    pack_app_name: str,
) -> None:
    macro = None
    if pack_spec.get("index_macro_name"):
        macro = client.get_macro(pack_app_name, pack_spec["index_macro_name"])
    if not macro and profile_meta.get("macro_discovery"):
        macro = _discover_macro(client, pack_app_name, profile_meta["macro_discovery"]["contains"])
    if not macro:
        findings.append(_finding("error", "macro", "Could not locate the Cisco ThousandEyes content-pack index macro."))
        return
    definition = str(macro.get("definition") or "")
    active_indexes = _input_indexes(
        client,
        "ta_cisco_thousandeyes",
        ["index", "test_index", "activity_index", "alerts_index"],
    )
    expected_indexes = extract_indexes_from_expression(pack_spec.get("index_macro_value", "")) or active_indexes
    if not expected_indexes:
        expected_indexes = extract_indexes_from_expression(definition)
    if not expected_indexes:
        findings.append(_finding("warn", "macro", "No ThousandEyes index values were discoverable from inputs or macro overrides."))
        return
    if all(looks_like_metrics_index(index_name) for index_name in expected_indexes):
        findings.append(_finding("error", "index", "Cisco ThousandEyes content-pack support is limited to events indexes, not metrics indexes."))
    else:
        findings.append(_finding("pass", "index", f"Detected ThousandEyes event indexes: {', '.join(expected_indexes)}."))
    if macro_mentions_indexes(definition, expected_indexes):
        findings.append(_finding("pass", "macro", "Cisco ThousandEyes macro aligns with the live ThousandEyes index configuration."))
    else:
        findings.append(_finding("error", "macro", f"Cisco ThousandEyes macro does not point to expected index values: {', '.join(expected_indexes)}."))


def _check_observability(
    client: Any,
    findings: list[dict[str, str]],
    pack_spec: dict[str, Any],
    pack_app_name: str,
    sim_app_name: str,
) -> None:
    enabled_inputs = [title for title in _input_titles(client, sim_app_name) if not title.startswith("SAMPLE_")]
    if enabled_inputs:
        findings.append(_finding("pass", "input", f"Non-sample Splunk Observability inputs are enabled: {', '.join(enabled_inputs[:4])}"))
    else:
        findings.append(_finding("error", "input", "No non-sample Splunk Observability modular inputs are enabled."))
    macro = client.get_macro(pack_app_name, "itsi-cp-observability-indexes")
    if not macro:
        findings.append(_finding("error", "macro", "Macro 'itsi-cp-observability-indexes' was not found."))
    else:
        expected_indexes = list(pack_spec.get("metrics_indexes") or ["sim_metrics"])
        definition = str(macro.get("definition") or "")
        if macro_mentions_indexes(definition, expected_indexes):
            findings.append(_finding("pass", "macro", f"Observability macro aligns with metrics indexes: {', '.join(expected_indexes)}."))
        else:
            findings.append(
                _finding(
                    "error",
                    "macro",
                    f"Observability macro does not include all required metrics indexes: {', '.join(expected_indexes)}.",
                )
            )
    custom_subdomain = str(pack_spec.get("custom_subdomain") or "").strip()
    if custom_subdomain:
        findings.append(
            _finding(
                "pass",
                "navigation",
                f"Custom subdomain '{custom_subdomain}' recorded for manual entity navigation updates.",
            )
        )


def _check_linux(client: Any, findings: list[dict[str, str]], nix_app_name: str) -> None:
    _check_local_inputs(client, findings, nix_app_name, "Unix and Linux", missing_is_warning=True)


def _check_vmware(findings: list[dict[str, str]], installed_app_name: str | None) -> None:
    if installed_app_name == "SA-VMWIndex-inframon":
        findings.append(
            _finding(
                "warn",
                "app",
                "Detected only the VMware Metrics indexes package on the search head. Verify the Splunk Add-on for VMware Metrics collection components are installed where they run.",
            )
        )


def _check_windows(client: Any, findings: list[dict[str, str]], windows_app_name: str) -> None:
    entries = _check_local_inputs(client, findings, windows_app_name, "Windows", missing_is_warning=True)
    if not entries:
        return
    required_patterns = {
        "WinHostMon://Processor": "Processor host monitoring",
        "WinHostMon://OperatingSystem": "Operating system host monitoring",
        "WinHostMon://Disk": "Disk host monitoring",
        "perfmon://CPU": "CPU perfmon collection",
        "perfmon://LogicalDisk": "Logical disk perfmon collection",
    }
    missing = [label for pattern, label in required_patterns.items() if not any(_input_matches_requirement(entry, pattern) for entry in entries)]
    if missing:
        findings.append(
            _finding(
                "error",
                "input",
                f"Detected local Windows inputs, but these required stanza families are missing: {', '.join(missing)}.",
            )
        )
    else:
        findings.append(_finding("pass", "input", "Detected the expected local WinHostMon and perfmon stanza families for Windows monitoring."))


def _check_custom_index_overrides(
    findings: list[dict[str, str]],
    *,
    label: str,
    observed_indexes: list[str],
    default_indexes: set[str],
    override_keys: list[str],
    pack_spec: dict[str, Any],
) -> None:
    custom_indexes = sorted({index_name for index_name in observed_indexes if index_name not in default_indexes})
    if not custom_indexes:
        return
    if any(pack_spec.get(override_key) for override_key in override_keys):
        return
    findings.append(
        _finding(
            "error",
            "index",
            f"Observed {label} add-on indexes {', '.join(custom_indexes)}. Set {', '.join(override_keys)} in the pack spec so macro validation does not rely on defaults.",
        )
    )


def validate_profile(
    client: Any,
    pack_spec: dict[str, Any],
    profile_meta: dict[str, Any],
    pack_app_name: str,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    profile_name = str(pack_spec.get("profile") or "").strip()
    if profile_meta.get("generic_catalog_profile"):
        findings.append(
            _finding(
                "warn",
                "profile",
                "Using catalog-generic content-pack validation. Install/visibility checks are automated; pack-specific data, macro, module, and dashboard checks are reported as follow-up steps.",
            )
        )
    installed_apps = _check_required_apps(client, findings, profile_meta)
    missing_requirements = _check_required_inputs(client, findings, profile_meta)
    if profile_name == "cisco_data_center":
        _check_cisco_data_center(client, findings, missing_requirements)
    if profile_name == "cisco_enterprise_networks":
        _check_cisco_enterprise_networks(client, findings, missing_requirements)
    _check_macro_alignment(client, findings, pack_spec, profile_meta, pack_app_name)
    if profile_name == "aws":
        aws_app = installed_apps.get("Splunk Add-on for AWS", "Splunk_TA_aws")
        _check_aws(client, findings, aws_app)
    if profile_name == "cisco_thousandeyes":
        _check_thousandeyes(client, findings, pack_spec, profile_meta, pack_app_name)
    if profile_name == "linux":
        nix_app = installed_apps.get("Splunk Add-on for Unix and Linux", "Splunk_TA_nix")
        _check_linux(client, findings, nix_app)
        _check_custom_index_overrides(
            findings,
            label="Unix and Linux",
            observed_indexes=_input_indexes(client, nix_app, ["index"]),
            default_indexes={"os"},
            override_keys=["event_indexes"],
            pack_spec=pack_spec,
        )
    if profile_name == "splunk_observability_cloud":
        sim_app = installed_apps.get("Splunk Infrastructure Monitoring Add-on", "splunk_ta_sim")
        _check_observability(client, findings, pack_spec, pack_app_name, sim_app)
    if profile_name == "vmware":
        _check_vmware(findings, installed_apps.get("Splunk Add-on for VMware Metrics"))
    if profile_name == "windows":
        windows_app = installed_apps.get("Splunk Add-on for Windows", "Splunk_TA_windows")
        _check_windows(client, findings, windows_app)
        _check_custom_index_overrides(
            findings,
            label="Windows",
            observed_indexes=_input_indexes(client, windows_app, ["index"]),
            default_indexes={"windows", "perfmon", "itsi_im_metrics"},
            override_keys=["event_indexes", "metrics_indexes"],
            pack_spec=pack_spec,
        )
    return findings


def _install_failures(install_result: Any) -> list[str]:
    failures: list[str] = []
    if not isinstance(install_result, dict):
        return failures
    raw_failure = install_result.get("failure")
    if isinstance(raw_failure, list) and raw_failure:
        failures.append(f"Install reported failures: {raw_failure}")
    elif isinstance(raw_failure, dict) and any(raw_failure.values()):
        failures.append(f"Install reported failures: {raw_failure}")
    saved_searches = install_result.get("saved_searches")
    if isinstance(saved_searches, dict):
        saved_search_failures = saved_searches.get("failure")
        if isinstance(saved_search_failures, list) and saved_search_failures:
            failures.append(f"Saved search updates reported failures: {saved_search_failures}")
        elif isinstance(saved_search_failures, dict) and any(saved_search_failures.values()):
            failures.append(f"Saved search updates reported failures: {saved_search_failures}")
    return failures


def _maybe_refresh_content_pack_catalog(client: Any, content_library_state: dict[str, Any], spec: dict[str, Any]) -> None:
    section = spec.get("content_library", {}) if isinstance(spec.get("content_library"), dict) else {}
    if not bool_from_any(section.get("refresh_catalog"), default=True):
        content_library_state["catalog_refresh"] = {"attempted": False, "status": "skipped"}
        return
    if not hasattr(client, "refresh_content_pack_catalog"):
        content_library_state["catalog_refresh"] = {"attempted": False, "status": "unsupported"}
        return
    try:
        response = client.refresh_content_pack_catalog()
        content_library_state["catalog_refresh"] = {"attempted": True, "status": "ok", "response": response}
        content_library_state.setdefault("checks", []).append(
            _finding("pass", "content_pack_refresh", "ITSI content-pack catalog refresh completed.")
        )
    except (KeyError, ValidationError) as exc:
        content_library_state["catalog_refresh"] = {"attempted": True, "status": "warn", "message": str(exc)}
        content_library_state.setdefault("checks", []).append(
            _finding("warn", "content_pack_refresh", f"ITSI content-pack catalog refresh was unavailable: {exc}")
        )


def _record_content_library_discovery_state(client: Any, content_library_state: dict[str, Any]) -> None:
    if not hasattr(client, "content_library_discovery_status"):
        return
    status = client.content_library_discovery_status()
    if not isinstance(status, dict) or not status.get("attempted"):
        return
    content_library_state["content_library_discovery"] = deepcopy(status)
    if status.get("status") == "ok":
        content_library_state.setdefault("checks", []).append(
            _finding("pass", "content_library_discovery", "Content Library discovery refresh completed before catalog lookup.")
        )
    elif status.get("status") == "warn":
        content_library_state.setdefault("checks", []).append(
            _finding(
                "warn",
                "content_library_discovery",
                f"Content Library discovery refresh was unavailable before catalog lookup: {status.get('message', 'unknown error')}",
            )
        )


def _summarize_content_pack_detail(detail: Any) -> dict[str, Any] | None:
    if not isinstance(detail, dict):
        return None
    summary: dict[str, Any] = {}
    for key in ("id", "name", "title", "version", "status", "installed_versions"):
        if key in detail:
            summary[key] = deepcopy(detail[key])
    for section_key in ("content", "itsi_objects", "splunk_objects", "user_selected_objects"):
        value = detail.get(section_key)
        if isinstance(value, dict):
            summary[f"{section_key}_keys"] = sorted(str(item) for item in value.keys())
    return summary or None


def _content_pack_lifecycle_metadata(client: Any, findings: list[dict[str, str]], catalog_entry: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    pack_status = None
    pack_detail = None
    if hasattr(client, "content_pack_status"):
        try:
            status = client.content_pack_status()
            if isinstance(status, dict):
                pack_status = deepcopy(status)
                status_failures = status.get("failure")
                if status_failures:
                    findings.append(_finding("warn", "content_pack_status", f"Content-pack status reports failures: {status_failures}"))
                else:
                    findings.append(_finding("pass", "content_pack_status", "Content-pack status endpoint is reachable."))
        except (KeyError, ValidationError) as exc:
            findings.append(_finding("warn", "content_pack_status", f"Content-pack status endpoint is unavailable: {exc}"))
    if hasattr(client, "content_pack_detail"):
        try:
            detail = client.content_pack_detail(str(catalog_entry["id"]), str(catalog_entry["version"]))
            pack_detail = _summarize_content_pack_detail(detail)
            findings.append(_finding("pass", "content_pack_detail", "Content-pack detail endpoint is reachable."))
        except (KeyError, ValidationError) as exc:
            findings.append(_finding("warn", "content_pack_detail", f"Content-pack detail endpoint is unavailable: {exc}"))
    return pack_status, pack_detail


def _record_outcome_step(result: dict[str, Any], status: str, kind: str, title: str, detail: str) -> None:
    result.setdefault("steps", []).append({"status": status, "kind": kind, "title": title, "detail": detail})


def _outcome_failed(result: dict[str, Any]) -> bool:
    return any(step.get("status") == "error" for step in result.get("steps", []))


def _outcome_warned(result: dict[str, Any]) -> bool:
    return any(step.get("status") == "warn" for step in result.get("steps", []))


def _configured_outcome_finding(result: dict[str, Any]) -> dict[str, str]:
    if _outcome_failed(result):
        return _finding("error", "configured_outcome", "Configured outcome automation reported errors.")
    if _outcome_warned(result):
        return _finding("warn", "configured_outcome", "Configured outcome automation reported unsupported or manual task types.")
    return _finding("pass", "configured_outcome", "Configured outcome automation completed or previewed cleanly.")


def _record_unsupported_outcome_steps(result: dict[str, Any], outcome_spec: dict[str, Any]) -> None:
    for key in sorted(str(item) for item in outcome_spec if item not in SUPPORTED_CONFIGURED_OUTCOME_KEYS):
        value = outcome_spec.get(key)
        if value in (None, False, "", [], {}):
            continue
        task_label = DOCUMENTED_MANUAL_OUTCOME_HINTS.get(key, key.replace("_", " "))
        _record_outcome_step(
            result,
            "warn",
            "unsupported_outcome",
            key,
            f"{task_label} is not automated by configured_outcome; keep this as an explicit manual follow-up or model it with native/topology payloads.",
        )


def _native_result_payload(native_result: NativeResult) -> dict[str, Any]:
    return {
        "mode": native_result.mode,
        "summary": native_result.summary(),
        "failed": native_result.failed,
        "changes": [change.__dict__ for change in native_result.changes],
        "validations": deepcopy(native_result.validations),
        "diagnostics": deepcopy(native_result.diagnostics),
    }


def _run_macro_outcomes(client: Any, result: dict[str, Any], macros: list[Any], mode: str, pack_app_name: str) -> None:
    for index, macro_spec in enumerate(macros):
        if not isinstance(macro_spec, dict):
            _record_outcome_step(result, "error", "macro", f"macro[{index}]", "Macro outcome entries must be mappings.")
            continue
        app_name = str(macro_spec.get("app") or pack_app_name).strip()
        macro_name = str(macro_spec.get("name") or macro_spec.get("macro") or "").strip()
        definition = macro_spec.get("definition")
        if not app_name or not macro_name or definition is None:
            _record_outcome_step(result, "error", "macro", macro_name or f"macro[{index}]", "Macro outcomes require app/name/definition.")
            continue
        current = client.get_macro(app_name, macro_name) if hasattr(client, "get_macro") else None
        current_definition = str((current or {}).get("definition") or "")
        if mode == "validate":
            if current and current_definition == str(definition):
                _record_outcome_step(result, "pass", "macro", macro_name, "Macro definition matches.")
            else:
                _record_outcome_step(result, "error", "macro", macro_name, "Macro definition does not match or macro is missing.")
            continue
        if mode == "preview":
            action = "noop" if current and current_definition == str(definition) else "update"
            _record_outcome_step(result, "pass", "macro", macro_name, f"Would {action} macro in app {app_name}.")
            continue
        if not hasattr(client, "update_macro"):
            _record_outcome_step(result, "error", "macro", macro_name, "Configured client cannot update macros.")
            continue
        if not current:
            _record_outcome_step(
                result,
                "error",
                "macro",
                macro_name,
                f"Macro '{macro_name}' was not found in app {app_name}; create the macro before running configured_outcome.macros.",
            )
            continue
        payload = {key: value for key, value in macro_spec.items() if key not in {"app", "name", "macro"}}
        payload["definition"] = str(definition)
        try:
            client.update_macro(app_name, macro_name, payload)
        except KeyError:
            _record_outcome_step(
                result,
                "error",
                "macro",
                macro_name,
                f"Macro '{macro_name}' was not found in app {app_name} during update; the macro may have been removed concurrently.",
            )
            continue
        except ValidationError as exc:
            _record_outcome_step(result, "error", "macro", macro_name, f"Macro update failed: {exc}")
            continue
        _record_outcome_step(result, "pass", "macro", macro_name, f"Updated macro in app {app_name}.")


def _run_saved_search_outcomes(client: Any, result: dict[str, Any], searches: list[Any], mode: str, pack_app_name: str) -> None:
    for index, search_spec in enumerate(searches):
        if not isinstance(search_spec, dict):
            _record_outcome_step(result, "error", "saved_search", f"saved_search[{index}]", "Saved-search outcome entries must be mappings.")
            continue
        app_name = str(search_spec.get("app") or pack_app_name).strip()
        search_name = str(search_spec.get("name") or search_spec.get("title") or "").strip()
        if not app_name or not search_name:
            _record_outcome_step(result, "error", "saved_search", search_name or f"saved_search[{index}]", "Saved-search outcomes require app/name.")
            continue
        current = client.get_saved_search(app_name, search_name) if hasattr(client, "get_saved_search") else None
        payload = {key: value for key, value in search_spec.items() if key not in {"app", "name", "title"}}
        if "enabled" in payload:
            payload["disabled"] = "0" if bool_from_any(payload.pop("enabled")) else "1"
        desired_subset = {key: str(value) for key, value in payload.items()}
        current_subset = {key: str((current or {}).get(key)) for key in desired_subset}
        matches = bool(current) and current_subset == desired_subset
        if mode == "validate":
            _record_outcome_step(
                result,
                "pass" if matches else "error",
                "saved_search",
                search_name,
                "Saved search matches." if matches else "Saved search does not match or is missing.",
            )
            continue
        if mode == "preview":
            action = "noop" if matches else "update"
            _record_outcome_step(result, "pass", "saved_search", search_name, f"Would {action} saved search in app {app_name}.")
            continue
        if not hasattr(client, "update_saved_search"):
            _record_outcome_step(result, "error", "saved_search", search_name, "Configured client cannot update saved searches.")
            continue
        if not current:
            _record_outcome_step(
                result,
                "error",
                "saved_search",
                search_name,
                f"Saved search '{search_name}' was not found in app {app_name}; create or install the saved search before running configured_outcome.saved_searches.",
            )
            continue
        try:
            client.update_saved_search(app_name, search_name, payload)
        except KeyError:
            _record_outcome_step(
                result,
                "error",
                "saved_search",
                search_name,
                f"Saved search '{search_name}' was not found in app {app_name} during update; the saved search may have been removed concurrently.",
            )
            continue
        except ValidationError as exc:
            _record_outcome_step(result, "error", "saved_search", search_name, f"Saved-search update failed: {exc}")
            continue
        _record_outcome_step(result, "pass", "saved_search", search_name, f"Updated saved search in app {app_name}.")


def _run_configured_outcome(
    client: Any,
    pack_spec: dict[str, Any],
    base_spec: dict[str, Any],
    mode: str,
    *,
    pack_app_name: str,
) -> dict[str, Any] | None:
    outcome_spec = pack_spec.get("configured_outcome") or pack_spec.get("outcome")
    if not outcome_spec:
        return None
    if not isinstance(outcome_spec, dict):
        raise ValidationError("configured_outcome must be a mapping when provided.")
    result: dict[str, Any] = {"mode": mode, "steps": []}
    native_spec = outcome_spec.get("native")
    if native_spec is not None:
        if not isinstance(native_spec, dict):
            raise ValidationError("configured_outcome.native must be a mapping.")
        merged_native_spec = deepcopy(native_spec)
        if isinstance(base_spec.get("defaults"), dict) and "defaults" not in merged_native_spec:
            merged_native_spec["defaults"] = deepcopy(base_spec["defaults"])
        native_result = NativeWorkflow(client).run(merged_native_spec, mode)
        result["native"] = _native_result_payload(native_result)
        _record_outcome_step(
            result,
            "error" if native_result.failed else "pass",
            "native",
            "configured_outcome.native",
            "Native configured outcome failed." if native_result.failed else "Native configured outcome completed.",
        )
    _run_macro_outcomes(client, result, listify(outcome_spec.get("macros") or outcome_spec.get("macro_updates")), mode, pack_app_name)
    _run_saved_search_outcomes(
        client,
        result,
        listify(outcome_spec.get("saved_searches") or outcome_spec.get("entity_discovery_searches")),
        mode,
        pack_app_name,
    )
    _record_unsupported_outcome_steps(result, outcome_spec)
    return result


def _build_pack_contexts_for_cleanup(spec: dict[str, Any]) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    seen_profiles: set[str] = set()
    for index, pack_spec in enumerate(listify(spec.get("packs"))):
        if not isinstance(pack_spec, dict):
            raise ValidationError("Each topology pack entry must be a mapping.")
        profile_key, profile_meta = resolve_pack_definition(pack_spec, index)
        if profile_key in seen_profiles:
            raise ValidationError(f"Content-pack profile '{profile_key}' is declared more than once in this run.")
        seen_profiles.add(profile_key)
        contexts.append(
            {
                "profile": profile_key,
                "pack_spec": deepcopy(pack_spec),
                "profile_meta": deepcopy(profile_meta),
                "title": str(profile_meta.get("title") or profile_key),
                "catalog_entry": {},
                "preview": {},
            }
        )
    return contexts


def _topology_desired_native_spec(spec: dict[str, Any], pack_contexts: list[dict[str, Any]]) -> dict[str, Any]:
    derived = deepcopy(spec)
    compiled = compile_topology(spec)
    declared_services = [
        deepcopy(service_spec)
        for service_spec in listify(derived.get("services"))
        if isinstance(service_spec, dict)
    ]
    service_titles = {
        str(service_spec.get("title") or "").strip()
        for service_spec in declared_services
        if str(service_spec.get("title") or "").strip()
    }
    pack_context_map = _pack_contexts_by_profile(pack_contexts)
    for node in compiled.get("nodes", {}).values():
        service_spec = node.get("service")
        if isinstance(service_spec, dict):
            title = str(service_spec.get("title") or "").strip()
            if title and title not in service_titles:
                declared_services.append(deepcopy(service_spec))
                service_titles.add(title)
            continue
        reference = node.get("service_ref")
        if isinstance(reference, dict):
            for title in _title_candidates(reference, pack_context_map):
                if title and title not in service_titles:
                    declared_services.append({"title": title})
                    service_titles.add(title)
    if declared_services:
        derived["services"] = declared_services
    return derived


def _native_payload(native_result: NativeResult) -> dict[str, Any]:
    payload = {
        "summary": native_result.summary(),
        "changes": [change.__dict__ for change in native_result.changes],
        "validations": native_result.validations,
        "diagnostics": native_result.diagnostics,
    }
    if native_result.exports:
        payload["exports"] = native_result.exports
    if native_result.inventory:
        payload["inventory"] = native_result.inventory
    if native_result.prune_plan:
        payload["prune_plan"] = native_result.prune_plan
    return payload


def _profile_follow_up_steps(profile_meta: dict[str, Any]) -> list[str]:
    return _candidate_list(profile_meta.get("post_install_steps")) or GENERIC_CONTENT_PACK_STEPS


def _profile_automation_scope(profile_meta: dict[str, Any]) -> str:
    return str(profile_meta.get("automation_scope") or "profile_install_validate_with_guided_followup")


def _append_prerequisite_state(lines: list[str], label: str, state: dict[str, Any]) -> None:
    lines.append(f"- {label} required: `{'yes' if state.get('required') else 'no'}`")
    lines.append(f"- {label} already present: `{'yes' if state.get('present_before') else 'no'}`")
    lines.append(f"- {label} installed in this run: `{'yes' if state.get('installed_in_this_run') else 'no'}`")
    if state.get("source"):
        lines.append(f"- {label} source: `{state['source']}`")
    if state.get("app_id"):
        lines.append(f"- {label} app ID: `{state['app_id']}`")
    if state.get("message"):
        lines.append(f"- {label} status: `{state['message']}`")
    if state.get("checks"):
        lines.append(f"- {label} checks:")
        for check in state["checks"]:
            lines.append(f"  - [{check['status']}] {check['check']}: {check['message']}")


def _render_report(
    mode: str,
    runs: list[PackRun],
    report_dir: Path,
    itsi_state: dict[str, Any],
    content_library_state: dict[str, Any],
) -> Path:
    lines = [
        "# Content Pack Summary",
        "",
        f"- Mode: `{mode}`",
    ]
    _append_prerequisite_state(lines, "ITSI", itsi_state)
    _append_prerequisite_state(lines, "Content library", content_library_state)
    lines.append("")
    for run in runs:
        lines.append(f"## {run.title}")
        lines.append("")
        lines.append(f"- Profile: `{run.profile}`")
        lines.append(f"- Catalog app: `{run.pack_id or 'unresolved'}`")
        lines.append(f"- Version: `{run.version or 'unresolved'}`")
        lines.append(f"- Installed in this run: `{'yes' if run.installed else 'no'}`")
        lines.append(f"- Automation scope: `{run.automation_scope}`")
        lines.append(f"- Operator follow-up required: `{'yes' if run.follow_up_required else 'no'}`")
        if run.preview_summary:
            lines.append(f"- Preview summary: `{run.preview_summary}`")
        if run.install_payload:
            lines.append(f"- Install payload: `{run.install_payload}`")
        if run.pack_status:
            lines.append(f"- Pack status: `{run.pack_status}`")
        if run.pack_detail:
            lines.append(f"- Pack detail: `{run.pack_detail}`")
        if run.configured_outcome:
            lines.append(f"- Configured outcome: `{run.configured_outcome}`")
        lines.append("- Findings:")
        for finding in run.findings:
            lines.append(f"  - [{finding['status']}] {finding['check']}: {finding['message']}")
        lines.append("- Follow-up steps:")
        for step in run.follow_up_steps:
            lines.append(f"  - {step}")
        lines.append("")
    report_path = report_dir / "content-pack-summary.md"
    write_text(report_path, "\n".join(lines).rstrip() + "\n")
    return report_path


def _render_topology_report(
    mode: str,
    runs: list[PackRun],
    report_dir: Path,
    itsi_state: dict[str, Any],
    content_library_state: dict[str, Any],
    native_result: Any,
    topology_result: Any,
) -> Path:
    lines = [
        "# ITSI Topology Summary",
        "",
        f"- Mode: `{mode}`",
    ]
    _append_prerequisite_state(lines, "ITSI", itsi_state)
    _append_prerequisite_state(lines, "Content library", content_library_state)
    lines.append("")
    lines.append("## Content Packs")
    lines.append("")
    if not runs:
        lines.append("- No content packs declared.")
    for run in runs:
        lines.append(f"- `{run.profile}` -> `{run.title}` ({run.version or 'unresolved'})")
        lines.append(f"  - Automation scope: `{run.automation_scope}`")
        lines.append(f"  - Operator follow-up required: `{'yes' if run.follow_up_required else 'no'}`")
        if run.configured_outcome:
            lines.append(f"  - Configured outcome: `{run.configured_outcome}`")
        for finding in run.findings:
            lines.append(f"  - [{finding['status']}] {finding['check']}: {finding['message']}")
        for step in run.follow_up_steps:
            lines.append(f"  - Follow-up: {step}")
    lines.append("")
    lines.append("## Native")
    lines.append("")
    if mode == "validate":
        for item in native_result.validations:
            lines.append(f"- [{item['status']}] {item['object_type']}: {item['title']}")
        if native_result.diagnostics:
            lines.append("")
            lines.append("### Native Diagnostics")
            lines.append("")
            for diagnostic in native_result.diagnostics:
                lines.append(
                    f"- [{diagnostic.get('status', 'info')}] {diagnostic.get('object_type', 'object')}: "
                    f"{diagnostic.get('title', 'unknown')} - {diagnostic.get('message', 'No detail')}"
                )
                for diff in listify(diagnostic.get("diffs"))[:5]:
                    lines.append(
                        f"  - `{diff.get('path', '$')}` expected `{diff.get('expected')}` actual `{diff.get('actual')}`"
                    )
    else:
        for change in native_result.changes:
            lines.append(f"- [{change.status}] {change.object_type}: {change.title} -> {change.detail}")
    lines.append("")
    lines.append("## Topology")
    lines.append("")
    if mode == "validate":
        for item in topology_result.validations:
            lines.append(f"- [{item['status']}] {item['object_type']}: {item['title']}")
    else:
        for change in topology_result.changes:
            lines.append(f"- [{change.status}] {change.object_type}: {change.title} -> {change.detail}")
    report_path = report_dir / "topology-summary.md"
    write_text(report_path, "\n".join(lines).rstrip() + "\n")
    return report_path


class ContentPackWorkflow:
    def __init__(
        self,
        client: Any,
        report_root: str | Path,
        content_library_installer: Any | None = None,
        itsi_installer: Any | None = None,
    ):
        self.client = client
        self.report_root = Path(report_root)
        self.content_library_installer = content_library_installer or ShellContentLibraryInstaller()
        self.itsi_installer = itsi_installer or ShellItsiInstaller()

    def run(self, spec: dict[str, Any], mode: str) -> dict[str, Any]:
        if mode not in {"preview", "apply", "validate"}:
            raise ValidationError(f"Unsupported content-pack mode '{mode}'.")
        platform = infer_platform(spec)
        itsi_state = _ensure_itsi(
            self.client,
            mode=mode,
            spec=spec,
            installer=self.itsi_installer,
        )
        content_library_state = _ensure_content_library(
            self.client,
            platform=platform,
            mode=mode,
            spec=spec,
            installer=self.content_library_installer,
        )
        report_dir = ensure_dir(self.report_root / timestamp_slug())
        _maybe_refresh_content_pack_catalog(self.client, content_library_state, spec)
        catalog = self.client.content_pack_catalog()
        _record_content_library_discovery_state(self.client, content_library_state)
        prerequisite_errors = _state_has_error(itsi_state) or _state_has_error(content_library_state)
        runs: list[PackRun] = []
        for index, pack_spec in enumerate(listify(spec.get("packs"))):
            profile_key, profile_meta = resolve_pack_definition(pack_spec, index)
            catalog_entry = resolve_pack_catalog_entry(catalog, pack_spec, profile_meta)
            pack_title = str(catalog_entry.get("title") or profile_meta["title"])
            pack_app_name = resolve_pack_app_name(self.client, profile_meta, str(catalog_entry.get("id") or ""))
            findings = validate_profile(self.client, pack_spec, profile_meta, pack_app_name)
            pack_status, pack_detail = _content_pack_lifecycle_metadata(self.client, findings, catalog_entry)
            preview_summary = None
            install_payload = None
            install_result = None
            installed = False
            configured_outcome = None
            if mode == "validate":
                installed_versions = _installed_versions(catalog_entry)
                if catalog_entry["version"] in installed_versions:
                    findings.append(_finding("pass", "install", f"{pack_title} version {catalog_entry['version']} is installed."))
                    _check_pack_bundle_visibility(self.client, findings, profile_meta, pack_app_name=pack_app_name)
                else:
                    findings.append(_finding("error", "install", f"{pack_title} version {catalog_entry['version']} is not installed."))
            else:
                try:
                    preview = self.client.preview_content_pack(catalog_entry["id"], catalog_entry["version"])
                except KeyError as exc:
                    raise ValidationError(
                        f"Preview is unavailable for content pack '{pack_title}' version {catalog_entry['version']}."
                    ) from exc
                preview_summary = _preview_summary(preview)
            if mode == "apply" and not prerequisite_errors and not _has_error(findings):
                install_payload = build_install_payload(pack_spec)
                try:
                    install_result = self.client.install_content_pack(catalog_entry["id"], catalog_entry["version"], install_payload)
                except KeyError as exc:
                    raise ValidationError(
                        f"Install failed because content pack '{pack_title}' version {catalog_entry['version']} could not be resolved."
                    ) from exc
                installed = True
                for failure_message in _install_failures(install_result):
                    findings.append(_finding("error", "install", failure_message))
                _check_pack_bundle_visibility(self.client, findings, profile_meta, pack_app_name=pack_app_name)
            elif mode == "preview":
                install_payload = build_install_payload(pack_spec)
            if not prerequisite_errors and not _has_error(findings):
                configured_outcome = _run_configured_outcome(self.client, pack_spec, spec, mode, pack_app_name=pack_app_name)
                if configured_outcome:
                    findings.append(_configured_outcome_finding(configured_outcome))
            runs.append(
                PackRun(
                    profile=profile_key,
                    title=pack_title,
                    pack_id=catalog_entry["id"],
                    version=catalog_entry["version"],
                    findings=findings,
                    preview_summary=preview_summary,
                    install_payload=install_payload,
                    install_result=install_result,
                    installed=installed,
                    automation_scope=_profile_automation_scope(profile_meta),
                    follow_up_required=bool(_profile_follow_up_steps(profile_meta)),
                    follow_up_steps=_profile_follow_up_steps(profile_meta),
                    pack_status=pack_status,
                    pack_detail=pack_detail,
                    configured_outcome=configured_outcome,
                )
            )
        report_path = _render_report(mode, runs, report_dir, itsi_state, content_library_state)
        return {
            "mode": mode,
            "itsi": itsi_state,
            "content_library": content_library_state,
            "report_path": str(report_path),
            "runs": [run.__dict__ for run in runs],
        }


class TopologyWorkflow:
    def __init__(
        self,
        client: Any,
        report_root: str | Path,
        content_library_installer: Any | None = None,
        itsi_installer: Any | None = None,
    ):
        self.client = client
        self.report_root = Path(report_root)
        self.content_library_installer = content_library_installer or ShellContentLibraryInstaller()
        self.itsi_installer = itsi_installer or ShellItsiInstaller()

    def run(self, spec: dict[str, Any], mode: str) -> dict[str, Any]:
        if mode not in {"preview", "apply", "validate", "prune-plan", "cleanup-apply"}:
            raise ValidationError(f"Unsupported topology mode '{mode}'.")
        if mode in {"prune-plan", "cleanup-apply"}:
            return self._run_cleanup_mode(spec, mode)
        platform = infer_platform(spec)
        pack_specs = listify(spec.get("packs"))
        if mode == "apply":
            seen_profiles: set[str] = set()
            resolved_profiles: list[str] = []
            for index, pack_spec in enumerate(pack_specs):
                if not isinstance(pack_spec, dict):
                    raise ValidationError("Each topology pack entry must be a mapping.")
                profile_key, _profile_meta = resolve_pack_definition(pack_spec, index)
                if profile_key in seen_profiles:
                    raise ValidationError(f"Content-pack profile '{profile_key}' is declared more than once in this run.")
                seen_profiles.add(profile_key)
                resolved_profiles.append(profile_key)
            compiled_topology = compile_topology(spec)
            validate_topology_pack_references(
                compiled_topology,
                resolved_profiles,
            )
        itsi_state = _ensure_itsi(
            self.client,
            mode=mode,
            spec=spec,
            installer=self.itsi_installer,
        )
        if pack_specs:
            content_library_state = _ensure_content_library(
                self.client,
                platform=platform,
                mode=mode,
                spec=spec,
                installer=self.content_library_installer,
            )
            _maybe_refresh_content_pack_catalog(self.client, content_library_state, spec)
            catalog = self.client.content_pack_catalog()
            _record_content_library_discovery_state(self.client, content_library_state)
        else:
            content_library_state = {
                "required": False,
                "present_before": False,
                "installed_in_this_run": False,
                "source": None,
                "app_id": None,
                "checks": [],
                "message": "Content library is not required because no content packs were declared.",
            }
            catalog = []
        report_dir = ensure_dir(self.report_root / timestamp_slug())
        prerequisite_errors = _state_has_error(itsi_state) or _state_has_error(content_library_state)
        runs: list[PackRun] = []
        pack_contexts: list[dict[str, Any]] = []
        profile_meta_by_key: dict[str, dict[str, Any]] = {}
        for index, pack_spec in enumerate(pack_specs):
            profile_key, profile_meta = resolve_pack_definition(pack_spec, index)
            profile_meta_by_key[profile_key] = profile_meta
            catalog_entry = resolve_pack_catalog_entry(catalog, pack_spec, profile_meta)
            pack_title = str(catalog_entry.get("title") or profile_meta["title"])
            pack_app_name = resolve_pack_app_name(self.client, profile_meta, str(catalog_entry.get("id") or ""))
            findings = validate_profile(self.client, pack_spec, profile_meta, pack_app_name)
            pack_status, pack_detail = _content_pack_lifecycle_metadata(self.client, findings, catalog_entry)
            preview_summary = None
            preview_payload = None
            install_payload = None
            install_result = None
            installed = False
            configured_outcome = None
            if mode == "validate":
                installed_versions = _installed_versions(catalog_entry)
                if catalog_entry["version"] in installed_versions:
                    findings.append(_finding("pass", "install", f"{pack_title} version {catalog_entry['version']} is installed."))
                    _check_pack_bundle_visibility(self.client, findings, profile_meta, pack_app_name=pack_app_name)
                else:
                    findings.append(_finding("error", "install", f"{pack_title} version {catalog_entry['version']} is not installed."))
            else:
                try:
                    preview_payload = self.client.preview_content_pack(catalog_entry["id"], catalog_entry["version"])
                except KeyError as exc:
                    raise ValidationError(
                        f"Preview is unavailable for content pack '{pack_title}' version {catalog_entry['version']}."
                    ) from exc
                preview_summary = _preview_summary(preview_payload)
            if mode == "apply" and not prerequisite_errors and not _has_error(findings):
                install_payload = build_install_payload(pack_spec)
            elif mode == "preview":
                install_payload = build_install_payload(pack_spec)
            if mode in {"preview", "validate"} and not prerequisite_errors and not _has_error(findings):
                configured_outcome = _run_configured_outcome(self.client, pack_spec, spec, mode, pack_app_name=pack_app_name)
                if configured_outcome:
                    findings.append(_configured_outcome_finding(configured_outcome))
            runs.append(
                PackRun(
                    profile=profile_key,
                    title=pack_title,
                    pack_id=catalog_entry["id"],
                    version=catalog_entry["version"],
                    findings=findings,
                    preview_summary=preview_summary,
                    install_payload=install_payload,
                    install_result=install_result,
                    installed=installed,
                    automation_scope=_profile_automation_scope(profile_meta),
                    follow_up_required=bool(_profile_follow_up_steps(profile_meta)),
                    follow_up_steps=_profile_follow_up_steps(profile_meta),
                    pack_status=pack_status,
                    pack_detail=pack_detail,
                    configured_outcome=configured_outcome,
                )
            )
            pack_contexts.append(
                {
                    "profile": profile_key,
                    "pack_spec": deepcopy(pack_spec),
                    "catalog_entry": deepcopy(catalog_entry),
                    "title": pack_title,
                    "preview": deepcopy(preview_payload),
                    "profile_meta": deepcopy(profile_meta),
                }
            )

        topology_workflow = ServiceTopologyWorkflow(self.client)
        if mode == "apply" and not prerequisite_errors and not any(_has_error(run.findings) for run in runs):
            native_preview = NativeWorkflow(self.client).run(spec, "preview")
            topology_workflow.preflight_apply(
                spec,
                pack_contexts=pack_contexts,
                native_service_snapshots=native_preview.service_snapshots,
                require_live_templates=False,
            )
            for run in runs:
                if not run.install_payload:
                    continue
                try:
                    run.install_result = self.client.install_content_pack(run.pack_id or "", run.version or "", run.install_payload)
                except KeyError as exc:
                    raise ValidationError(
                        f"Install failed because content pack '{run.title}' version {run.version} could not be resolved."
                    ) from exc
                run.installed = True
                for failure_message in _install_failures(run.install_result):
                    run.findings.append(_finding("error", "install", failure_message))
                profile_meta = profile_meta_by_key[run.profile]
                pack_app_name = resolve_pack_app_name(self.client, profile_meta, run.pack_id)
                _check_pack_bundle_visibility(self.client, run.findings, profile_meta, pack_app_name=pack_app_name)
                pack_spec = next(context["pack_spec"] for context in pack_contexts if context["profile"] == run.profile)
                run.configured_outcome = _run_configured_outcome(self.client, pack_spec, spec, mode, pack_app_name=pack_app_name)
                if run.configured_outcome:
                    run.findings.append(_configured_outcome_finding(run.configured_outcome))
            if not any(_has_error(run.findings) for run in runs):
                native_preview = NativeWorkflow(self.client).run(spec, "preview")
                topology_workflow.preflight_apply(
                    spec,
                    pack_contexts=pack_contexts,
                    native_service_snapshots=native_preview.service_snapshots,
                    require_live_templates=True,
                )

        if mode == "apply" and (prerequisite_errors or any(_has_error(run.findings) for run in runs)):
            native_result = NativeResult(mode=mode)
            topology_result = TopologyResult(mode=mode)
        else:
            native_result = NativeWorkflow(self.client).run(spec, mode)
            topology_result = topology_workflow.run(
                spec,
                mode,
                pack_contexts=pack_contexts,
                native_service_snapshots=native_result.service_snapshots,
            )
        report_path = _render_topology_report(
            mode,
            runs,
            report_dir,
            itsi_state,
            content_library_state,
            native_result,
            topology_result,
        )
        return {
            "mode": mode,
            "itsi": itsi_state,
            "content_library": content_library_state,
            "report_path": str(report_path),
            "runs": [run.__dict__ for run in runs],
            "native": {
                **_native_payload(native_result),
            },
            "topology": {
                "changes": [change.__dict__ for change in topology_result.changes],
                "validations": topology_result.validations,
                "resolved_nodes": topology_result.resolved_nodes,
            },
        }

    def _run_cleanup_mode(self, spec: dict[str, Any], mode: str) -> dict[str, Any]:
        pack_contexts = _build_pack_contexts_for_cleanup(spec)
        validate_topology_pack_references(
            compile_topology(spec),
            [str(context.get("profile") or "") for context in pack_contexts],
        )
        itsi_state = _ensure_itsi(
            self.client,
            mode="preview",
            spec=spec,
            installer=self.itsi_installer,
        )
        content_library_state = {
            "required": False,
            "present_before": False,
            "installed_in_this_run": False,
            "source": None,
            "app_id": None,
            "checks": [],
            "message": "Content library is not required for topology prune-plan or cleanup-apply.",
        }
        native_spec = _topology_desired_native_spec(spec, pack_contexts)
        native_result = NativeWorkflow(self.client).run(native_spec, mode)
        topology_result = TopologyResult(mode=mode)
        report_dir = ensure_dir(self.report_root / timestamp_slug())
        report_path = _render_topology_report(
            mode,
            [],
            report_dir,
            itsi_state,
            content_library_state,
            native_result,
            topology_result,
        )
        return {
            "mode": mode,
            "itsi": itsi_state,
            "content_library": content_library_state,
            "report_path": str(report_path),
            "runs": [],
            "native": _native_payload(native_result),
            "topology": {
                "changes": [],
                "validations": [],
                "resolved_nodes": {},
            },
        }

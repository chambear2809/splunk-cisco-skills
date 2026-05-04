#!/usr/bin/env python3
"""Render Splunk Platform <-> Splunk Observability Cloud integration assets.

Reads a YAML or JSON spec (default: ``template.example``) and emits a
numbered, render-first plan tree under ``--output-dir``:

- ``README.md`` + ``architecture.mmd``
- ``00-prerequisites.md`` through ``09-handoff.md``
- ``coverage-report.json``
- ``apply-plan.json``  (idempotency keys; never holds a secret)
- ``payloads/``  (per-step request bodies; never holds a secret)
- ``scripts/``   (per-step apply drivers + cross-skill handoff drivers)
- ``state/``     (apply-state.json + idempotency-keys.json placeholders)
- ``support-tickets/``  (rendered when Splunk Support is needed)
- ``sim-addon/``        (mts-sizing + signalflow-catalog/)

The renderer never accepts a secret value as an argument or writes one
into any rendered file. Token files referenced by the spec are written
only as path strings (e.g. ``${SPLUNK_O11Y_TOKEN_FILE}``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants and tables (single source of truth shared with API clients).
# ---------------------------------------------------------------------------

REGION_REALM_MAP: dict[str, str] = {
    "us-east-1": "us0",
    "us-west-2": "us1",
    "eu-west-1": "eu0",
    "eu-central-1": "eu1",
    "eu-west-2": "eu2",
    "ap-southeast-2": "au0",
    "ap-northeast-1": "jp0",
    "ap-southeast-1": "sg0",
}

REALM_REGION_MAP: dict[str, str] = {v: k for k, v in REGION_REALM_MAP.items()}
REALM_REGION_MAP["us2-gcp"] = "GCP us-central1"

UID_SUPPORTED_REALMS: tuple[str, ...] = (
    "us0",
    "us1",
    "eu0",
    "eu1",
    "eu2",
    "au0",
    "jp0",
    "sg0",
)

LOC_REALM_IPS: dict[str, list[str]] = {
    "us0": ["34.199.200.84/32", "52.20.177.252/32", "52.201.67.203/32", "54.89.1.85/32"],
    "us1": ["44.230.152.35/32", "44.231.27.66/32", "44.225.234.52/32", "44.230.82.104/32"],
    "eu0": ["108.128.26.145/32", "34.250.243.212/32", "54.171.237.247/32"],
    "eu1": ["3.73.240.7/32", "18.196.129.64/32", "3.126.181.171/32"],
    "eu2": ["13.41.86.83/32", "52.56.124.93/32", "35.177.204.133/32"],
    "jp0": ["35.78.47.79/32", "35.77.252.198/32", "35.75.200.181/32"],
    "au0": ["13.54.193.47/32", "13.55.9.109/32", "54.153.190.59/32"],
    "sg0": ["3.0.226.159/32", "18.136.255.76/32", "52.220.199.72/32"],
    "us2-gcp": ["35.247.113.38/32", "35.247.32.72/32", "35.247.86.219/32"],
}

# Full Auto Field Mapping allow-list per the Splunk docs.
AUTO_FIELD_MAPPING: dict[str, list[str]] = {
    "host.name": [
        "host", "host_id", "host.id", "hostid", "host_name", "hostname",
    ],
    "service.name": [
        "application", "application_name", "application.name", "applicationname",
        "application_id", "application.id", "applicationid",
        "app", "app_name", "app.name", "appname",
        "app_id", "app.id", "appid",
        "service", "service_name", "servicename",
        "service_id", "service.id", "serviceid",
    ],
    "trace_id": [
        "trace", "traceid", "trace.id",
    ],
}

SECTION_ORDER: tuple[str, ...] = (
    "prerequisites",
    "token_auth",
    "pairing",
    "centralized_rbac",
    "discover_app",
    "related_content_capabilities",
    "log_observer_connect",
    "dashboard_studio_o11y",
    "sim_addon",
    "handoff",
)

# Numbered file names map (00-prerequisites.md ... 09-handoff.md). Order
# matches the operator-facing plan-file ordering in the SKILL.md spec.
NUMBERED_PLAN_FILES: tuple[tuple[str, str], ...] = (
    ("00-prerequisites.md", "prerequisites"),
    ("01-token-auth.md", "token_auth"),
    ("02-pairing.md", "pairing"),
    ("03-rbac.md", "centralized_rbac"),
    ("04-discover-app.md", "discover_app"),
    ("05-related-content.md", "related_content_capabilities"),
    ("06-log-observer-connect.md", "log_observer_connect"),
    ("07-dashboard-studio.md", "dashboard_studio_o11y"),
    ("08-sim-addon.md", "sim_addon"),
    ("09-handoff.md", "handoff"),
)

# Curated SignalFlow catalog. Each entry stores: a runnable program (no
# SAMPLE_ prefix), an MTS-per-host estimate used for the sizing preflight,
# and a one-line description.
SIGNALFLOW_CATALOG: dict[str, dict[str, Any]] = {
    "aws_ec2": {
        "description": "AWS EC2: CPU, network in/out + packets, disk read/write bytes + ops, status check.",
        "mts_per_entity": 9,
        "program": (
            "data('CPUUtilization', filter=filter('stat', 'mean') and filter('namespace', 'AWS/EC2') and filter('InstanceId', '*'), rollup='average').publish(); "
            "data('NetworkIn', filter=filter('stat', 'sum') and filter('namespace', 'AWS/EC2') and filter('InstanceId', '*'), rollup='sum').publish(); "
            "data('NetworkOut', filter=filter('stat', 'sum') and filter('namespace', 'AWS/EC2') and filter('InstanceId', '*'), rollup='sum').publish(); "
            "data('NetworkPacketsIn', filter=filter('stat', 'sum') and filter('namespace', 'AWS/EC2') and filter('InstanceId', '*'), rollup='sum').publish(); "
            "data('NetworkPacketsOut', filter=filter('stat', 'sum') and filter('namespace', 'AWS/EC2') and filter('InstanceId', '*'), rollup='sum').publish(); "
            "data('DiskReadBytes', filter=filter('stat', 'sum') and filter('namespace', 'AWS/EC2') and filter('InstanceId', '*'), rollup='sum').publish(); "
            "data('DiskWriteBytes', filter=filter('stat', 'sum') and filter('namespace', 'AWS/EC2') and filter('InstanceId', '*'), rollup='sum').publish(); "
            "data('DiskReadOps', filter=filter('stat', 'sum') and filter('namespace', 'AWS/EC2') and filter('InstanceId', '*'), rollup='sum').publish(); "
            "data('DiskWriteOps', filter=filter('stat', 'sum') and filter('namespace', 'AWS/EC2') and filter('InstanceId', '*'), rollup='sum').publish(); "
            "data('StatusCheckFailed', filter=filter('stat', 'count') and filter('namespace', 'AWS/EC2') and filter('InstanceId', '*'), rollup='sum').publish();"
        ),
    },
    "aws_lambda": {
        "description": "AWS Lambda: duration, errors, concurrent executions, invocations, throttles.",
        "mts_per_entity": 5,
        "program": (
            "data('Duration', filter=filter('stat', 'mean') and filter('namespace', 'AWS/Lambda') and filter('Resource', '*'), rollup='average').publish(); "
            "data('Errors', filter=filter('stat', 'sum') and filter('namespace', 'AWS/Lambda') and filter('Resource', '*'), rollup='sum').publish(); "
            "data('ConcurrentExecutions', filter=filter('stat', 'sum') and filter('namespace', 'AWS/Lambda') and filter('Resource', '*'), rollup='sum').publish(); "
            "data('Invocations', filter=filter('stat', 'sum') and filter('namespace', 'AWS/Lambda') and filter('Resource', '*'), rollup='sum').publish(); "
            "data('Throttles', filter=filter('stat', 'sum') and filter('namespace', 'AWS/Lambda') and filter('Resource', '*'), rollup='sum').publish();"
        ),
    },
    "azure": {
        "description": "Azure VM and Functions: CPU, network, disk ops, function execution.",
        "mts_per_entity": 16,
        "program": (
            "data('Percentage CPU', filter=filter('primary_aggregation_type', 'true') and filter('aggregation_type', 'average'), rollup='average').promote('azure_resource_name').publish(); "
            "data('Network In', filter=filter('primary_aggregation_type', 'true') and filter('aggregation_type', 'total'), rollup='sum').promote('azure_resource_name').publish(); "
            "data('Network Out', filter=filter('primary_aggregation_type', 'true') and filter('aggregation_type', 'total'), rollup='sum').promote('azure_resource_name').publish(); "
            "data('Disk Read Bytes', filter=filter('primary_aggregation_type', 'true') and filter('aggregation_type', 'total'), rollup='sum').promote('azure_resource_name').publish(); "
            "data('Disk Write Bytes', filter=filter('primary_aggregation_type', 'true') and filter('aggregation_type', 'total'), rollup='sum').promote('azure_resource_name').publish();"
        ),
    },
    "gcp": {
        "description": "GCP Compute and Functions: CPU, network, disk, function execution.",
        "mts_per_entity": 14,
        "program": (
            "data('instance/cpu/utilization', filter=filter('instance_id', '*'), rollup='average').publish(); "
            "data('instance/network/sent_packets_count', filter=filter('instance_id', '*'), rollup='sum').publish(); "
            "data('instance/network/received_packets_count', filter=filter('instance_id', '*'), rollup='sum').publish(); "
            "data('instance/network/received_bytes_count', filter=filter('instance_id', '*'), rollup='sum').publish(); "
            "data('instance/network/sent_bytes_count', filter=filter('instance_id', '*'), rollup='sum').publish(); "
            "data('instance/disk/write_bytes_count', filter=filter('instance_id', '*'), rollup='sum').publish(); "
            "data('instance/disk/write_ops_count', filter=filter('instance_id', '*'), rollup='sum').publish(); "
            "data('instance/disk/read_bytes_count', filter=filter('instance_id', '*'), rollup='sum').publish(); "
            "data('instance/disk/read_ops_count', filter=filter('instance_id', '*'), rollup='sum').publish();"
        ),
    },
    "containers": {
        "description": "Docker containers: CPU usage, memory, blkio, network.",
        "mts_per_entity": 8,
        "program": (
            "data('cpu.usage.total', filter=filter('plugin', 'docker'), rollup='rate').promote('plugin-instance', allow_missing=True).publish('Docker'); "
            "data('cpu.usage.system', filter=filter('plugin', 'docker'), rollup='rate').promote('plugin-instance', allow_missing=True).publish('Docker'); "
            "data('memory.usage.total', filter=filter('plugin', 'docker')).promote('plugin-instance', allow_missing=True).publish('Docker'); "
            "data('memory.usage.limit', filter=filter('plugin', 'docker')).promote('plugin-instance', allow_missing=True).publish('Docker'); "
            "data('blkio.io_service_bytes_recursive.write', filter=filter('plugin', 'docker'), rollup='rate').promote('plugin-instance', allow_missing=True).publish('Docker'); "
            "data('blkio.io_service_bytes_recursive.read', filter=filter('plugin', 'docker'), rollup='rate').promote('plugin-instance', allow_missing=True).publish('Docker'); "
            "data('network.usage.tx_bytes', filter=filter('plugin', 'docker'), rollup='rate').scale(8).promote('plugin-instance', allow_missing=True).publish('Docker'); "
            "data('network.usage.rx_bytes', filter=filter('plugin', 'docker'), rollup='rate').scale(8).promote('plugin-instance', allow_missing=True).publish('Docker');"
        ),
    },
    "kubernetes": {
        "description": "Kubernetes: container CPU/memory, pod network errors.",
        "mts_per_entity": 5,
        "program": (
            "data('container_cpu_utilization', filter=filter('k8s.pod.name', '*'), rollup='rate').promote('plugin-instance', allow_missing=True).publish('Kubernetes'); "
            "data('container.memory.usage', filter=filter('k8s.pod.name', '*')).promote('plugin-instance', allow_missing=True).publish('Kubernetes'); "
            "data('kubernetes.container_memory_limit', filter=filter('k8s.pod.name', '*')).promote('plugin-instance', allow_missing=True).publish('Kubernetes'); "
            "data('pod_network_receive_errors_total', filter=filter('k8s.pod.name', '*'), rollup='rate').publish('Kubernetes'); "
            "data('pod_network_transmit_errors_total', filter=filter('k8s.pod.name', '*'), rollup='rate').publish('Kubernetes');"
        ),
    },
    "os_hosts": {
        "description": "Smart Agent / collectd OS hosts: CPU, memory, disk, vmpage, network.",
        "mts_per_entity": 18,
        "program": (
            "data('cpu.utilization', filter=(not filter('agent', '*'))).promote('host', allow_missing=True).publish('Hosts'); "
            "data('memory.free', filter=(not filter('agent', '*'))).sum(by=['host']).publish('Hosts'); "
            "data('memory.used', filter=(not filter('agent', '*'))).sum(by=['host']).publish('Hosts'); "
            "data('memory.utilization', filter=(not filter('agent', '*'))).promote('host', allow_missing=True).publish('Hosts'); "
            "data('disk_ops.read', rollup='rate').sum(by=['host.name']).publish('Hosts'); "
            "data('disk_ops.write', rollup='rate').sum(by=['host.name']).publish('Hosts'); "
            "data('df_complex.used', filter=(not filter('agent', '*'))).sum(by=['host']).publish('Hosts'); "
            "data('df_complex.free', filter=(not filter('agent', '*'))).sum(by=['host']).publish('Hosts'); "
            "data('vmpage_io.swap.in', filter=(not filter('agent', '*')), rollup='rate').promote('host', allow_missing=True).publish('Hosts'); "
            "data('vmpage_io.swap.out', filter=(not filter('agent', '*')), rollup='rate').promote('host', allow_missing=True).publish('Hosts'); "
            "data('if_octets.tx', rollup='rate').scale(8).mean(by=['host.name']).publish('Hosts'); "
            "data('if_octets.rx', rollup='rate').scale(8).mean(by=['host.name']).publish('Hosts'); "
            "data('if_errors.rx', rollup='delta').sum(by=['host.name']).publish('Hosts'); "
            "data('if_errors.tx', rollup='delta').sum(by=['host.name']).publish('Hosts');"
        ),
    },
    "apm_errors": {
        "description": "Splunk APM errors: request duration p99 + median + count, error vs non-error.",
        "mts_per_entity": 6,
        "program": (
            "error_durations_p99 = data('service.request.duration.ns.p99', filter=filter('sf_environment', '*') and filter('sf_service', '*') and filter('sf_error', 'true') and not filter('sf_dimensionalized', '*'), rollup='max').mean(by=['sf_service', 'sf_environment', 'sf_error']).publish(label='error_durations_p99'); "
            "non_error_durations_p99 = data('service.request.duration.ns.p99', filter=filter('sf_environment', '*') and filter('sf_service', '*') and filter('sf_error', 'false') and not filter('sf_dimensionalized', '*'), rollup='max').mean(by=['sf_service', 'sf_environment', 'sf_error']).publish(label='non_error_durations_p99'); "
            "error_counts = data('service.request.count', filter=filter('sf_environment', '*') and filter('sf_service', '*') and filter('sf_error', 'true') and not filter('sf_dimensionalized', '*'), rollup='sum').sum(by=['sf_service', 'sf_environment', 'sf_error']).publish(label='error_counts'); "
            "non_error_counts = data('service.request.count', filter=filter('sf_environment', '*') and filter('sf_service', '*') and filter('sf_error', 'false') and not filter('sf_dimensionalized', '*'), rollup='sum').sum(by=['sf_service', 'sf_environment', 'sf_error']).publish(label='non_error_counts');"
        ),
    },
    "apm_throughput": {
        "description": "Splunk APM throughput: request count rate by service / environment.",
        "mts_per_entity": 1,
        "program": (
            "thruput_avg_rate = data('service.request.count', filter=filter('sf_environment', '*') and filter('sf_service', '*') and (not filter('sf_dimensionalized', '*')), rollup='rate').sum(by=['sf_service', 'sf_environment']).publish(label='thruput_avg_rate');"
        ),
    },
    "rum": {
        "description": "Splunk RUM: page views, client errors, page view time, resource requests, web vitals.",
        "mts_per_entity": 12,
        "program": (
            "data('rum.page_view.count').publish(label='rum_page_view'); "
            "data('rum.client_error.count').publish(label='rum_client_error'); "
            "data('rum.page_view.time.ns.p75').scale(0.000001).publish(label='rum_page_view_time'); "
            "data('rum.resource_request.count').publish(label='rum_resource_request'); "
            "data('rum.resource_request.time.ns.p75').scale(0.000001).publish(label='rum_resource_request_time'); "
            "data('rum.crash.count').publish(label='rum_crash_count'); "
            "data('rum.app_error.count').publish(label='rum_app_error_count'); "
            "data('rum.cold_start.time.ns.p75').scale(0.000001).publish(label='rum_cold_start_time'); "
            "data('rum.cold_start.count').publish(label='rum_cold_start_count'); "
            "data('rum.webvitals_lcp.time.ns.p75').scale(0.000001).publish(label='rum_webvitals_lcp'); "
            "data('rum.webvitals_cls.score.p75').publish(label='rum_webvitals_cls'); "
            "data('rum.webvitals_fid.time.ns.p75').scale(0.000001).publish(label='rum_webvitals_fid');"
        ),
    },
    "synthetics": {
        "description": "Splunk Synthetic Monitoring: browser / API / HTTP / SSL / port test results.",
        "mts_per_entity": 6,
        "program": (
            "data('*', filter=filter('sf_product', 'synthetics') and filter('test_type', '*')).publish();"
        ),
    },
}

# MTS hard cap per modular input (Splunk Infrastructure Monitoring Add-on).
MTS_PER_MODULAR_INPUT_CAP = 250000

# Default per-template estimated entity count for the MTS sizing preflight.
DEFAULT_ENTITIES_PER_TEMPLATE = 200


# ---------------------------------------------------------------------------
# Spec loading and validation.
# ---------------------------------------------------------------------------


class RenderError(Exception):
    """Raised when the spec cannot be rendered (FAIL)."""


def load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in {".json"}:
        return json.loads(text)

    # YAML-ish loader. Prefer PyYAML when available, otherwise the bundled
    # ``yaml`` is missing; produce a clear error.
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RenderError(
            "PyYAML is required to parse YAML specs. Install with "
            "'python3 -m pip install -r requirements-agent.txt' or pass a "
            "JSON spec."
        ) from exc

    return yaml.safe_load(text) or {}


def validate_spec(spec: dict[str, Any], target_override: str | None = None) -> dict[str, Any]:
    """Normalize spec, fill in defaults, and FAIL on hard validation errors."""
    if not isinstance(spec, dict):
        raise RenderError("spec root must be a mapping")

    spec.setdefault("api_version", "splunk-observability-cloud-integration-setup/v1")
    if not isinstance(spec["api_version"], str):
        raise RenderError("api_version must be a string")

    target = target_override or spec.get("target", "cloud")
    if target not in {"cloud", "enterprise"}:
        raise RenderError(f"target must be 'cloud' or 'enterprise', got {target!r}")
    spec["target"] = target

    realm = spec.get("realm", "")
    if not realm:
        raise RenderError("realm is required (us0 / us1 / eu0 / eu1 / eu2 / au0 / jp0 / sg0 / us2-gcp)")
    if realm not in REALM_REGION_MAP:
        raise RenderError(
            f"realm {realm!r} is not recognized. Allowed: "
            f"{', '.join(sorted(REALM_REGION_MAP))}"
        )

    if target == "cloud":
        if not spec.get("splunk_cloud_stack"):
            raise RenderError("splunk_cloud_stack is required when target=cloud")

    spec.setdefault("discover_app_required", True)
    spec.setdefault("token_auth", {"enforce": True})

    pairing = spec.setdefault("pairing", {})
    pairing.setdefault("mode", "unified_identity")
    if pairing["mode"] not in {"unified_identity", "service_account"}:
        raise RenderError(
            f"pairing.mode must be 'unified_identity' or 'service_account', got {pairing['mode']!r}"
        )

    multi_org = pairing.get("multi_org") or []
    if not isinstance(multi_org, list):
        raise RenderError("pairing.multi_org must be a list")

    default_count = sum(1 for entry in multi_org if isinstance(entry, dict) and entry.get("make_default"))
    if multi_org and default_count > 1:
        raise RenderError("at most one pairing.multi_org entry may set make_default: true")

    rbac = spec.setdefault("centralized_rbac", {})
    rbac.setdefault("enable_capabilities", False)
    rbac.setdefault("enable_centralized_rbac", False)
    rbac.setdefault("o11y_access_role", {})
    rbac["o11y_access_role"].setdefault("create", True)
    rbac["o11y_access_role"].setdefault("assign_to_roles", ["user", "power", "sc_admin"])

    related = spec.setdefault("related_content", {})
    related.setdefault("enable", True)
    related.setdefault(
        "capabilities_to_grant",
        [
            "read_o11y_content",
            "write_o11y_content",
            "EXECUTE_SIGNAL_FLOW",
            "READ_APM_DATA",
            "READ_BASIC_UI_ACCESS",
            "READ_EVENT",
        ],
    )
    related.setdefault("assign_to_roles", ["user", "power", "sc_admin"])

    discover = spec.setdefault("discover_app", {})
    discover.setdefault("related_content_discovery", True)
    discover.setdefault("test_related_content", "deeplink_only")
    field = discover.setdefault("field_aliasing", {})
    field.setdefault("auto_field_mapping", True)
    discover.setdefault("automatic_ui_updates", True)
    discover.setdefault("access_tokens_realm_token_file_ref", "SPLUNK_O11Y_TOKEN_FILE")
    discover.setdefault("read_permission_roles", ["user", "power", "sc_admin"])

    loc = spec.setdefault("log_observer_connect", {})
    loc.setdefault("enable", True)
    sa = loc.setdefault("service_account", {})
    sa.setdefault("username", "svc_log_observer")
    sa.setdefault("password_file_ref", "--service-account-password-file")
    role = loc.setdefault("role", {})
    role.setdefault("name", "log_observer_connect")
    role.setdefault("base_role", "user")
    role.setdefault("indexes", ["main"])
    role.setdefault("standard_search_limit_per_user", 4)
    role.setdefault("expected_concurrent_users", 10)
    role.setdefault("time_window_seconds", 2592000)
    role.setdefault("earliest_event_seconds", 7776000)
    role.setdefault("disk_space_mb", 1000)
    loc.setdefault("workload_rule_runtime_seconds", 300)
    loc.setdefault("realm_ip_allowlist_handoff", True)

    ds = spec.setdefault("dashboard_studio", {})
    ds.setdefault("validate_default_connection", True)
    ds.setdefault("render_sample_chart", True)

    sim = spec.setdefault("sim_addon", {})
    sim.setdefault("install", True)
    sim.setdefault("index_name", "sim_metrics")
    sim.setdefault("account_name", "production")
    sim.setdefault("org_token_file_ref", "SPLUNK_O11Y_ORG_TOKEN_FILE")
    sim.setdefault("data_collection_enabled", True)
    sim.setdefault("modular_inputs", ["aws_ec2", "kubernetes", "os_hosts"])
    sim.setdefault("itsi_content_pack_handoff", True)
    sim.setdefault("victoria_stack_hec_allowlist_handoff", "auto")

    bad = [name for name in sim["modular_inputs"] if name.upper().startswith("SAMPLE_")]
    if bad:
        raise RenderError(
            "sim_addon.modular_inputs must not begin with 'SAMPLE_' "
            f"(got: {', '.join(bad)}). The renderer auto-strips SAMPLE_; "
            "supply the bare template name (e.g. 'aws_ec2', 'kubernetes')."
        )

    unknown = [name for name in sim["modular_inputs"] if name not in SIGNALFLOW_CATALOG]
    if unknown:
        raise RenderError(
            f"sim_addon.modular_inputs has unknown templates: {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(SIGNALFLOW_CATALOG))}"
        )

    spec.setdefault("enterprise_overrides", {}).setdefault(
        "log_observer_connect_tls_cert_helper", True
    )

    return spec


# ---------------------------------------------------------------------------
# Coverage decision logic.
# ---------------------------------------------------------------------------


def coverage_for(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    target = spec["target"]
    realm = spec["realm"]
    pairing_mode = spec["pairing"]["mode"]
    discover_required = spec.get("discover_app_required", True)
    multi_org = spec["pairing"].get("multi_org") or []
    rbac = spec["centralized_rbac"]
    sim = spec["sim_addon"]
    related = spec["related_content"]
    discover = spec["discover_app"]
    loc = spec["log_observer_connect"]
    ds = spec["dashboard_studio"]

    fed_or_excluded = realm not in UID_SUPPORTED_REALMS

    coverage: dict[str, dict[str, str]] = {}

    coverage["prerequisites"] = {"status": "api_validate", "notes": "Stack/version + region/realm + Discover-app version preflight."}

    coverage["token_auth.flip"] = {"status": "api_apply", "notes": "POST /services/admin/token-auth/tokens_auth -d disabled=false"}

    if target == "enterprise":
        coverage["pairing.uid"] = {"status": "not_applicable", "notes": "UID requires Splunk Cloud Platform."}
    elif fed_or_excluded:
        coverage["pairing.uid"] = {"status": "not_applicable", "notes": f"realm {realm} is excluded from UID (FedRAMP / GovCloud / GCP)."}
    elif pairing_mode == "unified_identity":
        coverage["pairing.uid"] = {"status": "api_apply", "notes": "acs observability pair + GET pairing-status-by-id."}
    else:
        coverage["pairing.uid"] = {"status": "not_applicable", "notes": "spec selected service_account mode."}

    coverage["pairing.sa"] = {
        "status": "api_apply" if (pairing_mode == "service_account" or target == "enterprise" or fed_or_excluded) else "api_validate",
        "notes": "Discover app Access tokens REST tab write (or alternate when UID is in scope).",
    }

    if multi_org:
        coverage["pairing.multi_org_default"] = {
            "status": "deeplink",
            "notes": "Discover app > Configurations > 3-dot menu > Make Default; no public API for default-org.",
        }
    else:
        coverage["pairing.multi_org_default"] = {"status": "not_applicable", "notes": "single-org spec."}

    if target == "enterprise" or fed_or_excluded:
        coverage["centralized_rbac.capabilities"] = {"status": "not_applicable", "notes": "ACS observability not available."}
        coverage["centralized_rbac.cutover"] = {"status": "not_applicable", "notes": "ACS observability not available."}
    else:
        coverage["centralized_rbac.capabilities"] = {
            "status": "api_apply" if rbac.get("enable_capabilities") else "deeplink",
            "notes": "acs observability enable-capabilities (provisions o11y_admin/power/read_only/usage; ~30 min propagation).",
        }
        coverage["centralized_rbac.cutover"] = {
            "status": "api_apply" if rbac.get("enable_centralized_rbac") else "deeplink",
            "notes": "acs observability enable-centralized-rbac (destructive; --i-accept-rbac-cutover required).",
        }
    coverage["centralized_rbac.o11y_access"] = {
        "status": "api_apply" if rbac["o11y_access_role"].get("create") else "deeplink",
        "notes": "Splunk authorize REST: create the o11y_access gate role + assign to roles.",
    }

    coverage["related_content_capabilities"] = {
        "status": "api_apply" if related.get("enable") else "deeplink",
        "notes": "Splunk authorize REST: assign Related Content + Real Time Metrics capabilities.",
    }

    if target == "enterprise" or (target == "cloud" and discover_required is False):
        coverage["discover_app.related_discovery"] = {"status": "not_applicable", "notes": "Discover app Configurations REST is SCP-only."}
        coverage["discover_app.field_aliasing"] = {"status": "not_applicable", "notes": "Discover app Configurations REST is SCP-only."}
        coverage["discover_app.ui_updates"] = {"status": "not_applicable", "notes": "Discover app Configurations REST is SCP-only."}
        coverage["discover_app.access_tokens"] = {"status": "not_applicable", "notes": "Discover app Configurations REST is SCP-only."}
        coverage["discover_app.read_permission"] = {"status": "not_applicable", "notes": "Discover app not installed."}
    else:
        coverage["discover_app.related_discovery"] = {
            "status": "api_apply" if discover.get("related_content_discovery") else "deeplink",
            "notes": "Discover app setup REST (Related Content discovery toggle).",
        }
        coverage["discover_app.field_aliasing"] = {
            "status": "api_apply" if discover.get("field_aliasing", {}).get("auto_field_mapping") else "deeplink",
            "notes": "Discover app setup REST (Auto Field Mapping toggle + alias map).",
        }
        coverage["discover_app.ui_updates"] = {
            "status": "api_apply" if discover.get("automatic_ui_updates") else "deeplink",
            "notes": "Discover app setup REST (Automatic UI updates toggle).",
        }
        coverage["discover_app.access_tokens"] = {
            "status": "api_apply",
            "notes": "Discover app setup REST (Realm + token write).",
        }
        coverage["discover_app.read_permission"] = {
            "status": "api_apply",
            "notes": "Splunk apps REST: grant Read on the Discover app to selected roles.",
        }
    coverage["discover_app.test"] = {"status": "deeplink", "notes": "Test now button is UI only."}

    if loc.get("enable"):
        coverage["log_observer_connect.user"] = {"status": "api_apply", "notes": "Splunk users REST: create LOC service-account user."}
        coverage["log_observer_connect.role"] = {"status": "api_apply", "notes": "Splunk authorize REST: create LOC role with caps + indexes + limits."}
        coverage["log_observer_connect.workload"] = {"status": "api_apply", "notes": "Splunk workload-management REST: create runtime>5m abort rule."}
        if target == "cloud":
            coverage["log_observer_connect.allowlist"] = {"status": "handoff", "notes": "Delegate LOC realm IPs to splunk-cloud-acs-allowlist-setup --features search-api."}
            coverage["log_observer_connect.tls_cert"] = {"status": "not_applicable", "notes": "TLS-cert paste path is SE-only."}
        else:
            coverage["log_observer_connect.allowlist"] = {"status": "handoff", "notes": "SE customers manage their own firewall; rendered IPs are advisory."}
            coverage["log_observer_connect.tls_cert"] = {"status": "handoff", "notes": "SE TLS-cert extraction helper (first cert in chain)."}
        coverage["log_observer_connect.wizard"] = {"status": "deeplink", "notes": "O11y > Settings > Log Observer connections > Add new connection."}
    else:
        for key in [
            "log_observer_connect.user",
            "log_observer_connect.role",
            "log_observer_connect.workload",
            "log_observer_connect.allowlist",
            "log_observer_connect.tls_cert",
            "log_observer_connect.wizard",
        ]:
            coverage[key] = {"status": "not_applicable", "notes": "log_observer_connect.enable=false."}

    coverage["dashboard_studio_o11y.default"] = {
        "status": "api_validate" if ds.get("validate_default_connection") else "deeplink",
        "notes": "Validate default Splunk Observability Cloud connection is set on this stack.",
    }
    coverage["dashboard_studio_o11y.sample"] = {
        "status": "api_apply" if ds.get("render_sample_chart") else "deeplink",
        "notes": "Splunk Dashboard Studio dashboard create REST (sample O11y-metric chart).",
    }

    if sim.get("install"):
        coverage["sim_addon.install"] = {"status": "handoff", "notes": "splunk-app-install --source splunkbase --app-id 5247."}
        coverage["sim_addon.index"] = {"status": "api_apply", "notes": f"Splunk indexes REST: ensure metrics index '{sim.get('index_name')}'."}
        coverage["sim_addon.account"] = {"status": "api_apply", "notes": "SIM Add-on UCC custom REST handler: account create + check-connection + enable."}
        coverage["sim_addon.modular_inputs"] = {
            "status": "api_apply",
            "notes": f"SIM Add-on UCC custom REST handler: modular-input create x{len(sim.get('modular_inputs') or [])}.",
        }
        if target == "cloud":
            coverage["sim_addon.victoria_hec"] = {"status": "handoff", "notes": "Delegate Victoria-stack search-head HEC allowlist to splunk-cloud-acs-allowlist-setup --features hec."}
        else:
            coverage["sim_addon.victoria_hec"] = {"status": "not_applicable", "notes": "Victoria-stack carve-out is Splunk Cloud Platform only."}
        coverage["sim_addon.itsi_pack"] = {
            "status": "handoff" if sim.get("itsi_content_pack_handoff") else "not_applicable",
            "notes": "Delegate Content Pack for Splunk Observability Cloud to splunk-itsi-config.",
        }
    else:
        for key in [
            "sim_addon.install",
            "sim_addon.index",
            "sim_addon.account",
            "sim_addon.modular_inputs",
            "sim_addon.victoria_hec",
            "sim_addon.itsi_pack",
        ]:
            coverage[key] = {"status": "not_applicable", "notes": "sim_addon.install=false."}

    return coverage


# ---------------------------------------------------------------------------
# MTS sizing preflight (renders the report and FAILs on hard cap breach).
# ---------------------------------------------------------------------------


def mts_sizing_report(spec: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[str]]:
    sim = spec["sim_addon"]
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    entities = int(sim.get("expected_entities_per_input") or DEFAULT_ENTITIES_PER_TEMPLATE)
    md_lines = [
        "# Splunk Infrastructure Monitoring Add-on MTS Sizing",
        "",
        f"Per-modular-input MTS estimate (assumed entities per input: {entities}).",
        "Hard caps: 250,000 MTS per computation; 10,000 MTS per data block (default subscription); 30,000 MTS (Enterprise subscription).",
        "",
        "| Template | Entities | MTS per entity | Estimated MTS | Status |",
        "|----------|----------|----------------|---------------|--------|",
    ]
    for name in sim.get("modular_inputs") or []:
        catalog = SIGNALFLOW_CATALOG[name]
        mts_per = catalog["mts_per_entity"]
        total = entities * mts_per
        status = "ok"
        if total > MTS_PER_MODULAR_INPUT_CAP:
            status = "FAIL"
            failures.append(
                f"sim_addon.modular_inputs.{name} estimated MTS {total} exceeds hard cap "
                f"{MTS_PER_MODULAR_INPUT_CAP}. Reduce `expected_entities_per_input` or split this template."
            )
        elif total > MTS_PER_MODULAR_INPUT_CAP * 0.8:
            status = "warn"
        rows.append({"template": name, "entities": entities, "mts_per_entity": mts_per, "mts_total": total, "status": status})
        md_lines.append(f"| {name} | {entities} | {mts_per} | {total} | {status} |")
    md_lines.append("")
    md_lines.append(
        "Sizing tips: keep all data blocks between pipes at the same resolution; avoid wildcard "
        "metric matches; chart `rollup='lag'` to understand lag; cap each modular input at "
        "8-10 computations on typical Splunk CPU sizing."
    )
    return "\n".join(md_lines) + "\n", rows, failures


# ---------------------------------------------------------------------------
# Markdown plan-file emitters.
# ---------------------------------------------------------------------------


def section_prerequisites(spec: dict[str, Any]) -> str:
    target = spec["target"]
    realm = spec["realm"]
    region = REALM_REGION_MAP.get(realm, "(GCP)")
    discover_required = spec.get("discover_app_required", True)
    fed_or_excluded = realm not in UID_SUPPORTED_REALMS
    lines = [
        "# 00 Prerequisites",
        "",
        f"- Target: `{target}`",
        f"- Splunk Observability Cloud realm: `{realm}` (in-region AWS partner: `{region}`)",
    ]
    if target == "cloud":
        lines.append(f"- Splunk Cloud Platform stack: `{spec['splunk_cloud_stack']}`")
        if discover_required:
            lines.append(
                "- Discover Splunk Observability Cloud app: REQUIRED (Splunk Cloud Platform 10.1.2507+); "
                "preflight FAILs render on older versions."
            )
        else:
            lines.append("- Discover Splunk Observability Cloud app: optional; falls back to API-token-only mode on older SCP.")
    else:
        lines.append("- Splunk Enterprise: 9.0.1+ required for Log Observer Connect.")

    if fed_or_excluded and target == "cloud":
        lines.append(
            f"- WARN: realm `{realm}` is outside the supported Unified Identity matrix "
            f"(FedRAMP / GovCloud / GCP). UID sections are marked `not_applicable`; "
            "Service Account pairing remains available."
        )

    lines.extend([
        "",
        "## Region <-> Realm map (UID requires in-region pairings)",
        "",
        "| AWS Region | Splunk Observability Cloud Realm |",
        "|------------|----------------------------------|",
    ])
    for region_name, realm_name in REGION_REALM_MAP.items():
        lines.append(f"| `{region_name}` | `{realm_name}` |")
    lines.append("")
    lines.append(
        "Cross-region pairing requires Splunk Account team approval (preflight WARNs but does not "
        "block render). FedRAMP / GovCloud / GCP regions are excluded from UID."
    )
    lines.extend([
        "",
        "## Operator capabilities required",
        "",
        "- Splunk Cloud Platform: `sc_admin` role + Splunk Cloud Platform admin token (JWT).",
        "- Splunk Enterprise: `admin_all_objects` capability or equivalent.",
        "- `edit_tokens_settings` capability (for token-auth flip).",
        "- Splunk Observability Cloud: admin role on the target org for Unified Identity / `enable-centralized-rbac`.",
        "",
        "## Browser caveat",
        "",
        "Splunk Observability Cloud Related Content previews are blocked by uBlock Origin. "
        "Operators using Firefox + uBlock Origin should turn the extension off for the Splunk domain.",
    ])
    return "\n".join(lines) + "\n"


def section_token_auth(spec: dict[str, Any]) -> str:
    return "\n".join([
        "# 01 Token Authentication",
        "",
        "Token authentication is OFF by default on the Splunk platform. Unified Identity REQUIRES it on.",
        "",
        "## Detection",
        "",
        "```bash",
        "curl -k -u <admin_user>:<admin_password> -X GET https://<splunk-host>:8089/services/admin/token-auth/tokens_auth",
        "```",
        "",
        "## Enable (no restart required)",
        "",
        "```bash",
        "curl -k -u <admin_user>:<admin_password> -X POST https://<splunk-host>:8089/services/admin/token-auth/tokens_auth -d disabled=false",
        "```",
        "",
        "Or use the skill's helper:",
        "",
        "```bash",
        "bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \\",
        "  --enable-token-auth",
        "```",
        "",
        "Required capability: `edit_tokens_settings`. The flip takes effect immediately and does not require a Splunk restart.",
        "",
        "On Splunk Enterprise, the equivalent `authorize.conf` stanza is:",
        "",
        "```ini",
        "[tokens_auth]",
        "disabled = false",
        "```",
    ]) + "\n"


def section_pairing(spec: dict[str, Any]) -> str:
    pairing = spec["pairing"]
    realm = spec["realm"]
    target = spec["target"]
    multi_org = pairing.get("multi_org") or []
    fed_or_excluded = realm not in UID_SUPPORTED_REALMS

    lines = [
        "# 02 Pairing",
        "",
        f"- Mode: `{pairing['mode']}`",
        f"- Realm: `{realm}`",
    ]
    if multi_org:
        lines.append(f"- Multi-org orgs: {len(multi_org)}")
    lines.append("")

    if target == "enterprise":
        lines.append("Splunk Enterprise supports Service Account pairing only. Unified Identity is not available.")
    elif fed_or_excluded:
        lines.append(
            f"Realm `{realm}` is excluded from Unified Identity. Service Account pairing is the supported path."
        )
    elif pairing["mode"] == "unified_identity":
        lines.extend([
            "## Unified Identity (UID) pair",
            "",
            "```bash",
            "bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh --apply pairing \\",
            "  --admin-token-file \"${SPLUNK_O11Y_ADMIN_TOKEN_FILE}\" \\",
            f"  --realm {realm}",
            "```",
            "",
            "Or via the ACS REST API:",
            "",
            "```bash",
            "SPLUNK_CLOUD_PAIRING_CURL_CONFIG=\"$(mktemp)\"",
            "chmod 600 \"${SPLUNK_CLOUD_PAIRING_CURL_CONFIG}\"",
            "{ printf 'header = \"Authorization: Bearer '; tr -d '\\r\\n' < \"${SPLUNK_CLOUD_ADMIN_JWT_FILE}\"; printf '\"\\n';",
            "  printf 'header = \"o11y-access-token: '; tr -d '\\r\\n' < \"${SPLUNK_O11Y_ADMIN_TOKEN_FILE}\"; printf '\"\\n'; } > \"${SPLUNK_CLOUD_PAIRING_CURL_CONFIG}\"",
            "trap 'rm -f \"${SPLUNK_CLOUD_PAIRING_CURL_CONFIG}\"' EXIT",
            "",
            "curl -X POST 'https://admin.splunk.com/${SPLUNK_CLOUD_STACK}/adminconfig/v2/observability/sso-pairing' \\",
            "  -K \"${SPLUNK_CLOUD_PAIRING_CURL_CONFIG}\" \\",
            "  -H 'Content-Type: application/json'",
            "```",
            "",
            "Returns `{\"id\": \"<pairing-id>\"}`. Poll with:",
            "",
            "```bash",
            "curl -X GET 'https://admin.splunk.com/${SPLUNK_CLOUD_STACK}/adminconfig/v2/observability/sso-pairing/${PAIRING_ID}' \\",
            "  -K \"${SPLUNK_CLOUD_PAIRING_CURL_CONFIG}\" \\",
            "  -H 'Content-Type: application/json'",
            "```",
            "",
            "Statuses are `SUCCESS`, `FAILED`, or `IN_PROGRESS`.",
        ])
    else:
        lines.append("Service Account (SA) pairing uses an Splunk Observability Cloud API access token written into the Discover app's Access tokens tab.")

    if multi_org:
        lines.extend([
            "",
            "## Multi-org plan",
            "",
            "| Realm | Label | Default? |",
            "|-------|-------|----------|",
        ])
        for entry in multi_org:
            label = entry.get("label", "")
            mark = "Yes" if entry.get("make_default") else ""
            lines.append(f"| `{entry.get('realm')}` | {label} | {mark} |")
        lines.extend([
            "",
            "**Make Default** has no public API. After all orgs are paired, open Discover Splunk Observability Cloud > Configurations > 3-dot menu next to the desired org > **Make Default**.",
            "",
            "Render the deeplink with:",
            "",
            "```bash",
            "bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \\",
            "  --make-default-deeplink \\",
            f"  --realm {next((e.get('realm') for e in multi_org if e.get('make_default')), multi_org[0].get('realm'))}",
            "```",
        ])

    return "\n".join(lines) + "\n"


def section_rbac(spec: dict[str, Any]) -> str:
    rbac = spec["centralized_rbac"]
    target = spec["target"]
    realm = spec["realm"]
    fed_or_excluded = realm not in UID_SUPPORTED_REALMS

    lines = [
        "# 03 Centralized RBAC",
        "",
    ]
    if target == "enterprise" or fed_or_excluded:
        lines.append("Centralized RBAC requires ACS observability commands; not available for the chosen target/realm. Marked `not_applicable`.")
        return "\n".join(lines) + "\n"

    lines.extend([
        "## Step 1: enable-capabilities (safe, ~30 min propagation)",
        "",
        "```bash",
        "acs --format structured observability enable-capabilities",
        "```",
        "",
        "Provisions the four prepackaged Splunk Observability Cloud roles (`o11y_admin`, `o11y_power`, `o11y_read_only`, `o11y_usage`) on Splunk Cloud Platform. The roles appear in the Roles UI after about 30 minutes.",
        "",
        "## Step 2: o11y_access gate role",
        "",
        f"Create the custom Splunk role `o11y_access` (no extra capabilities) and assign to: `{', '.join(rbac['o11y_access_role'].get('assign_to_roles') or [])}`.",
        "",
        "Missing this role yields the `You do not have access to Splunk Observability Cloud` error at first login.",
        "",
        "## Step 3 (DESTRUCTIVE): enable-centralized-rbac",
        "",
        "```bash",
        "bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh --apply rbac \\",
        "  --admin-token-file \"${SPLUNK_O11Y_ADMIN_TOKEN_FILE}\" \\",
        "  --i-accept-rbac-cutover",
        "```",
        "",
        "After this step Splunk Cloud Platform becomes the RBAC store for Splunk Observability Cloud. UID-mapped users WITHOUT an `o11y_*` role are LOCKED OUT.",
        "",
        "The skill refuses to apply this step without `--i-accept-rbac-cutover` AND a passed preflight that confirms every UID-mapped user already holds an `o11y_*` role.",
        "",
        "## UID role mapping (auto-applied at first login)",
        "",
        "| Splunk Cloud Platform role | Splunk Observability Cloud role |",
        "|----------------------------|---------------------------------|",
        "| `sc_admin` | `admin` |",
        "| `power` AND `can_delete` | `power` |",
        "| `user` | `power` |",
        "",
        "There is no auto-mapping to `usage` or `read_only`; assign manually after first login.",
    ])
    return "\n".join(lines) + "\n"


def section_discover_app(spec: dict[str, Any]) -> str:
    discover = spec["discover_app"]
    target = spec["target"]
    discover_required = spec.get("discover_app_required", True)
    realm = spec["realm"]
    multi_org = spec["pairing"].get("multi_org") or []

    lines = [
        "# 04 Discover Splunk Observability Cloud app",
        "",
    ]
    if target == "enterprise":
        lines.extend([
            "The Discover app's Configurations REST surface is Splunk Cloud Platform only. ",
            "On Splunk Enterprise, configure the equivalent connection via the Discover app's Access tokens UI ",
            "(if installed) or via Splunk Observability Cloud's Add new connection wizard.",
            "",
            "Marked `not_applicable` for the target=enterprise renderer.",
        ])
        return "\n".join(lines) + "\n"
    if not discover_required:
        lines.extend([
            "Spec set `discover_app_required: false`; renderer assumes Splunk Cloud Platform < 10.1.2507 (no Configurations UI).",
            "Falls back to API-token-only pairing recorded under `02-pairing.md`.",
        ])
        return "\n".join(lines) + "\n"

    lines.extend([
        "Configures the five Configurations tabs of the in-platform Discover app, plus the Read permission grant.",
        "",
        "## Tab 1: Related Content discovery",
        "",
        f"- Toggle: `{discover['related_content_discovery']}`",
        "- After enable, the Search & Reporting app surfaces a Related Content button beside logs whose host/service/trace fields correlate with Splunk Observability Cloud data.",
        "",
        "## Tab 2: Test related content",
        "",
        f"- Mode: `{discover['test_related_content']}`",
        "- The Test now button is UI only — rendered as a deeplink to Splunk's Search & Reporting app.",
        "",
        "## Tab 3: Field aliasing",
        "",
        f"- Auto Field Mapping: `{discover['field_aliasing']['auto_field_mapping']}`",
        "",
        "When Auto Field Mapping is on, the following aliases are applied in Splunk so Related Content matches Splunk Observability Cloud's canonical field names:",
        "",
    ])
    for canonical, aliases in AUTO_FIELD_MAPPING.items():
        lines.append(f"- **{canonical}** ⇐ {', '.join(aliases)}")
    lines.append("")

    lines.extend([
        "## Tab 4: Automatic UI updates",
        "",
        f"- Toggle: `{discover['automatic_ui_updates']}`",
        "- Required for real-time previews. Without it the Search & Reporting Related Content panel does not refresh.",
        "",
        "## Tab 5: Access tokens",
        "",
        f"- Realm: `{realm}`",
        f"- Token file: read from `${{{discover['access_tokens_realm_token_file_ref']}}}` (never inlined here).",
        "",
        "## Read permission grant",
        "",
        f"- Roles granted Read on the Discover app: `{', '.join(discover['read_permission_roles'])}`",
        "- Without Read permission, users cannot see Related Content links in the Search & Reporting page.",
    ])

    if multi_org:
        lines.extend([
            "",
            "## Multi-org Make Default + Override",
            "",
            "- **Make Default (Admin)**: Discover Splunk Observability Cloud > Configurations > 3-dot menu next to the org > Make Default. No public API.",
            "- **Override default organization (User)**: Discover Splunk Observability Cloud > Related Content discovery section > Override default organization. Per-user.",
        ])
    return "\n".join(lines) + "\n"


def section_related_content(spec: dict[str, Any]) -> str:
    related = spec["related_content"]
    if not related.get("enable"):
        return "# 05 Related Content + Real Time Metrics\n\nrelated_content.enable=false; section marked not_applicable.\n"
    lines = [
        "# 05 Related Content + Real Time Metrics",
        "",
        "Capabilities assigned for Real Time Metrics view + Search & Reporting Related Content previews:",
        "",
        "| Capability | Purpose |",
        "|------------|---------|",
        "| `read_o11y_content` | Read Splunk Observability Cloud content (Real Time Metrics). |",
        "| `write_o11y_content` | Create / import O11y charts and service maps. |",
        "| `EXECUTE_SIGNAL_FLOW` | Execute SignalFlow (troubleshooting fallback path). |",
        "| `READ_APM_DATA` | Read APM data in Related Content. |",
        "| `READ_BASIC_UI_ACCESS` | Basic UI access for Related Content links. |",
        "| `READ_EVENT` | Read O11y events in Related Content. |",
        "",
        f"Roles getting these capabilities: `{', '.join(related['assign_to_roles'])}`",
        "",
        "## uBlock Origin warning",
        "",
        "If users use Firefox with uBlock Origin, the extension blocks Splunk Observability Cloud previews. Recommend operators turn it off for the Splunk domain.",
    ]
    return "\n".join(lines) + "\n"


def section_loc(spec: dict[str, Any]) -> str:
    loc = spec["log_observer_connect"]
    target = spec["target"]
    realm = spec["realm"]

    if not loc.get("enable"):
        return "# 06 Log Observer Connect\n\nlog_observer_connect.enable=false; section marked not_applicable.\n"

    role = loc["role"]
    sa = loc["service_account"]
    runtime = loc["workload_rule_runtime_seconds"]

    lines = [
        "# 06 Log Observer Connect",
        "",
        f"- Service-account user: `{sa['username']}`",
        f"- Service-account password: read from {sa['password_file_ref']} (chmod 600).",
        f"- Role: `{role['name']}` (base: `{role['base_role']}`)",
        f"- Indexes: `{', '.join(role['indexes'])}`",
        f"- Standard search limit: `{role['standard_search_limit_per_user'] * role['expected_concurrent_users']}` (`{role['standard_search_limit_per_user']}` per user x `{role['expected_concurrent_users']}` users)",
        f"- Time window: `{role['time_window_seconds']}s` (~{role['time_window_seconds'] // 86400}d), earliest event: `{role['earliest_event_seconds']}s` (~{role['earliest_event_seconds'] // 86400}d)",
        f"- Disk space limit: `{role['disk_space_mb']} MB`",
        f"- Workload rule runtime cap: `{runtime}s` (Abort search predicate `user={sa['username']} AND runtime>5m`)",
        "",
        "## Capabilities",
        "",
        "Required: `edit_tokens_own`, `search`. Forbidden: `indexes_list_all`.",
    ]

    if target == "cloud":
        lines.extend([
            "",
            "## Splunk Cloud Platform: realm IPs (search-api allowlist)",
            "",
            f"For realm `{realm}`, the LOC backend reaches the search head from these IPs. Add to the Splunk Cloud Platform `search-api` allowlist:",
            "",
        ])
        ips = LOC_REALM_IPS.get(realm, [])
        for ip in ips:
            lines.append(f"- `{ip}`")
        lines.extend([
            "",
            "Handed off to `splunk-cloud-acs-allowlist-setup`:",
            "",
            "```bash",
            "bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh \\",
            "  --phase render \\",
            "  --features search-api \\",
            f"  --search-api-subnets {','.join(ips)}",
            "```",
        ])
    else:
        lines.extend([
            "",
            "## Splunk Enterprise: TLS-cert capture (Discover app Add new connection paste)",
            "",
            "The Splunk Observability Cloud Add new connection wizard (Splunk Enterprise path) requires the leaf certificate from the search-head TLS chain. The skill renders a helper:",
            "",
            "```bash",
            "openssl s_client -connect <splunk-host>:8089 -showcerts < /dev/null 2>/dev/null \\",
            "  | sed -n '/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/p' \\",
            "  | awk '/-----BEGIN/{c++} c==1' \\",
            "  > splunk-observability-cloud-integration-rendered/06-log-observer-connect/leaf-cert.pem",
            "```",
            "",
            "Paste the contents into the Add new connection wizard's Certificate field.",
            "",
            f"## Splunk Enterprise realm IPs (firewall guidance, realm `{realm}`)",
            "",
        ])
        for ip in LOC_REALM_IPS.get(realm, []):
            lines.append(f"- `{ip}`")
        lines.append("")
        lines.append("Splunk Enterprise customers manage their own firewall; the IPs above are advisory.")

    lines.extend([
        "",
        "## Splunk Observability Cloud wizard deeplink",
        "",
        f"https://app.{realm if realm != 'us2-gcp' else 'us2'}.signalfx.com/#/settings/logobserverconnections",
    ])
    return "\n".join(lines) + "\n"


def section_dashboard_studio(spec: dict[str, Any]) -> str:
    ds = spec["dashboard_studio"]
    lines = [
        "# 07 Dashboard Studio (Splunk Observability Cloud metrics)",
        "",
        f"- Validate default connection: `{ds['validate_default_connection']}`",
        f"- Render sample chart: `{ds['render_sample_chart']}`",
        "",
        "Dashboard Studio O11y metrics charts pull from the default Splunk Observability Cloud connection on this Splunk Cloud Platform stack. Without a default connection, the prepackaged dashboards do not work for Unified Identity SSO users.",
        "",
        "## Sample chart spec",
        "",
        "```json",
        json.dumps(
            {
                "title": "Splunk Observability Cloud sample (host CPU)",
                "dataSources": {
                    "ds_o11y_cpu": {
                        "type": "ds.observabilityMetrics",
                        "options": {
                            "program": "data('cpu.utilization').publish()",
                            "timeRange": {"earliest": "-15m", "latest": "now"},
                        },
                    }
                },
                "visualizations": {
                    "viz_cpu": {
                        "type": "splunk.line",
                        "dataSources": {"primary": "ds_o11y_cpu"},
                        "title": "CPU utilization",
                    }
                },
                "layout": {"type": "absolute", "structure": [{"item": "viz_cpu", "type": "block"}]},
            },
            indent=2,
        ),
        "```",
    ]
    return "\n".join(lines) + "\n"


def section_sim_addon(spec: dict[str, Any]) -> str:
    sim = spec["sim_addon"]
    target = spec["target"]
    if not sim.get("install"):
        return "# 08 Splunk Infrastructure Monitoring Add-on\n\nsim_addon.install=false; section marked not_applicable.\n"

    lines = [
        "# 08 Splunk Infrastructure Monitoring Add-on (Splunk_TA_sim, Splunkbase 5247)",
        "",
        "## Install (handed off to splunk-app-install)",
        "",
        "```bash",
        "bash skills/splunk-app-install/scripts/install_app.sh \\",
        "  --source splunkbase \\",
        "  --app-id 5247 \\",
        "  --no-update",
        "```",
        "",
        "Install on search heads (or the Splunk Cloud Inputs Data Manager on Splunk Cloud Platform).",
        "",
        f"## Index: `{sim['index_name']}`",
        "",
        f"Ensure metrics index `{sim['index_name']}` exists. The skill creates it if missing.",
        "",
        f"## Account: `{sim['account_name']}`",
        "",
        f"- Realm: `{spec['realm']}`",
        f"- Org token file: `${{{sim['org_token_file_ref']}}}` (chmod 600; never inlined).",
        f"- Data Collection: `{sim['data_collection_enabled']}`",
        "- Advanced Settings: Job Start Rate=60, Event Search Rate=30 (per Splunk's published defaults).",
        "- The first account auto-becomes the default (used when `org_id` is omitted from the `sim` SPL command).",
        "",
        f"## Modular inputs ({len(sim['modular_inputs'])} from the curated catalog)",
        "",
    ]
    for name in sim["modular_inputs"]:
        catalog = SIGNALFLOW_CATALOG[name]
        lines.append(f"- **{name}** — {catalog['description']} (≈ {catalog['mts_per_entity']} MTS/entity)")
    lines.extend([
        "",
        "All catalog programs are written without the `SAMPLE_` prefix so they actually run. The renderer rejects user-supplied names that begin with `SAMPLE_`.",
        "",
        "See `sim-addon/mts-sizing.md` for the per-input MTS estimate and `sim-addon/signalflow-catalog/` for the deterministic SignalFlow per template.",
        "",
        "## Splunk Cloud Victoria-stack search-head HEC allowlist",
    ])
    if target == "cloud" and sim.get("victoria_stack_hec_allowlist_handoff") in ("auto", True):
        lines.extend([
            "",
            "Splunk Cloud Victoria stacks require the search-head IP in the `hec` allowlist before the SIM Add-on can connect to the HEC receiver. Handed off to `splunk-cloud-acs-allowlist-setup`:",
            "",
            "```bash",
            "bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh \\",
            "  --phase render \\",
            "  --features hec",
            "```",
        ])
    elif target == "cloud":
        lines.append("\nVictoria-stack HEC allowlist handoff disabled in the spec.\n")
    else:
        lines.append("\nNot applicable on Splunk Enterprise.\n")

    if sim.get("itsi_content_pack_handoff"):
        lines.extend([
            "",
            "## ITSI Content Pack for Splunk Observability Cloud",
            "",
            "Handed off to `splunk-itsi-config`:",
            "",
            "```bash",
            "bash skills/splunk-itsi-config/scripts/setup.sh --content-pack splunk_observability_cloud",
            "```",
            "",
            "The pack depends on this skill's SIM Add-on configuration; install order is correct.",
        ])

    return "\n".join(lines) + "\n"


def section_handoff(spec: dict[str, Any]) -> str:
    target = spec["target"]
    realm = spec["realm"]
    sim = spec["sim_addon"]
    loc = spec["log_observer_connect"]

    lines = [
        "# 09 Handoff Bundle",
        "",
        "Every cross-skill handoff command rendered for this run. Copy and run individually as your team's change-management requires.",
        "",
        "## App install (Splunk_TA_sim)",
        "",
        "```bash",
        "bash skills/splunk-app-install/scripts/install_app.sh \\",
        "  --source splunkbase --app-id 5247 --no-update",
        "```",
    ]

    if target == "cloud" and loc.get("enable"):
        ips = LOC_REALM_IPS.get(realm, [])
        lines.extend([
            "",
            "## ACS Log Observer Connect search-api allowlist",
            "",
            "```bash",
            "bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh \\",
            "  --phase render --features search-api \\",
            f"  --search-api-subnets {','.join(ips)}",
            "```",
        ])
    if target == "cloud" and sim.get("install"):
        lines.extend([
            "",
            "## ACS Splunk Cloud Victoria-stack HEC allowlist",
            "",
            "```bash",
            "bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh \\",
            "  --phase render --features hec",
            "```",
        ])
    if sim.get("itsi_content_pack_handoff"):
        lines.extend([
            "",
            "## ITSI Content Pack for Splunk Observability Cloud",
            "",
            "```bash",
            "bash skills/splunk-itsi-config/scripts/setup.sh --content-pack splunk_observability_cloud",
            "```",
        ])

    lines.extend([
        "",
        "## Other Splunk Observability Cloud workflows (see those skills)",
        "",
        "- `skills/splunk-observability-otel-collector-setup/SKILL.md` — OTel collection.",
        "- `skills/splunk-observability-dashboard-builder/SKILL.md` — dashboards/charts/variables.",
        "- `skills/splunk-observability-native-ops/SKILL.md` — detectors, RUM, APM, Synthetics, On-Call routing.",
        "- `skills/splunk-oncall-setup/SKILL.md` — Splunk On-Call wiring.",
    ])
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Per-step apply scripts (rendered into <output>/scripts/).
# ---------------------------------------------------------------------------


SHEBANG = "#!/usr/bin/env bash\nset -euo pipefail\n\n"


SPLUNK_CURL_AUTH_HELPER = """\
_curl_config_escape() {
  local value="${1:-}"
  value="${value//\\\\/\\\\\\\\}"
  value="${value//\\"/\\\\\\"}"
  value="${value//$'\\n'/\\\\n}"
  value="${value//$'\\r'/\\\\r}"
  printf '%s' "${value}"
}

make_splunk_auth_config() {
  local auth_config
  auth_config="$(mktemp)"
  chmod 600 "${auth_config}"
  printf 'user = "%s:%s"\\n' "$(_curl_config_escape "${SPLUNK_USER}")" "$(_curl_config_escape "${SPLUNK_PASS}")" > "${auth_config}"
  printf '%s\\n' "${auth_config}"
}

"""


def apply_script_token_auth() -> str:
    return SHEBANG + (
        "# Step: enable token authentication on the Splunk platform.\n"
        ": \"${SPLUNK_SEARCH_API_URI:?SPLUNK_SEARCH_API_URI must be set (https://host:8089)}\"\n"
        ": \"${SPLUNK_USER:?SPLUNK_USER must be set}\"\n"
        ": \"${SPLUNK_PASS:?SPLUNK_PASS must be set}\"\n\n"
        + SPLUNK_CURL_AUTH_HELPER
        + "SPLUNK_AUTH_CONFIG=\"$(make_splunk_auth_config)\"\n"
        "trap 'rm -f \"${SPLUNK_AUTH_CONFIG}\"' EXIT\n\n"
        "curl -k -K \"${SPLUNK_AUTH_CONFIG}\" \\\n"
        "  -X POST \"${SPLUNK_SEARCH_API_URI}/services/admin/token-auth/tokens_auth\" \\\n"
        "  -d disabled=false\n"
    )


def apply_script_pairing(spec: dict[str, Any]) -> str:
    realm = spec["realm"]
    multi = spec["pairing"].get("multi_org") or [{"realm": realm}]
    stack = spec.get("splunk_cloud_stack", "")
    body = SHEBANG + (
        "# Step: Unified Identity pair (one call per realm).\n"
        ": \"${SPLUNK_O11Y_ADMIN_TOKEN_FILE:?SPLUNK_O11Y_ADMIN_TOKEN_FILE must point to a chmod-600 admin token file}\"\n\n"
        "PYTHON_BIN=\"${PYTHON_BIN:-python3}\"\n"
        "PAIRING_API=\"${PAIRING_API:-skills/splunk-observability-cloud-integration-setup/scripts/o11y_pairing_api.py}\"\n"
        f"SPLUNK_CLOUD_STACK=\"${{SPLUNK_CLOUD_STACK:-{stack}}}\"\n"
        "PAIRING_ARGS=(--admin-token-file \"${SPLUNK_O11Y_ADMIN_TOKEN_FILE}\")\n"
        "[[ -n \"${SPLUNK_CLOUD_STACK:-}\" ]] && PAIRING_ARGS+=(--splunk-cloud-stack \"${SPLUNK_CLOUD_STACK}\")\n"
        "[[ -n \"${SPLUNK_CLOUD_ADMIN_JWT_FILE:-}\" ]] && PAIRING_ARGS+=(--splunk-cloud-admin-jwt-file \"${SPLUNK_CLOUD_ADMIN_JWT_FILE}\")\n\n"
    )
    for entry in multi:
        body += (
            f"# Pair realm: {entry.get('realm')}\n"
            f"\"${{PYTHON_BIN}}\" \"${{PAIRING_API}}\" \"${{PAIRING_ARGS[@]}}\" pair --realm {entry.get('realm')}\n\n"
        )
    return body


def apply_script_rbac(spec: dict[str, Any]) -> str:
    rbac = spec["centralized_rbac"]
    body = SHEBANG + "# Step: Centralized RBAC.\n\n"
    if rbac.get("enable_capabilities"):
        body += "acs --format structured observability enable-capabilities\n\n"
    if rbac["o11y_access_role"].get("create"):
        body += (
            ": \"${SPLUNK_SEARCH_API_URI:?SPLUNK_SEARCH_API_URI must be set}\"\n"
            ": \"${SPLUNK_USER:?SPLUNK_USER must be set}\"\n"
            ": \"${SPLUNK_PASS:?SPLUNK_PASS must be set}\"\n\n"
            f"{SPLUNK_CURL_AUTH_HELPER}"
            "SPLUNK_AUTH_CONFIG=\"$(make_splunk_auth_config)\"\n"
            "trap 'rm -f \"${SPLUNK_AUTH_CONFIG}\"' EXIT\n\n"
            "# Create the o11y_access gate role (no extra capabilities).\n"
            "curl -k -K \"${SPLUNK_AUTH_CONFIG}\" \\\n"
            "  -X POST \"${SPLUNK_SEARCH_API_URI}/services/authorization/roles\" \\\n"
            "  -d name=o11y_access -d srchIndexesAllowed=\"\" -d srchIndexesDefault=\"\"\n\n"
        )
    if rbac.get("enable_centralized_rbac"):
        body += (
            "# DESTRUCTIVE: requires --i-accept-rbac-cutover at the setup.sh level.\n"
            ": \"${SPLUNK_O11Y_ADMIN_TOKEN_FILE:?SPLUNK_O11Y_ADMIN_TOKEN_FILE must point to a chmod-600 admin token file}\"\n"
            "if [[ \"${SOICS_RBAC_CUTOVER_ACK:-false}\" != \"true\" ]]; then\n"
            "  echo 'enable-centralized-rbac refused: SOICS_RBAC_CUTOVER_ACK!=true. Re-run with --i-accept-rbac-cutover.' >&2\n"
            "  exit 2\n"
            "fi\n"
            "PYTHON_BIN=\"${PYTHON_BIN:-python3}\"\n"
            "PAIRING_API=\"${PAIRING_API:-skills/splunk-observability-cloud-integration-setup/scripts/o11y_pairing_api.py}\"\n"
            "\"${PYTHON_BIN}\" \"${PAIRING_API}\" \\\n"
            "  --admin-token-file \"${SPLUNK_O11Y_ADMIN_TOKEN_FILE}\" \\\n"
            f"  --realm {spec['realm']} \\\n"
            "  --i-accept-rbac-cutover \\\n"
            "  enable-centralized-rbac\n"
        )
    return body


def apply_script_discover_app(spec: dict[str, Any]) -> str:
    target = spec["target"]
    if target == "enterprise" or not spec.get("discover_app_required", True):
        return SHEBANG + "# Discover app Configurations REST is Splunk Cloud Platform 10.1.2507+ only.\necho 'discover_app: not applicable for this target/version' >&2\n"
    realm = spec["realm"]
    discover = spec["discover_app"]
    body = SHEBANG + (
        "# Step: Discover Splunk Observability Cloud app — five Configurations tabs + Read permission grant.\n"
        ": \"${SPLUNK_SEARCH_API_URI:?SPLUNK_SEARCH_API_URI must be set}\"\n"
        ": \"${SPLUNK_USER:?SPLUNK_USER must be set}\"\n"
        ": \"${SPLUNK_PASS:?SPLUNK_PASS must be set}\"\n"
        f": \"${{{discover['access_tokens_realm_token_file_ref']}:?{discover['access_tokens_realm_token_file_ref']} must point to a chmod-600 token file}}\"\n\n"
        f"{SPLUNK_CURL_AUTH_HELPER}"
        "SPLUNK_AUTH_CONFIG=\"$(make_splunk_auth_config)\"\n"
        "trap 'rm -f \"${SPLUNK_AUTH_CONFIG}\"' EXIT\n"
        "AUTH=(\"-K\" \"${SPLUNK_AUTH_CONFIG}\")\n"
        "BASE_URL=\"${SPLUNK_SEARCH_API_URI}/servicesNS/nobody/discover_splunk_observability_cloud\"\n\n"
        "# Tab 1: Related Content discovery toggle.\n"
        f"curl -k \"${{AUTH[@]}}\" -X POST \"${{BASE_URL}}/related_content_discovery\" -d enabled={'1' if discover['related_content_discovery'] else '0'}\n\n"
        "# Tab 3: Field aliasing + Auto Field Mapping toggle.\n"
        f"curl -k \"${{AUTH[@]}}\" -X POST \"${{BASE_URL}}/field_aliasing\" -d auto_field_mapping={'1' if discover['field_aliasing']['auto_field_mapping'] else '0'}\n\n"
        "# Tab 4: Automatic UI updates toggle.\n"
        f"curl -k \"${{AUTH[@]}}\" -X POST \"${{BASE_URL}}/automatic_ui_updates\" -d enabled={'1' if discover['automatic_ui_updates'] else '0'}\n\n"
        "# Tab 5: Access tokens (realm + token from chmod-600 file).\n"
        f"curl -k \"${{AUTH[@]}}\" -X POST \"${{BASE_URL}}/access_tokens\" -d realm={realm} --data-urlencode \"access_token@${{{discover['access_tokens_realm_token_file_ref']}}}\"\n\n"
        "# Read permission grant on the Discover app.\n"
        f"curl -k \"${{AUTH[@]}}\" -X POST \"${{SPLUNK_SEARCH_API_URI}}/servicesNS/nobody/system/apps/local/discover_splunk_observability_cloud/permissions\" \\\n"
        f"  -d 'sharing=app' -d 'perms.read={','.join(discover['read_permission_roles'])}'\n"
    )
    return body


def apply_script_loc(spec: dict[str, Any]) -> str:
    loc = spec["log_observer_connect"]
    if not loc.get("enable"):
        return SHEBANG + "# log_observer_connect.enable=false; nothing to apply.\n"
    role = loc["role"]
    sa = loc["service_account"]
    runtime = loc["workload_rule_runtime_seconds"]
    role_search_jobs_quota = role["standard_search_limit_per_user"] * role["expected_concurrent_users"]
    body = SHEBANG + (
        "# Step: Log Observer Connect service-account user + role + workload rule.\n"
        ": \"${SPLUNK_SEARCH_API_URI:?SPLUNK_SEARCH_API_URI must be set}\"\n"
        ": \"${SPLUNK_USER:?SPLUNK_USER must be set}\"\n"
        ": \"${SPLUNK_PASS:?SPLUNK_PASS must be set}\"\n"
        ": \"${LOC_SERVICE_ACCOUNT_PASSWORD_FILE:?--service-account-password-file must be set (chmod 600)}\"\n\n"
        f"{SPLUNK_CURL_AUTH_HELPER}"
        "SPLUNK_AUTH_CONFIG=\"$(make_splunk_auth_config)\"\n"
        "trap 'rm -f \"${SPLUNK_AUTH_CONFIG}\"' EXIT\n"
        "AUTH=(\"-K\" \"${SPLUNK_AUTH_CONFIG}\")\n\n"
        "# Role.\n"
        f"curl -k \"${{AUTH[@]}}\" -X POST \"${{SPLUNK_SEARCH_API_URI}}/services/authorization/roles\" \\\n"
        f"  -d name={role['name']} \\\n"
        f"  -d imported_roles={role['base_role']} \\\n"
        f"  -d capabilities=edit_tokens_own -d capabilities=search \\\n"
        f"  -d srchTimeWin={role['time_window_seconds']} \\\n"
        f"  -d srchTimeEarliest=-{role['earliest_event_seconds']}s \\\n"
        f"  -d srchDiskQuota={role['disk_space_mb']} \\\n"
        f"  -d srchJobsQuota={role_search_jobs_quota} \\\n"
        f"  -d rtSrchJobsQuota=0 \\\n"
        f"  {' '.join(f'-d srchIndexesAllowed={ix}' for ix in role['indexes'])}\n\n"
        "# User.\n"
        f"curl -k \"${{AUTH[@]}}\" -X POST \"${{SPLUNK_SEARCH_API_URI}}/services/authentication/users\" \\\n"
        f"  -d name={sa['username']} \\\n"
        f"  -d roles={role['name']} \\\n"
        f"  --data-urlencode \"password@${{LOC_SERVICE_ACCOUNT_PASSWORD_FILE}}\"\n\n"
        "# Workload rule.\n"
        f"curl -k \"${{AUTH[@]}}\" -X POST \"${{SPLUNK_SEARCH_API_URI}}/services/workloads/rules\" \\\n"
        f"  -d name=loc_runtime_abort \\\n"
        f"  -d predicate=\"user={sa['username']} AND runtime>{runtime}s\" \\\n"
        f"  -d action=abort -d schedule=alwayson\n"
    )
    return body


def apply_script_sim_addon(spec: dict[str, Any]) -> str:
    sim = spec["sim_addon"]
    if not sim.get("install"):
        return SHEBANG + "# sim_addon.install=false; nothing to apply.\n"
    realm = spec["realm"]
    body = SHEBANG + (
        "# Step: Splunk Infrastructure Monitoring Add-on account + modular inputs.\n"
        ": \"${SPLUNK_SEARCH_API_URI:?SPLUNK_SEARCH_API_URI must be set}\"\n"
        ": \"${SPLUNK_USER:?SPLUNK_USER must be set}\"\n"
        ": \"${SPLUNK_PASS:?SPLUNK_PASS must be set}\"\n"
        f": \"${{{sim['org_token_file_ref']}:?--org-token-file must be set (chmod 600)}}\"\n\n"
        f"{SPLUNK_CURL_AUTH_HELPER}"
        "SPLUNK_AUTH_CONFIG=\"$(make_splunk_auth_config)\"\n"
        "trap 'rm -f \"${SPLUNK_AUTH_CONFIG}\"' EXIT\n"
        "AUTH=(\"-K\" \"${SPLUNK_AUTH_CONFIG}\")\n"
        "TA_BASE=\"${SPLUNK_SEARCH_API_URI}/servicesNS/nobody/Splunk_TA_sim\"\n\n"
        "# Index.\n"
        f"curl -k \"${{AUTH[@]}}\" -X POST \"${{SPLUNK_SEARCH_API_URI}}/services/data/indexes\" \\\n"
        f"  -d name={sim['index_name']} -d datatype=metric || true\n\n"
        "# Account.\n"
        f"curl -k \"${{AUTH[@]}}\" -X POST \"${{TA_BASE}}/splunk_infrastructure_monitoring_account\" \\\n"
        f"  -d name={sim['account_name']} \\\n"
        f"  -d realm={realm} \\\n"
        f"  --data-urlencode \"access_token@${{{sim['org_token_file_ref']}}}\" \\\n"
        f"  -d job_start_rate=60 \\\n"
        f"  -d event_search_rate=30\n"
        "\n"
    )
    for name in sim["modular_inputs"]:
        catalog = SIGNALFLOW_CATALOG[name]
        runnable = name  # already SAMPLE_-stripped
        body += (
            f"# Modular input: {runnable} ({catalog['description']})\n"
            f"curl -k \"${{AUTH[@]}}\" -X POST \"${{SPLUNK_SEARCH_API_URI}}/servicesNS/nobody/Splunk_TA_sim/data/inputs/splunk_infrastructure_monitoring_data_streams\" \\\n"
            f"  -d name={runnable} \\\n"
            f"  -d index={sim['index_name']} \\\n"
            f"  -d account={sim['account_name']} \\\n"
            f"  -d interval=300 \\\n"
            f"  -d disabled={'0' if sim.get('data_collection_enabled') else '1'} \\\n"
            f"  --data-urlencode signalflow_program={shlex.quote(catalog['program'])}\n\n"
        )
    return body


def handoff_script_app_install() -> str:
    return SHEBANG + (
        "# Splunk_TA_sim install handoff to splunk-app-install.\n"
        "exec bash skills/splunk-app-install/scripts/install_app.sh \\\n"
        "  --source splunkbase --app-id 5247 --no-update \"$@\"\n"
    )


def handoff_script_acs_loc(spec: dict[str, Any]) -> str:
    realm = spec["realm"]
    ips = LOC_REALM_IPS.get(realm, [])
    return SHEBANG + (
        "# Log Observer Connect realm-IP allowlist handoff to splunk-cloud-acs-allowlist-setup.\n"
        "exec bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh \\\n"
        "  --phase render --features search-api \\\n"
        f"  --search-api-subnets {','.join(ips) or '<no-realm-ips>'} \"$@\"\n"
    )


def handoff_script_acs_hec() -> str:
    return SHEBANG + (
        "# Splunk Cloud Victoria-stack HEC allowlist handoff to splunk-cloud-acs-allowlist-setup.\n"
        "exec bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh \\\n"
        "  --phase render --features hec \"$@\"\n"
    )


def handoff_script_itsi() -> str:
    return SHEBANG + (
        "# Content Pack for Splunk Observability Cloud handoff to splunk-itsi-config.\n"
        "exec bash skills/splunk-itsi-config/scripts/setup.sh \\\n"
        "  --content-pack splunk_observability_cloud \"$@\"\n"
    )


# ---------------------------------------------------------------------------
# Support-ticket templates.
# ---------------------------------------------------------------------------


def support_ticket_cross_region(spec: dict[str, Any]) -> str:
    realm = spec["realm"]
    region = REALM_REGION_MAP.get(realm, "(unknown)")
    return (
        "# Splunk Support Ticket: Cross-Region Pairing\n\n"
        f"Subject: Cross-region Splunk Cloud Platform <-> Splunk Observability Cloud pairing approval (realm `{realm}`)\n\n"
        "Hello Splunk Support,\n\n"
        f"Our Splunk Cloud Platform stack `{spec.get('splunk_cloud_stack', '<stack>')}` does not pair in-region with our preferred Splunk Observability Cloud realm `{realm}` "
        f"(in-region region per the Splunk docs is `{region}`). We would like Splunk Account team approval to enable the cross-region pairing.\n\n"
        "Stack: <fill in>\n"
        f"Splunk Observability Cloud realm: {realm}\n"
        "Use case justification: <fill in>\n\n"
        "Thank you.\n"
    )


def support_ticket_fedramp() -> str:
    return (
        "# Splunk Support Ticket: FedRAMP / IL5 readiness for Splunk Observability Cloud Unified Identity\n\n"
        "Subject: FedRAMP / IL5 readiness for Splunk Observability Cloud Unified Identity\n\n"
        "Hello Splunk Support,\n\n"
        "We operate a FedRAMP / IL5 Splunk Cloud Platform stack and would like guidance on Unified Identity availability for Splunk Observability Cloud "
        "(Splunk Cloud Platform itself is FedRAMP Moderate / DoD IL5 provisionally authorized, but Splunk Observability Cloud is not separately listed in the public FedRAMP / IL5 documentation as of this skill's authoring).\n\n"
        "Stack: <fill in>\n"
        "Compliance posture: FedRAMP <Moderate / High> / DoD IL5\n"
        "Use case: <fill in>\n\n"
        "Thank you.\n"
    )


def support_ticket_deactivate_local_login() -> str:
    return (
        "# Splunk Support Ticket: Deactivate local login on Splunk Observability Cloud (UID-only enforcement)\n\n"
        "Subject: Deactivate Splunk Observability Cloud local login for org <org-id>\n\n"
        "Hello Splunk Support,\n\n"
        "We have completed Unified Identity setup between our Splunk Cloud Platform stack and our Splunk Observability Cloud organization. "
        "We would like to deactivate non-UID local login so that all users authenticate exclusively through Splunk Cloud Platform SSO.\n\n"
        "Splunk Observability Cloud org: <org-id>\n"
        "Splunk Cloud Platform stack: <fill in>\n"
        "UID pairing-id: <fill in>\n\n"
        "Thank you.\n"
    )


def support_ticket_loc_fedramp() -> str:
    return (
        "# Splunk Support Ticket: Log Observer Connect IP allowlist on FedRAMP\n\n"
        "Subject: Log Observer Connect IP allowlist on FedRAMP stack\n\n"
        "Hello Splunk Support,\n\n"
        "Our FedRAMP Splunk Cloud Platform stack needs the Splunk Log Observer Connect realm IPs added to the `search-api` allowlist. "
        "Per FedRAMP procedure, allowlist edits must go through Splunk Support.\n\n"
        "Stack: <fill in>\n"
        "Splunk Observability Cloud realm: <realm>\n"
        "Realm IPs: <paste from references/log-observer-connect.md>\n\n"
        "Thank you.\n"
    )


def support_ticket_int_user() -> str:
    return (
        "# Explainer: int_* users in your Splunk Observability Cloud organization\n\n"
        "When a member of Splunk Support is added to your Splunk Observability Cloud organization to "
        "troubleshoot an issue, they appear under a username prefixed with `int_`. This is normal and "
        "is a feature of Unified Identity, not a bug. The `int_` users typically share a single IP "
        "address because Splunk Support staff are on a VPN.\n\n"
        "If an `int_*` user appears in your org WITHOUT an active Splunk Support case, contact Splunk "
        "Support immediately.\n"
    )


# ---------------------------------------------------------------------------
# Top-level renderer.
# ---------------------------------------------------------------------------


SECRET_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{12,}"),
    re.compile(r"(?i)password\s*=\s*[^&\s]{4,}"),
    re.compile(r"eyJ[A-Za-z0-9._-]{20,}"),
    re.compile(r"(?i)x-vo-api-key:\s*[A-Za-z0-9-]{8,}"),
]


def assert_no_secrets_in_text(label: str, text: str) -> None:
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            raise RenderError(f"refusing to write secret-looking content into {label}")


def write_text(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | 0o755)


def render(
    spec: dict[str, Any],
    output_dir: Path,
    discover_data: dict[str, Any] | None = None,
    doctor_data: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if output_dir.exists():
        # Remove only generated subdirs to avoid clobbering user files.
        for sub in ("payloads", "scripts", "state", "support-tickets", "sim-addon"):
            shutil.rmtree(output_dir / sub, ignore_errors=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    coverage = coverage_for(spec)
    mts_md, mts_rows, mts_failures = mts_sizing_report(spec)
    if mts_failures:
        raise RenderError("\n".join(mts_failures))

    # README + architecture diagram.
    readme = (
        "# Splunk Platform <-> Splunk Observability Cloud Integration (rendered)\n\n"
        f"- Target: `{spec['target']}`\n"
        f"- Realm: `{spec['realm']}`\n"
        f"- Generated: `{datetime.now(timezone.utc).isoformat()}`\n\n"
        "## Recommended next operator commands\n\n"
        "1. Review `00-prerequisites.md` ... `09-handoff.md` in order.\n"
        "2. Run `--doctor` to confirm readiness.\n"
        "3. `--apply token_auth` if token authentication is off.\n"
        "4. `--apply pairing` (the rest of the sections depend on a healthy pair).\n"
        "5. `--apply related_content,discover_app,log_observer_connect,sim_addon`.\n"
        "6. `--apply rbac --i-accept-rbac-cutover` ONLY when ready for the destructive cutover.\n"
        "7. Hand the cross-skill scripts under `scripts/` to the relevant teams.\n"
    )
    write_text(output_dir / "README.md", readme)

    architecture = (
        "flowchart LR\n"
        "  Splunk[Splunk Cloud Platform] -->|Discover app| O11y[Splunk Observability Cloud]\n"
        "  Splunk -->|Related Content| O11y\n"
        "  Splunk -->|Log Observer Connect| O11y\n"
        "  Splunk -->|sim SPL| O11y\n"
        "  O11y -->|UID SSO| Splunk\n"
    )
    write_text(output_dir / "architecture.mmd", architecture)

    for filename, key in NUMBERED_PLAN_FILES:
        emitter = {
            "prerequisites": section_prerequisites,
            "token_auth": section_token_auth,
            "pairing": section_pairing,
            "centralized_rbac": section_rbac,
            "discover_app": section_discover_app,
            "related_content_capabilities": section_related_content,
            "log_observer_connect": section_loc,
            "dashboard_studio_o11y": section_dashboard_studio,
            "sim_addon": section_sim_addon,
            "handoff": section_handoff,
        }[key]
        text = emitter(spec)
        assert_no_secrets_in_text(filename, text)
        write_text(output_dir / filename, text)

    write_text(
        output_dir / "coverage-report.json",
        json.dumps(
            {
                "api_version": spec.get("api_version"),
                "target": spec["target"],
                "realm": spec["realm"],
                "coverage": coverage,
            },
            indent=2,
        ),
    )

    apply_plan = {
        "api_version": spec.get("api_version"),
        "target": spec["target"],
        "realm": spec["realm"],
        "steps": [
            {
                "section": section,
                "idempotency_key": f"{section}:{spec['realm']}:{spec.get('splunk_cloud_stack', spec['target'])}",
                "coverage": {k: v for k, v in coverage.items() if k.startswith(section.split(".")[0])},
            }
            for section in [
                "token_auth",
                "pairing",
                "centralized_rbac",
                "related_content_capabilities",
                "discover_app",
                "log_observer_connect",
                "dashboard_studio_o11y",
                "sim_addon",
            ]
        ],
    }
    write_text(output_dir / "apply-plan.json", json.dumps(apply_plan, indent=2))

    # Per-step apply scripts.
    write_text(output_dir / "scripts/apply-token-auth.sh", apply_script_token_auth(), executable=True)
    write_text(output_dir / "scripts/apply-pairing.sh", apply_script_pairing(spec), executable=True)
    write_text(output_dir / "scripts/apply-rbac.sh", apply_script_rbac(spec), executable=True)
    write_text(output_dir / "scripts/apply-discover-app.sh", apply_script_discover_app(spec), executable=True)
    write_text(output_dir / "scripts/apply-loc.sh", apply_script_loc(spec), executable=True)
    write_text(output_dir / "scripts/apply-sim-addon.sh", apply_script_sim_addon(spec), executable=True)

    # Cross-skill handoff drivers.
    write_text(output_dir / "scripts/apply-app-install.sh", handoff_script_app_install(), executable=True)
    write_text(output_dir / "scripts/apply-acs-allowlist-loc.sh", handoff_script_acs_loc(spec), executable=True)
    write_text(output_dir / "scripts/apply-acs-allowlist-hec.sh", handoff_script_acs_hec(), executable=True)
    write_text(output_dir / "scripts/apply-itsi-content-pack.sh", handoff_script_itsi(), executable=True)

    # Payloads (sanitized to references only).
    payloads = {
        "pairing": {
            "method": "POST",
            "url": "https://admin.splunk.com/{stack}/adminconfig/v2/observability/sso-pairing",
            "headers": {
                "Authorization": "Bearer ${SPLUNK_CLOUD_ADMIN_JWT}",
                "o11y-access-token": "${SPLUNK_O11Y_ADMIN_TOKEN}",
                "Content-Type": "application/json",
            },
        },
        "pairing_status": {
            "method": "GET",
            "url": "https://admin.splunk.com/{stack}/adminconfig/v2/observability/sso-pairing/{pairing-id}",
        },
        "discover_app": {
            "tabs": [
                "/servicesNS/nobody/discover_splunk_observability_cloud/related_content_discovery",
                "/servicesNS/nobody/discover_splunk_observability_cloud/field_aliasing",
                "/servicesNS/nobody/discover_splunk_observability_cloud/automatic_ui_updates",
                "/servicesNS/nobody/discover_splunk_observability_cloud/access_tokens",
            ],
        },
        "sim_addon_account": {
            "method": "POST",
            "url": "/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account",
            "fields": ["name", "realm", "access_token (from --org-token-file)", "job_start_rate", "event_search_rate"],
        },
    }
    write_text(output_dir / "payloads/api-payload-shapes.json", json.dumps(payloads, indent=2))

    # State scaffolding (apply-state.json + idempotency keys).
    state_dir = output_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    write_text(state_dir / "apply-state.json", "{\"steps\": []}\n")
    os.chmod(state_dir / "apply-state.json", 0o600)
    write_text(state_dir / "idempotency-keys.json", json.dumps([s["idempotency_key"] for s in apply_plan["steps"]], indent=2))

    # Support-ticket templates (rendered when relevant gates fire).
    realm = spec["realm"]
    region = REALM_REGION_MAP.get(realm)
    fed_or_excluded = realm not in UID_SUPPORTED_REALMS
    tickets_dir = output_dir / "support-tickets"
    tickets_dir.mkdir(parents=True, exist_ok=True)
    if region is None or fed_or_excluded or spec["target"] == "enterprise":
        # Always render the FedRAMP template for honesty when UID is not in the supported realm matrix.
        write_text(tickets_dir / "fedramp-il5-readiness.md", support_ticket_fedramp())
        write_text(tickets_dir / "loc-ip-allowlist-on-fedramp.md", support_ticket_loc_fedramp())
    write_text(tickets_dir / "cross-region-pairing.md", support_ticket_cross_region(spec))
    write_text(tickets_dir / "deactivate-local-login.md", support_ticket_deactivate_local_login())
    write_text(tickets_dir / "int-user-explanation.md", support_ticket_int_user())

    # SIM Add-on artifacts.
    sim_dir = output_dir / "sim-addon"
    sim_dir.mkdir(parents=True, exist_ok=True)
    write_text(sim_dir / "mts-sizing.md", mts_md)
    catalog_dir = sim_dir / "signalflow-catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    for name, data in SIGNALFLOW_CATALOG.items():
        write_text(
            catalog_dir / f"{name}.signalflow",
            f"# {name}: {data['description']}\n# MTS-per-entity estimate: {data['mts_per_entity']}\n\n{data['program']}\n",
        )

    # Discover snapshot / doctor report when supplied by the bash wrapper.
    if discover_data is not None:
        write_text(output_dir / "current-state.json", json.dumps(discover_data, indent=2))
    if doctor_data is not None:
        rows = ["# Doctor Report", "", "| # | Severity | Check | Fix |", "|---|----------|-------|-----|"]
        for idx, row in enumerate(doctor_data, start=1):
            rows.append(
                f"| {idx} | {row.get('severity', 'INFO')} | {row.get('check', '')} | "
                f"{row.get('fix', '')} |"
            )
        write_text(output_dir / "doctor-report.md", "\n".join(rows) + "\n")

    return {
        "coverage": coverage,
        "apply_plan": apply_plan,
        "mts": mts_rows,
    }


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="Path to YAML or JSON spec file.")
    parser.add_argument("--output-dir", required=True, help="Where to write the rendered tree.")
    parser.add_argument("--target", choices=("cloud", "enterprise"), default=None)
    parser.add_argument("--realm", default=None)
    parser.add_argument("--list-sim-templates", action="store_true")
    parser.add_argument("--render-sim-templates", default=None,
                        help="Comma-separated subset of the SIM SignalFlow catalog to render.")
    parser.add_argument("--make-default-deeplink", action="store_true")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--discover-input", default=None,
                        help="Path to a current-state.json blob to embed when --discover ran upstream.")
    parser.add_argument("--doctor-input", default=None,
                        help="Path to a doctor catalog JSON to embed when --doctor ran upstream.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.list_sim_templates:
        for name, data in SIGNALFLOW_CATALOG.items():
            print(f"{name}\t{data['mts_per_entity']} MTS/entity\t{data['description']}")
        return 0

    if args.make_default_deeplink:
        realm = args.realm or "us0"
        host = "app.signalfx.com" if realm == "us2-gcp" else f"app.{realm}.signalfx.com"
        print(f"Make Default UI: https://{host}/#/myprofile/orgs (admin opens 3-dot menu next to {realm})")
        return 0

    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"spec not found: {spec_path}", file=__import__("sys").stderr)
        return 2
    raw_spec = load_spec(spec_path)
    spec = validate_spec(raw_spec, target_override=args.target)
    if args.realm:
        spec["realm"] = args.realm
        spec = validate_spec(spec)
    if args.render_sim_templates:
        chosen = [t.strip() for t in args.render_sim_templates.split(",") if t.strip()]
        spec["sim_addon"]["modular_inputs"] = chosen
        spec = validate_spec(spec)

    discover_data = None
    if args.discover_input:
        discover_data = json.loads(Path(args.discover_input).read_text(encoding="utf-8"))
    doctor_data = None
    if args.doctor_input:
        doctor_data = json.loads(Path(args.doctor_input).read_text(encoding="utf-8"))

    output_dir = Path(args.output_dir)

    if args.explain:
        print("Plan summary:")
        coverage = coverage_for(spec)
        for key, info in coverage.items():
            print(f"  {key}\t{info['status']}\t{info['notes']}")
        return 0

    try:
        result = render(spec, output_dir, discover_data=discover_data, doctor_data=doctor_data)
    except RenderError as exc:
        print(f"render FAILED: {exc}", file=__import__("sys").stderr)
        return 3

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Rendered into {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

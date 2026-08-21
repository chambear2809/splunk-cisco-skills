#!/usr/bin/env python3
"""Render Cisco Cloud Control setup and handoff assets.

The renderer is intentionally offline. It never reads token files and never
places secret values in rendered metadata, coverage reports, Markdown, or argv.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any


SKILL_NAME = "cisco-cloud-control-setup"
REPO_ROOT = Path(__file__).resolve().parents[3]
SECTIONS = [
    "data-fabric",
    "mcp",
    "agent-observability",
    "observability-content",
    "domain-readiness",
    "cloud-control-studio",
    "ai-canvas",
]
ALLOWED_STATUSES = {
    "delegated_apply",
    "delegated_render",
    "render",
    "ui_handoff",
    "ca_handoff",
    "validate",
    "not_applicable",
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
    r"(^|_)(access_token|api_key|api_token|bearer_token|client_secret|password|private_key|secret|token)($|_)"
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
)
SOURCE_URLS = {
    "getting_started": "https://cloud.cisco.com/docs/en/cisco-cloud-control-getting-started/cisco-cloud-control-getting-started.html",
    "release_notes": "https://cloud.cisco.com/docs/en/cisco-cloud-control-rn-open-bugs/cisco-cloud-control-release-notes.html",
    "ai_canvas_doc": "https://cloud.cisco.com/docs/en/cisco-cloud-control-canvas/cisco-cloud-control-canvas.html",
    "inventory": "https://cloud.cisco.com/docs/en/cisco-cloud-control-inventory/cisco-cloud-control-inventory.html",
    "licensing": "https://cloud.cisco.com/docs/en/cisco-cloud-control-licensing/cisco-cloud-control-licensing.html",
    "rbac": "https://cloud.cisco.com/docs/en/cisco-cloud-control-rbac/cisco-cloud-control-rbac.html",
    "topology": "https://cloud.cisco.com/docs/en/cisco-cloud-control-topology/cisco-cloud-control-topology.html",
    "workflows": "https://cloud.cisco.com/docs/en/cisco-cloud-control-workflows/cisco-cloud-control-workflows.html",
    "multicloud_fabric": "https://cloud.cisco.com/docs/en/cisco-multicloud-fabric/cisco-multicloud-fabric.html",
    "workflows_api": "https://documentation.meraki.com/Platform_Management/Workflows/Workflows/Using_the_Workflows_API",
    "workflow_account_keys": "https://documentation.meraki.com/Platform_Management/Workflows/Targets/Targets_Account_Keys",
    "platform": "https://www.cisco.com/site/us/en/solutions/artificial-intelligence/agentic-ops/cisco-cloud-control/index.html",
    "studio": "https://www.cisco.com/site/us/en/solutions/artificial-intelligence/agentic-ops/cloud-control-studio/index.html",
    "press": "https://newsroom.cisco.com/c/r/newsroom/en/us/a/y2026/m06/cisco-unveils-agentic-platform-for-operating-and-defending-critical-it-infrastructure.html",
    "agent_builder": "https://blogs.cisco.com/ai/announcing-cisco-cloud-control-agent-builder",
    "app_builder": "https://blogs.cisco.com/ai/from-an-idea-to-a-live-app-on-cisco-in-minutes",
    "ai_defense": "https://blogs.cisco.com/ai/ai-agents-need-built-in-security-here-is-how-cisco-does-it",
    "splunk": "https://www.splunk.com/en_us/blog/leadership/splunk-cisco-live-agentic-operations.html",
    "splunk_platform_innovations": "https://www.splunk.com/en_us/blog/platform/new-splunk-platform-innovations-cisco-live-2026.html",
    "cisco_data_fabric_press": "https://newsroom.cisco.com/c/r/newsroom/en/us/a/y2025/m09/cisco-data-fabric-transforms-machine-data-into-ai-ready-intelligence.html",
    "splunk_data_management": "https://www.splunk.com/en_us/blog/platform/the-complete-guide-to-splunk-data-management.html",
    "federated_options": "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/welcome-to-splunk-federated-search/overview-of-the-federated-search-options-for-the-splunk-platform",
    "ai_toolkit": "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/release-notes/whats-new-in-the-ai-toolkit",
    "ai_toolkit_dependencies": "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/install-and-upgrade-the-ai-toolkit/splunk-ai-toolkit-version-dependencies",
    "agent_launchpad": "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-connections-containers-and-agents/ai-toolkit-agent-launchpad",
    "cdtsm": "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-models/cisco-deep-time-series-model",
    "splunk_ai_canvas": "https://lantern.splunk.com/Splunk_and_Cisco_Use_Cases/Connecting_the_Splunk_platform_to_Cisco_Cloud_Control_and_AI_Canvas/Integrating_Splunk_Cloud_Platform_with_AI_Canvas",
}
DATA_FABRIC_2026_SURFACES = [
    {
        "key": "machine_data_lake_alpha",
        "title": "Machine Data Lake alpha",
        "status": "ui_handoff",
        "owner": "Splunk Cloud Platform / Cisco Data Fabric product workflow",
        "source": "splunk_platform_innovations",
        "summary": "Render readiness for alpha Machine Data Lake storage, promotion, governance, and AI-training use cases; no direct provisioning is emitted.",
    },
    {
        "key": "built_in_data_catalog",
        "title": "Built-in Data Catalog",
        "status": "ui_handoff",
        "owner": "Splunk Data Management",
        "source": "splunk_platform_innovations",
        "summary": "Render discovery, ownership, schema/context, and governance checklist for cataloged machine data.",
    },
    {
        "key": "ai_powered_data_management",
        "title": "AI-powered data management",
        "status": "delegated_render",
        "owner": "cisco-data-fabric-setup",
        "source": "splunk_platform_innovations",
        "summary": "Delegate lifecycle-aware onboarding, Automated Field Extraction CA, Guided Onboarding/Auto-Schematization alpha, SPL2, routing, redaction, monitoring, and tiering coverage to the dedicated Data Fabric parent.",
    },
    {
        "key": "expanded_federated_search",
        "title": "Expanded federated search",
        "status": "delegated_render",
        "owner": "cisco-data-fabric-setup",
        "source": "federated_options",
        "summary": "Delegate Splunk, Amazon S3, Microsoft Azure, Azure Databricks, Snowflake, DDSS, Amazon Security Lake, catalog, RBAC, DSU, and legacy-migration coverage to cisco-data-fabric-setup.",
    },
    {
        "key": "machine_data_ai_activation",
        "title": "Machine-data AI activation",
        "status": "delegated_render",
        "owner": "cisco-data-fabric-setup",
        "source": "ai_toolkit",
        "summary": "Delegate AI Toolkit, open CTSM, GA hosted CDTSM, Splunk AI Toolkit Agent Launchpad, the separate Cloud Control Studio Agent Builder, DSDL, MCP, and agent-governance coverage to cisco-data-fabric-setup.",
    },
]
PRODUCT_INTEGRATION_MATRIX = [
    ("Catalyst SD-WAN Manager", "Yes", "Yes", "Yes"),
    ("Collaboration Control Hub", "Yes", "No", "No"),
    ("Intersight", "Yes", "Yes", "Yes"),
    ("Meraki", "Yes", "Yes", "Yes"),
    ("Nexus Dashboard", "Yes", "Yes", "Yes"),
    ("Nexus Hyperfabric", "Yes", "Yes", "Yes"),
    ("Secure Access", "Yes", "No", "No"),
    ("Secure Firewall", "Yes", "Yes", "Yes"),
    ("ThousandEyes", "Yes", "No", "Yes"),
]
PRODUCT_ADJACENT_HANDOFFS = [
    ("Catalyst Center", "onboarding_handoff", "Appears in onboarding preparation, but not as a direct row in the current inventory/topology/notifications support matrix."),
    ("Security Cloud Control", "product_family_handoff", "Use the current Secure Firewall and Secure Access rows rather than treating the umbrella name as a supported matrix row."),
    ("Splunk Cloud", "controlled_availability_integration", "Separate Cloud Control/AI Canvas integration; during CA verify Splunk Cloud 10.5.2605.3, US commercial AWS, tenant approval, identity/domain, terms, AI Assistant, MCP Server, and mcp_tool_execute."),
    ("Cisco IQ", "not_in_current_matrix", "No direct row in the current inventory/topology/notifications support matrix; keep as a separately verified roadmap or handoff surface."),
]
OFFICIAL_FEATURES = [
    (
        "cloud_control_onboarding",
        "platform",
        "render",
        "cisco-cloud-control-setup",
        "getting_started",
        "Render admin onboarding, tenant linking, product association, and tenant-group checklist.",
    ),
    (
        "product_integration_timeline",
        "products",
        "render",
        "cisco-cloud-control-setup",
        "getting_started",
        "Render the current inventory, topology, and notifications product matrix plus separately classified onboarding/integration handoffs.",
    ),
    (
        "ai_context_readiness",
        "ai-canvas",
        "ca_handoff",
        "Cisco AI Canvas",
        "getting_started",
        "Render Meraki and ThousandEyes AI context prerequisites; operator enters values in Cloud Control.",
    ),
    (
        "admin_integrations_meraki",
        "integrations",
        "ui_handoff",
        "Cisco Cloud Control Admin Console",
        "getting_started",
        "Render Admin Console integration handoff; Meraki API key values are never accepted by this parent.",
    ),
    (
        "admin_integrations_thousandeyes",
        "integrations",
        "ui_handoff",
        "Cisco Cloud Control Admin Console",
        "getting_started",
        "Render ThousandEyes sign-in and integration handoff; child ThousandEyes Splunk/MCP skills remain separate.",
    ),
    (
        "admin_integrations_collaboration_control_hub",
        "integrations",
        "ui_handoff",
        "Collaboration Control Hub",
        "getting_started",
        "Render Collaboration Control Hub activation handoff and Webex inventory linkage notes.",
    ),
    (
        "users_roles_tenants",
        "identity",
        "ui_handoff",
        "Cisco Cloud Control Admin Console",
        "getting_started",
        "Render user, role, tenant-group, tenant-switcher, and Nexus Dashboard access handoffs.",
    ),
    (
        "sso_identity_provider",
        "identity",
        "ui_handoff",
        "Cisco Cloud Control Admin Console",
        "getting_started",
        "Render domain, SAML, OIDC, routing-rule, and service-provider certificate checklist.",
    ),
    (
        "audit_logs",
        "governance",
        "ui_handoff",
        "Cisco Cloud Control Admin Console",
        "getting_started",
        "Render audit-log review and evidence-export handoff.",
    ),
    (
        "ai_assistant",
        "ai-canvas",
        "ca_handoff",
        "Cisco Cloud Control Assistant",
        "ai_canvas_doc",
        "Render prompt and workflow handoffs for short focused assistant tasks.",
    ),
    (
        "ai_canvas_official",
        "ai-canvas",
        "ca_handoff",
        "Cisco AI Canvas",
        "ai_canvas_doc",
        "Render board, prompt-library, collaboration, knowledge, and multimodal input handoffs.",
    ),
    (
        "splunk_ai_canvas_prerequisites",
        "ai-canvas",
        "ca_handoff",
        "Cisco AI Canvas and Splunk Cloud",
        "splunk_ai_canvas",
        "Require Cloud Control enablement, Splunk Cloud 10.5.2605.3, current AI Assistant and MCP Server, admin onboarding, and mcp_tool_execute for every user.",
    ),
    (
        "splunk_ai_canvas_limits",
        "ai-canvas",
        "validate",
        "Cisco AI Canvas and Splunk Cloud",
        "splunk_ai_canvas",
        "Validate the 100-row-per-card results cap, visualization compatibility, and forbidden SPL commands that fail on refresh or run.",
    ),
    (
        "actions_notifications_favorites",
        "operations",
        "ui_handoff",
        "Cisco Cloud Control",
        "getting_started",
        "Render Actions, Notifications, Favorites, and support/help menu operating checklist.",
    ),
    (
        "inventory_global_assets",
        "inventory",
        "render",
        "cisco-cloud-control-setup",
        "inventory",
        "Render global inventory, AI search, supported-products, and export-limit readiness notes.",
    ),
    (
        "licensing_visibility",
        "licensing",
        "render",
        "cisco-cloud-control-setup",
        "licensing",
        "Render supported license products, licensing models, and reporting readiness notes.",
    ),
    (
        "rbac",
        "identity",
        "render",
        "cisco-cloud-control-setup",
        "rbac",
        "Render RBAC role and permission boundary checklist.",
    ),
    (
        "topology",
        "topology",
        "render",
        "cisco-cloud-control-setup",
        "topology",
        "Render topology, scopes, health indicators, and cross-domain navigation readiness.",
    ),
    (
        "workflows_and_atomics",
        "workflows",
        "ui_handoff",
        "Cisco Cloud Control Workflows",
        "workflows",
        "Render workflow, atomic, Exchange, run monitoring, approval, target, variable, and automation-rule handoffs.",
    ),
    (
        "workflows_api",
        "api",
        "render",
        "Cisco Workflows API",
        "workflows_api",
        "Render OAS, base URL, bearer-auth, rate-limit, and REST readiness; no API calls are made by this parent.",
    ),
    (
        "workflow_targets_account_keys",
        "api",
        "ui_handoff",
        "Cisco Cloud Control Workflows",
        "workflow_account_keys",
        "Render target and account-key setup handoff; secret material remains in Cisco or child secret-file stores.",
    ),
    (
        "multicloud_fabric_beta",
        "multicloud",
        "ui_handoff",
        "Cisco Multicloud Fabric",
        "multicloud_fabric",
        "Render beta handoff for AWS, Azure, GCP, and hybrid fabric onboarding.",
    ),
    (
        "release_notes_open_issues",
        "validation",
        "validate",
        "cisco-cloud-control-setup",
        "release_notes",
        "Track release-note issues as operator review items before production use.",
    ),
]
DOMAIN_HANDOFFS = {
    "intersight": ("cisco-intersight-setup", "Cisco Intersight inventory, UCS, alarms, and metrics readiness."),
    "nexus": ("cisco-dc-networking-setup", "Cisco Nexus Dashboard, ACI, Nexus 9K, and fabric telemetry readiness."),
    "nexus-hyperfabric": ("cisco-product-setup", "Nexus Hyperfabric Cloud Control inventory, topology, and AI Canvas readiness handoff."),
    "thousandeyes": ("cisco-thousandeyes-setup", "ThousandEyes metrics, HEC, dashboards, and MCP readiness."),
    "meraki": ("cisco-meraki-ta-setup", "Meraki organization, polling inputs, and dashboard readiness."),
    "catalyst": ("cisco-catalyst-ta-setup", "Catalyst Center, SD-WAN, Cyber Vision, and Enterprise Networking dashboards."),
    "catalyst-sdwan": ("cisco-catalyst-ta-setup", "Catalyst SD-WAN Manager readiness through the Catalyst add-on stack."),
    "security-cloud-control": ("cisco-security-cloud-setup", "Cisco Security Cloud Control product-specific Cloud Control handoff."),
    "secure-access": ("cisco-secure-access-setup", "Secure Access org accounts, event add-on, and dashboard prerequisites."),
    "duo": ("cisco-security-cloud-setup", "Duo via Cisco Security Cloud product-specific input setup."),
    "ise": ("cisco-catalyst-ta-setup", "ISE account/input readiness through the Catalyst add-on stack."),
    "secure-firewall": ("cisco-security-cloud-setup", "Secure Firewall API, eStreamer, syslog, and ASA handoff routing."),
    "splunk-cloud": ("splunk-observability-cloud-integration-setup", "Splunk Cloud Platform visibility and Observability pairing readiness."),
    "collaboration-control-hub": ("cisco-webex-setup", "Collaboration Control Hub and Webex inventory/readiness handoff."),
    "cisco-iq": ("cisco-product-setup", "Cisco IQ timeline and roadmap handoff through the product router."),
}


def reject_direct_secret_flags(argv: list[str]) -> None:
    for arg in argv:
        flag = arg.split("=", 1)[0] if arg.startswith("--") else arg
        if flag in DIRECT_SECRET_FLAGS:
            print(
                f"ERROR: Direct secret flag {flag} is blocked. Use delegated child skill secret-file options.",
                file=sys.stderr,
            )
            raise SystemExit(2)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    reject_direct_secret_flags(raw_args)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--spec", default="")
    parser.add_argument("--execute", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(raw_args)


def parse_scalar(value: str) -> Any:
    cleaned = value.strip()
    if cleaned.startswith(("'", '"')) and cleaned.endswith(("'", '"')) and len(cleaned) >= 2:
        return cleaned[1:-1]
    lowered = cleaned.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    return cleaned


def next_content_line(lines: list[str], start: int) -> str:
    for line in lines[start:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return line
    return ""


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by template.example.

    This fallback supports nested mappings plus lists of scalars or mappings.
    CI normally has PyYAML, but local smoke tests should not fail just because
    the developer has not installed optional dependencies yet.
    """

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
            raise SystemExit("ERROR: Could not parse YAML spec indentation.")
        current = stack[-1][1]

        if stripped.startswith("- "):
            if not isinstance(current, list):
                raise SystemExit("ERROR: Could not parse YAML list item in spec.")
            item = stripped[2:].strip()
            if not item:
                child: dict[str, Any] = {}
                current.append(child)
                stack.append((indent, child))
                continue
            if ":" in item:
                key, raw_value = item.split(":", 1)
                child = {}
                value = raw_value.strip()
                if value:
                    child[key.strip()] = parse_scalar(value)
                else:
                    child[key.strip()] = {}
                current.append(child)
                stack.append((indent, child))
            else:
                current.append(parse_scalar(item))
            continue

        if ":" not in stripped or not isinstance(current, dict):
            raise SystemExit("ERROR: Could not parse YAML spec line.")
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value:
            current[key] = parse_scalar(value)
            continue

        following = next_content_line(lines, index + 1)
        following_indent = len(following) - len(following.lstrip(" ")) if following else indent
        child: Any = [] if following and following_indent > indent and following.strip().startswith("- ") else {}
        current[key] = child
        stack.append((indent, child))
    return root


def normalize_key(value: str) -> str:
    lowered = value.lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "_", lowered).strip("_")


def reject_secret_like_spec_keys(node: Any, path: str = "") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            normalized = normalize_key(str(key))
            sub_path = f"{path}.{key}" if path else str(key)
            if normalized not in {"secret_files", "secrets"}:
                allowed = normalized.endswith(SECRET_KEY_ALLOW_SUFFIXES)
                if SECRET_KEY_RE.search(normalized) and not allowed:
                    raise SystemExit(
                        f"ERROR: Spec contains raw secret-looking key at {sub_path}; "
                        "use delegated child secret-file fields instead."
                    )
            reject_secret_like_spec_keys(value, sub_path)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            reject_secret_like_spec_keys(item, f"{path}[{index}]")


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
            if text.lstrip().startswith("{"):
                data = json.loads(text)
            else:
                data = parse_simple_yaml(text)
        else:
            data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SystemExit(f"ERROR: Spec must be a mapping: {path}")
    if data.get("api_version") not in {None, f"{SKILL_NAME}/v1"}:
        raise SystemExit(
            f"ERROR: Spec api_version must be {SKILL_NAME}/v1; got {data.get('api_version')!r}"
        )
    reject_secret_like_spec_keys(data)
    return data


def get_nested(spec: dict[str, Any], dotted: str, default: Any) -> Any:
    current: Any = spec
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def as_bool(value: Any, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def as_list(value: Any, default: list[str] | None = None) -> list[str]:
    if value in (None, ""):
        return list(default or [])
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def write_text(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def selected_sections(value: str) -> list[str]:
    if not value or value == "all":
        return list(SECTIONS)
    sections = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(sections) - set(SECTIONS))
    if unknown:
        raise SystemExit(f"ERROR: Unknown execute section(s): {', '.join(unknown)}")
    return sections


def merge_config(spec: dict[str, Any]) -> dict[str, Any]:
    child_specs = get_nested(spec, "data_fabric.child_specs", {})
    if not isinstance(child_specs, dict):
        child_specs = {}
    return {
        "organization": str(get_nested(spec, "organization.name", "example-enterprise") or "example-enterprise"),
        "environment": str(get_nested(spec, "organization.environment", "production") or "production"),
        "owner": str(get_nested(spec, "organization.owner", "platform-operations") or "platform-operations"),
        "adoption_goal": str(get_nested(spec, "cloud_control.adoption_goal", "governed-agentic-operations") or "governed-agentic-operations"),
        "studio_region": str(get_nested(spec, "cloud_control.studio_region", "us") or "us"),
        "data_fabric_enabled": as_bool(get_nested(spec, "data_fabric.enabled", True), True),
        "data_fabric_spec": str(get_nested(spec, "data_fabric.spec", "") or ""),
        "data_fabric_child_specs": {str(k): str(v or "") for k, v in child_specs.items()},
        "spl2_pipeline_kit_enabled": as_bool(get_nested(spec, "data_fabric.spl2_pipeline_kit.enabled", True), True),
        "machine_data_lake_enabled": as_bool(get_nested(spec, "data_fabric.machine_data_lake.enabled", True), True),
        "data_catalog_enabled": as_bool(get_nested(spec, "data_fabric.data_catalog.enabled", True), True),
        "edge_processor_tenant_url": str(get_nested(spec, "data_fabric.edge_processor.tenant_url", "") or ""),
        "edge_processor_name": str(get_nested(spec, "data_fabric.edge_processor.name", "cloud-control-edge") or "cloud-control-edge"),
        "mcp_enabled": as_bool(get_nested(spec, "mcp.enabled", True), True),
        "mcp_clients": ",".join(as_list(get_nested(spec, "mcp.clients", "codex"), ["codex"])),
        "splunk_mcp_enabled": as_bool(get_nested(spec, "mcp.splunk_mcp_enabled", True), True),
        "splunk_mcp_url": str(get_nested(spec, "mcp.splunk_mcp_url", "") or ""),
        "thousandeyes_mcp_enabled": as_bool(get_nested(spec, "mcp.thousandeyes_mcp_enabled", True), True),
        "agent_observability_enabled": as_bool(get_nested(spec, "agent_observability.enabled", True), True),
        "agent_observability_spec": str(get_nested(spec, "agent_observability.spec", "skills/splunk-observability-ai-agent-monitoring-setup/template.example") or ""),
        "observability_content_enabled": as_bool(get_nested(spec, "observability_content.enabled", True), True),
        "realm": str(get_nested(spec, "observability_content.realm", "us0") or "us0"),
        "dashboards_spec": str(get_nested(spec, "observability_content.dashboards_spec", "") or ""),
        "detectors_spec": str(get_nested(spec, "observability_content.detectors_spec", "") or ""),
        "workflows_api_enabled": as_bool(get_nested(spec, "api.workflows_api_enabled", True), True),
        "domain_readiness_enabled": as_bool(get_nested(spec, "domain_readiness.enabled", True), True),
        "domains": as_list(get_nested(spec, "domain_readiness.domains", list(DOMAIN_HANDOFFS)), list(DOMAIN_HANDOFFS)),
        "agent_blueprints": get_nested(spec, "studio.agent_blueprints", []),
        "app_builder_briefs": get_nested(spec, "studio.app_builder_briefs", []),
        "ai_canvas_boards": get_nested(spec, "ai_canvas.boards", []),
    }


def command(argv: list[str]) -> list[str]:
    secret_flags = {flag for flag in DIRECT_SECRET_FLAGS}
    for item in argv:
        flag = item.split("=", 1)[0] if item.startswith("--") else item
        if flag in secret_flags:
            raise SystemExit(f"Internal error: command includes blocked secret flag {flag}")
    return argv


def build_commands(config: dict[str, Any], output_dir: Path) -> dict[str, list[list[str]]]:
    delegated = output_dir / "delegated"
    dashboard_spec = config["dashboards_spec"] or str(output_dir / "observability/cloud-control-dashboard.yaml")
    detector_spec = config["detectors_spec"] or str(output_dir / "observability/cloud-control-native-ops.yaml")

    data_fabric: list[list[str]] = []
    if config["data_fabric_enabled"]:
        data_fabric_command = [
            "bash",
            "skills/cisco-data-fabric-setup/scripts/setup.sh",
            "--render",
            "--validate",
            "--output-dir",
            str(delegated / "cisco-data-fabric"),
        ]
        if config["data_fabric_spec"]:
            data_fabric_command.extend(["--spec", config["data_fabric_spec"]])
        data_fabric.append(command(data_fabric_command))

    mcp: list[list[str]] = []
    if config["mcp_enabled"]:
        if config["splunk_mcp_enabled"] and config["splunk_mcp_url"]:
            mcp.append(
                command(
                    [
                        "bash",
                        "skills/splunk-mcp-server-setup/scripts/setup.sh",
                        "--render-clients",
                        "--mcp-url",
                        config["splunk_mcp_url"],
                        "--no-register-codex",
                        "--no-configure-cursor",
                        "--no-configure-claude",
                        "--output-dir",
                        str(delegated / "splunk-mcp"),
                    ]
                )
            )
        if config["thousandeyes_mcp_enabled"]:
            mcp.append(command(["bash", "skills/cisco-thousandeyes-mcp-setup/scripts/setup.sh", "--render", "--client", config["mcp_clients"], "--output-dir", str(delegated / "thousandeyes-mcp")]))

    agent_obs: list[list[str]] = []
    if config["agent_observability_enabled"]:
        cmd = ["bash", "skills/splunk-observability-ai-agent-monitoring-setup/scripts/setup.sh", "--render", "--output-dir", str(delegated / "ai-agent-monitoring")]
        if config["agent_observability_spec"]:
            cmd.extend(["--spec", config["agent_observability_spec"]])
        agent_obs.append(command(cmd))

    observability: list[list[str]] = []
    if config["observability_content_enabled"]:
        observability.append(command(["bash", "skills/splunk-observability-dashboard-builder/scripts/setup.sh", "--render", "--spec", dashboard_spec, "--realm", config["realm"], "--output-dir", str(delegated / "cloud-control-dashboards")]))
        observability.append(command(["bash", "skills/splunk-observability-native-ops/scripts/setup.sh", "--render", "--spec", detector_spec, "--realm", config["realm"], "--output-dir", str(delegated / "cloud-control-native-ops")]))

    return {
        "data-fabric": data_fabric,
        "mcp": mcp,
        "agent-observability": agent_obs,
        "observability-content": observability,
        "domain-readiness": [["bash", str(output_dir / "scripts/execute-domain-readiness.sh")]],
        "cloud-control-studio": [["bash", str(output_dir / "scripts/execute-cloud-control-studio.sh")]],
        "ai-canvas": [["bash", str(output_dir / "scripts/execute-ai-canvas.sh")]],
    }


def render_observability_specs(output_dir: Path, config: dict[str, Any]) -> None:
    write_text(
        output_dir / "observability/cloud-control-dashboard.yaml",
        f"""api_version: splunk-observability-dashboard-builder/v1
mode: classic-api
realm: {config["realm"]}
dashboard_group:
  name: Cisco Cloud Control Readiness
dashboard:
  name: Cisco Cloud Control Readiness
  description: Cisco Cloud Control adoption, MCP, Data Fabric, and agent observability readiness.
charts:
  - id: cloud-control-agent-spans
    name: Agent workflow spans
    type: TimeSeriesChart
    plot_type: LineChart
    row: 0
    column: 0
    width: 6
    height: 1
    program_text: |
      data('spans.count', filter=filter('deployment.environment', '{config["environment"]}')).sum().publish(label='spans')
""",
    )
    write_text(
        output_dir / "observability/cloud-control-native-ops.yaml",
        f"""api_version: splunk-observability-native-ops/v1
realm: {config["realm"]}
detectors:
  - name: Cisco Cloud Control readiness gap
    description: Starter detector placeholder for reviewed Cloud Control readiness signals.
    program_text: |
      readiness = data('spans.count', filter=filter('deployment.environment', '{config["environment"]}')).sum().publish(label='readiness')
      detect(when(readiness < threshold(1))).publish('cloud_control_readiness_gap')
    rules:
      - detect_label: cloud_control_readiness_gap
        severity: Warning
        description: Review Data Fabric, MCP, and agent observability prerequisites.
""",
    )


def render_platform_assets(output_dir: Path, config: dict[str, Any]) -> None:
    feature_lines = [
        "# Official Cloud Control Feature Coverage",
        "",
        "This checklist is based on the Cisco Cloud Control Getting Started related resources.",
        "",
        "| Key | Area | Status | Boundary |",
        "| --- | --- | --- | --- |",
    ]
    for key, area, status, _owner, _source_key, boundary in OFFICIAL_FEATURES:
        feature_lines.append(f"| `{key}` | {area} | `{status}` | {boundary} |")
    write_text(output_dir / "platform/feature-coverage.md", "\n".join(feature_lines) + "\n")

    product_lines = [
        "# Product Integration Matrix",
        "",
        "Current support matrix from Cisco Cloud Control Getting Started. Verify the live page before production adoption because Controlled Availability coverage can change.",
        "",
        "| Product | Inventory | Topology | Notifications |",
        "| --- | --- | --- | --- |",
    ]
    for product, inventory, topology, notifications in PRODUCT_INTEGRATION_MATRIX:
        product_lines.append(f"| {product} | {inventory} | {topology} | {notifications} |")
    product_lines.extend(
        [
            "",
            "## Adjacent onboarding and integration handoffs",
            "",
            "These are not equivalent rows in the current support matrix.",
            "",
            "| Surface | Classification | Boundary |",
            "| --- | --- | --- |",
        ]
    )
    for product, classification, boundary in PRODUCT_ADJACENT_HANDOFFS:
        product_lines.append(f"| {product} | `{classification}` | {boundary} |")
    write_text(output_dir / "platform/product-integration-matrix.md", "\n".join(product_lines) + "\n")

    write_text(
        output_dir / "platform/admin-readiness.md",
        f"""# Admin Readiness

- Organization: `{config["organization"]}`
- Environment: `{config["environment"]}`
- Admin onboarding: confirm at least one product admin can complete tenant linking and tenant-group creation.
- AI context: collect Meraki API URL, Meraki network ID/name, Meraki organization ID, authenticated user email, and ThousandEyes account group ID before AI Canvas validation.
- Integrations: review Meraki, ThousandEyes, and Collaboration Control Hub handoffs in the Admin Console.
- Users and tenants: review Tenant Full Admin, Tenant Read-Only, Integration Admin, tenant groups, tenant switcher, and Nexus Dashboard access assignments.
- SSO: review domain verification, SAML or OIDC IdP configuration, routing rules, and service-provider certificates.
- Governance: review Identity and Access audit logs, Admin Activity logs, CSV/JSON evidence exports, Actions, Notifications, Favorites, and Help menu support flows.

Parent boundary: this artifact is a checklist only. It does not mutate Cisco Cloud Control.
""",
    )

    write_text(
        output_dir / "api/workflows-api-readiness.md",
        """# Cisco Workflows API Readiness

- API surface: Cisco Workflows / Meraki Automation REST API.
- Base URL pattern: `https://api.meraki.com/api/automate/organizations`.
- Example resource path: `/api/automate/organizations/<ORG_ID>/v1.1/workflows`.
- Authentication model: bearer API key in the request header, stored in Cisco target account keys or reviewed child secret-file stores, never in this parent spec or argv.
- OpenAPI basis: download the Automation OAS file from the Cisco Workflows API documentation before building a custom integration.
- Rate-limit basis from Cisco Workflows docs: Start API 20/min, Webhook API 20/min, Instances API 50/min, other APIs 8000/hour.
- Workflow design limits to check before automation: 500 workflows, 500 atomics, 200 actions per workflow, 30 minute maximum workflow run time, 20 remote targets, and 300 account keys per organization.
- CORS note: Swagger UI can be used to inspect the OAS, but not for live calls from the browser.

Parent boundary: this skill renders API readiness only. It does not call the Workflows API and does not claim a direct Cisco Cloud Control platform mutation API.
""",
    )

    write_text(
        output_dir / "api/cloud-control-api-boundary.md",
        """# Cloud Control API Boundary

The current executable basis is delegated child skills plus the documented Cisco Workflows API readiness path.

Supported by this parent:

- Render official Cloud Control feature, product, identity, topology, inventory, licensing, workflow, and release-note coverage.
- Render Cisco Workflows API readiness from the public API/OAS documentation.
- Render Cloud Control Studio, AI Canvas, Admin Console, SSO, tenant, audit, and integration handoffs.

Not supported by this parent:

- Direct Cisco Cloud Control platform mutation.
- Direct Cloud Control Studio Agent Builder or App Builder writes.
- Direct AI Canvas board creation.
- Secrets in chat, argv, rendered Markdown, coverage, metadata, or JSON.
""",
    )


def render_studio_assets(output_dir: Path, config: dict[str, Any]) -> None:
    blueprints = config["agent_blueprints"] or [
        {
            "name": "Network Incident Triage",
            "domain": "networking",
            "objective": "Summarize incident context, affected sites, recent changes, and next actions.",
        }
    ]
    for item in blueprints:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "Agent Blueprint"))
        write_text(
            output_dir / "studio/agent-blueprints" / f"{slugify(name)}.md",
            f"""# {name}

- Domain: {item.get("domain", "operations")}
- Objective: {item.get("objective", "Prepare a governed Cloud Control agent workflow.")}
- Data prerequisites: Cisco Data Fabric, MCP connectors, domain product telemetry, and Splunk Observability traces.
- Guardrails: require human review for mutating network, security, or cloud actions.
- Observability: instrument agent steps with Splunk AI Agent Monitoring before production use.

Cloud Control Studio action: create or refine this in Agent Builder.
""",
        )

    briefs = config["app_builder_briefs"] or [
        {
            "name": "Operations Console",
            "audience": "NOC and SecOps leads",
            "objective": "Shared Cloud Control view over network, security, and observability readiness.",
        }
    ]
    for item in briefs:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "App Builder Brief"))
        write_text(
            output_dir / "studio/app-builder-briefs" / f"{slugify(name)}.md",
            f"""# {name}

- Audience: {item.get("audience", "operations")}
- Objective: {item.get("objective", "Build a Cloud Control operational app.")}
- Required connectors: Splunk Platform, Splunk Observability Cloud, ThousandEyes, and selected Cisco domain sources.
- Review gates: data access, action permissions, AI Defense posture, and agent observability.

Cloud Control Studio action: create or refine this in App Builder.
""",
        )

    write_text(
        output_dir / "studio/mcp-connector-plan.md",
        f"""# MCP Connector Plan

- Splunk MCP owner: `splunk-mcp-server-setup`
- ThousandEyes MCP owner: `cisco-thousandeyes-mcp-setup`
- Requested clients: `{config["mcp_clients"]}`
- Splunk MCP URL provided: `{"true" if config["splunk_mcp_url"] else "false"}`
- Studio boundary: connect reviewed MCP servers in Cloud Control Studio; this parent does not push connector state into Cisco Cloud Control.

Splunk MCP render note: this parent emits the Splunk MCP client render command only when `mcp.splunk_mcp_url` is set, because the child skill otherwise must derive the endpoint from Splunk credentials. ThousandEyes MCP can still render without a Splunk endpoint.

Review `apply-plan.json` before executing the `mcp` section.
""",
    )


def render_ai_canvas_assets(output_dir: Path, config: dict[str, Any]) -> None:
    boards = config["ai_canvas_boards"] or [
        {
            "name": "Agentic Operations Readiness",
            "objective": "Track data, connector, guardrail, and observability prerequisites.",
        }
    ]
    for item in boards:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "AI Canvas Board"))
        write_text(
            output_dir / "ai-canvas/board-templates" / f"{slugify(name)}.md",
            f"""# {name}

- Objective: {item.get("objective", "Coordinate Cloud Control readiness.")}
- Lanes: Data Fabric, MCP connectors, domain sources, AI Defense, Observability, Studio build, validation.
- Exit criteria: child skill validation complete, agent traces visible, action boundaries documented, and owner approvals recorded.
- Splunk prerequisites: Cloud Control enabled, Splunk Cloud `10.5.2605.3`, current AI Assistant and MCP Server, and `mcp_tool_execute` for every user.
- Splunk limits: results are capped at 100 rows per card; incompatible visualizations do not render; some SPL commands are forbidden and fail on refresh or run.

AI Canvas action: recreate this board in the Cisco AI Canvas experience.
""",
        )


def render_domain_handoffs(output_dir: Path, config: dict[str, Any]) -> None:
    lines = ["# Domain Readiness Handoffs", ""]
    for domain in config["domains"]:
        key = slugify(domain)
        owner, purpose = DOMAIN_HANDOFFS.get(domain, ("cisco-product-setup", "Resolve this domain through the Cisco product router."))
        write_text(
            output_dir / "domain-readiness" / f"{key}.md",
            f"""# {domain}

- Owner skill: `{owner}`
- Purpose: {purpose}
- First command: `bash skills/{owner}/scripts/setup.sh --help`
- Parent boundary: render handoff only; execute the child skill directly after review.
""",
        )
        lines.append(f"- `{domain}` -> `{owner}`: {purpose}")
    write_text(output_dir / "domain-readiness/index.md", "\n".join(lines) + "\n")


def render_data_fabric_handoffs(output_dir: Path, config: dict[str, Any]) -> None:
    specs = config["data_fabric_child_specs"]
    lines = [
        "# Cisco Data Fabric Handoffs",
        "",
        "Cisco Data Fabric is owned by the dedicated `cisco-data-fabric-setup` architecture router.",
        "This Cloud Control parent delegates one render-and-validate command and never invokes constituent child skills with example defaults.",
        "",
    ]
    if config["data_fabric_spec"]:
        lines.append(f"- Data Fabric intake: `{config['data_fabric_spec']}`")
    else:
        lines.append(
            "- Data Fabric intake: no child spec supplied; the dedicated parent renders its complete evidence-backed default coverage packet without executing constituent skills."
        )
    for key, value in sorted(specs.items()):
        if value:
            lines.append(f"- Legacy `data_fabric.child_specs.{key}` value `{value}` is recorded for migration; move it into the dedicated Data Fabric intake.")
    lines.extend(
        [
            "- Data management coverage includes Data Inputs, Edge Processor, Ingest Processor, SPL2, Automated Field Extraction CA, Guided Onboarding/Auto-Schematization alpha, and Ingest Monitoring.",
            "- Federation coverage keeps Splunk, Amazon S3, Microsoft Azure, Azure Databricks, Snowflake, DDSS, and Amazon Security Lake lifecycle and entitlement boundaries separate.",
            "- Catalog coverage distinguishes the global Splunk Catalog, Splunk-native dataset catalogs, AWS Glue, Iceberg REST, Databricks Unity Catalog, and Machine Data Lake cataloging.",
            "- Storage coverage distinguishes indexed data, Machine Data Lake alpha, external stores, DDSS, DDAA, SmartStore, and S3 Promote.",
            "- AI coverage distinguishes AI Toolkit, open Cisco Time Series Model 1.0, the GA hosted Cisco Deep Time Series Model, GA Splunk AI Toolkit Agent Launchpad, the separate Cloud Control Studio Agent Builder, MCP Server, and AI Canvas CA.",
            f"- The audited AI Toolkit pair is `6.0.2` with Python for Scientific Computing `4.3.4`; `6.0.2` with `4.3.2` is an unsupported pairing. See {SOURCE_URLS['ai_toolkit_dependencies']}.",
            f"- Cisco Deep Time Series Model ({SOURCE_URLS['cdtsm']}) and Splunk AI Toolkit Agent Launchpad ({SOURCE_URLS['agent_launchpad']}) are both generally available as of AI Toolkit `6.0.0`. Treat supported region, allowlisted egress IP, a supported LLM connection, and an enabled agent as reachability gates rather than lifecycle stage.",
            "- Cloud Control Studio Agent Builder is a different Cisco product from Splunk AI Toolkit Agent Launchpad. Splunk GA is not evidence for the Cisco capability, and the dedicated Data Fabric parent owns its separately verified stage.",
            "- Machine Data Lake and built-in Data Catalog remain readiness handoffs; no undocumented provisioning API is called.",
        ]
    )
    write_text(output_dir / "data-fabric/handoff.md", "\n".join(lines) + "\n")

    readiness = [
        "# Cisco Data Fabric 2026 Readiness",
        "",
        "This parent treats Cisco Data Fabric as an architecture powered by Splunk",
        "Platform capabilities, not as a single package installer.",
        "",
        "| Surface | Status | Owner | Boundary |",
        "| --- | --- | --- | --- |",
    ]
    for surface in DATA_FABRIC_2026_SURFACES:
        readiness.append(
            f"| {surface['title']} | `{surface['status']}` | `{surface['owner']}` | {surface['summary']} |"
        )
    readiness.extend(
        [
            "",
            "## Review Checklist",
            "",
            "- Review the delegated `cisco-data-fabric-setup` product matrix, availability matrix, source ledger, gap register, and doctor report.",
            "- Classify data by indexed, alpha Machine Data Lake, archive/lifecycle, and store-specific external federation tiers before routing.",
            "- Confirm per-surface version, cloud, region, activation, entitlement, credential, catalog, and role requirements.",
            "- Keep lifecycle stage independent from repository automation status; a GA product can still be render-only or production-blocked in its owning child skill.",
            "- Keep action execution, data promotion, legacy migration, and agent workflows behind RBAC, audit, cost, and human-approval gates.",
        ]
    )
    write_text(output_dir / "data-fabric/cisco-data-fabric-2026-readiness.md", "\n".join(readiness) + "\n")


def coverage_rows(config: dict[str, Any]) -> list[dict[str, str]]:
    rows = [
        ("cloud_control_platform", "platform", "render", "cisco-cloud-control-setup", SOURCE_URLS["getting_started"], "Render adoption and readiness artifacts only; no direct Cloud Control API mutation."),
        ("cloud_control_launch_context", "platform", "render", "cisco-cloud-control-setup", SOURCE_URLS["press"], "Track launch context and product boundary in docs."),
        ("cloud_control_studio_agent_builder", "studio", "ui_handoff", "Cisco Cloud Control Studio", SOURCE_URLS["studio"], "Agent Builder actions are operator UI handoffs."),
        ("cloud_control_studio_app_builder", "studio", "ui_handoff", "Cisco Cloud Control Studio", SOURCE_URLS["app_builder"], "App Builder actions are operator UI handoffs."),
        ("ai_defense_guardrails", "governance", "render", "cisco-cloud-control-setup", SOURCE_URLS["ai_defense"], "Render guardrail review prompts; AI Defense configuration is a Cisco-side handoff."),
        ("ai_canvas_boards", "ai-canvas", "ca_handoff", "Cisco AI Canvas", SOURCE_URLS["ai_canvas_doc"], "Render board templates only."),
        ("data_fabric_prerequisites", "data-fabric", "delegated_render" if config["data_fabric_enabled"] else "not_applicable", "cisco-data-fabric-setup", SOURCE_URLS["splunk"], "Dedicated parent owns lifecycle-aware architecture coverage, child routing, and validation; this parent delegates render only."),
        ("data_fabric_full_architecture_coverage", "data-fabric", "delegated_render" if config["data_fabric_enabled"] else "not_applicable", "cisco-data-fabric-setup", SOURCE_URLS["cisco_data_fabric_press"], "Render the complete product, feature, federation, storage/catalog, AI, governance, experience, source-ledger, and gap packet."),
        ("data_fabric_spl2_pipeline_kit", "data-fabric", "delegated_render" if config["data_fabric_enabled"] and config["spl2_pipeline_kit_enabled"] else "not_applicable", "cisco-data-fabric-setup", SOURCE_URLS["splunk_data_management"], "Dedicated parent records and safely delegates reusable SPL2 templates when enabled by its reviewed intake."),
        ("mcp_connectors", "mcp", "delegated_apply" if config["mcp_enabled"] else "not_applicable", "splunk-mcp-server-setup,cisco-thousandeyes-mcp-setup", SOURCE_URLS["agent_builder"], "Child MCP skills own client writes and token-file validation."),
        ("agent_observability", "observability", "delegated_apply" if config["agent_observability_enabled"] else "not_applicable", "splunk-observability-ai-agent-monitoring-setup", SOURCE_URLS["splunk"], "Child skill owns collector/runtime/content apply."),
        ("observability_content", "observability", "delegated_apply" if config["observability_content_enabled"] else "not_applicable", "splunk-observability-dashboard-builder,splunk-observability-native-ops", SOURCE_URLS["splunk"], "Child skills own Observability API writes."),
        ("domain_readiness", "domains", "render" if config["domain_readiness_enabled"] else "not_applicable", "Cisco product setup skills", SOURCE_URLS["splunk"], "Parent renders handoffs only; child skills own live work."),
        ("validation", "validation", "validate", "cisco-cloud-control-setup", SOURCE_URLS["platform"], "Static validation checks artifacts, coverage, and secret hygiene."),
    ]
    for surface in DATA_FABRIC_2026_SURFACES:
        status = surface["status"]
        if not config["data_fabric_enabled"]:
            status = "not_applicable"
        if surface["key"] == "machine_data_lake_alpha" and not config["machine_data_lake_enabled"]:
            status = "not_applicable"
        if surface["key"] == "built_in_data_catalog" and not config["data_catalog_enabled"]:
            status = "not_applicable"
        rows.append(
            (
                f"data_fabric_{surface['key']}",
                "data-fabric",
                status,
                surface["owner"],
                SOURCE_URLS[surface["source"]],
                surface["summary"],
            )
        )
    for key, area, status, owner, source_key, apply_boundary in OFFICIAL_FEATURES:
        if key == "workflows_api" and not config["workflows_api_enabled"]:
            status = "not_applicable"
        rows.append((key, area, status, owner, SOURCE_URLS[source_key], apply_boundary))
    for product, inventory, topology, notifications in PRODUCT_INTEGRATION_MATRIX:
        rows.append(
            (
                f"product_{slugify(product).replace('-', '_')}",
                "products",
                "render",
                "cisco-cloud-control-setup",
                SOURCE_URLS["getting_started"],
                f"Current support matrix: inventory={inventory}; topology={topology}; notifications={notifications}.",
            )
        )
    for product, classification, boundary in PRODUCT_ADJACENT_HANDOFFS:
        rows.append(
            (
                f"product_{slugify(product).replace('-', '_')}",
                "products",
                "render",
                "cisco-cloud-control-setup",
                SOURCE_URLS["getting_started"],
                f"Adjacent surface classification={classification}. {boundary}",
            )
        )
    output = []
    for key, area, status, owner, source_url, apply_boundary in rows:
        if status not in ALLOWED_STATUSES:
            raise SystemExit(f"Internal error: unsupported coverage status {status}")
        output.append(
            {
                "key": key,
                "area": area,
                "status": status,
                "owner": owner,
                "source_url": source_url,
                "apply_boundary": apply_boundary,
            }
        )
    return output


def build_apply_plan(config: dict[str, Any], commands: dict[str, list[list[str]]], sections: list[str], output_dir: Path) -> dict[str, Any]:
    owners = {
        "data-fabric": "cisco-data-fabric-setup",
        "mcp": "splunk-mcp-server-setup,cisco-thousandeyes-mcp-setup",
        "agent-observability": "splunk-observability-ai-agent-monitoring-setup",
        "observability-content": "splunk-observability-dashboard-builder,splunk-observability-native-ops",
        "domain-readiness": "cisco-product-setup and Cisco domain setup skills",
        "cloud-control-studio": "Cisco Cloud Control Studio UI handoff",
        "ai-canvas": "Cisco AI Canvas handoff",
    }
    return {
        "api_version": f"{SKILL_NAME}/v1",
        "output_dir": str(output_dir),
        "selected_sections": sections,
        "secret_values_rendered": False,
        "sections": [
            {
                "name": section,
                "owner": owners[section],
                "commands": commands[section],
                "script": f"scripts/execute-{section}.sh",
                "requires_accept_execute": section in {"data-fabric", "mcp", "agent-observability", "observability-content"},
                "secret_values_rendered": False,
            }
            for section in SECTIONS
        ],
    }


def render_coverage(output_dir: Path, rows: list[dict[str, str]]) -> None:
    write_json(
        output_dir / "coverage-report.json",
        {
            "api_version": f"{SKILL_NAME}/coverage/v1",
            "secret_values_rendered": False,
            "allowed_statuses": sorted(ALLOWED_STATUSES),
            "coverage": rows,
        },
    )
    lines = [
        "# Coverage Report",
        "",
        "| Key | Area | Status | Owner | Apply boundary |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['key']}` | {row['area']} | `{row['status']}` | `{row['owner']}` | {row['apply_boundary']} |"
        )
    write_text(output_dir / "coverage-report.md", "\n".join(lines) + "\n")


def script_header() -> str:
    repo_root = str(REPO_ROOT)
    return f"""#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
OUTPUT_DIR="$(cd "${{SCRIPT_DIR}}/.." && pwd)"
PROJECT_ROOT="${{PROJECT_ROOT:-{repo_root}}}"
cd "${{PROJECT_ROOT}}"
"""


def render_command_script(section: str, commands: list[list[str]]) -> str:
    lines = [script_header()]
    if not commands:
        lines.append(f"echo {shell_quote('ERROR: no executable commands selected for ' + section)} >&2\n")
        lines.append("exit 2\n")
        return "".join(lines)
    if section in {"domain-readiness", "cloud-control-studio", "ai-canvas"}:
        rel = {
            "domain-readiness": "domain-readiness/index.md",
            "cloud-control-studio": "studio/mcp-connector-plan.md",
            "ai-canvas": "ai-canvas/board-templates",
        }[section]
        lines.append(f"echo {shell_quote('ERROR: this section is a rendered handoff, not an executed change.')} >&2\n")
        lines.append(f"echo {shell_quote('Review rendered handoff artifacts: ')}\"${{OUTPUT_DIR}}/{rel}\" >&2\n")
        lines.append("exit 2\n")
        return "".join(lines)
    for argv in commands:
        quoted = " ".join(shell_quote(part) for part in argv)
        lines.append(f"cmd=({quoted})\n")
        lines.append('"${cmd[@]}"\n')
    return "".join(lines)


def render_scripts(output_dir: Path, commands: dict[str, list[list[str]]], selected: list[str]) -> None:
    for section in SECTIONS:
        write_text(
            output_dir / "scripts" / f"execute-{section}.sh",
            render_command_script(section, commands[section]),
            executable=True,
        )
    selected_lines = [script_header(), "sections=(" + " ".join(shell_quote(s) for s in selected) + ")\n"]
    selected_lines.append(
        """for section in "${sections[@]}"; do
  case "${section}" in
    domain-readiness|cloud-control-studio|ai-canvas)
      echo "ERROR: ${section} is handoff-only; refusing the mixed execution before any delegated mutation." >&2
      exit 2
      ;;
  esac
done
for section in "${sections[@]}"; do
  "${SCRIPT_DIR}/execute-${section}.sh"
done
"""
    )
    write_text(output_dir / "scripts/execute-selected.sh", "".join(selected_lines), executable=True)


def render_metadata(output_dir: Path, config: dict[str, Any]) -> None:
    write_json(
        output_dir / "metadata.json",
        {
            "api_version": f"{SKILL_NAME}/v1",
            "organization": config["organization"],
            "environment": config["environment"],
            "owner": config["owner"],
            "adoption_goal": config["adoption_goal"],
            "studio_region": config["studio_region"],
            "secret_values_rendered": False,
            "cloud_control_api_mutation": False,
            "official_cloud_control_docs_reviewed": True,
            "workflow_api_readiness_rendered": config["workflows_api_enabled"],
            "data_fabric_2026_readiness_rendered": config["data_fabric_enabled"],
            "machine_data_lake_readiness_enabled": config["machine_data_lake_enabled"],
            "data_catalog_readiness_enabled": config["data_catalog_enabled"],
        },
    )


def render_handoff(output_dir: Path, config: dict[str, Any], selected: list[str]) -> None:
    lines = [
        "# Cisco Cloud Control Handoff",
        "",
        f"- Organization: `{config['organization']}`",
        f"- Environment: `{config['environment']}`",
        f"- Adoption goal: `{config['adoption_goal']}`",
        "- Direct Cisco Cloud Control mutation: `false`",
        "- Secret values rendered: `false`",
        "",
        "## Review Order",
        "1. Read `platform/feature-coverage.md`, `platform/product-integration-matrix.md`, `coverage-report.md`, and `doctor-report.md`.",
        "2. Review `api/cloud-control-api-boundary.md` and `api/workflows-api-readiness.md` before any custom workflow API work.",
        "3. Review Cloud Control Studio, AI Canvas, Admin Console, SSO, audit, inventory, topology, licensing, and workflow handoff artifacts.",
        "4. Execute only delegated sections that have child owners and reviewed specs.",
        "5. Run child-skill validation after any delegated apply.",
        "",
        "## Selected Sections",
    ]
    for section in selected:
        lines.append(f"- `{section}`")
    write_text(output_dir / "handoff.md", "\n".join(lines) + "\n")


def render_doctor(output_dir: Path, config: dict[str, Any], rows: list[dict[str, str]]) -> None:
    delegated = [row for row in rows if row["status"] == "delegated_apply"]
    delegated_render = [row for row in rows if row["status"] == "delegated_render"]
    handoffs = [row for row in rows if row["status"] in {"ui_handoff", "ca_handoff"}]
    lines = [
        "# Cisco Cloud Control Doctor Report",
        "",
        f"- Organization: `{config['organization']}`",
        f"- Environment: `{config['environment']}`",
        f"- Delegated apply surfaces: {len(delegated)}",
        f"- Delegated render surfaces: {len(delegated_render)}",
        f"- UI/CA handoff surfaces: {len(handoffs)}",
        "- Direct Cisco Cloud Control API mutation: `false`",
        "- Secret values rendered: `false`",
        "",
        "## Required Reviews",
        "- Confirm Cisco Cloud Control entitlement and Studio access.",
        "- Confirm Cisco AI Canvas access; for Splunk require Cloud Control enablement, Splunk Cloud 10.5.2605.3, current AI Assistant and MCP Server, and mcp_tool_execute for every user.",
        "- Validate AI Canvas's 100-row-per-card cap, visualization compatibility, and forbidden SPL commands before relying on generated searches.",
        "- Review the current Inventory/Topology/Notifications matrix for Catalyst SD-WAN Manager, Collaboration Control Hub, Intersight, Meraki, Nexus Dashboard, Nexus Hyperfabric, Secure Access, Secure Firewall, and ThousandEyes; treat Catalyst Center, Security Cloud Control, Splunk Cloud, and Cisco IQ as separately classified handoffs.",
        "- Review inventory, licensing, RBAC, topology, workflows, audit logs, SSO, users, tenants, Actions, Notifications, Favorites, and support/help coverage.",
        "- If custom automation is needed, review the Cisco Workflows API OAS, target/account-key model, and rate limits before implementation.",
        "- Review Cisco Cloud Control release-note open issues before production agent use.",
        "- Confirm Splunk Platform, ITSI, and Observability Cloud prerequisites through delegated skills.",
        "- Review the dedicated Cisco Data Fabric source ledger and lifecycle matrix; do not infer product availability from Cloud Control launch messaging.",
        "- Confirm AI Defense and action-approval boundaries before production agent execution.",
    ]
    write_text(output_dir / "doctor-report.md", "\n".join(lines) + "\n")


def render(args: argparse.Namespace) -> dict[str, Any]:
    spec = load_spec(args.spec)
    config = merge_config(spec)
    output_dir = Path(args.output_dir).expanduser().resolve()
    selected = selected_sections(args.execute)
    commands = build_commands(config, output_dir)
    plan = build_apply_plan(config, commands, selected, output_dir)

    if args.dry_run:
        return plan

    output_dir.mkdir(parents=True, exist_ok=True)
    render_metadata(output_dir, config)
    render_platform_assets(output_dir, config)
    render_observability_specs(output_dir, config)
    render_studio_assets(output_dir, config)
    render_ai_canvas_assets(output_dir, config)
    render_data_fabric_handoffs(output_dir, config)
    render_domain_handoffs(output_dir, config)
    render_scripts(output_dir, commands, selected)
    write_json(output_dir / "apply-plan.json", plan)
    rows = coverage_rows(config)
    render_coverage(output_dir, rows)
    render_handoff(output_dir, config, selected)
    render_doctor(output_dir, config, rows)
    return {
        "output_dir": str(output_dir),
        "apply_plan": str(output_dir / "apply-plan.json"),
        "coverage_report": str(output_dir / "coverage-report.json"),
        "doctor_report": str(output_dir / "doctor-report.md"),
        "handoff": str(output_dir / "handoff.md"),
        "selected_sections": selected,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = render(args)
    if args.json or args.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Rendered Cisco Cloud Control assets to {payload['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

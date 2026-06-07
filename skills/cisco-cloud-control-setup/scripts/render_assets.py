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
}
PRODUCT_INTEGRATION_MATRIX = [
    ("Meraki", "Available", "Available", "Available"),
    ("Catalyst Center", "Q3 2026", "Q3 2026", "Q3 2026"),
    ("Nexus Dashboard", "Available", "Available", "Available"),
    ("Nexus Hyperfabric", "Available", "Available", "Available"),
    ("Intersight", "Available", "Available", "Available"),
    ("Catalyst SD-WAN Manager", "End of May 2026", "End of May 2026", "End of May 2026"),
    ("Security Cloud Control", "Available", "Firewall: Available; Secure Access: Available", "Available"),
    ("ThousandEyes", "End of May 2026", "Available via Meraki; native support End of May 2026", "Available"),
    ("Splunk Cloud", "Q3 2026", "Q3 2026", "Q3 2026"),
    ("Collaboration Control Hub", "Available", "Available", "Available"),
    ("Cisco IQ", "End of May 2026", "Future roadmap", "Future roadmap"),
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
        "Render official navigation, inventory, and AI Canvas product timeline matrix.",
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
        "data_fabric_child_specs": {str(k): str(v or "") for k, v in child_specs.items()},
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
    specs = config["data_fabric_child_specs"]
    dashboard_spec = config["dashboards_spec"] or str(output_dir / "observability/cloud-control-dashboard.yaml")
    detector_spec = config["detectors_spec"] or str(output_dir / "observability/cloud-control-native-ops.yaml")

    data_fabric: list[list[str]] = []
    if config["data_fabric_enabled"]:
        if specs.get("federated_search"):
            fed = ["bash", "skills/splunk-federated-search-setup/scripts/setup.sh", "--phase", "render", "--output-dir", str(delegated / "splunk-federated-search")]
            fed.extend(["--spec", specs["federated_search"]])
            data_fabric.append(command(fed))
        if config["edge_processor_tenant_url"]:
            data_fabric.append(
                command(
                    [
                        "bash",
                        "skills/splunk-edge-processor-setup/scripts/setup.sh",
                        "--phase",
                        "render",
                        "--ep-tenant-url",
                        config["edge_processor_tenant_url"],
                        "--ep-name",
                        config["edge_processor_name"],
                        "--output-dir",
                        str(delegated / "splunk-edge-processor"),
                    ]
                )
            )
        data_fabric.append(command(["bash", "skills/splunk-ingest-processor-setup/scripts/setup.sh", "--phase", "render", "--output-dir", str(delegated / "splunk-ingest-processor")]))
        ai_ml = ["bash", "skills/splunk-ai-ml-toolkit-setup/scripts/setup.sh", "--render", "--output-dir", str(delegated / "splunk-ai-ml-toolkit")]
        if specs.get("ai_ml_toolkit"):
            ai_ml.extend(["--spec", specs["ai_ml_toolkit"]])
        data_fabric.append(command(ai_ml))

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
        "Cisco marks these timelines as roadmap information that can change.",
        "",
        "| Product | Navigation | Inventory | AI Canvas |",
        "| --- | --- | --- | --- |",
    ]
    for product, navigation, inventory, ai_canvas in PRODUCT_INTEGRATION_MATRIX:
        product_lines.append(f"| {product} | {navigation} | {inventory} | {ai_canvas} |")
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
        "The parent executes only child render commands that have enough non-secret input.",
        "",
    ]
    if specs.get("federated_search"):
        lines.append(f"- Federated Search spec: `{specs['federated_search']}`")
    else:
        lines.append(
            "- Federated Search: skipped until `data_fabric.child_specs.federated_search` points to a reviewed child spec."
        )
    if config["edge_processor_tenant_url"]:
        lines.append(f"- Edge Processor tenant URL: `{config['edge_processor_tenant_url']}`")
    else:
        lines.append(
            "- Edge Processor: skipped until `data_fabric.edge_processor.tenant_url` is set."
        )
    for key in ("edge_processor", "ingest_processor"):
        if specs.get(key):
            lines.append(
                f"- {key}: spec path `{specs[key]}` recorded for operator review; the current child skill CLI does not accept a parent `--spec` handoff."
            )
    lines.extend(
        [
            "- Ingest Processor: render command uses default child render mode.",
            "- AI/ML Toolkit: render command uses child spec when `data_fabric.child_specs.ai_ml_toolkit` is set.",
        ]
    )
    write_text(output_dir / "data-fabric/handoff.md", "\n".join(lines) + "\n")


def coverage_rows(config: dict[str, Any]) -> list[dict[str, str]]:
    rows = [
        ("cloud_control_platform", "platform", "render", "cisco-cloud-control-setup", SOURCE_URLS["getting_started"], "Render adoption and readiness artifacts only; no direct Cloud Control API mutation."),
        ("cloud_control_launch_context", "platform", "render", "cisco-cloud-control-setup", SOURCE_URLS["press"], "Track launch context and product boundary in docs."),
        ("cloud_control_studio_agent_builder", "studio", "ui_handoff", "Cisco Cloud Control Studio", SOURCE_URLS["studio"], "Agent Builder actions are operator UI handoffs."),
        ("cloud_control_studio_app_builder", "studio", "ui_handoff", "Cisco Cloud Control Studio", SOURCE_URLS["studio"], "App Builder actions are operator UI handoffs."),
        ("ai_defense_guardrails", "governance", "render", "cisco-cloud-control-setup", SOURCE_URLS["ai_defense"], "Render guardrail review prompts; AI Defense configuration is a Cisco-side handoff."),
        ("ai_canvas_boards", "ai-canvas", "ca_handoff", "Cisco AI Canvas", SOURCE_URLS["ai_canvas_doc"], "Render board templates only."),
        ("data_fabric_prerequisites", "data-fabric", "delegated_apply" if config["data_fabric_enabled"] else "not_applicable", "Splunk Data Fabric child skills", SOURCE_URLS["splunk"], "Child skills own render/apply/validate."),
        ("mcp_connectors", "mcp", "delegated_apply" if config["mcp_enabled"] else "not_applicable", "splunk-mcp-server-setup,cisco-thousandeyes-mcp-setup", SOURCE_URLS["agent_builder"], "Child MCP skills own client writes and token-file validation."),
        ("agent_observability", "observability", "delegated_apply" if config["agent_observability_enabled"] else "not_applicable", "splunk-observability-ai-agent-monitoring-setup", SOURCE_URLS["splunk"], "Child skill owns collector/runtime/content apply."),
        ("observability_content", "observability", "delegated_apply" if config["observability_content_enabled"] else "not_applicable", "splunk-observability-dashboard-builder,splunk-observability-native-ops", SOURCE_URLS["splunk"], "Child skills own Observability API writes."),
        ("domain_readiness", "domains", "render" if config["domain_readiness_enabled"] else "not_applicable", "Cisco product setup skills", SOURCE_URLS["splunk"], "Parent renders handoffs only; child skills own live work."),
        ("validation", "validation", "validate", "cisco-cloud-control-setup", SOURCE_URLS["platform"], "Static validation checks artifacts, coverage, and secret hygiene."),
    ]
    for key, area, status, owner, source_key, apply_boundary in OFFICIAL_FEATURES:
        if key == "workflows_api" and not config["workflows_api_enabled"]:
            status = "not_applicable"
        rows.append((key, area, status, owner, SOURCE_URLS[source_key], apply_boundary))
    for product, navigation, inventory, ai_canvas in PRODUCT_INTEGRATION_MATRIX:
        rows.append(
            (
                f"product_{slugify(product).replace('-', '_')}",
                "products",
                "render",
                "cisco-cloud-control-setup",
                SOURCE_URLS["getting_started"],
                f"Official timeline: navigation={navigation}; inventory={inventory}; ai_canvas={ai_canvas}.",
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
        "data-fabric": "Splunk Data Fabric child skills",
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
        lines.append(f"echo {shell_quote('No commands selected for ' + section)}\n")
        return "".join(lines)
    if section in {"domain-readiness", "cloud-control-studio", "ai-canvas"}:
        rel = {
            "domain-readiness": "domain-readiness/index.md",
            "cloud-control-studio": "studio/mcp-connector-plan.md",
            "ai-canvas": "ai-canvas/board-templates",
        }[section]
        lines.append(f"echo {shell_quote('Review rendered handoff artifacts: ')}\"${{OUTPUT_DIR}}/{rel}\"\n")
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
    handoffs = [row for row in rows if row["status"] in {"ui_handoff", "ca_handoff"}]
    lines = [
        "# Cisco Cloud Control Doctor Report",
        "",
        f"- Organization: `{config['organization']}`",
        f"- Environment: `{config['environment']}`",
        f"- Delegated apply surfaces: {len(delegated)}",
        f"- UI/CA handoff surfaces: {len(handoffs)}",
        "- Direct Cisco Cloud Control API mutation: `false`",
        "- Secret values rendered: `false`",
        "",
        "## Required Reviews",
        "- Confirm Cisco Cloud Control entitlement and Studio access.",
        "- Confirm Cisco AI Canvas access if board templates will be used.",
        "- Review the official product integration timeline for Meraki, Catalyst Center, Nexus Dashboard, Nexus Hyperfabric, Intersight, Catalyst SD-WAN Manager, Security Cloud Control, ThousandEyes, Splunk Cloud, Collaboration Control Hub, and Cisco IQ.",
        "- Review inventory, licensing, RBAC, topology, workflows, audit logs, SSO, users, tenants, Actions, Notifications, Favorites, and support/help coverage.",
        "- If custom automation is needed, review the Cisco Workflows API OAS, target/account-key model, and rate limits before implementation.",
        "- Review Cisco Cloud Control release-note open issues before production agent use.",
        "- Confirm Splunk Platform, ITSI, and Observability Cloud prerequisites through delegated skills.",
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

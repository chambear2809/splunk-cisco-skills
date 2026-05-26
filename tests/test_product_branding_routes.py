"""Regression checks for newer product/branding routes."""

from __future__ import annotations

from tests.regression_helpers import REPO_ROOT


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_observability_new_names_are_first_class_without_dropping_old_names() -> None:
    deep_native = read("skills/splunk-observability-deep-native-workflows/SKILL.md")
    renderer = read("skills/splunk-observability-deep-native-workflows/scripts/render_workflows.py")
    browser_rum = read("skills/splunk-observability-k8s-frontend-rum-setup/SKILL.md")
    mobile_rum = read("skills/splunk-observability-mobile-rum-setup/SKILL.md")

    for term in (
        "Digital Experience Analytics",
        "DXA",
        "digital_experience_analytics",
        "Metrics Pipeline Management",
        "MPM",
        "metrics_pipeline_management",
    ):
        assert term in deep_native or term in renderer

    for old_surface in (
        "rum_session_replay",
        "rum_error_analysis",
        "rum_url_grouping",
        "rum_mobile",
        "synthetic_waterfall",
        "log_observer_chart",
    ):
        assert old_surface in renderer

    assert "dxa" in renderer
    assert "telemetry_pipeline_management" in renderer
    assert "Splunk Browser RUM" in browser_rum
    assert "Digital Experience Analytics" in browser_rum
    assert "Mobile RUM" in mobile_rum
    assert "Digital Experience" in mobile_rum
    assert "Analytics" in mobile_rum


def test_cisco_data_fabric_routes_to_existing_platform_skills() -> None:
    files = {
        "README.md",
        "skills/splunk-federated-search-setup/SKILL.md",
        "skills/splunk-edge-processor-setup/SKILL.md",
        "skills/splunk-ingest-processor-setup/SKILL.md",
        "skills/splunk-spl2-pipeline-kit/SKILL.md",
        "skills/splunk-ai-ml-toolkit-setup/SKILL.md",
        "skills/splunk-mcp-server-setup/SKILL.md",
    }
    combined = "\n".join(read(path) for path in sorted(files))

    assert "Cisco Data Fabric" in combined
    assert "Federated Search" in combined
    assert "Edge Processor" in combined
    assert "Ingest Processor" in combined
    assert "AI Toolkit" in combined
    assert "MCP" in combined

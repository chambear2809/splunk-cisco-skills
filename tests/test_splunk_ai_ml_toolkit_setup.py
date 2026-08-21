#!/usr/bin/env python3
"""Regression tests for splunk-ai-ml-toolkit-setup."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


SKILL = "skills/splunk-ai-ml-toolkit-setup/scripts/setup.sh"


def run_setup(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["bash", str(REPO_ROOT / SKILL), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_ai_ml_toolkit_render_validate_outputs_complete_tree(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--render",
        "--validate",
        "--include-dsdl",
        "--dsdl-runtime",
        "kubernetes",
        "--legacy-anomaly-audit",
        "--output-dir",
        str(output_dir),
    )

    assert "Rendered Splunk AI/ML Toolkit plan" in result.stdout
    assert "Rendered validation passed" in result.stdout

    required = [
        "coverage-report.json",
        "coverage-report.md",
        "apply-plan.json",
        "doctor-report.md",
        "dsdl-runtime-handoff.md",
        "agent-launchpad-handoff.md",
        "time-series-model-handoff.md",
        "legacy-anomaly-migration.md",
    ]
    for rel in required:
        assert (output_dir / rel).is_file(), rel

    coverage = json.loads((output_dir / "coverage-report.json").read_text())["coverage"]
    assert all(entry["status"] != "unknown" for entry in coverage)
    assert all(entry["product_stage"] != "unknown" for entry in coverage)
    assert all(entry["source_url"] for entry in coverage)
    keys = {entry["key"] for entry in coverage}
    expected = {
        "ai_toolkit.package",
        "ai_toolkit.compatibility",
        "ai_toolkit.ml_spl_commands",
        "ai_toolkit.permissions_and_safeguards",
        "ai_toolkit.assistants",
        "ai_toolkit.anomaly_cisco_deep_time_series",
        "ai_toolkit.open_cisco_time_series_model_1_0",
        "ai_toolkit.hosted_foundation_models",
        "ai_toolkit.agent_launchpad",
        "ai_toolkit.agent_launchpad_knowledge_base_connections",
        "ai_toolkit.agent_launchpad_mcp_connections",
        "ai_toolkit.agent_skills",
        "ai_toolkit.aiagent_command",
        "ai_toolkit.agent_run_history",
        "ai_toolkit.llm_ai_command",
        "ai_toolkit.connections_tab",
        "ai_toolkit.container_management",
        "ai_toolkit.onnx",
        "ai_toolkit.alerting",
        "psc.linux64",
        "psc.windows64",
        "psc.mac-intel",
        "psc.mac-arm",
        "dsdl.package",
        "dsdl.setup_page",
        "dsdl.runtime.kubernetes",
        "dsdl.api_endpoint",
        "dsdl.container_health",
        "dsdl.hec_observability",
        "legacy.legacy_anomaly_app",
        "legacy.smart_alerts_beta",
    }
    assert expected.issubset(keys)
    legacy_statuses = {
        entry["key"]: entry["status"]
        for entry in coverage
        if entry["key"].startswith("legacy.")
    }
    assert set(legacy_statuses.values()) == {"eol_migration"}


def test_ai_ml_toolkit_tracks_agent_and_time_series_product_lifecycle(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_setup(
        "--render",
        "--platform",
        "cloud",
        "--output-dir",
        str(output_dir),
    )

    payload = json.loads((output_dir / "coverage-report.json").read_text())
    assert payload["research_verified"] == "2026-08-20"
    by_key = {entry["key"]: entry for entry in payload["coverage"]}

    # aiagent/agentstatus and CDTSM left preview in AI Toolkit 6.0.0, so every
    # agent surface must render as GA. A regression back to `alpha` would tell
    # operators a shipped command does not exist.
    agent_keys = {
        "ai_toolkit.agent_launchpad",
        "ai_toolkit.agent_launchpad_knowledge_base_connections",
        "ai_toolkit.agent_launchpad_mcp_connections",
        "ai_toolkit.agent_skills",
        "ai_toolkit.aiagent_command",
        "ai_toolkit.agent_run_history",
    }
    assert {by_key[key]["product_stage"] for key in agent_keys} == {"ga"}
    assert {by_key[key]["status"] for key in agent_keys} == {"manual_handoff"}
    assert all("alpha" not in by_key[key]["summary"].lower() for key in agent_keys)
    assert all("private preview" not in by_key[key]["summary"].lower() for key in agent_keys)
    assert by_key["ai_toolkit.open_cisco_time_series_model_1_0"]["product_stage"] == "available"
    assert by_key["ai_toolkit.anomaly_cisco_deep_time_series"]["product_stage"] == "ga"
    assert "CDTSM is a separate" in by_key["ai_toolkit.hosted_foundation_models"]["summary"]
    assert "6.0.2" in by_key["ai_toolkit.package"]["summary"]
    assert "4.3.4" in by_key["ai_toolkit.compatibility"]["summary"]

    commands = by_key["ai_toolkit.ml_spl_commands"]["summary"]
    for command in ("aiagent", "agentstatus", "externalendpointinventory", "mltkmanage"):
        assert command in commands

    agent_handoff = (output_dir / "agent-launchpad-handoff.md").read_text()
    assert "Agent Launchpad" in agent_handoff
    assert "generally available" in agent_handoff
    for stale in ("Alpha/private preview", "ai_agent_run_history_index", "Fall 2026", "25 invocations"):
        assert stale not in agent_handoff, f"handoff still claims {stale!r}"
    assert "not Cisco Cloud Control Studio Agent Builder" in agent_handoff
    assert "`edit_agent_connections`" in agent_handoff
    assert "`run_agents`" in agent_handoff
    assert "`aiagent`" in agent_handoff
    assert "apiAllowlistIP" in agent_handoff
    assert "agent_run_index" in agent_handoff

    time_series_handoff = (output_dir / "time-series-model-handoff.md").read_text()
    assert "`available` open-weight release" in time_series_handoff
    assert "`Apache-2.0`" in time_series_handoff
    assert "`ga` since AI Toolkit `6.0.0`" in time_series_handoff
    assert "apply CDTSM" in time_series_handoff
    assert "separately governed layers" in time_series_handoff

    plan = json.loads((output_dir / "apply-plan.json").read_text())
    sections = {step["section"] for step in plan["steps"]}
    assert "agent-launchpad" not in sections
    assert "ctsm" not in sections
    assert "cdtsm" not in sections


def test_ai_ml_toolkit_agent_launchpad_routes_enterprise_through_cloud_connect(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_setup(
        "--render",
        "--platform",
        "enterprise",
        "--output-dir",
        str(output_dir),
    )

    coverage = json.loads((output_dir / "coverage-report.json").read_text())["coverage"]
    agent_entries = [entry for entry in coverage if entry["key"].startswith("ai_toolkit.agent_")]
    agent_entries.append(next(entry for entry in coverage if entry["key"] == "ai_toolkit.aiagent_command"))
    assert agent_entries
    assert {entry["product_stage"] for entry in agent_entries} == {"ga"}
    assert {entry["status"] for entry in agent_entries} == {"manual_handoff"}

    launchpad = next(entry for entry in coverage if entry["key"] == "ai_toolkit.agent_launchpad")
    assert launchpad["source_url"].endswith("agent-launchpad-for-on-premises-users")

    agent_handoff = (output_dir / "agent-launchpad-handoff.md").read_text()
    assert "Splunk Cloud Connect" in agent_handoff
    assert "## Splunk Enterprise Gate" in agent_handoff


def test_ai_ml_toolkit_apply_plan_orders_psc_ai_toolkit_then_dsdl(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_setup(
        "--render",
        "--include-dsdl",
        "--psc-target",
        "mac-arm",
        "--output-dir",
        str(output_dir),
    )

    plan = json.loads((output_dir / "apply-plan.json").read_text())
    delegated = [step for step in plan["steps"] if step["automation"] == "delegated"]
    assert [step["app_id"] for step in delegated] == ["6785", "2890", "4607"]
    joined = "\n".join(" ".join(step["command"]) for step in delegated)
    assert "splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 6785 --update" in joined
    assert "--app-version" not in joined
    assert " --token " not in f" {joined} "
    assert " --password " not in f" {joined} "


def test_ai_ml_toolkit_install_dry_run_uses_delegated_install_commands(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_setup(
        "--install",
        "--dry-run",
        "--psc-target",
        "windows64",
        "--include-dsdl",
        "--output-dir",
        str(output_dir),
    )

    lines = [line for line in result.stdout.splitlines() if line.startswith("DRY-RUN:")]
    assert len(lines) == 3
    assert "--app-id 2883" in lines[0]
    assert "--app-id 2890" in lines[1]
    assert "--app-id 4607" in lines[2]


def test_ai_ml_toolkit_rejects_direct_secret_flags() -> None:
    result = run_setup("--render", "--token", "abc123", check=False)
    assert result.returncode != 0
    assert "would expose a secret" in result.stdout + result.stderr


def test_ai_ml_toolkit_registry_metadata_tracks_current_apps() -> None:
    registry = json.loads((REPO_ROOT / "skills/shared/app_registry.json").read_text())
    apps = {
        app["splunkbase_id"]: app
        for app in registry["apps"]
        if app.get("skill") == "splunk-ai-ml-toolkit-setup"
    }

    assert apps["2890"]["app_name"] == "Splunk_ML_Toolkit"
    assert apps["2890"]["latest_verified_version"] == "6.0.2"
    assert apps["2882"]["app_name"] == "Splunk_SA_Scientific_Python_linux_x86_64"
    assert apps["2883"]["app_name"] == "Splunk_SA_Scientific_Python_windows_x86_64"
    assert apps["2881"]["app_name"] == "Splunk_SA_Scientific_Python_darwin_x86_64"
    assert apps["6785"]["app_name"] == "Splunk_SA_Scientific_Python_darwin_arm64"
    assert apps["4607"]["app_name"] == "mltk-container"
    assert apps["4607"]["install_requires"] == ["2890"]


def test_ai_ml_toolkit_docs_are_derived_from_the_verified_package() -> None:
    """The 6.0.2 derivation must not leave 5.7.4-era paths or the gap notice behind.

    The renderer, SKILL.md, and reference.md previously described 5.7.4 while
    the registry pin had already advanced. A stale version-pathed help.splunk.com
    URL sends operators to documentation for a release they are not running, and
    the 5.6.4 Agent Builder preview path now 404s outright.
    """
    skill_dir = REPO_ROOT / "skills/splunk-ai-ml-toolkit-setup"
    tracked = [
        skill_dir / "SKILL.md",
        skill_dir / "reference.md",
        skill_dir / "scripts/render_assets.py",
        skill_dir / "template.example",
    ]
    for path in tracked:
        text = path.read_text(encoding="utf-8")
        for stale in ("use-ai-toolkit/5.7.4", "use-ai-toolkit/5.6.4", "feature-preview-cisco-deep-time-series-model"):
            assert stale not in text, f"{path.name} still references {stale}"
        assert "Derivation Gap" not in text, f"{path.name} still carries the derivation-gap notice"
        assert "ai_agent_run_history_index" not in text, f"{path.name} still requires the preview run-history index"

    reference = (skill_dir / "reference.md").read_text(encoding="utf-8")
    # reference.md is hard-wrapped, so compare against a single-space form.
    unwrapped = " ".join(reference.split())
    assert "`6.0.2`, August 10, 2026" in unwrapped
    assert "`6.0.2` requires PSC `4.3.4` on Python `3.13`" in unwrapped
    assert "agent-launchpad-for-on-premises-users" in reference
    assert "6.0.2/ai-toolkit-connections-containers-and-agents/connections-in-the-ai-toolkit" in reference
    for command in ("agentstatus", "externalendpointinventory", "kvstorelookup", "logexperiment", "mltkmanage"):
        assert f"`{command}`" in reference


def test_security_portfolio_routes_mltk_dsdl_and_anomaly_to_ai_ml_skill() -> None:
    for product, expected_args in {
        "mltk": [],
        "dsdl": ["--include-dsdl"],
        "anomaly detection": ["--legacy-anomaly-audit"],
        "anomaly detection assistant": ["--legacy-anomaly-audit"],
    }.items():
        result = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "skills/splunk-security-portfolio-setup/scripts/setup.sh"),
                "--product",
                product,
                "--json",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["entry"]["route"] == ["splunk-ai-ml-toolkit-setup"]
        assert "skills/splunk-ai-ml-toolkit-setup/scripts/setup.sh" in " ".join(payload["route_command"])
        for arg in expected_args:
            assert arg in payload["route_command"]

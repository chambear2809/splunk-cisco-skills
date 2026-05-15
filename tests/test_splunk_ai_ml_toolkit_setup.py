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
        "--json",
    )

    assert '"api_version": "splunk-ai-ml-toolkit-setup/v1"' in result.stdout
    assert "Rendered validation passed" in result.stdout

    required = [
        "coverage-report.json",
        "coverage-report.md",
        "apply-plan.json",
        "doctor-report.md",
        "dsdl-runtime-handoff.md",
        "legacy-anomaly-migration.md",
    ]
    for rel in required:
        assert (output_dir / rel).is_file(), rel

    coverage = json.loads((output_dir / "coverage-report.json").read_text())["coverage"]
    assert all(entry["status"] != "unknown" for entry in coverage)
    assert all(entry["source_url"] for entry in coverage)
    keys = {entry["key"] for entry in coverage}
    expected = {
        "ai_toolkit.package",
        "ai_toolkit.compatibility",
        "ai_toolkit.ml_spl_commands",
        "ai_toolkit.permissions_and_safeguards",
        "ai_toolkit.assistants",
        "ai_toolkit.anomaly_cisco_deep_time_series",
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
    assert apps["2890"]["latest_verified_version"] == "5.7.3"
    assert apps["2882"]["app_name"] == "Splunk_SA_Scientific_Python_linux_x86_64"
    assert apps["2883"]["app_name"] == "Splunk_SA_Scientific_Python_windows_x86_64"
    assert apps["2881"]["app_name"] == "Splunk_SA_Scientific_Python_darwin_x86_64"
    assert apps["6785"]["app_name"] == "Splunk_SA_Scientific_Python_darwin_arm64"
    assert apps["4607"]["app_name"] == "mltk-container"
    assert apps["4607"]["install_requires"] == ["2890"]


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

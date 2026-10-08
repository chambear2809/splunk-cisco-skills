"""Regression tests for Monitoring Console mode boundaries."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "skills/splunk-monitoring-console-setup/scripts/setup.sh"


def render(tmp_path: Path, mode: str, enterprise_version: str | None = None) -> Path:
    version_args = [] if enterprise_version is None else ["--enterprise-version", enterprise_version]
    result = subprocess.run(
        [
            "bash", str(SETUP), "--mode", mode, "--phase", "render",
            "--output-dir", str(tmp_path), "--splunk-home",
            "/opt/splunk-10.6-lab-core-20261005", "--enable-auto-config", "true",
            "--enable-forwarder-monitoring", "false", "--enable-platform-alerts", "false",
            "--restart-splunk", "true",
            *version_args,
        ], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return tmp_path / "monitoring-console"


def test_standalone_omits_invalid_mc_auto_config_setting(tmp_path: Path) -> None:
    assets = (render(tmp_path, "standalone") / "splunk_monitoring_console_assets.conf").read_text()
    assert "mc_auto_config =" not in assets


def test_distributed_omits_removed_mc_auto_config_setting(tmp_path: Path) -> None:
    assets = (render(tmp_path, "distributed") / "splunk_monitoring_console_assets.conf").read_text()
    assert "mc_auto_config =" not in assets


def test_legacy_104_retains_mc_auto_config_setting(tmp_path: Path) -> None:
    assets = (render(tmp_path, "distributed", "10.4.1") / "splunk_monitoring_console_assets.conf").read_text()
    assert "mc_auto_config = enabled" in assets


def test_rendered_scripts_enforce_expected_installed_version(tmp_path: Path) -> None:
    rendered = render(tmp_path, "standalone", "10.6.0.5")
    apply = (rendered / "apply.sh").read_text()
    assert 'expected_version=10.6.0.5' in apply
    assert 'rendered assets expect Splunk Enterprise' in apply

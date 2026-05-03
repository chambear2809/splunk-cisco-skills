"""Regressions for splunk-observability-cisco-nexus-integration rendering."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-cisco-nexus-integration/scripts/setup.sh"


def run_setup(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def rendered_text(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def write_spec(path: Path, **overrides: object) -> Path:
    spec: dict[str, object] = {
        "api_version": "splunk-observability-cisco-nexus-integration/v1",
        "realm": "us0",
        "cluster_name": "lab-cluster",
        "distribution": "kubernetes",
        "ssh_secret": {
            "name": "cisco-nexus-ssh",
            "namespace": "splunk-otel",
            "username_key": "username",
            "password_key": "password",
            "key_file_key": "",
        },
        "devices": [
            {"name": "core-switch-01", "host": "192.168.1.10", "port": 22},
            {"name": "core-switch-02", "host": "192.168.1.11", "port": 22},
        ],
        "scrapers": {
            "system": {"enabled": True, "metrics": {}},
            "interfaces": {"enabled": True, "metrics": {}},
        },
        "collection_interval": 60,
        "timeout": 30,
        "dashboards": {"enabled": True},
        "detectors": {"enabled": True, "thresholds": {}},
        "handoffs": {"base_collector": True, "dashboard_builder": True, "native_ops": True},
    }
    spec.update(overrides)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return path


def test_render_produces_cisco_os_overlay(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--validate", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    for f in (
        "splunk-otel-overlay/values.overlay.yaml",
        "secrets/cisco-nexus-ssh-secret.yaml",
        "dashboards/cisco-nexus-overview.signalflow.yaml",
        "scripts/handoff-base-collector.sh",
        "scripts/handoff-dashboards.sh",
        "scripts/handoff-detectors.sh",
        "metadata.json",
    ):
        assert (output / f).is_file(), f"Missing rendered file: {f}"
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    # cisco_os receiver lives under clusterReceiver (not agent) so each device
    # is scraped exactly once.
    assert "clusterReceiver" in overlay
    assert "cisco_os:" in overlay
    assert "metrics/cisco-os-metrics" in overlay
    # SSH credentials must be env-var placeholders, not inline.
    assert "${env:CISCO_NEXUS_SSH_USERNAME}" in overlay
    assert "${env:CISCO_NEXUS_SSH_PASSWORD}" in overlay


def test_devices_from_cli_override_spec(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", devices=[])
    result = run_setup(
        "--render",
        "--spec",
        str(spec),
        "--nexus-device",
        "core-switch-99:10.0.0.99:22",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    assert "core-switch-99" in overlay
    assert "10.0.0.99" in overlay
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["device_count"] == 1


def test_secret_manifest_is_placeholders_only(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    secret = (output / "secrets/cisco-nexus-ssh-secret.yaml").read_text(encoding="utf-8")
    assert "PLACEHOLDER_USERNAME" in secret
    assert "PLACEHOLDER_PASSWORD" in secret


@pytest.mark.parametrize(
    "flag", ["--o11y-token", "--access-token", "--token", "--bearer-token", "--api-token", "--sf-token"]
)
def test_direct_secret_flags_are_rejected(flag: str, tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), flag, "INLINE_SHOULD_NOT_LEAK")
    assert result.returncode == 1
    assert "--o11y-token-file" in combined_output(result)
    assert "INLINE_SHOULD_NOT_LEAK" not in combined_output(result)


def test_idempotent_re_render(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    args = ["--render", "--spec", str(spec), "--output-dir", str(output)]
    first = run_setup(*args)
    second = run_setup(*args)
    assert first.returncode == 0, combined_output(first)
    assert second.returncode == 0, combined_output(second)
    first_overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    assert (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8") == first_overlay

"""Regressions for cisco-isovalent-platform-setup rendering."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/cisco-isovalent-platform-setup/scripts/setup.sh"


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


def write_spec(path: Path, **overrides: object) -> Path:
    spec: dict[str, object] = {
        "api_version": "cisco-isovalent-platform-setup/v1",
        "edition": "oss",
        "cluster_name": "lab-cluster",
        "namespaces": {
            "cilium": "kube-system",
            "tetragon": "tetragon",
        },
        "tetragon": {
            "export": {"mode": "file", "directory": "/var/run/cilium/tetragon", "filename": "tetragon.log"},
        },
        "tracing_policy": {"enabled": True, "name": "network-monitoring"},
    }
    spec.update(overrides)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return path


def test_oss_render_produces_helm_values_and_install_scripts(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--validate", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    for f in (
        "helm/cilium-values.yaml",
        "helm/tetragon-values.yaml",
        "helm/tracing-policy.yaml",
        "scripts/install-cilium.sh",
        "scripts/install-tetragon.sh",
        "scripts/preflight.sh",
        "metadata.json",
    ):
        assert (output / f).is_file(), f"Missing rendered file: {f}"
    install_cilium = (output / "scripts/install-cilium.sh").read_text(encoding="utf-8")
    # OSS edition uses cilium/cilium chart from helm.cilium.io.
    assert "helm.cilium.io" in install_cilium
    assert "cilium/cilium" in install_cilium
    # Enterprise chart name must NOT appear in OSS render.
    assert "isovalent/cilium-enterprise" not in install_cilium


def test_enterprise_render_uses_isovalent_charts(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json", edition="enterprise")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    install_cilium = (output / "scripts/install-cilium.sh").read_text(encoding="utf-8")
    assert "helm.isovalent.com" in install_cilium
    assert "isovalent/cilium-enterprise" in install_cilium


def test_tetragon_default_export_mode_file(tmp_path: Path) -> None:
    """Default Tetragon export mode is `file` -- coordinates with the integration skill."""
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    tetragon = (output / "helm/tetragon-values.yaml").read_text(encoding="utf-8")
    assert "exportDirectory: /var/run/cilium/tetragon" in tetragon
    assert "exportFilename: tetragon.log" in tetragon


def test_legacy_fluentd_emits_deprecation_warning(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render",
        "--spec",
        str(spec),
        "--export-mode",
        "fluentd",
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    warnings = " ".join(metadata.get("warnings", []))
    assert "DEPRECATED" in warnings
    assert "2025-06-24" in warnings


@pytest.mark.parametrize("flag", ["--license", "--license-key", "--pull-secret"])
def test_direct_secret_flags_are_rejected(flag: str) -> None:
    result = run_setup("--render", flag, "INLINE_SHOULD_NOT_LEAK")
    assert result.returncode == 1
    assert "isovalent" in combined_output(result).lower()
    assert "INLINE_SHOULD_NOT_LEAK" not in combined_output(result)


def test_idempotent_re_render(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    args = ["--render", "--spec", str(spec), "--output-dir", str(output)]
    first = run_setup(*args)
    second = run_setup(*args)
    assert first.returncode == 0, combined_output(first)
    assert second.returncode == 0, combined_output(second)
    first_cilium = (output / "helm/cilium-values.yaml").read_text(encoding="utf-8")
    assert (output / "helm/cilium-values.yaml").read_text(encoding="utf-8") == first_cilium


def test_dry_run_json(tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--dry-run", "--json", "--output-dir", str(tmp_path / "rendered"))
    assert result.returncode == 0, combined_output(result)
    plan = json.loads(result.stdout)
    assert plan["skill"] == "cisco-isovalent-platform-setup"
    assert plan["edition"] == "oss"

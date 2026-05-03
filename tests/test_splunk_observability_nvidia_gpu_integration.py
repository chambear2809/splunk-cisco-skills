"""Regressions for splunk-observability-nvidia-gpu-integration rendering."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-nvidia-gpu-integration/scripts/setup.sh"


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
        "api_version": "splunk-observability-nvidia-gpu-integration/v1",
        "realm": "us0",
        "cluster_name": "lab-cluster",
        "distribution": "kubernetes",
        "receiver_creator_name": "dcgm-cisco",
        "dcgm": {"port": 9400, "scrape_interval_seconds": 10, "metrics_path": "/metrics"},
        "filter": {"mode": "none", "extra_metrics": []},
        "enable_dcgm_pod_labels": False,
        "dcgm_namespace": "nvidia-gpu-operator",
        "dcgm_service_account": "nvidia-dcgm-exporter",
        "dashboards": {"enabled": True},
        "detectors": {"enabled": True, "thresholds": {}},
        "handoffs": {"base_collector": True, "dashboard_builder": True, "native_ops": True},
    }
    spec.update(overrides)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return path


def test_render_uses_dcgm_cisco_receiver_creator_not_nvidia(tmp_path: Path) -> None:
    """CRITICAL: must use receiver_creator/dcgm-cisco to avoid chart autodetect collision."""
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--validate", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    assert "receiver_creator/dcgm-cisco:" in overlay
    assert "receiver_creator/nvidia:" not in overlay


def test_renderer_rejects_receiver_creator_named_nvidia() -> None:
    """The renderer fails fast if the operator passes --receiver-creator-name nvidia."""
    result = run_setup("--render", "--receiver-creator-name", "nvidia")
    assert result.returncode == 1
    assert "collide" in combined_output(result).lower() or "collides" in combined_output(result).lower()


def test_dual_label_discovery_rule(tmp_path: Path) -> None:
    """Discovery must match BOTH `app` and `app.kubernetes.io/name`.

    YAML safe_dump line-wraps the rule string, so collapse whitespace
    before substring matching.
    """
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    collapsed = " ".join(overlay.split())
    assert 'labels["app"] == "nvidia-dcgm-exporter"' in collapsed
    assert 'labels["app.kubernetes.io/name"] == "nvidia-dcgm-exporter"' in collapsed


def test_dcgm_pod_labels_patch_when_enabled(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render",
        "--enable-dcgm-pod-labels",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    for f in (
        "dcgm-pod-labels-patch/01-cluster-role.yaml",
        "dcgm-pod-labels-patch/02-cluster-role-binding.yaml",
        "dcgm-pod-labels-patch/03-service-account-automount.yaml",
        "dcgm-pod-labels-patch/04-daemonset-env-patch.yaml",
        "scripts/apply-dcgm-pod-labels-patch.sh",
    ):
        assert (output / f).is_file(), f"Missing patch file: {f}"
    daemonset = (output / "dcgm-pod-labels-patch/04-daemonset-env-patch.yaml").read_text(encoding="utf-8")
    assert "DCGM_EXPORTER_KUBERNETES_ENABLE_POD_LABELS" in daemonset
    assert "DCGM_EXPORTER_KUBERNETES_ENABLE_POD_UID" in daemonset


def test_filter_strict_renders_canonical_allowlist(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--filter", "strict", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    assert "filter/dcgm_strict" in overlay
    # Canonical signalfx allow-list keys.
    assert "DCGM_FI_DEV_GPU_UTIL" in overlay
    assert "DCGM_FI_PROF_PCIE_TX_BYTES" in overlay


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

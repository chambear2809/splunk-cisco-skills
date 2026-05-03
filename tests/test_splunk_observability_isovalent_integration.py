"""Regressions for splunk-observability-isovalent-integration rendering."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-isovalent-integration/scripts/setup.sh"


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
        "api_version": "splunk-observability-isovalent-integration/v1",
        "realm": "us0",
        "cluster_name": "lab-cluster",
        "distribution": "kubernetes",
        "splunk_platform": {
            "enabled": True,
            "index": "cisco_isovalent",
            "sourcetype": "cisco:isovalent",
        },
        "tetragon_export": {
            "mode": "file",
            "host_path": "/var/run/cilium/tetragon",
            "filename_pattern": "*.log",
        },
        "scrape": {
            "cilium_agent_9962": True,
            "hubble_metrics_9965": True,
            "cilium_envoy_9964": True,
            "cilium_operator_9963": True,
            "tetragon_2112": True,
            "tetragon_operator_2113": True,
        },
        "dashboards": {"enabled": True},
        "detectors": {"enabled": True, "thresholds": {}},
        "handoffs": {
            "base_collector": True,
            "hec_service": True,
            "cisco_security_cloud": True,
            "dashboard_builder": True,
            "native_ops": True,
        },
    }
    spec.update(overrides)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return path


def test_render_produces_overlay_and_handoffs(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--validate", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    for f in (
        "splunk-otel-overlay/values.overlay.yaml",
        "scripts/handoff-base-collector.sh",
        "scripts/handoff-hec-token.sh",
        "scripts/handoff-cisco-security-cloud.sh",
        "scripts/handoff-dashboards.sh",
        "scripts/handoff-detectors.sh",
        "scripts/scrub-tokens.py",
        "metadata.json",
    ):
        assert (output / f).is_file(), f"Missing rendered file: {f}"
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    assert "prometheus/isovalent_cilium" in overlay
    assert "prometheus/isovalent_hubble" in overlay
    assert "prometheus/isovalent_tetragon" in overlay
    assert "filter/includemetrics" in overlay


def test_default_file_path_renders_extra_file_logs_aligned_with_hostpath(tmp_path: Path) -> None:
    """The hostPath mount and extraFileLogs include glob must reference the same directory."""
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--validate", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    overlay = (output / "splunk-otel-overlay/values.overlay.yaml").read_text(encoding="utf-8")
    assert "extraVolumes" in overlay
    assert "/var/run/cilium/tetragon" in overlay
    assert "filelog/tetragon" in overlay
    assert "com.splunk.sourcetype: cisco:isovalent" in overlay
    assert "com.splunk.index: cisco_isovalent" in overlay


def test_legacy_fluentd_warns(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup(
        "--render",
        "--legacy-fluentd-hec",
        "--spec",
        str(spec),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    warnings = " ".join(metadata.get("warnings", []))
    assert "DEPRECATED" in warnings


def test_handoff_to_hec_uses_correct_token_name_flag(tmp_path: Path) -> None:
    """Regression: splunk-hec-service-setup uses --token-name, not --hec-token-name.

    The Isovalent integration emits handoff-hec-token.sh that the operator runs to
    provision a Splunk Platform HEC token for cisco_isovalent-index events. If this
    handoff scripts the wrong flag, the operator's hand-off command fails.
    """
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    handoff = (output / "scripts/handoff-hec-token.sh").read_text(encoding="utf-8")
    assert "--token-name " in handoff
    assert "--platform " in handoff
    assert "--default-index " in handoff
    assert "--allowed-indexes " in handoff
    assert "--hec-token-name" not in handoff


def test_handoff_to_dashboards_uses_spec_flag(tmp_path: Path) -> None:
    """Regression: splunk-observability-dashboard-builder uses --spec, not --import-json.

    Earlier the Isovalent handoff emitted --import-json which is not a flag of
    splunk-observability-dashboard-builder/scripts/setup.sh. Operator running
    the handoff verbatim got "Unknown option: --import-json".
    """
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    handoff = (output / "scripts/handoff-dashboards.sh").read_text(encoding="utf-8")
    assert "--spec " in handoff
    assert "--token-file " in handoff
    assert "--realm " in handoff
    assert "--import-json" not in handoff


def test_handoff_to_cisco_security_cloud(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    handoff = (output / "scripts/handoff-cisco-security-cloud.sh").read_text(encoding="utf-8")
    # cisco-security-cloud-setup uses two scripts: setup.sh --install for the app,
    # then configure_input.sh --input-type sbg_isovalent_input for the Isovalent
    # input. There is no --product flag.
    assert "cisco-security-cloud-setup/scripts/setup.sh --install" in handoff
    assert "cisco-security-cloud-setup/scripts/configure_input.sh" in handoff
    assert "--input-type sbg_isovalent_input" in handoff
    # The default index for Isovalent Runtime Security must align with the
    # Cisco Security Cloud App Splunk Threat Research Team detection scope.
    assert "cisco_isovalent" in handoff
    # Negative: confirm we do NOT emit the legacy/wrong --product flag that was
    # never a valid cisco-security-cloud-setup CLI argument.
    assert "--product isovalent" not in handoff


@pytest.mark.parametrize(
    "flag",
    [
        "--access-token",
        "--token",
        "--bearer-token",
        "--api-token",
        "--o11y-token",
        "--sf-token",
        "--platform-hec-token",
        "--hec-token",
    ],
)
def test_direct_secret_flags_are_rejected(flag: str, tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), flag, "INLINE_SHOULD_NOT_LEAK")
    assert result.returncode == 1
    assert "-token-file" in combined_output(result)
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

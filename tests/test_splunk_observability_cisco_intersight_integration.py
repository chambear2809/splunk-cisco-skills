"""Regressions for splunk-observability-cisco-intersight-integration rendering."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-cisco-intersight-integration/scripts/setup.sh"
VALIDATE = REPO_ROOT / "skills/splunk-observability-cisco-intersight-integration/scripts/validate.sh"


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
        "api_version": "splunk-observability-cisco-intersight-integration/v1",
        "realm": "us0",
        "cluster_name": "lab-cluster",
        "distribution": "kubernetes",
        "intersight_otel": {
            "namespace": "intersight-otel",
            "secret_name": "intersight-api-credentials",
            "key_id_secret_key": "intersight-key-id",
            "key_pem_secret_key": "intersight-key",
            "image": "ghcr.io/intersight/intersight-otel:latest",
        },
        "collector": {
            "release": "splunk-otel-collector",
            "namespace": "splunk-otel",
            "otlp_port": 4317,
        },
        "collection_interval": 60,
        "dashboards": {"enabled": True},
        "detectors": {"enabled": True, "thresholds": {}},
        "handoffs": {"base_collector": True, "dashboard_builder": True, "native_ops": True},
    }
    spec.update(overrides)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return path


def test_render_produces_intersight_manifests(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--validate", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    for f in (
        "intersight-integration/intersight-otel-namespace.yaml",
        "intersight-integration/intersight-credentials-secret.yaml",
        "intersight-integration/intersight-otel-config.yaml",
        "intersight-integration/intersight-otel-deployment.yaml",
        "splunk-otel-overlay/intersight-pipeline.yaml",
        "scripts/apply-intersight-manifests.sh",
        "metadata.json",
    ):
        assert (output / f).is_file(), f"Missing rendered file: {f}"


def test_otlp_endpoint_matches_chart_service_shape(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    config = (output / "intersight-integration/intersight-otel-config.yaml").read_text(encoding="utf-8")
    # Service name follows the Splunk OTel chart's <release>-splunk-otel-collector-agent.<ns> form.
    assert "splunk-otel-collector-agent.splunk-otel.svc.cluster.local:4317" in config


def test_secret_stub_uses_placeholders(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    secret = (output / "intersight-integration/intersight-credentials-secret.yaml").read_text(encoding="utf-8")
    assert "PLACEHOLDER_INTERSIGHT_KEY_ID" in secret
    assert "PLACEHOLDER_PRIVATE_KEY_PEM_CONTENT" in secret


def test_apply_script_refuses_when_secret_missing(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), "--output-dir", str(output))
    assert result.returncode == 0, combined_output(result)
    apply_script = (output / "scripts/apply-intersight-manifests.sh").read_text(encoding="utf-8")
    # Apply script must fail loudly if the operator forgot to create the Secret.
    assert "Secret 'intersight-api-credentials' not found" in apply_script
    assert "kubectl apply" in apply_script


@pytest.mark.parametrize(
    "flag",
    [
        "--intersight-key-id",
        "--intersight-key",
        "--api-key",
        "--client-secret",
        "--o11y-token",
        "--access-token",
        "--token",
        "--bearer-token",
        "--api-token",
        "--sf-token",
    ],
)
def test_direct_secret_flags_are_rejected(flag: str, tmp_path: Path) -> None:
    spec = write_spec(tmp_path / "spec.json")
    result = run_setup("--render", "--spec", str(spec), flag, "INLINE_SHOULD_NOT_LEAK")
    assert result.returncode == 1
    assert "INLINE_SHOULD_NOT_LEAK" not in combined_output(result)


def test_idempotent_re_render(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    spec = write_spec(tmp_path / "spec.json")
    args = ["--render", "--spec", str(spec), "--output-dir", str(output)]
    first = run_setup(*args)
    second = run_setup(*args)
    assert first.returncode == 0, combined_output(first)
    assert second.returncode == 0, combined_output(second)
    first_deploy = (output / "intersight-integration/intersight-otel-deployment.yaml").read_text(encoding="utf-8")
    assert (output / "intersight-integration/intersight-otel-deployment.yaml").read_text(encoding="utf-8") == first_deploy


def test_live_validate_prefers_oc_and_catches_otlp_metrics_service_error() -> None:
    script = VALIDATE.read_text(encoding="utf-8")
    assert "command -v oc" in script
    assert "unknown service opentelemetry.proto.collector.metrics.v1.MetricsService" in script
    assert "service.pipelines.metrics.receivers" in script

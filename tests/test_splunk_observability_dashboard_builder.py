"""Regressions for Splunk Observability dashboard builder rendering."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-observability-dashboard-builder/scripts/setup.sh"
EXAMPLE_SPEC = (
    REPO_ROOT / "skills/splunk-observability-dashboard-builder/templates/dashboard.example.json"
)
EXAMPLE_YAML_SPEC = (
    REPO_ROOT / "skills/splunk-observability-dashboard-builder/templates/dashboard.example.yaml"
)
SCRIPT_DIR = REPO_ROOT / "skills/splunk-observability-dashboard-builder/scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from o11y_dashboard_api import normalize_metric_query  # noqa: E402


def run_setup(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def rendered_text(root: Path) -> str:
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_metric_discovery_normalizes_simple_bare_terms() -> None:
    assert normalize_metric_query("latency") == "sf_metric:*latency*"
    assert normalize_metric_query("kubeproxy_sync_proxy_rules_duration_seconds") == (
        "sf_metric:*kubeproxy_sync_proxy_rules_duration_seconds*"
    )
    assert normalize_metric_query("sf_metric:*latency*") == "sf_metric:*latency*"


def test_example_spec_renders_classic_api_payloads(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"

    result = run_setup("--render", "--spec", str(EXAMPLE_SPEC), "--output-dir", str(output_dir))

    assert result.returncode == 0, result.stdout
    assert (output_dir / "dashboardgroup.json").is_file()
    assert (output_dir / "dashboard.json").is_file()
    assert (output_dir / "apply-plan.json").is_file()
    chart_files = sorted((output_dir / "charts").glob("*.json"))
    assert len(chart_files) == 4

    dashboard = json.loads((output_dir / "dashboard.json").read_text(encoding="utf-8"))
    assert dashboard["groupId"] == "${dashboard_group_id}"
    assert dashboard["charts"][0]["chartId"] == "${chart:latency-p95}"

    request_rate = json.loads((output_dir / "charts/03-request-rate.json").read_text(encoding="utf-8"))
    assert request_rate["options"]["publishLabelOptions"][0]["label"] == "requests"
    assert request_rate["options"]["publishLabelOptions"][0]["valueSuffix"] == "req/s"


def test_json_example_renders_with_system_python_without_pyyaml(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = subprocess.run(
        [
            "python3",
            str(SCRIPT_DIR / "render_dashboard.py"),
            "--spec",
            str(EXAMPLE_SPEC),
            "--output-dir",
            str(output_dir),
            "--json",
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert (output_dir / "dashboard.json").is_file()


def test_yaml_example_still_valid_when_pyyaml_is_available() -> None:
    pytest.importorskip("yaml")

    result = run_setup("--validate", "--spec", str(EXAMPLE_YAML_SPEC), "--json")

    assert result.returncode == 0, result.stdout


def test_rendered_assets_never_include_token_values(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    secret = "O11Y_DASHBOARD_SECRET_SHOULD_NOT_RENDER"
    token_file = tmp_path / "token"
    token_file.write_text(secret, encoding="utf-8")

    result = run_setup(
        "--render",
        "--spec",
        str(EXAMPLE_SPEC),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stdout
    assert secret not in rendered_text(output_dir)
    assert str(token_file) not in rendered_text(output_dir)


def test_direct_token_flags_are_rejected() -> None:
    result = run_setup("--discover-metrics", "--realm", "us0", "--token", "inline")

    assert result.returncode == 1
    assert "--token-file" in result.stdout
    assert "process listings" in result.stdout


def test_classic_mode_rejects_modern_only_features(tmp_path: Path) -> None:
    spec = tmp_path / "modern-feature.json"
    spec.write_text(
        json.dumps(
            {
                "mode": "classic-api",
                "dashboard_group": {"name": "Modern features"},
                "dashboard": {"name": "Bad classic dashboard"},
                "sections": [{"name": "APM"}],
                "charts": [
                    {
                        "id": "requests",
                        "name": "Requests",
                        "type": "TimeSeriesChart",
                        "program_text": "data('service.requests').publish(label='requests')",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_setup("--validate", "--spec", str(spec))

    assert result.returncode == 1
    assert "sections is a modern-dashboard-only feature" in result.stdout


def test_classic_mode_rejects_documented_but_unverified_chart_types(tmp_path: Path) -> None:
    spec = tmp_path / "unverified-chart.json"
    spec.write_text(
        json.dumps(
            {
                "mode": "classic-api",
                "dashboard_group": {"name": "Chart coverage"},
                "dashboard": {"name": "Unsupported chart"},
                "charts": [
                    {
                        "id": "events",
                        "name": "Recent events",
                        "type": "event_feed",
                        "program_text": "data('sf.org.numEvents').publish(label='events')",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_setup("--validate", "--spec", str(spec))

    assert result.returncode == 1
    assert "documented product chart types" in result.stdout
    assert "verified classic /v2/chart schema" in result.stdout


def test_chart_name_is_required(tmp_path: Path) -> None:
    spec = tmp_path / "missing-chart-name.json"
    spec.write_text(
        json.dumps(
            {
                "mode": "classic-api",
                "dashboard_group": {"name": "Bad chart"},
                "dashboard": {"name": "Bad chart"},
                "charts": [
                    {
                        "id": "requests",
                        "type": "TimeSeriesChart",
                        "program_text": "data('service.requests').publish(label='requests')",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_setup("--validate", "--spec", str(spec))

    assert result.returncode == 1
    assert "charts[0].name is required" in result.stdout


def test_render_refuses_to_clean_non_rendered_output_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "important"
    output_dir.mkdir()
    (output_dir / "keep.txt").write_text("do not delete", encoding="utf-8")

    result = run_setup("--render", "--spec", str(EXAMPLE_SPEC), "--output-dir", str(output_dir))

    assert result.returncode == 1
    assert "Refusing to clean non-rendered output directory" in result.stdout
    assert (output_dir / "keep.txt").read_text(encoding="utf-8") == "do not delete"


def test_advisory_mode_allows_modern_only_feature_notes(tmp_path: Path) -> None:
    spec = tmp_path / "modern-advisory.json"
    spec.write_text(
        json.dumps(
            {
                "mode": "modern-ui-advisory",
                "dashboard": {"name": "APM operations"},
                "sections": [{"name": "Service maps"}],
                "logs_charts": [{"name": "Recent errors", "query": "service.name=checkout error"}],
            }
        ),
        encoding="utf-8",
    )

    result = run_setup("--validate", "--spec", str(spec))

    assert result.returncode == 0, result.stdout
    assert "advisory only" in result.stdout


def test_dry_run_apply_uses_rendered_sequence_without_network(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    token_file = tmp_path / "token"
    token_file.write_text("token-value", encoding="utf-8")

    result = run_setup(
        "--apply",
        "--dry-run",
        "--spec",
        str(EXAMPLE_SPEC),
        "--output-dir",
        str(output_dir),
        "--realm",
        "us0",
        "--token-file",
        str(token_file),
    )

    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["dry_run"] is True
    assert payload["realm"] == "us0"
    assert [item["action"] for item in payload["sequence"]] == [
        "create-dashboard-group",
        "create-chart",
        "create-chart",
        "create-chart",
        "create-chart",
        "create-dashboard",
    ]


def test_apply_can_use_observability_credentials_defaults(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    token_file = tmp_path / "o11y.token"
    credentials_file = tmp_path / "credentials"
    token_file.write_text("token-value", encoding="utf-8")
    credentials_file.write_text(
        f'SPLUNK_O11Y_REALM="eu0"\nSPLUNK_O11Y_TOKEN_FILE="{token_file}"\n',
        encoding="utf-8",
    )

    result = run_setup(
        "--apply",
        "--dry-run",
        "--spec",
        str(EXAMPLE_SPEC),
        "--output-dir",
        str(output_dir),
        env={"SPLUNK_CREDENTIALS_FILE": str(credentials_file)},
    )

    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["dry_run"] is True
    assert payload["realm"] == "eu0"

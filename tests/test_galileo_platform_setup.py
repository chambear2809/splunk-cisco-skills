"""Regression coverage for galileo-platform-setup."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import importlib.util
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/galileo-platform-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
VALIDATE = SKILL_DIR / "scripts/validate.sh"
RENDER = SKILL_DIR / "scripts/render_assets.py"
BRIDGE = SKILL_DIR / "scripts/galileo_to_splunk_hec.py"


def run_cmd(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def rendered_text(root: Path) -> str:
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def load_bridge() -> ModuleType:
    spec = importlib.util.spec_from_file_location("galileo_to_splunk_hec", BRIDGE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setup_help_lists_apply_sections() -> None:
    result = run_cmd("bash", str(SETUP), "--help")
    combined = result.stdout + result.stderr

    assert "--o11y-only" in combined
    for section in [
        "readiness",
        "observe-export",
        "observe-runtime",
        "protect-runtime",
        "evaluate-assets",
        "splunk-hec",
        "splunk-otlp",
        "otel-collector",
        "dashboards",
        "detectors",
    ]:
        assert section in combined


def test_default_render_emits_plan_coverage_and_handoff_scripts(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        "--json",
    )
    payload = json.loads(result.stdout)

    assert payload["output_dir"] == str(output_dir.resolve())
    assert (output_dir / "apply-plan.json").is_file()
    assert (output_dir / "coverage-report.json").is_file()
    assert (output_dir / "handoff.md").is_file()
    assert (output_dir / "readiness/readiness-report.json").is_file()
    assert (output_dir / "runtime/python-opentelemetry-env.sh").is_file()
    assert (output_dir / "runtime/python-galileo-protect.py").is_file()
    assert (output_dir / "evaluate/evaluate-assets.yaml").is_file()
    assert (output_dir / "splunk-platform/hec-event-sample.json").is_file()
    assert (output_dir / "splunk-platform/export-records-request.json").is_file()
    assert (output_dir / "otel/collector-galileo-fanout.yaml").is_file()
    for script in [
        "apply-readiness.sh",
        "apply-observe-export.sh",
        "apply-observe-runtime.sh",
        "apply-protect-runtime.sh",
        "apply-evaluate-assets.sh",
        "apply-splunk-hec.sh",
        "apply-splunk-otlp.sh",
        "apply-otel-collector.sh",
        "apply-dashboards.sh",
        "apply-detectors.sh",
        "apply-selected.sh",
    ]:
        assert (output_dir / "scripts" / script).is_file()
        assert (output_dir / "scripts" / script).stat().st_mode & 0o111

    run_cmd("bash", str(VALIDATE), "--output-dir", str(output_dir))


def test_hec_handoff_delegates_to_hec_service_with_token_file_only(tmp_path: Path) -> None:
    secret = "SPLUNK_HEC_SECRET_SHOULD_NOT_RENDER"
    token_file = tmp_path / "hec.token"
    token_file.write_text(secret, encoding="utf-8")
    output_dir = tmp_path / "rendered"

    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        "--splunk-hec-token-file",
        str(token_file),
        "--splunk-index",
        "galileo_prod",
    )

    script = (output_dir / "scripts/apply-splunk-hec.sh").read_text(encoding="utf-8")
    assert "splunk-hec-service-setup/scripts/setup.sh" in script
    assert "--token-file" in script
    assert not re.search(r"--splunk-hec-token(?:=|\s)", script)
    assert secret not in rendered_text(output_dir)
    assert str(token_file) in script


def test_otlp_handoff_delegates_to_splunk_connect_for_otlp(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd("bash", str(SETUP), "--render", "--output-dir", str(output_dir))

    script = (output_dir / "scripts/apply-splunk-otlp.sh").read_text(encoding="utf-8")
    assert "splunk-connect-for-otlp-setup/scripts/setup.sh" in script
    assert "--hec-token-file" in script
    assert "--configure-input" in script


def test_otel_collector_handoff_delegates_to_splunk_otel_collector(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        "--realm",
        "us0",
    )

    script = (output_dir / "scripts/apply-otel-collector.sh").read_text(encoding="utf-8")
    assert "splunk-observability-otel-collector-setup/scripts/setup.sh" in script
    assert "--o11y-token-file" in script
    assert "--platform-hec-token-file" in script
    assert "--render-platform-hec-helper" in script


def test_o11y_only_otel_collector_handoff_omits_platform_hec(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        "--o11y-only",
        "--realm",
        "us0",
    )

    script = (output_dir / "scripts/apply-otel-collector.sh").read_text(encoding="utf-8")
    assert "splunk-observability-otel-collector-setup/scripts/setup.sh" in script
    assert "--o11y-token-file" in script
    assert "SPLUNK_HEC_TOKEN_FILE" not in script
    assert "--render-platform-hec-helper" not in script
    assert "--platform-hec-token-file" not in script
    assert "--platform-hec-url" not in script
    assert "--platform-hec-index" not in script

    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    assert plan["modes"] == {
        "o11y_only": True,
        "splunk_platform_hec_enabled": False,
    }
    assert plan["selected_sections"] == [
        "readiness",
        "observe-runtime",
        "protect-runtime",
        "evaluate-assets",
        "otel-collector",
        "dashboards",
        "detectors",
    ]


def test_o11y_only_default_apply_dry_run_selects_cloud_sections(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--apply",
        "--o11y-only",
        "--dry-run",
        "--json",
        "--output-dir",
        str(tmp_path / "rendered"),
    )
    payload = json.loads(result.stdout)

    assert payload["modes"]["o11y_only"] is True
    assert payload["modes"]["splunk_platform_hec_enabled"] is False
    assert payload["selected_sections"] == [
        "readiness",
        "observe-runtime",
        "protect-runtime",
        "evaluate-assets",
        "otel-collector",
        "dashboards",
        "detectors",
    ]
    for platform_section in ["splunk-hec", "observe-export", "splunk-otlp"]:
        assert platform_section not in payload["selected_sections"]


def test_o11y_only_apply_all_uses_cloud_sections_before_apply(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--apply",
        "all",
        "--o11y-only",
        "--realm",
        "us0",
        "--output-dir",
        str(tmp_path / "rendered"),
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode != 0
    assert "Unknown apply section: all" not in combined
    assert "--o11y-token-file is required" in combined


def test_o11y_only_rejects_explicit_platform_sections(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--apply",
        "observe-export",
        "--o11y-only",
        "--dry-run",
        "--output-dir",
        str(tmp_path / "rendered"),
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode != 0
    assert "--o11y-only" in combined
    assert "Splunk Platform" in combined
    assert "observe-export" in combined


def test_direct_secret_flags_are_rejected_without_echoing_values(tmp_path: Path) -> None:
    secret = "DIRECT_GALILEO_SECRET_SHOULD_NOT_ECHO"
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(tmp_path / "rendered"),
        "--galileo-api-key",
        secret,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert secret not in combined
    assert "--galileo-api-key-file" in combined


def test_rendered_files_do_not_contain_token_values_or_direct_authorization(tmp_path: Path) -> None:
    galileo_secret = "GALILEO_SECRET_SHOULD_NOT_RENDER"
    hec_secret = "HEC_SECRET_SHOULD_NOT_RENDER"
    o11y_secret = "O11Y_SECRET_SHOULD_NOT_RENDER"
    galileo_file = tmp_path / "galileo.token"
    hec_file = tmp_path / "hec.token"
    o11y_file = tmp_path / "o11y.token"
    galileo_file.write_text(galileo_secret, encoding="utf-8")
    hec_file.write_text(hec_secret, encoding="utf-8")
    o11y_file.write_text(o11y_secret, encoding="utf-8")
    output_dir = tmp_path / "rendered"

    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        "--galileo-api-key-file",
        str(galileo_file),
        "--splunk-hec-token-file",
        str(hec_file),
        "--o11y-token-file",
        str(o11y_file),
        "--splunk-hec-url",
        "https://splunk.example.com:8088/services/collector/event",
        "--realm",
        "us0",
    )
    text = rendered_text(output_dir)

    assert galileo_secret not in text
    assert hec_secret not in text
    assert o11y_secret not in text
    assert "Authorization: Splunk" not in text
    assert "Authorization: Bearer" not in text
    assert str(galileo_file) in text
    assert str(hec_file) in text
    assert str(o11y_file) in text


def test_export_records_request_shape_defaults_to_jsonl_and_redaction() -> None:
    bridge = load_bridge()
    args = bridge.parse_args(
        [
            "--project-id",
            "00000000-0000-4000-8000-000000000001",
            "--log-stream-id",
            "00000000-0000-4000-8000-000000000002",
            "--experiment-id",
            "00000000-0000-4000-8000-000000000003",
            "--metrics-testing-id",
            "00000000-0000-4000-8000-000000000004",
            "--galileo-api-key-file",
            "/tmp/galileo",
            "--splunk-hec-token-file",
            "/tmp/hec",
            "--splunk-hec-url",
            "https://splunk.example.com:8088",
            "--since",
            "2026-05-01T00:00:00Z",
        ]
    )
    body = bridge.build_export_records_request(args, args.since)

    assert body["root_type"] == "trace"
    assert body["export_format"] == "jsonl"
    assert body["redact"] is True
    assert body["log_stream_id"].endswith("0002")
    assert body["experiment_id"].endswith("0003")
    assert body["metrics_testing_id"].endswith("0004")
    assert body["filters"][0] == {
        "column_id": "updated_at",
        "operator": "gte",
        "type": "date",
        "value": "2026-05-01T00:00:00Z",
    }


def test_repo_has_no_legacy_galileo_skill_references() -> None:
    legacy = "splunk-" + "galileo-integration"
    result = run_cmd("rg", legacy, ".", check=False)
    assert result.returncode == 1, result.stdout + result.stderr


def test_python_scripts_compile() -> None:
    run_cmd(sys.executable, "-m", "py_compile", str(RENDER), str(BRIDGE))

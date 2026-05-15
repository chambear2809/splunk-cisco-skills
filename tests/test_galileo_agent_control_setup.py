"""Regression coverage for galileo-agent-control-setup."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/galileo-agent-control-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
VALIDATE = SKILL_DIR / "scripts/validate.sh"
RENDER = SKILL_DIR / "scripts/render_assets.py"


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


def test_setup_help_lists_apply_sections() -> None:
    result = run_cmd("bash", str(SETUP), "--help")
    combined = result.stdout + result.stderr

    for section in [
        "server",
        "auth",
        "controls",
        "python-runtime",
        "typescript-runtime",
        "otel-sink",
        "splunk-sink",
        "splunk-hec",
        "otel-collector",
        "dashboards",
        "detectors",
    ]:
        assert section in combined


def test_default_render_emits_server_auth_controls_runtime_sinks_and_handoffs(tmp_path: Path) -> None:
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
    for path in [
        "metadata.json",
        "apply-plan.json",
        "coverage-report.json",
        "handoff.md",
        "server/docker-compose.env.example",
        "server/external-server-readiness.md",
        "auth/agent-control-auth.env.example",
        "controls/policy-templates.json",
        "runtime/python-control.py",
        "runtime/typescript-control.ts",
        "sinks/otel-sink.env",
        "sinks/splunk-hec-sink.py",
        "sinks/splunk-hec-event-sample.json",
        "dashboards/agent-control-dashboard.yaml",
        "detectors/agent-control-detectors.yaml",
    ]:
        assert (output_dir / path).is_file()

    for script in [
        "apply-server.sh",
        "apply-auth.sh",
        "apply-controls.sh",
        "apply-python-runtime.sh",
        "apply-typescript-runtime.sh",
        "apply-otel-sink.sh",
        "apply-splunk-sink.sh",
        "apply-splunk-hec.sh",
        "apply-otel-collector.sh",
        "apply-dashboards.sh",
        "apply-detectors.sh",
        "apply-selected.sh",
    ]:
        assert (output_dir / "scripts" / script).is_file()
        assert (output_dir / "scripts" / script).stat().st_mode & 0o111

    run_cmd("bash", str(VALIDATE), "--output-dir", str(output_dir))


def test_direct_secret_flags_are_rejected_without_echoing_values(tmp_path: Path) -> None:
    secret = "DIRECT_AGENT_CONTROL_SECRET_SHOULD_NOT_ECHO"
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(tmp_path / "rendered"),
        "--agent-control-api-key",
        secret,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert secret not in combined
    assert "--agent-control-api-key-file" in combined


def test_rendered_files_do_not_contain_token_values(tmp_path: Path) -> None:
    api_secret = "AGENT_CONTROL_API_SECRET_SHOULD_NOT_RENDER"
    admin_secret = "AGENT_CONTROL_ADMIN_SECRET_SHOULD_NOT_RENDER"
    hec_secret = "HEC_SECRET_SHOULD_NOT_RENDER"
    o11y_secret = "O11Y_SECRET_SHOULD_NOT_RENDER"
    api_file = tmp_path / "agent-api.key"
    admin_file = tmp_path / "agent-admin.key"
    hec_file = tmp_path / "hec.token"
    o11y_file = tmp_path / "o11y.token"
    api_file.write_text(api_secret, encoding="utf-8")
    admin_file.write_text(admin_secret, encoding="utf-8")
    hec_file.write_text(hec_secret, encoding="utf-8")
    o11y_file.write_text(o11y_secret, encoding="utf-8")
    output_dir = tmp_path / "rendered"

    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        "--agent-control-api-key-file",
        str(api_file),
        "--agent-control-admin-key-file",
        str(admin_file),
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

    assert api_secret not in text
    assert admin_secret not in text
    assert hec_secret not in text
    assert o11y_secret not in text
    assert "Authorization: Splunk" not in text
    assert "Authorization: Bearer" not in text
    assert str(api_file) in text
    assert str(admin_file) in text
    assert str(hec_file) in text
    assert str(o11y_file) in text


def test_handoffs_include_otel_and_splunk_hec(tmp_path: Path) -> None:
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

    hec_script = (output_dir / "scripts/apply-splunk-hec.sh").read_text(encoding="utf-8")
    collector_script = (output_dir / "scripts/apply-otel-collector.sh").read_text(encoding="utf-8")
    assert "splunk-hec-service-setup/scripts/setup.sh" in hec_script
    assert "--token-file" in hec_script
    assert "splunk-observability-otel-collector-setup/scripts/setup.sh" in collector_script
    assert "--o11y-token-file" in collector_script


def test_python_scripts_compile() -> None:
    run_cmd(sys.executable, "-m", "py_compile", str(RENDER))

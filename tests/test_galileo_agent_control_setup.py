"""Regression coverage for galileo-agent-control-setup."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest


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


def load_generated_sink(path: Path, monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    agent_control = types.ModuleType("agent_control")
    agent_control.register_control_event_sink = lambda _sink: None
    telemetry = types.ModuleType("agent_control_telemetry")
    telemetry.BaseControlEventSink = object

    class SinkResult:
        def __init__(self, *, accepted: int, dropped: int) -> None:
            self.accepted = accepted
            self.dropped = dropped

    telemetry.SinkResult = SinkResult
    monkeypatch.setitem(sys.modules, "agent_control", agent_control)
    monkeypatch.setitem(sys.modules, "agent_control_telemetry", telemetry)
    spec = importlib.util.spec_from_file_location("generated_agent_control_hec_sink", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_server_url_is_normalized_and_runtime_overrides_are_revalidated(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        "--server-url",
        "https://CONTROL.Example.COM:8443/",
    )

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["server_url"] == "https://control.example.com:8443"
    python_runtime = (output_dir / "runtime/python-control.py").read_text(encoding="utf-8")
    typescript_runtime = (output_dir / "runtime/typescript-control.ts").read_text(
        encoding="utf-8"
    )
    assert "_normalize_agent_control_base_url" in python_runtime
    assert "AGENT_CONTROL_BASE_URL must not contain credentials" in python_runtime
    assert "normalizeServerUrl" in typescript_runtime
    assert "must use HTTPS outside loopback testing" in typescript_runtime


@pytest.mark.parametrize(
    "server_url",
    [
        "https://user:SERVER_SECRET@control.example.com",
        "https://control.example.com/api",
        "https://control.example.com?tenant=other",
        "https://control.example.com#fragment",
        "https://control.example.com:bad",
        "https://control.example.com:0",
        "http://control.example.com:8000",
        "ftp://control.example.com",
        "control.example.com",
    ],
)
def test_server_url_rejects_unsafe_credential_transport(
    tmp_path: Path, server_url: str
) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(tmp_path / "rendered"),
        "--server-url",
        server_url,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Agent Control server URL" in combined
    assert "SERVER_SECRET" not in combined


def test_hec_url_normalizes_to_exact_event_path_and_disables_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        "--splunk-hec-url",
        "https://SPLUNK.Example.COM:8088/services/collector/",
    )

    sink_path = output_dir / "sinks/splunk-hec-sink.py"
    sink_source = sink_path.read_text(encoding="utf-8")
    assert "https://splunk.example.com:8088/services/collector/event" in sink_source
    assert "request.build_opener(NoRedirectHandler())" in sink_source
    assert "request.urlopen(" not in sink_source

    sink_module = load_generated_sink(sink_path, monkeypatch)
    assert (
        sink_module._normalize_hec_url("http://127.0.0.1:8088")
        == "http://127.0.0.1:8088/services/collector/event"
    )
    assert (
        sink_module._normalize_hec_url(
            "https://splunk.example.com:8088/services/collector"
        )
        == "https://splunk.example.com:8088/services/collector/event"
    )
    handler = sink_module.NoRedirectHandler()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://other") is None


@pytest.mark.parametrize(
    "hec_url",
    [
        "https://user:HEC_SECRET@splunk.example.com:8088/services/collector/event",
        "https://splunk.example.com:8088/services/collector/raw",
        "https://splunk.example.com:8088//services/collector/event",
        "https://splunk.example.com:8088/services/collector/event?token=secret",
        "https://splunk.example.com:bad/services/collector/event",
        "https://splunk.example.com:0/services/collector/event",
        "http://splunk.example.com:8088/services/collector/event",
        "ftp://splunk.example.com:8088/services/collector/event",
    ],
)
def test_hec_url_rejects_unsafe_credential_transport(tmp_path: Path, hec_url: str) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(tmp_path / "rendered"),
        "--splunk-hec-url",
        hec_url,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Splunk HEC URL" in combined
    assert "HEC_SECRET" not in combined


def test_generated_hec_runtime_rejects_unsafe_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd("bash", str(SETUP), "--render", "--output-dir", str(output_dir))
    sink_module = load_generated_sink(output_dir / "sinks/splunk-hec-sink.py", monkeypatch)

    for unsafe_url in [
        "https://user:secret@splunk.example.com:8088/services/collector/event",
        "https://splunk.example.com:8088/services/collector/raw",
        "https://splunk.example.com:8088//services/collector/event",
        "https://splunk.example.com:8088/services/collector/event?token=secret",
        "https://splunk.example.com:0/services/collector/event",
        "http://splunk.example.com:8088/services/collector/event",
    ]:
        with pytest.raises(RuntimeError):
            sink_module._normalize_hec_url(unsafe_url)


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

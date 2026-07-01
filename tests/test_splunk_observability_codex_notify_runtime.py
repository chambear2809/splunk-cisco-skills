from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "skills/splunk-observability-codex-instrumentation-setup/runtime"
SPAN_SCRIPT = RUNTIME_DIR / "codex-splunk-o11y-notify-span.py"
NOTIFY_SCRIPT = RUNTIME_DIR / "codex-splunk-o11y-notify.zsh"
HEALTH_SCRIPT = RUNTIME_DIR / "codex-splunk-o11y-health.zsh"
INSTALLER = REPO_ROOT / "skills/splunk-observability-codex-instrumentation-setup/scripts/install_notify_runtime.sh"


def load_runtime_module():
    spec = importlib.util.spec_from_file_location("codex_splunk_notify_runtime_test", SPAN_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_notify_runtime_is_static_secret_safe_and_package_manager_free() -> None:
    notify = NOTIFY_SCRIPT.read_text(encoding="utf-8")
    span = SPAN_SCRIPT.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "uv run" not in notify
    assert "pip install" not in notify
    assert "--payload-stdin" in notify
    assert "umask 077" in notify
    assert "-u CODEX_SPLUNK_TRACE_ENDPOINT" in notify
    assert "-u CODEX_SPLUNK_METRICS_ENDPOINT" in notify
    assert "sf_service" in span
    assert "sf_environment" in span
    assert "--require-hashes" in installer
    assert "UV_NO_CONFIG=1" in installer
    assert HEALTH_SCRIPT.is_file()


def test_resource_dimensions_are_stable() -> None:
    runtime = load_runtime_module()
    attrs = runtime.resource_attributes(
        {"service_name": "codex-desktop", "environment": "aleccham-codex"}
    )
    assert attrs["service.name"] == "codex-desktop"
    assert attrs["sf_service"] == "codex-desktop"
    assert attrs["deployment.environment.name"] == "aleccham-codex"
    assert attrs["deployment.environment"] == "aleccham-codex"
    assert attrs["sf_environment"] == "aleccham-codex"


def test_loopback_export_never_forwards_splunk_token(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = load_runtime_module()
    monkeypatch.setenv("SPLUNK_ACCESS_TOKEN", "must-not-go-to-loopback")
    assert runtime._headers_for({"trace_endpoint": "http://127.0.0.1:14318/v1/traces"}) == {}
    assert runtime._headers_for({"trace_endpoint": "http://localhost:4318/v1/traces"}) == {}


def test_splunk_token_is_scoped_to_trusted_https_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = load_runtime_module()
    monkeypatch.setenv("SPLUNK_ACCESS_TOKEN", "must-not-go-to-arbitrary-host")
    assert runtime._headers_for({"trace_endpoint": "https://collector.example.invalid/v1/traces"}) == {}
    assert runtime._headers_for(
        {"trace_endpoint": "https://ingest.us1.observability.splunkcloud.com/v2/trace/otlp"}
    ) == {"X-SF-TOKEN": "must-not-go-to-arbitrary-host"}
    with pytest.raises(RuntimeError, match="requires HTTPS"):
        runtime._headers_for(
            {"trace_endpoint": "http://ingest.us1.observability.splunkcloud.com/v2/trace/otlp"}
        )


def test_runtime_rejects_cleartext_non_loopback_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = load_runtime_module()
    monkeypatch.setenv("CODEX_SPLUNK_TRACE_ENDPOINT", "http://collector.example.invalid/v1/traces")
    with pytest.raises(ValueError, match="HTTPS unless it is loopback"):
        runtime.runtime_config()


def test_installer_rejects_cleartext_non_loopback_endpoint(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash",
            str(INSTALLER),
            "--codex-home",
            str(tmp_path / ".codex"),
            "--trace-endpoint",
            "http://collector.example.invalid/v1/traces",
            "--dry-run",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "HTTPS unless it is loopback" in result.stderr


def test_incomplete_turn_is_not_selected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = load_runtime_module()
    codex_home = tmp_path / ".codex"
    session = codex_home / "sessions/2026/07/01/rollout-incomplete.jsonl"
    session.parent.mkdir(parents=True)
    rows = [
        {"timestamp": "2026-07-01T19:00:00Z", "payload": {"type": "task_started", "turn_id": "t1"}},
        {"timestamp": "2026-07-01T19:00:01Z", "payload": {"type": "user_message", "turn_id": "t1"}},
    ]
    session.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert runtime.latest_completed_turn(session) is None


def test_notify_payload_resolves_exact_thread_and_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = load_runtime_module()
    codex_home = tmp_path / ".codex"
    thread_id = "019f1f20-1a04-7811-9499-0ac359233bf4"
    turn_id = "019f1f20-1ca2-7ea3-bc71-2a29107a3c0d"
    session = codex_home / f"sessions/2026/07/01/rollout-test-{thread_id}.jsonl"
    session.parent.mkdir(parents=True)
    rows = [
        {"timestamp": "2026-07-01T19:00:00Z", "payload": {"type": "task_started", "turn_id": turn_id}},
        {"timestamp": "2026-07-01T19:00:01Z", "payload": {"type": "task_complete", "turn_id": turn_id}},
    ]
    session.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    payload = {"type": "agent-turn-complete", "thread-id": thread_id, "turn-id": turn_id}
    assert runtime.latest_session_file(payload) == session
    turn = runtime.completed_turn_for_payload(session, payload)
    assert turn is not None
    assert turn.turn_id == turn_id


def test_failed_export_remains_in_outbox_then_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = load_runtime_module()
    codex_home = tmp_path / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    turn = runtime.synthetic_turn()
    runtime.enqueue_turn(turn, "turn-ended")

    def fail_export(*_args, **_kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(runtime, "emit_live", fail_export)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        runtime.drain_outbox({})
    assert runtime.outbox_depth() == 1
    assert not runtime.already_emitted(turn.turn_id)

    trace_id = "1" * 32
    monkeypatch.setattr(
        runtime,
        "emit_live",
        lambda *_args, **_kwargs: {"ok": True, "trace_id": trace_id},
    )
    results = runtime.drain_outbox({})
    assert results == [{"ok": True, "trace_id": trace_id}]
    assert runtime.outbox_depth() == 0
    assert runtime.already_emitted(turn.turn_id)

    for path in (
        codex_home / "log/codex-splunk-o11y-outbox.json",
        codex_home / "log/codex-splunk-o11y-outbox.json.lock",
        codex_home / "log/codex-splunk-o11y-emitted-turns.json",
        codex_home / "log/codex-splunk-o11y-emitted-turns.json.lock",
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((codex_home / "log").stat().st_mode) == 0o700


def test_explicit_drain_mode_retries_without_a_new_turn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = load_runtime_module()
    config = {"service_name": "codex", "environment": "test"}
    expected = [{"ok": True, "trace_id": "1" * 32}]
    monkeypatch.setattr(runtime, "runtime_config", lambda: config)
    monkeypatch.setattr(runtime, "drain_outbox", lambda actual: expected if actual is config else [])
    monkeypatch.setattr(runtime, "outbox_depth", lambda: 0)
    assert runtime.main(["--drain"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["exported"] == expected
    assert payload["outbox_depth"] == 0


def test_installer_rolls_back_every_managed_artifact_on_final_health_failure(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / ".codex"
    managed = {
        "bin/codex-splunk-o11y-notify.zsh": "old-notify\n",
        "bin/codex-splunk-o11y-notify-span.py": "old-span\n",
        "bin/codex-splunk-o11y-health.zsh": "old-health\n",
        "codex-splunk-o11y-runtime.json": "old-config\n",
        "o11y-runtime/requirements-notify.lock": "old-lock\n",
        "o11y-runtime/manifest.json": "old-manifest\n",
        "o11y-venv/old-runtime-marker": "old-venv\n",
    }
    for relative, content in managed.items():
        path = codex_home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    fake_uv = tmp_path / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ ${1:-} == --version ]]; then echo 'uv 0.test'; exit 0; fi\n"
        "if [[ ${1:-} == venv ]]; then\n"
        "  target=${@: -1}; mkdir -p \"$target/bin\"\n"
        "  printf '#!/usr/bin/env bash\\nexit 0\\n' > \"$target/bin/python\"\n"
        "  chmod 700 \"$target/bin/python\"; exit 0\n"
        "fi\n"
        "if [[ ${1:-} == pip && ${2:-} == sync ]]; then exit 0; fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o700)

    result = subprocess.run(
        [
            "bash",
            str(INSTALLER),
            "--codex-home",
            str(codex_home),
            "--service-name",
            "codex-test",
            "--environment",
            "test",
            "--realm",
            "us1",
        ],
        env={
            **dict(os.environ),
            "UV_BIN": str(fake_uv),
            "CODEX_SPLUNK_O11Y_PYTHON": "/bin/false",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    for relative, content in managed.items():
        assert (codex_home / relative).read_text(encoding="utf-8") == content
    assert not list(codex_home.glob(".o11y-runtime-stage.*"))

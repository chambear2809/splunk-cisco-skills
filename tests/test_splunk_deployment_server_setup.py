"""Regression coverage for splunk-deployment-server-setup."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/splunk-deployment-server-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
VALIDATE = SKILL_DIR / "scripts/validate.sh"
RENDER = SKILL_DIR / "scripts/render_assets.py"
SMOKE = SKILL_DIR / "scripts/smoke_offline.sh"


def run_cmd(*args: str, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


# --------------------------------------------------------------------------
# Static smoke tests (no live Splunk calls)
# --------------------------------------------------------------------------

def test_setup_sh_exists() -> None:
    assert SETUP.exists()
    assert VALIDATE.exists()
    assert RENDER.exists()


def test_setup_help() -> None:
    result = run_cmd("bash", str(SETUP), "--help")
    combined = result.stdout + result.stderr
    for phrase in ["render", "bootstrap", "reload", "inspect"]:
        assert phrase in combined, f"Expected '{phrase}' in --help output"


def test_render_produces_required_files(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--ds-host", "ds01.example.com",
        "--fleet-size", "500",
        "--output-dir", str(tmp_path),
    )
    required = [
        "ds/bootstrap/enable-deploy-server.sh",
        "ds/bootstrap/deployment-apps-layout.md",
        "ds/reload/reload-deploy-server.sh",
        "ds/inspect/inspect-fleet.sh",
        "ds/migrate/retarget-clients.sh",
        "ds/migrate/staged-rollout.sh",
        "ds/runbook-failure-modes.md",
        "ds/validate.sh",
        "ds/preflight-report.md",
        "ds/handoffs/agent-management.txt",
        "ds/handoffs/monitoring-console.txt",
    ]
    for f in required:
        assert (tmp_path / f).exists(), f"Missing rendered file: {f}"


@pytest.mark.parametrize("uri_flag", ["--ds-uri", "--ds-secondary-uri", "--new-ds-uri"])
def test_renderer_rejects_plaintext_management_uris_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    uri_flag: str,
) -> None:
    monkeypatch.delenv("SPLUNK_ALLOW_INSECURE_HTTP", raising=False)
    result = run_cmd(
        sys.executable,
        str(RENDER),
        "--ds-host",
        "ds01.example.com",
        uri_flag,
        "http://ds01.example.com:8089",
        "--output-dir",
        str(tmp_path),
        check=False,
    )
    assert result.returncode != 0
    assert "SPLUNK_ALLOW_INSECURE_HTTP=true" in result.stderr


def test_renderer_lab_http_opt_in_warns_and_embeds_runtime_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPLUNK_ALLOW_INSECURE_HTTP", "true")
    result = run_cmd(
        sys.executable,
        str(RENDER),
        "--ds-host",
        "ds01.example.com",
        "--ds-uri",
        "http://ds01.example.com:8089",
        "--output-dir",
        str(tmp_path),
    )
    assert "WARNING: LAB ONLY" in result.stderr
    client = (tmp_path / "ds/inspect/client-drift-report.py").read_text(encoding="utf-8")
    assert "SPLUNK_ALLOW_INSECURE_HTTP" in client
    assert "cross-origin redirect refused" in client


def test_renderer_rejects_embedded_uri_credentials_without_echoing_them(
    tmp_path: Path,
) -> None:
    result = run_cmd(
        sys.executable,
        str(RENDER),
        "--ds-host",
        "ds01.example.com",
        "--ds-uri",
        "https://:embedded-secret@ds01.example.com:8089",
        "--output-dir",
        str(tmp_path),
        check=False,
    )
    assert result.returncode != 0
    assert "only scheme, host, and optional port" in result.stderr
    assert "embedded-secret" not in result.stderr


def test_phone_home_scales_with_fleet_size(tmp_path: Path) -> None:
    import json as _json
    result = run_cmd(
        sys.executable, str(RENDER),
        "--ds-host", "ds01.example.com",
        "--fleet-size", "6000",
        "--output-dir", str(tmp_path),
        "--json",
    )
    data = _json.loads(result.stdout)
    # For 6000 UFs, phoneHome should be >= 600s
    assert data["phone_home_interval"] >= 600, (
        f"Expected phoneHome >= 600s for 6000 UF fleet, got {data['phone_home_interval']}"
    )


def test_no_inline_password_in_rendered_files(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--ds-host", "ds01.example.com",
        "--fleet-size", "100",
        "--output-dir", str(tmp_path),
    )
    for path in sorted(tmp_path.rglob("*")):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            # No raw password values — file-path references are allowed
            assert "SPLUNK_PASS=" not in text, f"Inline SPLUNK_PASS= in {path}"


def test_ha_renders_haproxy_when_enabled(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--ds-host", "ds01.example.com",
        "--ds-host2", "ds02.example.com",
        "--fleet-size", "100",
        "--ha-enabled",
        "--output-dir", str(tmp_path),
    )
    assert (tmp_path / "ds" / "ha" / "haproxy.cfg").exists()
    assert (tmp_path / "ds" / "ha" / "sync-deployment-apps.sh").exists()


def test_validate_passes_after_render(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--ds-host", "ds01.example.com",
        "--fleet-size", "500",
        "--output-dir", str(tmp_path),
    )
    result = run_cmd("bash", str(VALIDATE), "--output-dir", str(tmp_path), "--summary")
    assert "errors=0" in result.stdout + result.stderr


def test_validate_does_not_execute_output_dir_as_shell_code(tmp_path: Path) -> None:
    hostile_output = tmp_path / "x' ]]; touch PWNED; [[ -f 'y"
    hostile_output.mkdir()
    marker = tmp_path / "PWNED"
    result = subprocess.run(
        ["bash", str(VALIDATE), "--output-dir", str(hostile_output), "--summary"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "errors=0" not in result.stdout
    assert not marker.exists()
    assert 'eval "${condition}"' not in VALIDATE.read_text(encoding="utf-8")


def test_rendered_basic_auth_client_rejects_http_then_allows_explicit_lab_capture(
    tmp_path: Path,
) -> None:
    import base64
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    rendered = tmp_path / "rendered"
    run_cmd(
        sys.executable,
        str(RENDER),
        "--ds-host",
        "ds01.example.com",
        "--output-dir",
        str(rendered),
    )
    client = rendered / "ds/inspect/client-drift-report.py"
    password_file = tmp_path / "admin-password"
    password_file.write_text("lab-secret\n", encoding="utf-8")
    password_file.chmod(0o600)
    base_env = {
        **os.environ,
        "ADMIN_PASS_FILE": str(password_file),
        "SPLUNK_AUTH_USER": "admin",
    }
    base_env.pop("SPLUNK_ALLOW_INSECURE_HTTP", None)
    rejected = subprocess.run(
        [sys.executable, str(client), "http://127.0.0.1:9"],
        capture_output=True,
        text=True,
        check=False,
        env=base_env,
    )
    assert rejected.returncode == 2
    assert "plaintext HTTP is refused" in rejected.stderr

    embedded = subprocess.run(
        [sys.executable, str(client), "https://:runtime-secret@127.0.0.1:8089"],
        capture_output=True,
        text=True,
        check=False,
        env=base_env,
    )
    assert embedded.returncode == 2
    assert "credential-free http(s) base URI" in embedded.stderr
    assert "runtime-secret" not in embedded.stderr

    captured: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            captured["authorization"] = self.headers.get("Authorization", "")
            payload = b'{"entry": []}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 2
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    allowed = subprocess.run(
        [sys.executable, str(client), f"http://127.0.0.1:{server.server_port}"],
        capture_output=True,
        text=True,
        check=False,
        env={**base_env, "SPLUNK_ALLOW_INSECURE_HTTP": "true"},
        timeout=10,
    )
    thread.join(timeout=10)
    server.server_close()
    assert allowed.returncode == 0, allowed.stderr
    assert "WARNING: LAB ONLY" in allowed.stderr
    assert base64.b64decode(captured["authorization"].removeprefix("Basic ")).decode() == (
        "admin:lab-secret"
    )


def test_rendered_basic_auth_client_refuses_cross_origin_redirect(
    tmp_path: Path,
) -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    rendered = tmp_path / "rendered"
    run_cmd(
        sys.executable,
        str(RENDER),
        "--ds-host",
        "ds01.example.com",
        "--output-dir",
        str(rendered),
    )
    client = rendered / "ds/inspect/client-drift-report.py"
    password_file = tmp_path / "admin-password"
    password_file.write_text("lab-secret\n", encoding="utf-8")
    password_file.chmod(0o600)
    target_called = threading.Event()

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            target_called.set()
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args) -> None:
            return

    target = HTTPServer(("127.0.0.1", 0), TargetHandler)

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{target.server_port}/credential-capture",
            )
            self.end_headers()

        def log_message(self, *_args) -> None:
            return

    redirect = HTTPServer(("127.0.0.1", 0), RedirectHandler)
    redirect.timeout = 2
    target.timeout = 2
    redirect_thread = threading.Thread(target=redirect.handle_request, daemon=True)
    target_thread = threading.Thread(target=target.handle_request, daemon=True)
    redirect_thread.start()
    target_thread.start()
    result = subprocess.run(
        [sys.executable, str(client), f"http://127.0.0.1:{redirect.server_port}"],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "ADMIN_PASS_FILE": str(password_file),
            "SPLUNK_ALLOW_INSECURE_HTTP": "true",
        },
        timeout=10,
    )
    redirect_thread.join(timeout=10)
    target.server_close()
    redirect.server_close()
    target_thread.join(timeout=1)
    assert result.returncode != 0
    assert "cross-origin redirect refused" in result.stderr
    assert not target_called.is_set()


def test_smoke_offline() -> None:
    run_cmd("bash", str(SMOKE))


def test_preflight_report_fleet_size(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--ds-host", "ds01.example.com",
        "--fleet-size", "2500",
        "--output-dir", str(tmp_path),
    )
    preflight = (tmp_path / "ds" / "preflight-report.md").read_text(encoding="utf-8")
    assert "2500" in preflight
    assert "phoneHomeIntervalInSecs" in preflight or "phone" in preflight.lower()


# --------------------------------------------------------------------------
# Live tests (skipped by default; opt-in via SPLUNK_DS_LIVE_TEST=1)
# --------------------------------------------------------------------------

LIVE_ENV_VAR = "SPLUNK_DS_LIVE_TEST"


@pytest.mark.skipif(
    __import__("os").environ.get(LIVE_ENV_VAR, "0") != "1",
    reason=f"Set {LIVE_ENV_VAR}=1 to run live DS API tests"
)
def test_live_ds_clients_endpoint() -> None:
    """Probe DS clients endpoint. Requires DS_URI env var."""
    import os
    ds_uri = os.environ.get("DS_URI", "")
    if not ds_uri:
        pytest.skip("Set DS_URI=https://ds01:8089 to run this test")
    result = run_cmd(
        "bash", str(VALIDATE),
        "--live",
        "--ds-uri", ds_uri,
        "--summary",
    )
    assert "errors=0" in result.stdout + result.stderr

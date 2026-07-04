"""Regressions for credential-bearing generated shell REST clients."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_RENDERER = REPO_ROOT / "skills/splunk-dashboard-studio/scripts/render_assets.py"
DDAA_RENDERER = REPO_ROOT / "skills/splunk-ddaa-archive/scripts/render_assets.py"
FEDERATED_RENDERER = REPO_ROOT / "skills/splunk-federated-search-setup/scripts/render_assets.py"
PKI_RENDERER = REPO_ROOT / "skills/splunk-platform-pki-setup/scripts/render_assets.py"


def run_renderer(renderer: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(renderer), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def assert_curl_transport_policy(script: str) -> None:
    assert "curl -q" in script
    assert "--proto '=https'" in script
    assert "--proto-redir '=https'" in script
    assert "--max-redirs 0" in script
    assert "--globoff" in script


def test_dashboard_apply_rejects_plaintext_and_curl_config_injection(tmp_path: Path) -> None:
    result = run_renderer(
        DASHBOARD_RENDERER,
        "--output-dir",
        str(tmp_path),
        "--title",
        "Transport policy",
        "--panel",
        "Count::single::index=main | stats count",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    render_dir = tmp_path / "dashboard-studio"
    apply_script = render_dir / "apply.sh"
    text = apply_script.read_text(encoding="utf-8")
    assert_curl_transport_policy(text)
    assert "command curl -q" in text
    assert "auth-only user directive" in text
    assert "stat -c '%a' --" in text
    assert "|| stat -f '%A' --" in text

    config = tmp_path / "curl.cfg"
    config.write_text('user = "admin:test-password"\n', encoding="utf-8")
    config.chmod(0o600)
    env = {
        **os.environ,
        "SPLUNK_CURL_CONFIG": str(config),
        "SPLUNK_MGMT_URI": "http://127.0.0.1:9",
    }
    env.pop("SPLUNK_ALLOW_INSECURE_HTTP", None)
    refused = subprocess.run(
        ["bash", str(apply_script)],
        cwd=render_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert refused.returncode != 0
    assert "credential-free HTTPS origin" in refused.stderr

    config.write_text('user = "admin:test-password"\nlocation\n', encoding="utf-8")
    env["SPLUNK_MGMT_URI"] = "https://127.0.0.1:9"
    refused = subprocess.run(
        ["bash", str(apply_script)],
        cwd=render_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert refused.returncode != 0
    assert "auth-only user directive" in refused.stderr
    assert "test-password" not in refused.stderr

    env.pop("SPLUNK_CURL_CONFIG")
    env["SPLUNK_USERNAME"] = "admin:inline-password-must-not-reach-argv"
    refused = subprocess.run(
        ["bash", str(apply_script)],
        cwd=render_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert refused.returncode != 0
    assert "inline :password material" in refused.stderr
    assert "inline-password-must-not-reach-argv" not in refused.stderr


def test_ddaa_generated_clients_are_https_only_and_no_redirect(tmp_path: Path) -> None:
    base_args = (
        "--output-dir",
        str(tmp_path),
        "--stack",
        "test-stack",
        "--index",
        "main",
        "--searchable-days",
        "30",
        "--archival-retention-days",
        "90",
    )
    result = run_renderer(DDAA_RENDERER, *base_args)
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("enable-ddaa.sh", "status.sh"):
        script = (tmp_path / "ddaa" / name).read_text(encoding="utf-8")
        assert_curl_transport_policy(script)
        assert "command curl -q" in script
        assert 'token_escaped="${token//' in script
        assert '"${token_escaped}" > "${curl_config}"' in script

    secret = "uri-password-must-not-leak"
    refused = run_renderer(
        DDAA_RENDERER,
        *base_args,
        "--acs-base",
        f"https://user:{secret}@admin.splunk.com",
    )
    assert refused.returncode != 0
    assert "credential-free HTTPS origin" in refused.stderr
    assert secret not in refused.stderr


def test_federated_status_and_toggle_use_hardened_curl_wrapper(tmp_path: Path) -> None:
    result = run_renderer(
        FEDERATED_RENDERER,
        "--output-dir",
        str(tmp_path),
        "--remote-host-port",
        "remote.example.test:8089",
        "--service-account",
        "federated_svc",
        "--password-file",
        "/tmp/provider-password",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    render_dir = tmp_path / "federated-search"
    for name in ("status.sh", "global-enable.sh", "global-disable.sh"):
        script = (render_dir / name).read_text(encoding="utf-8")
        assert_curl_transport_policy(script)
        assert "command curl -q" in script
        assert "splunk_rest_curl" in script
        assert "password = '; cat" not in script

    admin_password = tmp_path / "admin-password"
    admin_password.write_text("admin-password", encoding="utf-8")
    admin_password.chmod(0o600)
    env = {
        **os.environ,
        "SPLUNK_REST_USER": "admin",
        "SPLUNK_REST_PASSWORD_FILE": str(admin_password),
        "SPLUNK_REST_URI": "http://127.0.0.1:9",
    }
    env.pop("SPLUNK_ALLOW_INSECURE_HTTP", None)
    refused = subprocess.run(
        ["bash", str(render_dir / "status.sh")],
        cwd=render_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert refused.returncode != 0
    assert "credential-free HTTPS origin" in refused.stderr

    secret = "embedded-uri-secret"
    env["SPLUNK_REST_URI"] = f"https://user:{secret}@example.test:8089"
    refused = subprocess.run(
        ["bash", str(render_dir / "status.sh")],
        cwd=render_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert refused.returncode != 0
    assert secret not in refused.stderr


def test_platform_pki_generated_rest_calls_own_transport_policy(tmp_path: Path) -> None:
    result = run_renderer(
        PKI_RENDERER,
        "--output-dir",
        str(tmp_path),
        "--mode",
        "private",
        "--target",
        "edge-processor",
        "--include-edge-processor",
        "true",
        "--ep-fqdn",
        "ep01.example.com",
        "--ep-data-source-fqdn",
        "source01.example.com",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    render_dir = tmp_path / "platform-pki"
    upload = (
        render_dir / "pki/distribute/edge-processor/upload-via-rest.sh.example"
    ).read_text(encoding="utf-8")
    validate = (render_dir / "validate.sh").read_text(encoding="utf-8")
    assert_curl_transport_policy(upload)
    assert "command curl -q" in upload
    assert "credential-free HTTPS origin" in upload
    assert "curl -q --fail" in validate
    assert "--proto-redir '=https' --max-redirs 0 --globoff" in validate

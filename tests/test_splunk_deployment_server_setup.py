"""Regression coverage for splunk-deployment-server-setup."""

from __future__ import annotations

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

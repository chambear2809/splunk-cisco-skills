"""Regression coverage for splunk-search-head-cluster-setup."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/splunk-search-head-cluster-setup"
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
    for phrase in ["render", "bootstrap", "rolling-restart", "transfer-captain"]:
        assert phrase in combined, f"Expected '{phrase}' in --help output"


def test_render_produces_required_files(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--shc-label", "test_shc",
        "--deployer-host", "deployer01.example.com",
        "--member-hosts", "sh01.example.com,sh02.example.com,sh03.example.com",
        "--output-dir", str(tmp_path),
    )
    required = [
        "shc/bootstrap/sequenced-bootstrap.sh",
        "shc/bundle/apply.sh",
        "shc/bundle/validate.sh",
        "shc/restart/searchable-rolling-restart.sh",
        "shc/restart/transfer-captain.sh",
        "shc/kvstore/status.sh",
        "shc/runbook-failure-modes.md",
        "shc/preflight-report.md",
        "shc/handoffs/license-peers.txt",
        "shc/handoffs/es-deployer.txt",
        "shc/handoffs/monitoring-console.txt",
    ]
    for f in required:
        assert (tmp_path / f).exists(), f"Missing rendered file: {f}"


def test_render_pass4symmkey_not_inlined(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--shc-label", "test_shc",
        "--deployer-host", "deployer01.example.com",
        "--member-hosts", "sh01.example.com,sh02.example.com,sh03.example.com",
        "--output-dir", str(tmp_path),
    )
    # No inline pass4SymmKey value should appear outside of placeholder/file-read patterns
    for path in sorted(tmp_path.rglob("*.conf")):
        text = path.read_text(encoding="utf-8")
        lines = [
            line
            for line in text.splitlines()
            if "pass4SymmKey" in line
            and "$SHC_SECRET" not in line
            and "SHC_SECRET" not in line
        ]
        assert not lines, f"Inline pass4SymmKey in {path}: {lines}"


def test_render_replication_factor_minimum(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--shc-label", "test_shc",
        "--deployer-host", "deployer01.example.com",
        "--member-hosts", "sh01.example.com,sh02.example.com,sh03.example.com",
        "--replication-factor", "3",
        "--output-dir", str(tmp_path),
    )
    preflight = (tmp_path / "shc" / "preflight-report.md").read_text(encoding="utf-8")
    assert "OK" in preflight


def test_validate_passes_after_render(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--shc-label", "test_shc",
        "--deployer-host", "deployer01.example.com",
        "--member-hosts", "sh01.example.com,sh02.example.com,sh03.example.com",
        "--output-dir", str(tmp_path),
    )
    result = run_cmd("bash", str(VALIDATE), "--output-dir", str(tmp_path), "--summary")
    assert "errors=0" in result.stdout + result.stderr


def test_smoke_offline() -> None:
    run_cmd("bash", str(SMOKE))


def test_preflight_reports_quorum(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--shc-label", "test_shc",
        "--deployer-host", "deployer01.example.com",
        "--member-hosts", "sh01.example.com,sh02.example.com,sh03.example.com",
        "--output-dir", str(tmp_path),
    )
    preflight = (tmp_path / "shc" / "preflight-report.md").read_text(encoding="utf-8")
    assert "Quorum" in preflight
    assert "2" in preflight  # N/2+1 = 2 for 3 members


def test_handoffs_contain_member_uris(tmp_path: Path) -> None:
    members = ["sh01.example.com", "sh02.example.com", "sh03.example.com"]
    run_cmd(
        sys.executable, str(RENDER),
        "--shc-label", "test_shc",
        "--deployer-host", "deployer01.example.com",
        "--member-hosts", ",".join(members),
        "--output-dir", str(tmp_path),
    )
    license_txt = (tmp_path / "shc" / "handoffs" / "license-peers.txt").read_text(encoding="utf-8")
    for m in members:
        assert m in license_txt


# --------------------------------------------------------------------------
# Live tests (skipped by default; opt-in via SPLUNK_SHC_LIVE_TEST=1)
# --------------------------------------------------------------------------

LIVE_ENV_VAR = "SPLUNK_SHC_LIVE_TEST"


@pytest.mark.skipif(
    __import__("os").environ.get(LIVE_ENV_VAR, "0") != "1",
    reason=f"Set {LIVE_ENV_VAR}=1 to run live SHC API tests"
)
def test_live_shc_captain_reachable() -> None:
    """Probe SHC captain info endpoint. Requires SHC_URI env var."""
    import os
    shc_uri = os.environ.get("SHC_URI", "")
    if not shc_uri:
        pytest.skip("Set SHC_URI=https://sh01:8089 to run this test")
    result = run_cmd(
        "bash", str(VALIDATE),
        "--live",
        "--shc-uri", shc_uri,
        "--summary",
    )
    assert "errors=0" in result.stdout + result.stderr

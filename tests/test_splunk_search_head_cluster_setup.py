"""Regression coverage for splunk-search-head-cluster-setup."""

from __future__ import annotations

import subprocess
import sys
import os
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
        "shc/bootstrap/apply-system-local.sh",
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
    validate_text = (tmp_path / "shc/validate.sh").read_text(encoding="utf-8")
    assert "spv_require_supported_enterprise_server_info" in validate_text
    assert "SHC members are on different Splunk Enterprise patch versions" in validate_text


def test_deployer_is_disabled_and_bundle_targets_reviewed_member(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--shc-label", "test_shc",
        "--deployer-host", "deployer01.example.com",
        "--member-hosts", "sh01.example.com,sh02.example.com,sh03.example.com",
        "--output-dir", str(tmp_path),
    )
    deployer = (tmp_path / "shc/deployer/server.conf").read_text()
    assert "disabled = true" in deployer
    assert "mgmt_uri" not in deployer
    assert "disabled = false" in (tmp_path / "shc/member-sh01.example.com/server.conf").read_text()
    apply = (tmp_path / "shc/bundle/apply.sh").read_text()
    assert "apply shcluster-bundle --answer-yes -target https://sh01.example.com:8089" in apply
    assert "deployer01.example.com:8089" not in apply


def test_member_role_fragment_is_applied_to_system_local(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--shc-label", "test_shc",
        "--deployer-host", "deployer01.example.com",
        "--member-hosts", "sh01.example.com,sh02.example.com,sh03.example.com",
        "--output-dir", str(tmp_path),
    )
    script = (tmp_path / "shc/bootstrap/apply-system-local.sh").read_text()
    assert "system/local/server.conf" in script
    assert "MERGE_SERVER_CONF_HELPER" in script
    assert "sudo python3" in script
    assert "pass4SymmKey" not in script


def test_rendered_rest_scripts_load_platform_profile_before_auth(tmp_path: Path) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--shc-label", "test_shc",
        "--deployer-host", "deployer01.example.com",
        "--member-hosts", "sh01.example.com,sh02.example.com,sh03.example.com",
        "--output-dir", str(tmp_path),
    )
    text = (tmp_path / "shc/restart/searchable-rolling-restart.sh").read_text()
    assert text.index("load_splunk_platform_settings") < text.index("get_session_key_from_password_file")
    assert "Failed to load Splunk platform settings/profile" in text


@pytest.mark.parametrize(
    ("mode_response", "restart_response", "expected_error"),
    [
        ('{"content":{"success":1,"msg":"ok"}}', '{"content":{"success":1,"msg":"ok"}}', None),
        ('{"messages":[{"type":"ERROR","text":"config failed"}]}', '{"content":{"success":1}}', "config failed"),
        ('{"content":{"success":1}}', '{"content":{"success":0,"msg":"restart failed"}}', "success=false"),
    ],
)
def test_rendered_rolling_restart_checks_json_control_responses(
    tmp_path: Path,
    mode_response: str,
    restart_response: str,
    expected_error: str | None,
) -> None:
    run_cmd(
        sys.executable, str(RENDER),
        "--shc-label", "test_shc",
        "--deployer-host", "deployer01.example.com",
        "--member-hosts", "sh01.example.com,sh02.example.com,sh03.example.com",
        "--output-dir", str(tmp_path),
    )
    lib = tmp_path / "fake-lib"
    lib.mkdir()
    (lib / "platform_version_helpers.sh").write_text("")
    (lib / "credential_helpers.sh").write_text(
        """load_splunk_platform_settings() { return 0; }
get_session_key_from_password_file() { printf sk; }
splunk_curl_post() {
  local n=0
  [[ -f \"${FAKE_CALLS}\" ]] && n=$(cat \"${FAKE_CALLS}\")
  n=$((n + 1)); printf '%s' \"${n}\" > \"${FAKE_CALLS}\"
  if [[ \"${n}\" == 1 ]]; then printf '%s' \"${FAKE_MODE_RESPONSE}\"; else printf '%s' \"${FAKE_RESTART_RESPONSE}\"; fi
}
"""
    )
    password = tmp_path / "password"
    password.write_text("synthetic-password\n")
    password.chmod(0o600)
    calls = tmp_path / "calls"
    env = os.environ.copy()
    env.update(
        {
            "SKILLS_SHARED_LIB_DIR": str(lib),
            "SPLUNK_ADMIN_PASSWORD_FILE": str(password),
            "CAPTAIN_URI": "https://sh01.example.com:8089",
            "FAKE_CALLS": str(calls),
            "FAKE_MODE_RESPONSE": mode_response,
            "FAKE_RESTART_RESPONSE": restart_response,
        }
    )
    script = tmp_path / "shc/restart/searchable-rolling-restart.sh"
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, check=False)
    if expected_error is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "initiated" in result.stdout
    else:
        assert result.returncode != 0
        assert expected_error in result.stderr
        assert "Traceback" not in result.stderr
        assert "NameError" not in result.stderr
        if "success=false" in expected_error:
            assert "response reported success=false" in result.stderr
    text = script.read_text()
    assert "output_mode=json" in text
    assert "-o /dev/null" not in text


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

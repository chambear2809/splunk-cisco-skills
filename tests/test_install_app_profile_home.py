"""Regression coverage for profile-selected installer homes."""

from pathlib import Path
import os
import subprocess

from tests.regression_helpers import REPO_ROOT


INSTALLER = REPO_ROOT / "skills/splunk-app-install/scripts/install_app.sh"


def _run_installer_prefix(
    tmp_path: Path,
    *,
    profile_home: str | None,
    explicit_home: str | None,
    top_level_home: str | None = "/flat-profile-home",
) -> str:
    lines = [
        "SPLUNK_PLATFORM=enterprise",
        "SPLUNK_URI=https://127.0.0.1:18089",
        "SPLUNK_USER=synthetic-user",
        "SPLUNK_PASS=synthetic-pass",
    ]
    if profile_home is not None:
        lines += ["SPLUNK_PROFILE=lab", f"PROFILE_lab__SPLUNK_HOME={profile_home}"]
    elif top_level_home is not None:
        lines += [f"SPLUNK_HOME={top_level_home}"]
    credentials = tmp_path / "credentials"
    credentials.write_text("\n".join(lines) + "\n", encoding="utf-8")
    credentials.chmod(0o600)
    source_copy = tmp_path / "install_app_without_main.sh"
    source = INSTALLER.read_text(encoding="utf-8")
    source = source.replace(
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'SCRIPT_DIR="{INSTALLER.parent}"',
        1,
    )
    source = source[: source.rfind("\nmain\n")]
    capture = tmp_path / "captured-home"
    source += f'''\nPROJECT_TA_DIR="{tmp_path / "ta"}"
TA_CACHE="{tmp_path / "cache"}"
require_registry_provenance() {{ :; }}
prompt_source() {{ printf '%s' "$SPLUNK_HOME" > "{capture}"; exit 0; }}
main
'''
    source_copy.write_text(source, encoding="utf-8")
    source_copy.chmod(0o700)
    env = os.environ.copy()
    env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
    if explicit_home is None:
        env.pop("SPLUNK_HOME", None)
    else:
        env["SPLUNK_HOME"] = explicit_home
    result = subprocess.run(
        ["bash", str(source_copy)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "=== Splunk App Installer ===\n\n"
    return capture.read_text(encoding="utf-8")


def test_installer_uses_selected_profile_home_after_credential_load(tmp_path: Path) -> None:
    assert _run_installer_prefix(tmp_path, profile_home="/profile-selected/splunk", explicit_home=None) == "/profile-selected/splunk"


def test_installer_preserves_explicit_operator_home(tmp_path: Path) -> None:
    assert _run_installer_prefix(tmp_path, profile_home="/profile-selected/splunk", explicit_home="/operator-selected/splunk") == "/operator-selected/splunk"


def test_installer_uses_top_level_home_without_profile(tmp_path: Path) -> None:
    assert _run_installer_prefix(tmp_path, profile_home=None, explicit_home=None) == "/flat-profile-home"


def test_installer_falls_back_when_home_is_unset(tmp_path: Path) -> None:
    assert _run_installer_prefix(
        tmp_path, profile_home=None, explicit_home=None, top_level_home=None
    ) == "/opt/splunk"

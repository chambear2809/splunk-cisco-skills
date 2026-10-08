"""Regression coverage for SSH-backed loopback REST forwards."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "skills/splunk-app-install/scripts/install_app.sh"


def _target_is_local(tmp_path: Path, uri: str, ssh_host: str | None) -> bool:
    source = INSTALLER.read_text(encoding="utf-8")
    prefix = source[: source.rfind("\nmain\n")]
    prefix = prefix.replace(
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'SCRIPT_DIR="{INSTALLER.parent}"',
        1,
    )
    script = tmp_path / "target-check.sh"
    script.write_text(
        prefix + '\nprintf "%s\\n" "$(splunk_install_target_is_local && echo local || echo remote)"\n',
        encoding="utf-8",
    )
    script.chmod(0o700)
    env = os.environ.copy()
    env["SPLUNK_URI"] = uri
    if ssh_host is None:
        env.pop("SPLUNK_SSH_HOST", None)
    else:
        env["SPLUNK_SSH_HOST"] = ssh_host
    result = subprocess.run(
        ["bash", str(script)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "local"


def test_loopback_forward_with_explicit_remote_ssh_target_stages_remotely(tmp_path: Path) -> None:
    assert _target_is_local(tmp_path, "https://127.0.0.1:49601", "13.218.98.76") is False


def test_plain_loopback_without_remote_identity_remains_local(tmp_path: Path) -> None:
    assert _target_is_local(tmp_path, "https://127.0.0.1:49601", None) is True


def test_loopback_ssh_to_localhost_remains_local(tmp_path: Path) -> None:
    assert _target_is_local(tmp_path, "https://localhost:8089", "localhost") is True


def test_remote_staging_uses_shared_key_auth_helper(tmp_path: Path) -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    prefix = source[: source.rfind("\nmain\n")]
    prefix = prefix.replace(
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'SCRIPT_DIR="{INSTALLER.parent}"',
        1,
    )
    script = tmp_path / "stage-check.sh"
    script.write_text(
        prefix
        + """
load_splunk_ssh_credentials() { return 0; }
hbs_stage_file_for_execution() { printf '/tmp/%s' "$3"; }
stage_file_via_ssh /tmp/package.tgz /tmp/remote-package.tgz
""",
        encoding="utf-8",
    )
    script.chmod(0o700)
    result = subprocess.run(
        ["bash", str(script)],
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "/tmp/remote-package.tgz"


def _redact_url(tmp_path: Path, value: str) -> str:
    source = INSTALLER.read_text(encoding="utf-8")
    prefix = source[: source.rfind("\nmain\n")]
    prefix = prefix.replace(
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'SCRIPT_DIR="{INSTALLER.parent}"',
        1,
    )
    script = tmp_path / "redact-check.sh"
    script.write_text(prefix + '\nIFS= read -r value\nredact_url_for_log "$value"\n', encoding="utf-8")
    script.chmod(0o700)
    result = subprocess.run(
        ["bash", str(script)],
        input=value + "\n",
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_redacted_url_strips_userinfo_query_and_fragment(tmp_path: Path) -> None:
    assert (
        _redact_url(
            tmp_path,
            "https://signed-user:secret@cdn.example.test:8443/pkg.tgz?Signature=secret#fragment",
        )
        == "https://cdn.example.test:8443/pkg.tgz"
    )


def test_redacted_url_fails_closed_for_invalid_url(tmp_path: Path) -> None:
    assert _redact_url(tmp_path, "not-a-url?secret=value#fragment") == "[REDACTED_URL]"
    assert _redact_url(tmp_path, "https://[malformed/pkg.tgz?secret=value") == "[REDACTED_URL]"

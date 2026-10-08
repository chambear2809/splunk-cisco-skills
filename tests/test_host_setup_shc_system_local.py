from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "skills/splunk-enterprise-host-setup/scripts/merge_server_conf_sections.py"


def run_merge(target: Path, fragment: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), str(target), str(fragment)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_merge_replaces_owned_sections_and_preserves_unrelated_bytes(tmp_path: Path) -> None:
    target = tmp_path / "opt/splunk/etc/system/local/server.conf"
    target.parent.mkdir(parents=True)
    target.write_text(
        "# keep this comment\n[general]\nfoo =   spaced\n\n[shclustering]\nid = bootstrapped-id\ndisabled = true\nunknown = preserve\n\n[kvstore]\nport = 8191\n",
        encoding="utf-8",
    )
    target.chmod(0o600)
    fragment = tmp_path / "fragment"
    fragment.write_text("[shclustering]\ndisabled = false\nlabel = reviewed\n", encoding="utf-8")
    fragment.chmod(0o600)

    result = run_merge(target, fragment)
    assert result.returncode == 0, result.stderr
    merged = target.read_text(encoding="utf-8")
    assert "# keep this comment\n[general]\nfoo =   spaced\n" in merged
    assert "[shclustering]\n" in merged
    assert "disabled = false\n" in merged
    assert "label = reviewed\n" in merged
    assert "[shclustering]\ndisabled = true" not in merged
    assert "id = bootstrapped-id\n" in merged
    assert "unknown = preserve\n" in merged
    assert "[kvstore]\nport = 8191\n" in merged
    assert list(target.parent.glob("server.conf.bak.shc.*"))


def test_merge_rejects_duplicate_owned_sections_and_unsafe_target(tmp_path: Path) -> None:
    target = tmp_path / "opt/splunk/etc/system/local/server.conf"
    target.parent.mkdir(parents=True)
    target.write_text("[shclustering]\ndisabled = false\n", encoding="utf-8")
    target.chmod(0o600)
    duplicate = tmp_path / "duplicate"
    duplicate.write_text("[shclustering]\na=1\n[shclustering]\na=2\n", encoding="utf-8")
    duplicate.chmod(0o600)
    result = run_merge(target, duplicate)
    assert result.returncode != 0
    assert "duplicate owned" in result.stderr

    unsafe = tmp_path / "server.conf"
    unsafe.write_text("[general]\na=b\n", encoding="utf-8")
    unsafe.chmod(0o600)
    result = run_merge(unsafe, duplicate)
    assert result.returncode != 0
    assert "system/local/server.conf" in result.stderr


def test_merge_rejects_world_readable_fragment_and_symlink_parent(tmp_path: Path) -> None:
    target = tmp_path / "opt/splunk/etc/system/local/server.conf"
    target.parent.mkdir(parents=True)
    target.write_text("[general]\na=b\n", encoding="utf-8")
    target.chmod(0o600)
    fragment = tmp_path / "fragment"
    fragment.write_text("[shclustering]\ndisabled = false\n", encoding="utf-8")
    fragment.chmod(0o644)
    result = run_merge(target, fragment)
    assert result.returncode != 0
    assert "mode 600" in result.stderr

    real_parent = tmp_path / "real"
    (real_parent / "etc/system/local").mkdir(parents=True)
    linked = tmp_path / "linked"
    linked.symlink_to(real_parent, target_is_directory=True)
    linked_target = linked / "etc/system/local/server.conf"
    linked_target.write_text("[general]\na=b\n", encoding="utf-8")
    linked_target.chmod(0o600)
    fragment.chmod(0o600)
    result = run_merge(linked_target, fragment)
    assert result.returncode != 0
    assert "symlink" in result.stderr


def test_merge_missing_target_secure_mode_and_no_final_newline(tmp_path: Path) -> None:
    target = tmp_path / "opt/splunk/etc/system/local/server.conf"
    target.parent.mkdir(parents=True)
    fragment = tmp_path / "fragment"
    fragment.write_text("[shclustering]\nid = one\ndisabled = false", encoding="utf-8")
    fragment.chmod(0o600)
    result = run_merge(target, fragment)
    assert result.returncode == 0, result.stderr
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.read_text(encoding="utf-8") == "[shclustering]\nid = one\ndisabled = false"

    target.write_text("[shclustering]\nid = old", encoding="utf-8")
    target.chmod(0o644)
    fragment.write_text("[shclustering]\ndisabled = false\n", encoding="utf-8")
    result = run_merge(target, fragment)
    assert result.returncode == 0, result.stderr
    assert target.stat().st_mode & 0o777 == 0o600
    assert "id = old\ndisabled = false\n" in target.read_text(encoding="utf-8")


def test_merge_rejects_duplicate_fragment_keys(tmp_path: Path) -> None:
    target = tmp_path / "opt/splunk/etc/system/local/server.conf"
    target.parent.mkdir(parents=True)
    fragment = tmp_path / "fragment"
    fragment.write_text("[shclustering]\ndisabled = false\ndisabled = true\n", encoding="utf-8")
    fragment.chmod(0o600)
    result = run_merge(target, fragment)
    assert result.returncode != 0
    assert "duplicate key" in result.stderr

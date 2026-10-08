"""Offline contract regressions for the provenance-bound ITSI bundle."""
from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "skills/splunk-app-install/scripts/install_app.sh"
SHA = "88cc12d00bcb114d626cc312db2eb5eb1aabcb51cfa44245e8abb6ec465b116b"
MEMBERS = {
    "DA-ITSI-APPSERVER", "DA-ITSI-DATABASE", "DA-ITSI-EUEM", "DA-ITSI-LB",
    "DA-ITSI-OS", "DA-ITSI-STORAGE", "DA-ITSI-VIRTUALIZATION", "DA-ITSI-WEBSERVER",
    "SA-ITOA", "SA-ITSI-AI-Summarization", "SA-ITSI-AT-Recommendations", "SA-ITSI-ATAD",
    "SA-ITSI-AlertCorrelation", "SA-ITSI-CustomModuleViz", "SA-ITSI-DriftDetection",
    "SA-ITSI-Licensechecker", "SA-IndexCreation", "SA-UserAccess", "itsi",
}


def inspector_source() -> str:
    source = INSTALLER.read_text(encoding="utf-8")
    start = source.index("result=\"$(python3 - \"${package_path}\"")
    start = source.index("<<'PY'\n", start) + len("<<'PY'\n")
    end = source.index("\nPY\n", start)
    return source[start:end]


def write_archive(path: Path, names: set[str], *, version: str = "5.0.2", bad_id: str | None = None) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name in sorted(names):
            package_id = bad_id if name == "SA-ITOA" and bad_id else name
            body = f"[package]\nid = {package_id}\n[launcher]\nversion = {version}\n".encode()
            info = tarfile.TarInfo(f"{name}/default/app.conf")
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))


def run_inspector(package: Path, *, expected_sha: str = SHA, expected_version: str = "5.0.2") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "-c", inspector_source(), str(package), "SA-ITOA", expected_version, expected_sha],
        text=True,
        capture_output=True,
        check=False,
    )


def test_contract_is_bound_to_actual_digest_and_exact_member_set() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    assert "actual_sha = sha256.hexdigest()" in source
    assert "actual_sha == \"88cc12d00bcb114d626cc312db2eb5eb1aabcb51cfa44245e8abb6ec465b116b\"" in source
    assert "top_levels != verified_itsi_members" in source
    for member in MEMBERS:
        assert member in source


def test_verified_bundle_fails_closed_before_rest_or_automatic_extraction() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    assert "is_verified_itsi_bundle_contract" in source
    assert "is not accepted by REST upload" in source
    assert "Stop Splunk, back up the existing app directories" in source
    assert "Restore reviewed local configuration" in source
    assert "install_verified_itsi_bundle_local" not in source
    assert 'INSTALL_BODY=\'{"entry":[{"name":"SA-ITOA"}]}\'' not in source


def test_generic_multi_app_archive_remains_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "multi.tgz"
    write_archive(archive, {"SA-ITOA", "itsi"})
    result = run_inspector(archive)
    assert result.returncode != 0
    assert "exactly one top-level" in result.stderr


def test_wrong_version_and_member_identity_are_rejected(tmp_path: Path) -> None:
    wrong_version = tmp_path / "wrong-version.tgz"
    write_archive(wrong_version, {"SA-ITOA"}, version="5.0.1")
    result = run_inspector(wrong_version)
    assert result.returncode != 0
    assert "version" in result.stderr

    wrong_id = tmp_path / "wrong-id.tgz"
    write_archive(wrong_id, {"SA-ITOA"}, bad_id="unexpected")
    result = run_inspector(wrong_id)
    assert result.returncode != 0
    assert "Package [package] id" in result.stderr


def test_altered_expected_sha_cannot_authorize_bundle(tmp_path: Path) -> None:
    archive = tmp_path / "altered-expected-sha.tgz"
    write_archive(archive, MEMBERS)
    result = run_inspector(archive, expected_sha="0" * 64)
    assert result.returncode != 0
    assert "exactly one top-level" in result.stderr


def test_synthetic_exact_shape_cannot_bypass_real_digest_gate(tmp_path: Path) -> None:
    archive = tmp_path / "synthetic-19-member.tgz"
    write_archive(archive, MEMBERS)
    result = run_inspector(archive)
    assert result.returncode != 0
    assert "exactly one top-level" in result.stderr

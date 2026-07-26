"""Focused regressions for package extraction and external-command hardening."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
import tarfile
from io import BytesIO
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SAFE_EXTRACTOR = REPO_ROOT / "skills/shared/scripts/safe_extract_tar.py"
SPLUNKBASE_DOWNLOADER = REPO_ROOT / "skills/shared/scripts/download_splunkbase_package.sh"
PUBLIC_RENDERER = (
    REPO_ROOT
    / "skills/splunk-enterprise-public-exposure-hardening/scripts/render_assets.py"
)
SOAR_SETUP = REPO_ROOT / "skills/splunk-soar-setup/scripts/setup.sh"


def load_safe_extractor():
    spec = importlib.util.spec_from_file_location("safe_extract_tar_test", SAFE_EXTRACTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_regular(archive: tarfile.TarFile, name: str, data: bytes = b"data") -> None:
    member = tarfile.TarInfo(name)
    member.size = len(data)
    member.mode = 0o755
    archive.addfile(member, BytesIO(data))


def run_extractor(
    archive: Path,
    destination: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SAFE_EXTRACTOR), *args, str(archive), str(destination)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("name", "member_type", "linkname"),
    [
        ("../escape", tarfile.REGTYPE, ""),
        ("/absolute", tarfile.REGTYPE, ""),
        ("C:/absolute", tarfile.REGTYPE, ""),
        ("app/device", tarfile.CHRTYPE, ""),
        ("app/link", tarfile.SYMTYPE, "../../escape"),
        ("app/hardlink", tarfile.LNKTYPE, "../escape"),
    ],
)
def test_safe_extractor_rejects_unsafe_members_and_leaves_no_destination(
    tmp_path: Path,
    name: str,
    member_type: bytes,
    linkname: str,
) -> None:
    archive_path = tmp_path / "unsafe.tgz"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        member.type = member_type
        member.linkname = linkname
        if member_type == tarfile.REGTYPE:
            member.size = 1
            archive.addfile(member, BytesIO(b"x"))
        else:
            archive.addfile(member)

    destination = tmp_path / "extracted"
    result = run_extractor(archive_path, destination)

    assert result.returncode != 0
    assert "unsafe archive" in result.stderr
    assert not destination.exists()
    assert not (tmp_path / "escape").exists()


def test_safe_extractor_verifies_digest_roots_and_internal_links(tmp_path: Path) -> None:
    archive_path = tmp_path / "safe.tgz"
    with tarfile.open(archive_path, "w:gz") as archive:
        directory = tarfile.TarInfo("splunk-soar")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        archive.addfile(directory)
        add_regular(archive, "splunk-soar/soar-install", b"#!/bin/sh\n")
        link = tarfile.TarInfo("splunk-soar/install-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "soar-install"
        archive.addfile(link)

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    destination = tmp_path / "extracted"
    result = run_extractor(
        archive_path,
        destination,
        "--expected-sha256",
        digest,
        "--expected-root",
        "splunk-soar",
        "--require-exact-roots",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / "splunk-soar/soar-install").is_file()
    assert (destination / "splunk-soar/install-link").is_symlink()

    mismatch_destination = tmp_path / "mismatch"
    mismatch = run_extractor(
        archive_path,
        mismatch_destination,
        "--expected-sha256",
        "0" * 64,
    )
    assert mismatch.returncode != 0
    assert not mismatch_destination.exists()


def test_safe_extractor_keeps_one_verified_descriptor_across_reopens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_safe_extractor()
    archive_path = tmp_path / "package.tgz"
    replacement = tmp_path / "replacement.tgz"
    original_backup = tmp_path / "original.tgz"
    for path, content in ((archive_path, b"trusted"), (replacement, b"malicious")):
        with tarfile.open(path, "w:gz") as archive:
            add_regular(archive, "app/payload", content)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    original_inspect = module.inspect_archive

    def inspect_then_swap(*args, **kwargs):
        result = original_inspect(*args, **kwargs)
        archive_path.rename(original_backup)
        replacement.rename(archive_path)
        return result

    monkeypatch.setattr(module, "inspect_archive", inspect_then_swap)
    destination = tmp_path / "extracted"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SAFE_EXTRACTOR),
            "--expected-sha256",
            digest,
            str(archive_path),
            str(destination),
        ],
    )

    with pytest.raises(SystemExit):
        module.main()

    assert not destination.exists()
    source = SAFE_EXTRACTOR.read_text(encoding="utf-8")
    assert source.count("tarfile.open(fileobj=archive_stream") == 2
    assert "tarfile.open(archive_path" not in source


def test_splunkbase_downloader_rejects_path_components_before_network(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            "bash",
            str(SPLUNKBASE_DOWNLOADER),
            "--app-id",
            "1",
            "--version",
            "1.0.0",
            "--app-name",
            "../outside",
            "--ta-dir",
            str(tmp_path / "cache"),
            "--unpack-root",
            str(tmp_path / "unpacked"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--app-name contains unsupported characters" in result.stderr
    text = SPLUNKBASE_DOWNLOADER.read_text(encoding="utf-8")
    assert "contained_path" in text
    assert "safe_extract_tar.py" in text
    assert "tar -xf" not in text


def public_render(tmp_path: Path, probe: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(PUBLIC_RENDERER),
            "--output-dir",
            str(tmp_path),
            "--public-fqdn",
            "splunk.example.com",
            "--proxy-cidr",
            "10.0.0.0/24",
            "--external-probe-cmd",
            probe,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_external_probe_is_validated_and_rendered_as_argv(tmp_path: Path) -> None:
    rejected = public_render(tmp_path / "rejected", "ssh probe@host nc -zv; touch /tmp/x")
    assert rejected.returncode != 0
    assert "shell metacharacters" in rejected.stderr

    accepted = public_render(tmp_path / "accepted", "ssh -o BatchMode=yes probe@host nc -zv")
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    for name in ("preflight.sh", "validate.sh"):
        script = (
            tmp_path / "accepted/public-exposure" / name
        ).read_text(encoding="utf-8")
        assert "external_probe=(ssh -o BatchMode=yes probe@host nc -zv)" in script
        assert '"${external_probe[@]}" "$fqdn" "$port"' in script
        assert 'eval "$external_probe' not in script


def make_soar_package(path: Path) -> str:
    with tarfile.open(path, "w:gz") as archive:
        directory = tarfile.TarInfo("splunk-soar")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        archive.addfile(directory)
        add_regular(archive, "splunk-soar/soar-prepare-system", b"#!/bin/sh\n")
        add_regular(archive, "splunk-soar/soar-install", b"#!/bin/sh\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_soar_mutation_requires_digest_before_rendering(tmp_path: Path) -> None:
    package = tmp_path / "soar.tgz"
    make_soar_package(package)
    output = tmp_path / "rendered"
    result = subprocess.run(
        [
            "bash",
            str(SOAR_SETUP),
            "--phase",
            "onprem-single",
            "--apply",
            "--soar-tgz",
            str(package),
            "--output-dir",
            str(output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--soar-tgz-sha256" in result.stdout + result.stderr
    assert not output.exists()


def test_soar_rendered_installers_verify_stage_and_promote(tmp_path: Path) -> None:
    package = tmp_path / "soar.tgz"
    digest = make_soar_package(package)
    output = tmp_path / "rendered"
    result = subprocess.run(
        [
            "bash",
            str(SOAR_SETUP),
            "--phase",
            "render",
            "--soar-platform",
            "onprem-cluster",
            "--soar-hosts",
            "soar01,soar02,soar03",
            "--soar-tgz",
            str(package),
            "--soar-tgz-sha256",
            digest,
            "--output-dir",
            str(output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (output / "shared/safe_extract_tar.py").is_file()
    single = (output / "onprem-single/prepare-system.sh").read_text(encoding="utf-8")
    cluster = (output / "onprem-cluster/make-cluster-node.sh").read_text(encoding="utf-8")
    for script in (single, cluster):
        assert "--expected-sha256" in script
        assert "--require-exact-roots" in script
        assert ".install-stage." in script
        assert "refusing to replace existing" in script
        assert "tar -x" not in script
        assert str(REPO_ROOT / "skills/shared/scripts/safe_extract_tar.py") not in script
    assert cluster.index("--validate-only") < cluster.index('remote_dir="$(ssh')
    assert "safe_extract_tar.py" in cluster
    assert "archive is missing non-symlink SOAR installer entrypoints" in cluster

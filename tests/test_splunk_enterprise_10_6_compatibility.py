"""Regression checks for the separate self-managed Enterprise 10.6 contract."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/shared/lib"))
from platform_versions import classify_enterprise_version, platform_minor_train  # noqa: E402


def load_audit():
    path = ROOT / "skills/shared/scripts/audit_splunk_enterprise_10_6_compatibility.py"
    spec = importlib.util.spec_from_file_location("enterprise_10_6_audit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_four_segment_enterprise_version_and_cloud_train_are_separate() -> None:
    assert platform_minor_train("10.6.0.5") == "10.6"
    assert classify_enterprise_version("10.6.0.5") == "supported"
    assert classify_enterprise_version("10.5.2605") == "not-publicly-released"


def test_all_canonical_skills_have_explicit_enterprise_10_6_status() -> None:
    payload = load_audit().audit()
    assert payload["ok"] is True
    assert payload["skill_count"] == 169
    assert payload["counts"]["blocked"] == 1
    assert payload["counts"]["conditional"] > 0
    assert payload["counts"]["delegated"] > 0
    assert payload["counts"]["not-applicable"] > 0


def test_cloud_service_workflows_do_not_require_enterprise_live_validation() -> None:
    rows = {row["skill"]: row for row in load_audit().audit()["skills"]}
    for name in (
        "splunk-ddaa-archive-setup",
        "splunk-cloud-acs-admin-setup",
        "splunk-cloud-acs-allowlist-setup",
        "splunk-cloud-data-manager-setup",
        "splunk-ingest-processor-setup",
    ):
        assert rows[name]["status"] == "not-applicable"
        assert rows[name]["verified"] == "2026-10-08"


def test_cloud_package_evidence_does_not_qualify_enterprise_packages() -> None:
    payload = load_audit().audit()
    supported = conditional = 0
    for row in payload["skills"]:
        if row["packages"] and row["status"] not in {"blocked", "not-applicable", "delegated"}:
            if row["status"] == "supported":
                supported += 1
                assert all(package["supports"] for package in row["packages"]), row["skill"]
            else:
                conditional += 1
                assert any(not package["supports"] for package in row["packages"]), row["skill"]
    assert supported > 0
    assert conditional > 0


def test_itsi_502_is_the_verified_enterprise_106_default_package() -> None:
    import json

    registry = json.loads((ROOT / "skills/shared/app_registry.json").read_text())
    app = next(item for item in registry["apps"] if item.get("splunkbase_id") == "1841")
    assert app["latest_verified_version"] == "5.0.2"
    assert "10.6" in app["verified_platform_versions"]
    evidence = load_audit().selected_package_evidence(app)
    assert evidence["version"] == "5.0.2"
    assert evidence["supports"] is True


def test_newer_public_release_does_not_qualify_a_different_verified_pin() -> None:
    module = load_audit()
    app = next(
        app for app in __import__("json").loads((ROOT / "skills/shared/app_registry.json").read_text())["apps"]
        if app.get("splunkbase_id") == "2731"
    )
    # Model the earlier 4.3.2 pin so the guard still covers an
    # older-selected/newer-public mismatch after the repo verifies 4.3.3.
    app = dict(app)
    app["latest_verified_version"] = "4.3.2"
    app["verified_platform_versions"] = [
        version for version in app["verified_platform_versions"] if version != "10.6"
    ]
    evidence = module.selected_package_evidence(app)
    assert evidence["version"] == "4.3.2"
    assert evidence["supports"] is False
    assert "newer public" in evidence["evidence"]


def test_generated_enterprise_matrix_is_current() -> None:
    module = load_audit()
    payload = module.audit()
    assert (ROOT / "SPLUNK_ENTERPRISE_10_6_COMPATIBILITY.md").read_text() == module.render(payload)


def test_evidence_dates_preserve_baseline_and_allow_new_verification() -> None:
    module = load_audit()
    assert module.valid_evidence_date("2026-10-05", "2026-10-05")
    assert module.valid_evidence_date("2026-10-07", "2026-10-05")
    for invalid in ("", "20261007", "2026-10-7", "2026-02-30", "2026-10-04"):
        assert not module.valid_evidence_date(invalid, "2026-10-05")
    payload = module.audit()
    row = next(row for row in payload["skills"] if row["skill"] == "splunk-security-essentials-setup")
    assert row["verified"] == "2026-10-07"
    assert "| 2026-10-07 |" in module.render(payload)


def test_audit_json_from_relocated_library_without_git_or_credentials(tmp_path) -> None:
    """Portable audits resolve bundled inputs from the script, independent of cwd."""
    relocated = tmp_path / "relocated skill library"
    shutil.copytree(ROOT / "skills/shared", relocated / "skills/shared")
    shutil.copy2(ROOT / "skills/catalog.yaml", relocated / "skills/catalog.yaml")
    for path in (ROOT / "skills").glob("*/SKILL.md"):
        destination = relocated / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    result = subprocess.run(
        [sys.executable, "-S", str(relocated / "skills/shared/scripts/audit_splunk_enterprise_10_6_compatibility.py"), "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["skill_count"] == 169


def test_enterprise_matrix_escapes_package_table_separators() -> None:
    module = load_audit()
    payload = {
        "verified": "2026-10-05", "skill_count": 1, "counts": {"conditional": 1},
        "skills": [{"skill": "example", "status": "conditional", "packages": [
            {"id": "1", "name": "package|name", "evidence": "evidence|note"},
        ]}],
    }
    assert "package\\|name" in module.render(payload)
    assert "evidence\\|note" in module.render(payload)

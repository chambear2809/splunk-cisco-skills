from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from skills.shared.skill_catalog import load_catalog


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = REPO_ROOT / "skills/shared/scripts/audit_skill_compatibility.py"
GENERATOR_PATH = (
    REPO_ROOT / "skills/shared/scripts/generate_splunk_10_5_compatibility.py"
)


def load_audit_module():
    spec = importlib.util.spec_from_file_location("skill_compatibility_audit", AUDIT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_skill_has_an_enforced_splunk_cloud_10_5_classification() -> None:
    payload = load_audit_module().audit()
    assert payload["ok"], payload["findings"]
    assert payload["target"] == "10.5.2605"
    assert payload["skill_count"] == len(load_catalog().skills)
    assert sum(payload["status_counts"].values()) == payload["skill_count"]


def test_help_only_aliases_delegate_runtime_compatibility_to_replacements() -> None:
    catalog = load_catalog()
    payload = load_audit_module().audit()
    statuses = {row["skill"]: row["status"] for row in payload["skills"]}

    for legacy, canonical in catalog.aliases.items():
        assert catalog.by_name[legacy].deprecated
        assert statuses[legacy] == "delegated"
        assert statuses[canonical] != "delegated"


def test_latest_release_gaps_use_verified_10_5_pins() -> None:
    payload = load_audit_module().audit()
    statuses = {row["skill"]: row["status"] for row in payload["skills"]}
    release_specific = {
        "cisco-enterprise-networking-setup",
        "cisco-intersight-setup",
        "cisco-security-cloud-setup",
    }
    assert {skill: statuses[skill] for skill in release_specific} == {
        skill: "conditional" for skill in release_specific
    }
    registry = json.loads(
        (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
    )
    by_skill = {app["skill"]: app for app in registry["apps"]}
    for skill in release_specific:
        assert "10.5" not in by_skill[skill]["platform_versions"]
        assert "10.5" in by_skill[skill]["verified_platform_versions"]


def test_all_unsupported_registry_apps_have_non_unconditional_skill_status() -> None:
    payload = load_audit_module().audit()
    statuses = {row["skill"]: row["status"] for row in payload["skills"]}
    registry = json.loads(
        (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
    )
    offenders = []
    for app in registry["apps"]:
        if app.get("relationship", "primary") not in {"primary", "private-primary"}:
            continue
        if app.get("compatibility_status") != "unsupported":
            continue
        if statuses[app["skill"]] == "supported":
            offenders.append(f"{app['splunkbase_id']}:{app['skill']}")
    assert offenders == []


def test_private_packages_are_explicitly_classified() -> None:
    payload = load_audit_module().audit()
    mcp = next(row for row in payload["skills"] if row["skill"] == "splunk-mcp-server-setup")
    assert mcp["splunkbase_apps"] == [
        {
            "id": "",
            "name": "Splunk_MCP_Server",
            "relationship": "private-primary",
            "status": "nonproduction",
            "release_version": "",
            "verified_version": "1.2.1",
            "verified_status": "nonproduction",
            "cloud_compatible": None,
        }
    ]


def test_generic_installer_contains_fail_closed_version_and_release_gates() -> None:
    text = (
        REPO_ROOT / "skills/splunk-app-install/scripts/install_app.sh"
    ).read_text(encoding="utf-8")
    for phrase in (
        "preflight_current_install_target_compatibility",
        "require_registry_provenance",
        "audit_splunkbase_registry.py",
        "apply_registry_verified_version_default",
        "--target-splunk-version",
        "--accept-unsupported-platform",
        "--accept-unverified-release",
        "--accept-historical-review-only-pin",
        "does not advertise Splunk",
    ):
        assert phrase in text


def test_cloud_batch_installer_uses_the_same_fail_closed_contract() -> None:
    text = (
        REPO_ROOT / "skills/shared/scripts/cloud_batch_install.sh"
    ).read_text(encoding="utf-8")
    for phrase in (
        "preflight_app_compatibility",
        "require_registry_provenance",
        "audit_splunkbase_registry.py",
        "resolve_app_install_version",
        "--target-splunk-version",
        "--accept-unsupported-platform",
        "--accept-unverified-release",
        "--accept-historical-review-only-pin",
        "before ACS mutation",
    ):
        assert phrase in text


def test_generated_compatibility_matrix_is_current() -> None:
    spec = importlib.util.spec_from_file_location(
        "skill_compatibility_generator", GENERATOR_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = module.render()
    actual = (REPO_ROOT / "SPLUNK_10_5_COMPATIBILITY.md").read_text(
        encoding="utf-8"
    )
    assert actual == expected

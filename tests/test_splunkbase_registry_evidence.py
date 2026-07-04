#!/usr/bin/env python3
"""Regression tests for tracked Splunkbase metadata/release provenance."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT = REPO_ROOT / "skills/shared/scripts/audit_splunkbase_registry.py"
REGISTRY = REPO_ROOT / "skills/shared/app_registry.json"
EVIDENCE = REPO_ROOT / "skills/shared/references/splunkbase_registry_evidence.json"
GENERIC_INSTALL = REPO_ROOT / "skills/splunk-app-install/scripts/install_app.sh"
CLOUD_INSTALL = REPO_ROOT / "skills/shared/scripts/cloud_batch_install.sh"


def load_module():
    spec = importlib.util.spec_from_file_location("splunkbase_evidence_audit", AUDIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tracked_evidence_covers_and_binds_all_numeric_registry_apps() -> None:
    module = load_module()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    apps = module.registry_apps(registry)

    findings, evidence = module.audit_evidence(registry, apps, REGISTRY)

    assert findings == []
    assert evidence is not None
    assert evidence["app_count"] == len(apps) == 119
    assert [int(item["splunkbase_id"]) for item in evidence["apps"]] == sorted(
        int(app["splunkbase_id"]) for app in apps
    )
    assert evidence["registry_package_facts_sha256"] == (
        module.registry_package_facts_sha256(apps)
    )
    assert evidence["max_evidence_age_days"] == module.DEFAULT_MAX_EVIDENCE_AGE_DAYS
    assert registry["splunkbase_metadata_evidence"]["max_evidence_age_days"] == (
        module.DEFAULT_MAX_EVIDENCE_AGE_DAYS
    )


def test_evidence_marks_only_non_reproducible_reviewed_pins_as_historical() -> None:
    module = load_module()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    historical_ids = {
        str(app["splunkbase_id"])
        for app in registry["apps"]
        if app.get("verified_release_evidence_status") == module.HISTORICAL_ONLY_STATUS
    }
    evidence_historical_ids = {
        item["splunkbase_id"]
        for item in evidence["apps"]
        if item["verified_release"]["source_status"]
        == module.HISTORICAL_ONLY_STATUS
    }

    assert historical_ids == evidence_historical_ids == {
        "1761",
        "1928",
        "2911",
        "3549",
        "7557",
    }
    assert all(
        item["verified_release"]["source_status"]
        in {module.SOURCE_VERIFIED_STATUS, module.HISTORICAL_ONLY_STATUS}
        for item in evidence["apps"]
    )


def test_offline_evidence_fails_closed_when_registry_package_facts_drift() -> None:
    module = load_module()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    changed = copy.deepcopy(registry)
    app = next(item for item in changed["apps"] if item.get("splunkbase_id") == "8704")
    app["latest_verified_version"] = "0.4.0"

    findings, _ = module.audit_evidence(
        changed,
        module.registry_apps(changed),
        REGISTRY,
    )

    fields = {item["field"] for item in findings}
    assert "pointer.registry_package_facts_sha256" in fields
    assert "snapshot.registry_package_facts_sha256" in fields
    assert "apps.8704.registry_package_facts_sha256" in fields


def test_dependency_and_mutation_routing_fields_are_bound() -> None:
    module = load_module()
    required = {
        "label",
        "license_ack_url",
        "package_patterns",
        "install_requires",
        "role_support",
        "capabilities",
        "relationship",
        "compatibility_classification",
        "target_product",
    }
    assert required <= set(module.PACKAGE_FACT_FIELDS)

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    changed = copy.deepcopy(registry)
    app = next(item for item in changed["apps"] if item.get("splunkbase_id") == "7539")
    app["install_requires"] = ["7538", "8704"]
    findings, _ = module.audit_evidence(
        changed,
        module.registry_apps(changed),
        REGISTRY,
    )

    assert any("package-facts binding" in item["message"] for item in findings)


def test_dependency_schema_rejects_invalid_graphs() -> None:
    module = load_module()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    apps = module.registry_apps(registry)

    def findings_for(app_id: str, dependencies) -> list[dict]:
        changed = copy.deepcopy(apps)
        target = next(item for item in changed if item["splunkbase_id"] == app_id)
        target["install_requires"] = dependencies
        return module.audit_install_dependencies(changed)

    scenarios = (
        ("7539", "7538", "must be a list"),
        ("7539", [7538], "canonical non-zero numeric strings"),
        ("7539", ["0007538"], "canonical non-zero numeric strings"),
        ("7539", ["999999"], "target 999999 is missing"),
        ("7539", ["7539"], "self-dependency"),
        ("7539", ["7538", "7538"], "duplicate dependency 7538"),
    )
    for app_id, dependencies, expected in scenarios:
        findings = findings_for(app_id, dependencies)
        assert any(expected in item["message"] for item in findings)

    cycle_apps = copy.deepcopy(apps)
    next(item for item in cycle_apps if item["splunkbase_id"] == "7539")[
        "install_requires"
    ] = ["7538"]
    next(item for item in cycle_apps if item["splunkbase_id"] == "7538")[
        "install_requires"
    ] = ["7539"]
    findings = module.audit_install_dependencies(cycle_apps)
    assert any("dependency cycle detected" in item["message"] for item in findings)


def test_cloud_dependency_expansion_propagates_failures_and_protects_versions() -> None:
    script = CLOUD_INSTALL.read_text(encoding="utf-8")
    assert 'if ! expanded_output="$(expand_dependency_app_ids)"' in script
    assert "done < <(expand_dependency_app_ids)" not in script
    assert "dependency cycle detected" in script
    assert "--version requires exactly one explicitly requested root app ID" in script
    assert 'is_explicitly_requested_app_id "${app_id}"' in script


def test_offline_evidence_fails_closed_when_pointer_is_missing() -> None:
    module = load_module()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry.pop(module.EVIDENCE_POINTER_FIELD)

    findings, evidence = module.audit_evidence(
        registry,
        module.registry_apps(registry),
        REGISTRY,
    )

    assert evidence is None
    assert [item["field"] for item in findings] == [module.EVIDENCE_POINTER_FIELD]


def bound_fixture_with_date(tmp_path: Path, generated_date: str) -> tuple[dict, Path]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence["generated_date"] = generated_date
    evidence_path = tmp_path / "evidence.json"
    payload = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()
    evidence_path.write_bytes(payload)
    registry["splunkbase_metadata_evidence"]["path"] = "evidence.json"
    registry["splunkbase_metadata_evidence"]["generated_date"] = generated_date
    registry["splunkbase_metadata_evidence"]["sha256"] = hashlib.sha256(payload).hexdigest()
    registry_path = tmp_path / "app_registry.json"
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return registry, registry_path


def test_offline_evidence_rejects_future_date(tmp_path: Path) -> None:
    module = load_module()
    registry, registry_path = bound_fixture_with_date(tmp_path, "2026-07-04")

    findings, _ = module.audit_evidence(
        registry,
        module.registry_apps(registry),
        registry_path,
        today=module.date(2026, 7, 3),
    )

    assert any(item["message"] == "evidence date is in the future" for item in findings)


def test_offline_evidence_rejects_snapshot_older_than_max_age(tmp_path: Path) -> None:
    module = load_module()
    registry, registry_path = bound_fixture_with_date(tmp_path, "2026-03-01")

    findings, _ = module.audit_evidence(
        registry,
        module.registry_apps(registry),
        registry_path,
        today=module.date(2026, 7, 3),
        max_age_days=90,
    )

    assert any(item["message"] == "evidence exceeds the maximum age" for item in findings)


def test_read_only_audit_allows_explicit_freshness_window() -> None:
    result = subprocess.run(
        [
            "python3",
            str(AUDIT),
            "--max-evidence-age-days",
            "365",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_freshness_override_cannot_be_used_while_writing(tmp_path: Path) -> None:
    output = tmp_path / "must-not-write.json"
    result = subprocess.run(
        [
            "python3",
            str(AUDIT),
            "--live",
            "--write-evidence",
            str(output),
            "--max-evidence-age-days",
            "365",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "read-only audit option" in result.stderr
    assert not output.exists()


def test_installers_block_missing_or_tampered_evidence_before_mutation(
    tmp_path: Path,
) -> None:
    registry_source = json.loads(REGISTRY.read_text(encoding="utf-8"))
    evidence_bytes_source = EVIDENCE.read_bytes()
    cases: list[tuple[str, dict]] = []

    missing = copy.deepcopy(registry_source)
    missing.pop("splunkbase_metadata_evidence")
    cases.append(("missing", missing))

    tampered = copy.deepcopy(registry_source)
    evidence_path = tmp_path / "tampered-evidence.json"
    evidence_path.write_bytes(evidence_bytes_source + b" ")
    tampered["splunkbase_metadata_evidence"]["path"] = str(evidence_path)
    cases.append(("tampered", tampered))

    commands = (
        (
            "local",
            [
                "bash",
                str(GENERIC_INSTALL),
                "--source",
                "local",
                "--file",
                str(tmp_path / "unread-package.spl"),
                "--no-update",
                "--no-restart",
            ],
        ),
        (
            "acs",
            ["bash", str(CLOUD_INSTALL), "--no-restart", "8704"],
        ),
    )
    for case_name, registry in cases:
        registry_path = tmp_path / f"{case_name}-registry.json"
        registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        for path_name, command in commands:
            env = os.environ.copy()
            env["REGISTRY_FILE"] = str(registry_path)
            env["TA_CACHE"] = str(tmp_path / f"{case_name}-{path_name}-cache")
            result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            output = result.stdout + result.stderr
            assert result.returncode != 0
            assert "registry provenance validation failed" in output
            assert "before mutation" in output or "before ACS mutation" in output
            assert not Path(env["TA_CACHE"]).exists()


def test_local_unknown_numeric_id_requires_release_and_platform_approvals(
    tmp_path: Path,
) -> None:
    package = tmp_path / "unknown-app.spl"
    package.write_text("not reached", encoding="utf-8")
    base_command = [
        "bash",
        str(GENERIC_INSTALL),
        "--source",
        "local",
        "--file",
        str(package),
        "--app-id",
        "999999",
        "--no-update",
        "--no-restart",
    ]
    env = os.environ.copy()
    env["SPLUNK_PLATFORM"] = "enterprise"
    env["TA_CACHE"] = str(tmp_path / "cache")

    unacknowledged = subprocess.run(
        base_command,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    output = unacknowledged.stdout + unacknowledged.stderr
    assert unacknowledged.returncode != 0
    assert "outside the provenance-bound registry" in output
    assert "--accept-unverified-release" in output

    release_only = subprocess.run(
        [*base_command, "--accept-unverified-release"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    output = release_only.stdout + release_only.stderr
    assert release_only.returncode != 0
    assert "has no registry platform evidence" in output
    assert "--accept-unsupported-platform" in output


def test_listing_payload_hash_normalization_canonicalizes_next_data() -> None:
    module = load_module()
    first = b'<script id="__NEXT_DATA__" type="application/json">{"a":[2,1],"b":{"x":"stable"}}</script>'
    second = b'<div id="dynamic-ui-value"></div><script type="application/json" id="__NEXT_DATA__">{"b":{"x":"stable"},"a":[1,2]}</script>'

    assert module.sha256_bytes(module.canonical_listing_payload(first)) == (
        module.sha256_bytes(module.canonical_listing_payload(second))
    )
    assert b'"stable"' in module.canonical_listing_payload(first)


def test_evidence_builder_is_deterministic_for_order_and_date() -> None:
    module = load_module()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    tracked = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    apps = sorted(module.registry_apps(registry), key=lambda item: int(item["splunkbase_id"]))[:2]
    evidence_by_id = {item["splunkbase_id"]: item for item in tracked["apps"]}
    live = []
    for app in apps:
        item = evidence_by_id[str(app["splunkbase_id"])]
        verified = dict(item["verified_release"])
        verified.pop("source_status")
        live.append(
            {
                "splunkbase_id": str(app["splunkbase_id"]),
                "sources": item["sources"],
                "latest_release_facts": item["latest_release"],
                "verified_release_facts": verified,
            }
        )

    first = module.build_evidence(apps, live, "10.5", "2026-07-03")
    second = module.build_evidence(apps, list(reversed(live)), "10.5", "2026-07-03")

    assert module.evidence_bytes(first) == module.evidence_bytes(second)


def test_write_refreshes_stale_registry_pointer_in_one_workflow(tmp_path: Path) -> None:
    module = load_module()
    source = json.loads(REGISTRY.read_text(encoding="utf-8"))
    source[module.EVIDENCE_POINTER_FIELD] = {
        "schema_version": 1,
        "path": "old.json",
        "sha256": "0" * 64,
        "generated_date": "2026-01-01",
        "registry_package_facts_sha256": "0" * 64,
        "scope": module.EVIDENCE_SCOPE,
    }
    registry_path = tmp_path / "app_registry.json"
    registry_path.write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence_path = tmp_path / "evidence.json"
    file_hash = module.write_evidence(evidence_path, evidence)

    pointer = module.update_registry_evidence_pointer(
        registry_path,
        evidence_path,
        evidence,
        file_hash,
    )
    refreshed = json.loads(registry_path.read_text(encoding="utf-8"))
    findings, _ = module.audit_evidence(
        refreshed,
        module.registry_apps(refreshed),
        registry_path,
    )

    assert pointer["path"] == "evidence.json"
    assert pointer["sha256"] == file_hash
    assert evidence_path.stat().st_mode & 0o777 == 0o644
    assert registry_path.stat().st_mode & 0o777 == 0o644
    assert findings == []


def test_audit_script_remains_executable_for_documented_direct_use() -> None:
    assert os.access(AUDIT, os.X_OK)

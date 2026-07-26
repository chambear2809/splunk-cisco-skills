"""Regression coverage for repo-wide product and feature coverage contracts."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from tests.regression_helpers import REPO_ROOT


AUDIT = REPO_ROOT / "skills/shared/scripts/audit_product_feature_coverage.py"
MANIFEST = REPO_ROOT / "skills/shared/product_feature_coverage.json"


def run_audit(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDIT), "--json", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_product_feature_coverage_contract_passes() -> None:
    result = run_audit()

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["summary"]["app_registry:apps"] == payload["summary"]["app_registry:routed_apps"]
    assert payload["summary"]["router_contracts:covered"] == payload["summary"]["router_contracts:expected"]
    assert payload["summary"]["router_contracts:features"] >= 400
    assert (
        payload["summary"]["router_inventory:catalog_explicit"]
        == payload["summary"]["router_inventory:catalog_explicit_covered"]
    )
    router_hashes = {
        key: value
        for key, value in payload["summary"].items()
        if key.endswith(":feature_ids_sha256")
    }
    assert len(router_hashes) == payload["summary"]["router_contracts:expected"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in router_hashes.values())
    contract_hashes = {
        key: value
        for key, value in payload["summary"].items()
        if key.endswith(":feature_contracts_sha256")
    }
    assert len(contract_hashes) == payload["summary"]["router_contracts:expected"]
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", value)
        for value in contract_hashes.values()
    )


def write_manifest(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> Path:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mutate(payload)
    path = tmp_path / "product_feature_coverage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_product_feature_coverage_rejects_feature_scope_drift(
    tmp_path: Path,
) -> None:
    manifest = write_manifest(
        tmp_path,
        lambda payload: payload["routers"][0].__setitem__(
            "feature_ids_sha256", "0" * 64
        ),
    )

    result = run_audit(
        "--manifest",
        str(manifest),
        "--as-of",
        "2026-07-25",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any("feature ID snapshot drift" in error for error in payload["errors"])


def test_product_feature_coverage_rejects_semantic_contract_drift(
    tmp_path: Path,
) -> None:
    manifest = write_manifest(
        tmp_path,
        lambda payload: payload["routers"][0].__setitem__(
            "feature_contracts_sha256", "0" * 64
        ),
    )

    result = run_audit(
        "--manifest",
        str(manifest),
        "--as-of",
        "2026-07-25",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(
        "feature contract snapshot drift" in error
        for error in payload["errors"]
    )
    assert not any(
        "feature ID snapshot drift" in error for error in payload["errors"]
    )


def test_product_feature_coverage_rejects_missing_catalog_router(
    tmp_path: Path,
) -> None:
    def remove_widefield_router(payload: dict[str, Any]) -> None:
        payload["routers"] = [
            router
            for router in payload["routers"]
            if router["router_skill"] != "widefield-security-setup"
        ]
        payload["router_count"] = len(payload["routers"])

    manifest = write_manifest(tmp_path, remove_widefield_router)
    result = run_audit(
        "--manifest",
        str(manifest),
        "--as-of",
        "2026-07-25",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(
        "omits canonical catalog routers: widefield-security-setup" in error
        for error in payload["errors"]
    )


def test_product_feature_coverage_rejects_stale_provenance(
    tmp_path: Path,
) -> None:
    manifest = write_manifest(
        tmp_path,
        lambda payload: payload.__setitem__("maximum_source_age_days", 1),
    )

    result = run_audit(
        "--manifest",
        str(manifest),
        "--as-of",
        "2026-07-25",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any("is stale" in error for error in payload["errors"])


def test_product_feature_coverage_rejects_missing_automation_boundary(
    tmp_path: Path,
) -> None:
    def remove_boundary(payload: dict[str, Any]) -> None:
        payload["routers"][0]["status_contracts"]["automated"][
            "automation_boundary"
        ] = ""

    manifest = write_manifest(tmp_path, remove_boundary)
    result = run_audit(
        "--manifest",
        str(manifest),
        "--as-of",
        "2026-07-25",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any("lacks an automation_boundary" in error for error in payload["errors"])

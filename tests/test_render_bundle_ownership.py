"""Canonical renderer safety around bundles made by retired aliases."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from skills.shared.render_bundle_ownership import (
    MARKER_NAME,
    _HISTORICAL_RETIRED_ALIASES,
    _BUNDLE_COMPATIBILITY,
    _build_compatibility_contracts,
    _validate_marker,
    _write_marker,
    compatibility_contract,
)
from skills.shared.skill_catalog import CatalogError, load_catalog


REPO_ROOT = Path(__file__).resolve().parents[1]
RENDERERS = {
    "splunk-cim-data-model-setup": (
        "cim",
        ("--datamodel", "Authentication"),
    ),
    "splunk-dashboard-studio-setup": (
        "dashboard-studio",
        (
            "--dashboard-name",
            "ownership_test",
            "--search",
            "index=_internal | stats count",
        ),
    ),
    "splunk-ddaa-archive-setup": (
        "ddaa",
        (
            "--index",
            "main",
            "--searchable-days",
            "30",
            "--archival-retention-days",
            "90",
        ),
    ),
    "splunk-ingest-actions-setup": (
        "ingest-actions",
        (
            "--ruleset-sourcetype",
            "test",
            "--ruleset-name",
            "drop_debug",
            "--rule-type",
            "drop",
            "--drop-regex",
            "debug",
        ),
    ),
    "splunk-knowledge-objects-setup": (
        "knowledge-objects",
        (
            "--object-kind",
            "macro",
            "--name",
            "ownership_test",
            "--definition",
            "index=main",
        ),
    ),
    "splunk-kvstore-admin-setup": ("kvstore", ()),
    "splunk-secure-gateway-setup": ("secure-gateway", ()),
}


def _run_renderer(canonical: str, output_dir: Path) -> subprocess.CompletedProcess[str]:
    _, args = RENDERERS[canonical]
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / canonical / "scripts/render_assets.py"),
            "--output-dir",
            str(output_dir),
            *args,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_compatibility_extension_is_canonical_only_and_manifest_validated() -> None:
    contracts = _build_compatibility_contracts()

    assert set(contracts) == set(RENDERERS)
    assert set(contracts) == set(_BUNDLE_COMPATIBILITY)
    for canonical, contract in contracts.items():
        assert contract.retired_alias == "retired-renderer"
        assert contract.canonical == canonical


def test_unrelated_future_thin_alias_needs_no_bundle_contract() -> None:
    catalog = load_catalog()
    target = catalog.by_name["cisco-product-setup"]
    thin_alias = replace(
        target,
        name="unrelated-thin-alias",
        path="skills/unrelated-thin-alias/SKILL.md",
        status="deprecated",
        replaced_by=target.name,
    )
    extended = replace(catalog, skills=(*catalog.skills, thin_alias))

    contracts = _build_compatibility_contracts(extended)

    assert set(contracts) == set(RENDERERS)
    assert "cisco-product-setup" not in contracts


@pytest.mark.parametrize(
    "extension, message",
    [
        (
            {"cisco-product-setup": {"canonical_files": {"a"}, "retired_alias_files": {"b"}}},
            "exactly one manifest alias",
        ),
        (
            {"splunk-cim-data-model-setup": {"canonical_files": {"a"}}},
            "contain exactly",
        ),
        (
            {
                "splunk-cim-data-model-setup": {
                    "canonical_files": set(),
                    "retired_alias_files": {"b"},
                }
            },
            "half/empty",
        ),
    ],
)
def test_orphan_or_half_compatibility_contract_fails_closed(
    extension: dict[str, dict[str, set[str]]],
    message: str,
) -> None:
    with pytest.raises(CatalogError, match=message):
        _build_compatibility_contracts(extension=extension)


def test_marker_writer_retries_short_writes_and_publishes_complete_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compatibility_contract("splunk-cim-data-model-setup")
    marker = tmp_path / MARKER_NAME
    real_write = __import__("os").write
    write_calls = 0

    def short_write(descriptor: int, data: bytes) -> int:
        nonlocal write_calls
        write_calls += 1
        return real_write(descriptor, data[: max(1, len(data) // 3)])

    monkeypatch.setattr("skills.shared.render_bundle_ownership.os.write", short_write)

    _write_marker(marker, contract)

    assert write_calls > 1
    assert json.loads(marker.read_text(encoding="utf-8")) == {
        "canonical_owner": contract.canonical,
        "retired_alias": contract.retired_alias,
        "schema": 2,
    }
    assert not list(tmp_path.glob(f".{MARKER_NAME}.*.tmp"))


def test_marker_writer_failure_leaves_no_marker_or_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compatibility_contract("splunk-cim-data-model-setup")
    marker = tmp_path / MARKER_NAME

    def fail_write(descriptor: int, data: bytes) -> int:
        del descriptor, data
        raise OSError("injected write failure")

    monkeypatch.setattr("skills.shared.render_bundle_ownership.os.write", fail_write)

    with pytest.raises(OSError, match="injected write failure"):
        _write_marker(marker, contract)

    assert not marker.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("schema", [1, 2])
@pytest.mark.parametrize("canonical, aliases", sorted(_HISTORICAL_RETIRED_ALIASES.items()))
def test_canonical_renderer_accepts_historical_alias_marker(
    tmp_path: Path,
    schema: int,
    canonical: str,
    aliases: frozenset[str],
) -> None:
    contract = compatibility_contract(canonical)
    historical_alias = next(iter(aliases))
    marker = tmp_path / MARKER_NAME
    payload = (
        {
            "schema": schema,
            "owner": canonical,
            "incompatible_peer": historical_alias,
        }
        if schema == 1
        else {
            "schema": schema,
            "canonical_owner": canonical,
            "retired_alias": historical_alias,
        }
    )
    marker.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    _validate_marker(marker, contract)


@pytest.mark.parametrize("canonical", sorted(RENDERERS))
def test_canonical_renderer_rejects_legacy_owned_marker_without_deleting(
    tmp_path: Path,
    canonical: str,
) -> None:
    child, _ = RENDERERS[canonical]
    contract = compatibility_contract(canonical)
    render_dir = tmp_path / child
    render_dir.mkdir()
    sentinel = render_dir / "operator-note.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")
    marker = render_dir / MARKER_NAME
    marker.write_text(
        json.dumps(
            {
                "schema": 1,
                "owner": contract.retired_alias,
                "incompatible_peer": canonical,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_renderer(canonical, tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert f"retired alias '{contract.retired_alias}'" in output
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"
    assert marker.exists()


@pytest.mark.parametrize("canonical", sorted(RENDERERS))
def test_canonical_renderer_rejects_mixed_legacy_artifacts_without_deleting(
    tmp_path: Path,
    canonical: str,
) -> None:
    child, _ = RENDERERS[canonical]
    contract = compatibility_contract(canonical)
    render_dir = tmp_path / child
    render_dir.mkdir()
    retired_file = render_dir / sorted(contract.retired_only_files)[0]
    retired_file.write_text("legacy\n", encoding="utf-8")
    sentinel = render_dir / "operator-note.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")

    result = _run_renderer(canonical, tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert f"retired alias '{contract.retired_alias}'" in output
    assert retired_file.read_text(encoding="utf-8") == "legacy\n"
    assert sentinel.read_text(encoding="utf-8") == "preserve\n"

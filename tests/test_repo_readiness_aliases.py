"""Readiness regressions for manifest-declared thin compatibility aliases."""

from __future__ import annotations

from pathlib import Path

from skills.shared.skill_catalog import load_catalog
from tests import check_repo_readiness as readiness


def test_readiness_accepts_only_manifest_aliases_without_reference_docs(
    monkeypatch,
) -> None:
    catalog = load_catalog()
    errors: list[str] = []

    readiness.check_skill_surface_completeness(errors)

    for legacy in catalog.aliases:
        assert not (readiness.SKILLS_DIR / legacy / "reference.md").exists()
        assert not any(
            f"skills/{legacy}/reference.md: missing" in error for error in errors
        )

    canonical = next(record.name for record in catalog.skills if not record.deprecated)
    canonical_reference = readiness.SKILLS_DIR / canonical / "reference.md"
    real_is_file = Path.is_file

    def hide_one_canonical_reference(path: Path) -> bool:
        if path == canonical_reference:
            return False
        return real_is_file(path)

    monkeypatch.setattr(Path, "is_file", hide_one_canonical_reference)
    missing_errors: list[str] = []
    readiness.check_skill_surface_completeness(missing_errors)
    assert f"skills/{canonical}/reference.md: missing reference index" in missing_errors


def test_readiness_requires_alias_warning_and_canonical_command_handoff() -> None:
    errors: list[str] = []

    readiness.check_cursor_and_claude_commands(errors)

    assert errors == []

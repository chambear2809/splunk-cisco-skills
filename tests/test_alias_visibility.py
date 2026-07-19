"""User-facing alias lifecycle must never look like an ordinary peer skill."""

from __future__ import annotations

import json
import re
from pathlib import Path

from skills.shared.skill_catalog import load_catalog


REPO_ROOT = Path(__file__).resolve().parents[1]
ROW_SURFACES = (
    "AGENTS.md",
    "CLAUDE.md",
    "SKILL_UX_CATALOG.md",
    "SPLUNK_10_5_COMPATIBILITY.md",
    "SKILL_VALIDATION_MATRIX.md",
    "DEPLOYMENT_ROLE_MATRIX.md",
    "SKILL_REQUIREMENTS.md",
)


def _table_rows(text: str, skill: str) -> list[str]:
    pattern = re.compile(rf"^\| (?:\[)?`{re.escape(skill)}`")
    return [line for line in text.splitlines() if pattern.match(line)]


def test_every_user_facing_skill_table_visibly_labels_manifest_aliases() -> None:
    catalog = load_catalog()
    for relative in ROW_SURFACES:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for legacy, canonical in catalog.aliases.items():
            alias_rows = _table_rows(text, legacy)
            canonical_rows = _table_rows(text, canonical)
            assert alias_rows, f"{relative} omitted alias {legacy} without an alias policy"
            assert any(
                "Deprecated" in row and f"`{canonical}`" in row
                for row in alias_rows
            ), f"{relative} does not label {legacy} -> {canonical}"
            assert canonical_rows, f"{relative} omitted canonical skill {canonical}"


def test_deployment_extension_describes_aliases_as_help_only_not_peers() -> None:
    catalog = load_catalog()
    registry = json.loads(
        (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
    )
    topologies = {row["skill"]: row for row in registry["skill_topologies"]}
    for legacy, canonical in catalog.aliases.items():
        notes = topologies[legacy]["notes"]
        assert "Deprecated help-only compatibility alias" in notes
        assert canonical in notes
        assert "operational peer" in notes


def test_generated_alias_commands_show_warning_and_canonical_handoff() -> None:
    for legacy, canonical in load_catalog().aliases.items():
        text = (REPO_ROOT / ".claude/commands" / f"{legacy}.md").read_text(
            encoding="utf-8"
        )
        assert "[!WARNING]" in text
        assert "deprecated" in text.lower()
        assert canonical in text

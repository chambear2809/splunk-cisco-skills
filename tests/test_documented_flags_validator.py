"""Regression tests for nested documented-command flag validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "tests/check_documented_flags.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_documented_flags", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nested_reference_annexes_are_checked(tmp_path: Path, monkeypatch) -> None:
    checker = load_checker()
    repo = tmp_path / "repo"
    skill = repo / "skills/example"
    script = skill / "scripts/setup.sh"
    annex = skill / "references/nested/operator.md"
    script.parent.mkdir(parents=True)
    annex.parent.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Example\n", encoding="utf-8")
    script.write_text(
        '#!/usr/bin/env bash\ncase "${1:-}" in --supported) ;; esac\n',
        encoding="utf-8",
    )
    annex.write_text(
        "```bash\nbash skills/example/scripts/setup.sh --unsupported\n```\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(checker, "REPO_ROOT", repo)
    monkeypatch.setattr(checker, "SKILLS_DIR", repo / "skills")

    errors = checker.check_skill(skill)

    assert len(errors) == 1
    assert "references/nested/operator.md:2" in errors[0]
    assert "--unsupported" in errors[0]


def test_current_repository_documented_flags_pass() -> None:
    checker = load_checker()

    assert checker.main() == 0

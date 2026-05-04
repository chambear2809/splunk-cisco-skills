"""Regression coverage for the generated skill UX catalog."""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
CATALOG_PATH = REPO_ROOT / "SKILL_UX_CATALOG.md"
GENERATOR = REPO_ROOT / "skills/shared/scripts/generate_skill_ux_catalog.py"


def skill_names() -> set[str]:
    return {
        path.name
        for path in SKILLS_DIR.iterdir()
        if path.is_dir()
        and path.name != "shared"
        and not path.name.startswith(".")
        and (path / "SKILL.md").is_file()
    }


class SkillUXCatalogTests(unittest.TestCase):
    def test_catalog_is_current(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_catalog_covers_every_skill_once(self) -> None:
        text = CATALOG_PATH.read_text(encoding="utf-8")
        rows = re.findall(r"^\| `([^`]+)` \|", text, flags=re.MULTILINE)

        self.assertEqual(set(rows), skill_names())
        self.assertEqual(len(rows), len(set(rows)))

    def test_catalog_keeps_operator_safe_path_visible(self) -> None:
        text = CATALOG_PATH.read_text(encoding="utf-8")

        self.assertIn("Safe first command", text)
        self.assertIn("Validation", text)
        self.assertIn("never paste secrets into chat or argv", text)


if __name__ == "__main__":
    unittest.main()

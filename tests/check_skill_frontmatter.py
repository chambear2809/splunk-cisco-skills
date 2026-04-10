#!/usr/bin/env python3
"""Validate SKILL.md frontmatter: every skills/*/SKILL.md must have a YAML
frontmatter block with ``name`` matching its directory and a non-empty
``description``."""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---", re.DOTALL
)
NAME_RE = re.compile(r"^name:\s*(.+)$", re.MULTILINE)
DESC_RE = re.compile(r"^description:\s*", re.MULTILINE)


def check_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    dir_name = skill_dir.name

    if not skill_md.exists():
        errors.append(f"{dir_name}: missing SKILL.md")
        return errors

    text = skill_md.read_text(encoding="utf-8")
    fm = FRONTMATTER_RE.match(text)
    if not fm:
        errors.append(f"{dir_name}: SKILL.md missing YAML frontmatter (--- block)")
        return errors

    block = fm.group(1)

    name_match = NAME_RE.search(block)
    if not name_match:
        errors.append(f"{dir_name}: frontmatter missing 'name' field")
    else:
        name_value = name_match.group(1).strip()
        if name_value != dir_name:
            errors.append(
                f"{dir_name}: frontmatter name '{name_value}' does not match "
                f"directory name '{dir_name}'"
            )

    if not DESC_RE.search(block):
        errors.append(f"{dir_name}: frontmatter missing 'description' field")

    return errors


def main() -> int:
    skill_dirs = sorted(
        d for d in SKILLS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )

    if not skill_dirs:
        print("ERROR: no skill directories found under skills/", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    for skill_dir in skill_dirs:
        if skill_dir.name == "shared":
            continue
        all_errors.extend(check_skill(skill_dir))

    if all_errors:
        print("SKILL.md frontmatter errors:", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"All {len(skill_dirs) - 1} SKILL.md files pass frontmatter checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

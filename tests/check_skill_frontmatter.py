#!/usr/bin/env python3
"""Validate SKILL.md frontmatter with the same YAML semantics agents read."""

import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised when PyYAML is absent locally
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---", re.DOTALL
)


def parse_frontmatter(block: str) -> dict[str, str]:
    if yaml is not None:
        loaded = yaml.safe_load(block) or {}
        if not isinstance(loaded, dict):
            raise TypeError("YAML frontmatter must be a mapping")
        return loaded

    # Minimal fallback for local environments that have not installed
    # requirements-dev.txt yet. It supports the scalar and folded-block fields
    # used by SKILL.md files; CI installs PyYAML and uses the full parser.
    metadata: dict[str, str] = {}
    lines = block.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if ":" not in line:
            index += 1
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value in {">", ">-", "|", "|-"}:
            parts: list[str] = []
            index += 1
            while index < len(lines) and (lines[index].startswith(" ") or not lines[index].strip()):
                parts.append(lines[index].strip())
                index += 1
            metadata[key] = " ".join(part for part in parts if part)
            continue
        metadata[key] = value.strip("\"'")
        index += 1
    return metadata


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

    try:
        metadata = parse_frontmatter(fm.group(1))
    except Exception as exc:
        errors.append(f"{dir_name}: invalid YAML frontmatter: {exc}")
        return errors

    if not isinstance(metadata, dict):
        errors.append(f"{dir_name}: YAML frontmatter must be a mapping")
        return errors

    name_value = metadata.get("name")
    if not isinstance(name_value, str) or not name_value.strip():
        errors.append(f"{dir_name}: frontmatter missing 'name' field")
    elif name_value.strip() != dir_name:
        errors.append(
            f"{dir_name}: frontmatter name '{name_value}' does not match "
            f"directory name '{dir_name}'"
        )

    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{dir_name}: frontmatter missing non-empty 'description' field")
    elif len(description.strip()) < 60:
        errors.append(f"{dir_name}: frontmatter description is too short")

    if isinstance(description, str) and "Use when" not in description:
        errors.append(f"{dir_name}: frontmatter description must include a 'Use when' trigger")

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

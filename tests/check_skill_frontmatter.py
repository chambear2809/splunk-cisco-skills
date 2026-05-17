#!/usr/bin/env python3
"""Validate SKILL.md files against the Agent Skills frontmatter contract."""

import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised when PyYAML is absent locally
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORD_RE = re.compile(r"\S+")

SPEC_FRONTMATTER_KEYS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_COMPATIBILITY_LENGTH = 500
MAX_SKILL_MD_LINES = 500
MAX_BODY_WORDS = 5000


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

    unexpected_keys = sorted(set(metadata) - SPEC_FRONTMATTER_KEYS)
    if unexpected_keys:
        errors.append(
            f"{dir_name}: frontmatter contains non-spec field(s): "
            + ", ".join(unexpected_keys)
        )

    name_value = metadata.get("name")
    if not isinstance(name_value, str) or not name_value.strip():
        errors.append(f"{dir_name}: frontmatter missing 'name' field")
    else:
        name = name_value.strip()
        if len(name) > MAX_NAME_LENGTH:
            errors.append(
                f"{dir_name}: frontmatter name is {len(name)} characters; "
                f"maximum is {MAX_NAME_LENGTH}"
            )
        if not NAME_RE.fullmatch(name):
            errors.append(
                f"{dir_name}: frontmatter name must use lowercase letters, "
                "digits, and single hyphens only"
            )
        if name != dir_name:
            errors.append(
                f"{dir_name}: frontmatter name '{name_value}' does not match "
                f"directory name '{dir_name}'"
            )

    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{dir_name}: frontmatter missing non-empty 'description' field")
    elif len(description.strip()) > MAX_DESCRIPTION_LENGTH:
        errors.append(
            f"{dir_name}: frontmatter description is {len(description.strip())} "
            f"characters; maximum is {MAX_DESCRIPTION_LENGTH}"
        )
    else:
        if len(description.strip()) < 60:
            errors.append(f"{dir_name}: frontmatter description is too short")
        if "Use when" not in description:
            errors.append(
                f"{dir_name}: frontmatter description must include a 'Use when' trigger"
            )

    license_value = metadata.get("license")
    if license_value is not None and not isinstance(license_value, str):
        errors.append(f"{dir_name}: frontmatter license must be a string when present")

    compatibility = metadata.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str) or not compatibility.strip():
            errors.append(
                f"{dir_name}: frontmatter compatibility must be a non-empty string"
            )
        elif len(compatibility.strip()) > MAX_COMPATIBILITY_LENGTH:
            errors.append(
                f"{dir_name}: frontmatter compatibility is "
                f"{len(compatibility.strip())} characters; maximum is "
                f"{MAX_COMPATIBILITY_LENGTH}"
            )

    metadata_value = metadata.get("metadata")
    if metadata_value is not None:
        if not isinstance(metadata_value, dict):
            errors.append(f"{dir_name}: frontmatter metadata must be a mapping")
        else:
            for key, value in metadata_value.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    errors.append(
                        f"{dir_name}: frontmatter metadata entries must be string "
                        "keys and string values"
                    )
                    break

    allowed_tools = metadata.get("allowed-tools")
    if allowed_tools is not None and not isinstance(allowed_tools, str):
        errors.append(f"{dir_name}: frontmatter allowed-tools must be a string")

    lines = text.splitlines()
    if len(lines) > MAX_SKILL_MD_LINES:
        errors.append(
            f"{dir_name}: SKILL.md has {len(lines)} lines; keep it under "
            f"{MAX_SKILL_MD_LINES} lines and move details to references/"
        )

    body = text[fm.end() :]
    body_words = len(WORD_RE.findall(body))
    if body_words > MAX_BODY_WORDS:
        errors.append(
            f"{dir_name}: SKILL.md body has about {body_words} words; move "
            "detailed reference material to references/"
        )

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
    checked_count = 0
    for skill_dir in skill_dirs:
        if skill_dir.name == "shared":
            continue
        if not (skill_dir / "SKILL.md").exists() and not any(
            path.is_file() for path in skill_dir.rglob("*")
        ):
            continue
        all_errors.extend(check_skill(skill_dir))
        checked_count += 1

    if all_errors:
        print("SKILL.md frontmatter errors:", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"All {checked_count} SKILL.md files pass frontmatter checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

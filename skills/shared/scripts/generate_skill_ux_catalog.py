#!/usr/bin/env python3
"""Generate the top-level skill UX catalog from SKILL.md metadata."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - local fallback
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
OUTPUT_PATH = REPO_ROOT / "SKILL_UX_CATALOG.md"

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)
GENERATED_BANNER = (
    "_Generated from `skills/*/SKILL.md` and local skill files by "
    "`skills/shared/scripts/generate_skill_ux_catalog.py`; do not edit manually._"
)

ASCII_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate SKILL_UX_CATALOG.md from repo-local skill metadata."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if SKILL_UX_CATALOG.md differs from generated output.",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Write generated output to SKILL_UX_CATALOG.md.",
    )
    return parser.parse_args()


def ascii_text(value: str) -> str:
    return value.translate(ASCII_TRANSLATION).encode("ascii", "ignore").decode("ascii")


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", ascii_text(value)).strip()


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    block = match.group(1)
    if yaml is not None:
        loaded = yaml.safe_load(block) or {}
        if not isinstance(loaded, dict):
            return {}
        return {str(key): compact(str(value or "")) for key, value in loaded.items()}

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
            while index < len(lines) and (
                lines[index].startswith(" ") or not lines[index].strip()
            ):
                parts.append(lines[index].strip())
                index += 1
            metadata[key] = compact(" ".join(part for part in parts if part))
            continue
        metadata[key] = compact(value.strip("\"'"))
        index += 1
    return metadata


def skill_dirs() -> list[Path]:
    return sorted(
        path
        for path in SKILLS_DIR.iterdir()
        if path.is_dir()
        and path.name != "shared"
        and not path.name.startswith(".")
        and (path / "SKILL.md").is_file()
    )


def template_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    primary = skill_dir / "template.example"
    if primary.is_file():
        files.append(primary)
    templates_dir = skill_dir / "templates"
    if templates_dir.is_dir():
        for path in sorted(templates_dir.rglob("*")):
            if path.is_file() and not any(
                part.startswith(".") for part in path.relative_to(templates_dir).parts
            ):
                files.append(path)
    return files


def reference_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    primary = skill_dir / "reference.md"
    if primary.is_file():
        files.append(primary)
    references_dir = skill_dir / "references"
    if references_dir.is_dir():
        files.extend(sorted(path for path in references_dir.glob("*.md") if path.is_file()))
    return files


def scripts(skill_dir: Path) -> list[str]:
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return []
    return sorted(path.name for path in scripts_dir.iterdir() if path.is_file())


def split_description(description: str) -> tuple[str, str]:
    marker = " Use when "
    if marker in description:
        before, after = description.split(marker, 1)
        return compact(before), compact(f"Use when {after}")
    return compact(description), ""


def first_sentence(value: str, limit: int = 150) -> str:
    sentence_match = re.search(r"(.+?[.!?])(?:\s|$)", value)
    sentence = sentence_match.group(1) if sentence_match else value
    sentence = compact(sentence)
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 3].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


def category_for(skill_name: str) -> str:
    if skill_name.startswith("cisco-"):
        return "Cisco Product And App Setup"
    if skill_name.startswith("splunk-observability"):
        return "Splunk Observability"
    security_markers = (
        "security",
        "soar",
        "uba",
        "oncall",
        "attack-analyzer",
        "asset-risk",
    )
    if any(marker in skill_name for marker in security_markers):
        return "Security And Response"
    if any(marker in skill_name for marker in ("connect-for", "stream", "forwarder")):
        return "Collectors And Forwarders"
    return "Splunk Platform Operations"


def command_for(skill_name: str, script_names: list[str], preferred: str | None = None) -> str:
    selected = preferred if preferred in script_names else None
    if selected is None and script_names:
        selected = script_names[0]
    if selected is None:
        return "Read `SKILL.md`"

    rel_path = f"skills/{skill_name}/scripts/{selected}"
    suffix = Path(selected).suffix
    if suffix == ".py":
        return f"`python3 {rel_path} --help`"
    if suffix == ".rb":
        return f"`ruby {rel_path} --help`"
    return f"`bash {rel_path} --help`"


def safe_first_command(skill_name: str, script_names: list[str]) -> str:
    for preferred in ("setup.sh", "render_assets.py", "render_dashboard.py", "render_native_ops.py"):
        if preferred in script_names:
            return command_for(skill_name, script_names, preferred)
    return command_for(skill_name, script_names)


def validation_command(skill_name: str, script_names: list[str]) -> str:
    for preferred in (
        "validate.sh",
        "validate_dashboard.py",
        "validate_native_ops.py",
        "validate_oncall.py",
    ):
        if preferred in script_names:
            return command_for(skill_name, script_names, preferred)
    return "See `SKILL.md`"


def summarize_paths(skill_dir: Path, paths: list[Path], empty_text: str) -> str:
    if not paths:
        return empty_text
    rels = [path.relative_to(skill_dir).as_posix() for path in paths]
    if len(rels) <= 2:
        return ", ".join(f"`{rel}`" for rel in rels)
    return f"`{rels[0]}` plus {len(rels) - 1} more"


def escape_cell(value: str) -> str:
    return compact(value).replace("|", r"\|")


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(escape_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def skill_row(skill_dir: Path) -> tuple[str, list[str]]:
    skill_md = skill_dir / "SKILL.md"
    metadata = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    name = metadata.get("name") or skill_dir.name
    description, use_when = split_description(metadata.get("description", ""))
    script_names = scripts(skill_dir)
    templates = template_files(skill_dir)
    references = reference_files(skill_dir)
    intake = summarize_paths(skill_dir, templates, "No intake template")
    refs = summarize_paths(skill_dir, references, "`SKILL.md` only")
    start = (
        f"Start with {intake}"
        if templates
        else "Start with `SKILL.md` and the safe command"
    )
    if use_when:
        start = f"{start}. {first_sentence(use_when, 110)}"

    return category_for(name), [
        f"`{name}`",
        first_sentence(description),
        start,
        safe_first_command(name, script_names),
        validation_command(name, script_names),
        refs,
    ]


def render_catalog() -> str:
    rows_by_category: dict[str, list[list[str]]] = {}
    for skill_dir in skill_dirs():
        category, row = skill_row(skill_dir)
        rows_by_category.setdefault(category, []).append(row)

    lines = [
        "# Skill UX Catalog",
        "",
        GENERATED_BANNER,
        "",
        "This catalog is the user-facing entry point for choosing and consuming a skill.",
        "Every row gives an operator the smallest safe path into that skill before",
        "they open the longer instructions.",
        "",
        "## How To Use This Catalog",
        "",
        "1. Pick the skill whose summary matches the user's goal.",
        "2. Open the listed intake template when one exists and collect only non-secret values.",
        "3. Run the safe first command to inspect flags before any setup or apply path.",
        "4. Keep all credentials in local files; never paste secrets into chat or argv.",
        "5. Run the validation command after setup, or use it first to inspect existing state.",
        "",
    ]

    headers = [
        "Skill",
        "Plain-language purpose",
        "Start here",
        "Safe first command",
        "Validation",
        "Deeper docs",
    ]
    for category in sorted(rows_by_category):
        lines.extend(
            [
                f"## {category}",
                "",
                markdown_table(headers, rows_by_category[category]),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    rendered = render_catalog()
    if args.write:
        OUTPUT_PATH.write_text(rendered, encoding="utf-8")
        return 0
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        if current != rendered:
            print(
                "SKILL_UX_CATALOG.md is out of date. Run "
                "`python3 skills/shared/scripts/generate_skill_ux_catalog.py --write`.",
                file=sys.stderr,
            )
            return 1
        return 0
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

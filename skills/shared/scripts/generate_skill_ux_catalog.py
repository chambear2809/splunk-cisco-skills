#!/usr/bin/env python3
"""Generate the top-level skill UX catalog from the canonical manifest."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - local fallback
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.shared.skill_catalog import SkillCatalog, SkillRecord, load_catalog  # noqa: E402


SKILLS_DIR = REPO_ROOT / "skills"
OUTPUT_PATH = REPO_ROOT / "SKILL_UX_CATALOG.md"
PRODUCT_REGISTRY_PATH = SKILLS_DIR / "shared" / "skill_product_registry.json"

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)
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


def skill_dirs(catalog: SkillCatalog | None = None) -> list[Path]:
    manifest = catalog or load_catalog()
    return [(REPO_ROOT / record.path).parent for record in manifest.skills]


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


def load_product_registry(catalog: SkillCatalog) -> list[dict[str, Any]]:
    try:
        payload = json.loads(PRODUCT_REGISTRY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing product registry: {PRODUCT_REGISTRY_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid product registry JSON: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise ValueError("product registry must be an object with schema_version 2")
    expected_provenance = {
        "path": "skills/catalog.yaml",
        "schema_version": catalog.schema_version,
        "sha256": catalog.checksum,
    }
    if payload.get("generated_from") != expected_provenance:
        raise ValueError(
            "product registry provenance does not match skills/catalog.yaml; "
            "run generate_skill_catalog.py --write"
        )
    expected_skill_records = [
        {
            "name": record.name,
            "status": record.status,
            "replaced_by": record.replaced_by,
        }
        for record in catalog.skills
    ]
    if payload.get("skill_records") != expected_skill_records:
        raise ValueError(
            "product registry lifecycle records do not match skills/catalog.yaml; "
            "run generate_skill_catalog.py --write"
        )
    products = payload.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError("product registry products must be a non-empty list")

    product_ids: set[str] = set()
    product_names: set[str] = set()
    classified: dict[str, str] = {}
    for product_index, product in enumerate(products):
        location = f"products[{product_index}]"
        if not isinstance(product, dict):
            raise ValueError(f"{location} must be an object")
        product_id = product.get("id")
        product_name = product.get("name")
        description = product.get("description")
        capabilities = product.get("capabilities")
        if not isinstance(product_id, str) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", product_id
        ):
            raise ValueError(f"{location}.id must be a lowercase hyphenated identifier")
        if not isinstance(product_name, str) or not product_name.strip():
            raise ValueError(f"{location}.name must be a non-empty string")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"{location}.description must be a non-empty string")
        if product_id in product_ids:
            raise ValueError(f"duplicate product id: {product_id}")
        if product_name in product_names:
            raise ValueError(f"duplicate product name: {product_name}")
        product_ids.add(product_id)
        product_names.add(product_name)
        if not isinstance(capabilities, list) or not capabilities:
            raise ValueError(f"{location}.capabilities must be a non-empty list")

        capability_ids: set[str] = set()
        capability_names: set[str] = set()
        for capability_index, capability in enumerate(capabilities):
            capability_location = f"{location}.capabilities[{capability_index}]"
            if not isinstance(capability, dict):
                raise ValueError(f"{capability_location} must be an object")
            capability_id = capability.get("id")
            capability_name = capability.get("name")
            names = capability.get("skills")
            if not isinstance(capability_id, str) or not re.fullmatch(
                r"[a-z0-9]+(?:-[a-z0-9]+)*", capability_id
            ):
                raise ValueError(
                    f"{capability_location}.id must be a lowercase hyphenated identifier"
                )
            if not isinstance(capability_name, str) or not capability_name.strip():
                raise ValueError(
                    f"{capability_location}.name must be a non-empty string"
                )
            if capability_id in capability_ids:
                raise ValueError(
                    f"duplicate capability id {capability_id!r} in product {product_id!r}"
                )
            if capability_name in capability_names:
                raise ValueError(
                    f"duplicate capability name {capability_name!r} in product {product_id!r}"
                )
            capability_ids.add(capability_id)
            capability_names.add(capability_name)
            if not isinstance(names, list) or not names:
                raise ValueError(
                    f"{capability_location}.skills must be a non-empty list"
                )
            if names != sorted(names):
                raise ValueError(f"{capability_location}.skills must be alphabetized")
            for skill_name in names:
                if not isinstance(skill_name, str) or not skill_name:
                    raise ValueError(
                        f"{capability_location}.skills must contain non-empty strings"
                    )
                owner = f"{product_name} / {capability_name}"
                if skill_name in classified:
                    raise ValueError(
                        f"skill {skill_name!r} is classified more than once: "
                        f"{classified[skill_name]} and {owner}"
                    )
                classified[skill_name] = owner

    manifest_names = set(catalog.by_name)
    missing = sorted(manifest_names - set(classified))
    unknown = sorted(set(classified) - manifest_names)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("unclassified skills: " + ", ".join(missing))
        if unknown:
            details.append("unknown skills: " + ", ".join(unknown))
        raise ValueError(
            "product registry does not match skills/catalog.yaml: "
            + "; ".join(details)
        )

    return products


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


def skill_row(skill_dir: Path, record: SkillRecord) -> list[str]:
    skill_md = skill_dir / "SKILL.md"
    metadata = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    name = record.name
    _, use_when = split_description(metadata.get("description", ""))
    compatibility = metadata.get("compatibility", "Compatibility not classified")
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

    return [
        f"`{name}`",
        (
            f"**Deprecated** -> `{record.replaced_by}`"
            if record.deprecated
            else "Canonical"
        ),
        first_sentence(record.purpose),
        first_sentence(compatibility),
        start,
        safe_first_command(name, script_names),
        validation_command(name, script_names),
        refs,
    ]


def render_catalog() -> str:
    catalog = load_catalog()
    products = load_product_registry(catalog)
    rows_by_skill: dict[str, list[str]] = {}
    for record in catalog.skills:
        skill_md = REPO_ROOT / record.path
        rows_by_skill[record.name] = skill_row(skill_md.parent, record)

    generated_banner = (
        "_Generated from `skills/catalog.yaml` "
        f"(schema {catalog.schema_version}, SHA-256 `{catalog.checksum}`), "
        "repo-local skill files, and the manifest-generated "
        "`skills/shared/skill_product_registry.json` by "
        "`skills/shared/scripts/generate_skill_ux_catalog.py`; do not edit manually._"
    )

    lines = [
        "# Skill UX Catalog",
        "",
        generated_banner,
        "",
        "This product-first catalog is the user-facing entry point for choosing and",
        "consuming a skill. Canonical skill directories remain flat at",
        "`skills/<skill-name>/` so commands, editor integrations, and automation keep",
        "stable paths. Every skill has one primary product and capability here; use the",
        "skill summary to identify cross-product handoffs.",
        "",
        "## How To Use This Catalog",
        "",
        "1. Pick the skill whose summary matches the user's goal.",
        "2. Open the listed intake template when one exists and collect only non-secret values.",
        "3. Run the safe first command to inspect flags before any setup or apply path.",
        "4. Keep all credentials in local files; never paste secrets into chat or argv.",
        "5. Run the validation command after setup, or use it first to inspect existing state.",
        "",
        "## Product Index",
        "",
    ]

    product_index_rows: list[list[str]] = []
    for product in products:
        count = sum(len(capability["skills"]) for capability in product["capabilities"])
        anchor = re.sub(r"[^a-z0-9]+", "-", product["name"].lower()).strip("-")
        product_index_rows.append(
            [
                f"[{product['name']}](#{anchor})",
                product["description"],
                str(count),
            ]
        )
    lines.extend(
        [
            markdown_table(["Product", "Scope", "Skills"], product_index_rows),
            "",
        ]
    )

    headers = [
        "Skill",
        "Lifecycle",
        "Plain-language purpose",
        "Splunk 10.5 compatibility",
        "Start here",
        "Safe first command",
        "Validation",
        "Deeper docs",
    ]
    for product in products:
        lines.extend([f"## {product['name']}", "", product["description"], ""])
        for capability in product["capabilities"]:
            rows = [rows_by_skill[name] for name in capability["skills"]]
            lines.extend(
                [
                    f"### {capability['name']}",
                    "",
                    markdown_table(headers, rows),
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    try:
        rendered = render_catalog()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
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

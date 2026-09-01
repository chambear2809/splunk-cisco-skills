#!/usr/bin/env python3
"""Generate and check all direct surfaces of skills/catalog.yaml."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.shared.skill_catalog import (  # noqa: E402
    CatalogError,
    SkillCatalog,
    SkillRecord,
    command_handoff_boilerplate,
    load_catalog,
    parse_requirement_skill_rows,
)
from skills.shared.skill_validation import normalize_evidence_extension  # noqa: E402


CATALOG_BEGIN = "<!-- BEGIN GENERATED SKILL CATALOG -->"
CATALOG_END = "<!-- END GENERATED SKILL CATALOG -->"
MCP_BEGIN = "<!-- BEGIN GENERATED LOCAL SKILL MCP SAFETY -->"
MCP_END = "<!-- END GENERATED LOCAL SKILL MCP SAFETY -->"
MANAGED_DOCS = ("AGENTS.md", "CLAUDE.md")
COMMANDS_DIR = Path(".claude/commands")
CURSOR_SKILLS_DIR = Path(".cursor/skills")
PRODUCT_REGISTRY = Path("skills/shared/skill_product_registry.json")
APP_REGISTRY = Path("skills/shared/app_registry.json")
VALIDATION_REGISTRY = Path("skills/shared/skill_validation_registry.json")
REQUIREMENTS_DOC = Path("SKILL_REQUIREMENTS.md")
ALIAS_MIGRATION_DOC = Path("skills/shared/deprecated_skill_aliases.md")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)
GENERATED_COMMAND_RE = re.compile(
    r"\A<!-- Generated from skills/catalog\.yaml; schema: \d+; "
    r"entry-sha256: [0-9a-f]{64}\. -->\n"
)
GENERATED_CURSOR_TARGET_RE = re.compile(r"\.\./\.\./skills/[a-z0-9]+(?:-[a-z0-9]+)*")


def _has_generated_cursor_provenance(path: Path, target: str) -> bool:
    """Recognize only the exact name-preserving link shape emitted here."""

    return bool(
        GENERATED_CURSOR_TARGET_RE.fullmatch(target)
        and path.name == Path(target).name
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate direct catalog, command, link, and shared safety surfaces."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Write stale generated surfaces.")
    mode.add_argument("--check", action="store_true", help="Fail if any surface is stale.")
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def _managed_relative(root: Path, path: Path) -> Path:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise CatalogError(f"managed path escapes repository root: {path}") from exc
    if not relative.parts or ".." in relative.parts:
        raise CatalogError(f"invalid managed path: {path}")
    return relative


def _validate_root(root: Path) -> None:
    try:
        info = os.lstat(root)
    except FileNotFoundError as exc:
        raise CatalogError(f"repository root does not exist: {root}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise CatalogError(f"repository root must be a real directory: {root}")


def _ensure_managed_parent(root: Path, path: Path, *, create: bool) -> None:
    """Reject symlink traversal and keep every managed parent below root."""

    relative = _managed_relative(root, path)
    root_resolved = root.resolve(strict=True)
    current = root
    for part in relative.parent.parts:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if not create:
                raise CatalogError(f"missing managed parent directory: {current}")
            try:
                os.mkdir(current, 0o755)
            except FileExistsError:
                pass
            info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise CatalogError(
                f"managed parent must be a real directory, not a link or file: {current}"
            )
        resolved = current.resolve(strict=True)
        if resolved != root_resolved and not resolved.is_relative_to(root_resolved):
            raise CatalogError(f"managed parent resolves outside repository root: {current}")


def _managed_file_info(
    root: Path,
    path: Path,
    *,
    required: bool,
    create_parent: bool = False,
) -> os.stat_result | None:
    _ensure_managed_parent(root, path, create=create_parent)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if required:
            raise CatalogError(f"missing managed file: {path.relative_to(root)}")
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise CatalogError(
            f"managed output must be a regular file, not a link or special file: "
            f"{path.relative_to(root)}"
        )
    if info.st_nlink != 1:
        raise CatalogError(
            f"managed output must have exactly one hard link: {path.relative_to(root)}"
        )
    return info


def _read_managed_text(root: Path, path: Path, *, required: bool) -> str | None:
    info = _managed_file_info(root, path, required=required)
    if info is None:
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_dev != info.st_dev
            or opened.st_ino != info.st_ino
        ):
            raise CatalogError(
                f"managed output changed during safe open: {path.relative_to(root)}"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            return stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_required_source_text(root: Path, path: Path) -> str:
    """Read a root-confined, non-linked source file without following links."""

    _ensure_managed_parent(root, path, create=False)
    try:
        info = os.lstat(path)
    except FileNotFoundError as exc:
        raise CatalogError(f"missing managed source: {path.relative_to(root)}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise CatalogError(
            "managed source must be a regular file, not a link or special file: "
            f"{path.relative_to(root)}"
        )
    if info.st_nlink != 1:
        raise CatalogError(
            f"managed source must have exactly one hard link: {path.relative_to(root)}"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_dev != info.st_dev
            or opened.st_ino != info.st_ino
        ):
            raise CatalogError(
                f"managed source changed during safe open: {path.relative_to(root)}"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            return stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _managed_directory_exists(root: Path, path: Path) -> bool:
    _ensure_managed_parent(root, path, create=False)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise CatalogError(
            f"managed directory must be a real directory: {path.relative_to(root)}"
        )
    return True


def _escape_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", r"\|")


def _lifecycle(record: SkillRecord) -> str:
    if record.deprecated:
        return f"Deprecated -> `{record.replaced_by}`"
    return "Canonical"


def render_catalog_block(catalog: SkillCatalog) -> str:
    lines = [
        CATALOG_BEGIN,
        (
            "<!-- source: skills/catalog.yaml; schema: "
            f"{catalog.schema_version}; sha256: {catalog.checksum} -->"
        ),
        "## Skill Index",
        "",
        (
            f"The complete {catalog.declared_skill_count}-entry catalog is maintained "
            "in `skills/catalog.yaml`. If a product term or alias does not clearly match "
            "a skill name below, search that catalog for the term before selecting a "
            "skill. Read only the selected skill's `SKILL.md` on demand."
        ),
        "",
        "| Skill | Instructions | Lifecycle |",
        "| --- | --- | --- |",
    ]
    for record in catalog.skills:
        lines.append(
            f"| `{record.name}` | `{_escape_cell(record.path)}` | "
            f"{_lifecycle(record)} |"
        )
    lines.append(CATALOG_END)
    return "\n".join(lines)


def render_mcp_block(catalog: SkillCatalog) -> str:
    return "\n".join(
        [
            MCP_BEGIN,
            (
                "<!-- source: skills/catalog.yaml#shared_sections.local_skill_mcp_server; "
                f"schema: {catalog.schema_version}; sha256: {catalog.checksum} -->"
            ),
            catalog.shared_sections["local_skill_mcp_server"],
            MCP_END,
        ]
    )


def _replace_generated_or_legacy_section(
    text: str,
    *,
    begin: str,
    end: str,
    legacy_start: str,
    legacy_next: str,
    rendered: str,
) -> str:
    if begin in text or end in text:
        if text.count(begin) != 1 or text.count(end) != 1:
            raise CatalogError(f"malformed generated markers {begin!r}/{end!r}")
        pattern = re.compile(
            rf"^{re.escape(begin)}\n.*?^{re.escape(end)}\n*(?="
            rf"^{re.escape(legacy_next)}\n)",
            re.MULTILINE | re.DOTALL,
        )
    else:
        pattern = re.compile(
            rf"^{re.escape(legacy_start)}\n.*?(?=^{re.escape(legacy_next)}\n)",
            re.MULTILINE | re.DOTALL,
        )
    updated, count = pattern.subn(lambda _match: rendered + "\n\n", text, count=1)
    if count != 1:
        raise CatalogError(
            f"could not locate exactly one section starting with {legacy_start!r}"
        )
    return updated


def render_context_doc(text: str, catalog: SkillCatalog) -> str:
    updated = _replace_generated_or_legacy_section(
        text,
        begin=CATALOG_BEGIN,
        end=CATALOG_END,
        legacy_start="## Skill Catalog",
        legacy_next="## Splunk MCP Server",
        rendered=render_catalog_block(catalog),
    )
    updated = _replace_generated_or_legacy_section(
        updated,
        begin=MCP_BEGIN,
        end=MCP_END,
        legacy_start="## Local Skill MCP Server",
        legacy_next="## Credentials",
        rendered=render_mcp_block(catalog),
    )
    return updated.rstrip() + "\n"


def render_command(catalog: SkillCatalog, record: SkillRecord) -> str:
    handoff_skill = record.replaced_by if record.deprecated else record.name
    assert handoff_skill is not None
    lines = [
        (
            "<!-- Generated from skills/catalog.yaml; schema: "
            f"{catalog.schema_version}; entry-sha256: {catalog.entry_checksum(record)}. -->"
        ),
        "",
    ]
    if record.deprecated:
        lines.extend(
            [
                (
                    f"> [!WARNING]\n> `{record.name}` is deprecated and replaced by "
                    f"`{record.replaced_by}`. Use `/{record.replaced_by}` for new work."
                ),
                (
                    f"> Read `skills/{record.name}/SKILL.md` for the compatibility "
                    "warning only; follow the canonical documents below for all work."
                ),
                "",
            ]
        )
    lines.extend(
        [
            record.command_summary,
            "",
            command_handoff_boilerplate(handoff_skill),
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _load_json(root: Path, relative: Path) -> dict[str, Any]:
    path = root / relative

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"duplicate JSON key: {key!r}")
            payload[key] = value
        return payload

    def reject_non_finite(value: str) -> None:
        raise ValueError(f"non-finite JSON constant is not allowed: {value}")

    try:
        content = _read_managed_text(root, path, required=True)
        assert content is not None
        payload = json.loads(
            content,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise CatalogError(f"invalid JSON in {relative}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CatalogError(f"{relative} must contain a JSON object")
    return payload


def _provenance(catalog: SkillCatalog) -> dict[str, object]:
    return {
        "path": "skills/catalog.yaml",
        "schema_version": catalog.schema_version,
        "sha256": catalog.checksum,
    }


def render_product_registry(catalog: SkillCatalog) -> str:
    """Render product grouping entirely from manifest taxonomy and skill entries."""

    skills_by_capability: dict[tuple[str, str], list[str]] = {}
    for record in catalog.skills:
        skills_by_capability.setdefault(
            (record.product, record.capability), []
        ).append(record.name)
    capabilities_by_product: dict[str, list[dict[str, object]]] = {}
    for capability in catalog.capabilities:
        capabilities_by_product.setdefault(capability.product, []).append(
            {
                "id": capability.id,
                "name": capability.name,
                "skills": sorted(
                    skills_by_capability[(capability.product, capability.id)]
                ),
            }
        )
    payload = {
        "schema_version": 2,
        "generated_from": _provenance(catalog),
        "skill_records": [
            {
                "name": record.name,
                "status": record.status,
                "replaced_by": record.replaced_by,
            }
            for record in catalog.skills
        ],
        "products": [
            {
                "id": product.id,
                "name": product.name,
                "description": product.description,
                "capabilities": capabilities_by_product[product.id],
            }
            for product in catalog.products
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_alias_migration_doc(catalog: SkillCatalog) -> str:
    """Render reviewable behavior boundaries for every deprecated alias."""

    lines = [
        "# Deprecated Skill Alias Migration Guide",
        "",
        (
            "_Generated from `skills/catalog.yaml` "
            f"(schema {catalog.schema_version}, SHA-256 `{catalog.checksum}`) by "
            "`skills/shared/scripts/generate_skill_catalog.py`; do not edit manually._"
        ),
        "",
    ]
    if not catalog.aliases:
        lines.extend([
            "No deprecated aliases are currently declared.",
            "",
        ])
        return "\n".join(lines)
    lines.extend([
        "Deprecated names are help-only compatibility aliases. Their setup, validation,",
        "and renderer entrypoints fail closed and name the canonical replacement.",
        "",
        "| Deprecated name | Canonical replacement | Migration / omission boundary |",
        "| --- | --- | --- |",
    ])
    for record in catalog.skills:
        if not record.deprecated:
            continue
        assert record.replaced_by is not None and record.migration is not None
        migration = record.migration.replace("|", r"\|")
        lines.append(
            f"| `{record.name}` | `{record.replaced_by}` | {migration} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_validation_registry(root: Path, catalog: SkillCatalog) -> str:
    """Merge generated identity with the manually maintained evidence extension."""

    current = _load_json(root, VALIDATION_REGISTRY)
    allowed_keys = {
        "schema_version",
        "generated_from",
        "description",
        "skills",
        "evidence",
    }
    required_keys = {"schema_version", "description", "skills", "evidence"}
    unknown_keys = sorted(set(current) - allowed_keys)
    missing_keys = sorted(required_keys - set(current))
    if unknown_keys:
        raise CatalogError(
            f"{VALIDATION_REGISTRY}: unsupported top-level fields: "
            + ", ".join(unknown_keys)
        )
    if missing_keys:
        raise CatalogError(
            f"{VALIDATION_REGISTRY}: missing top-level fields: "
            + ", ".join(missing_keys)
        )
    if current.get("schema_version") != 1:
        raise CatalogError(f"{VALIDATION_REGISTRY}: schema_version must be 1")
    description = current.get("description")
    evidence = current.get("evidence")
    if (
        not isinstance(description, str)
        or not description.strip()
        or description != description.strip()
    ):
        raise CatalogError(f"{VALIDATION_REGISTRY}: description must be non-empty")
    existing_skills = current.get("skills")
    if not isinstance(existing_skills, list) or any(
        not isinstance(skill, str) or not skill for skill in existing_skills
    ):
        raise CatalogError(f"{VALIDATION_REGISTRY}: skills must be a string list")
    if len(existing_skills) != len(set(existing_skills)):
        raise CatalogError(f"{VALIDATION_REGISTRY}: skills must not contain duplicates")
    if existing_skills != sorted(existing_skills):
        raise CatalogError(f"{VALIDATION_REGISTRY}: skills must be alphabetized")
    generated_from = current.get("generated_from")
    if generated_from is not None:
        if not isinstance(generated_from, dict) or set(generated_from) != {
            "path",
            "schema_version",
            "sha256",
        }:
            raise CatalogError(
                f"{VALIDATION_REGISTRY}: generated_from has an invalid shape"
            )
        if generated_from.get("path") != "skills/catalog.yaml":
            raise CatalogError(
                f"{VALIDATION_REGISTRY}: generated_from.path is invalid"
            )
        if generated_from.get("schema_version") != catalog.schema_version:
            raise CatalogError(
                f"{VALIDATION_REGISTRY}: generated_from.schema_version is invalid"
            )
        checksum = generated_from.get("sha256")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise CatalogError(
                f"{VALIDATION_REGISTRY}: generated_from.sha256 is invalid"
            )
    normalized_evidence, evidence_findings = normalize_evidence_extension(
        evidence,
        known_skills=set(catalog.by_name),
        repo_root=root,
    )
    if evidence_findings:
        raise CatalogError(
            f"{VALIDATION_REGISTRY}: invalid evidence extension:\n"
            + "\n".join(evidence_findings)
        )
    payload = {
        "schema_version": 1,
        "generated_from": _provenance(catalog),
        "description": description,
        "skills": sorted(catalog.by_name),
        "evidence": normalized_evidence,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _validate_exact_names(
    *,
    label: str,
    actual: list[str],
    expected: set[str],
) -> list[str]:
    errors: list[str] = []
    actual_set = set(actual)
    duplicates = sorted(name for name in actual_set if actual.count(name) > 1)
    missing = sorted(expected - actual_set)
    unknown = sorted(actual_set - expected)
    if duplicates:
        errors.append(f"{label}: duplicate skills: {', '.join(duplicates)}")
    if missing:
        errors.append(f"{label}: missing skills: {', '.join(missing)}")
    if unknown:
        errors.append(f"{label}: unknown skills: {', '.join(unknown)}")
    return errors


def _frontmatter_metadata(block: str) -> dict[str, str]:
    match = re.search(r"^metadata:\n((?:  [^\n]+\n?)*)", block, re.MULTILINE)
    if not match:
        return {}
    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, raw = line.strip().split(":", 1)
        raw = raw.strip()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw.strip("'\"")
        if isinstance(value, str):
            metadata[key] = value
    return metadata


def _parse_alias_openai_metadata(text: str, *, skill: str) -> dict[str, str]:
    """Parse the exact dependency-free YAML shape required for alias UI metadata."""

    lines = text.splitlines()
    expected_prefixes = (
        "interface:",
        "  display_name: ",
        "  short_description: ",
        "  default_prompt: ",
        "policy:",
        "  allow_implicit_invocation: false",
    )
    if len(lines) != len(expected_prefixes):
        raise CatalogError(
            f"skills/{skill}/agents/openai.yaml must contain exactly the alias "
            "interface and policy mappings"
        )
    values: dict[str, str] = {}
    for index, prefix in enumerate(expected_prefixes):
        if index in {0, 4, 5}:
            if lines[index] != prefix:
                raise CatalogError(
                    f"skills/{skill}/agents/openai.yaml:{index + 1}: "
                    f"expected {prefix!r}"
                )
            continue
        if not lines[index].startswith(prefix):
            raise CatalogError(
                f"skills/{skill}/agents/openai.yaml:{index + 1}: expected {prefix!r}"
            )
        try:
            value = json.loads(lines[index][len(prefix) :])
        except json.JSONDecodeError as exc:
            raise CatalogError(
                f"skills/{skill}/agents/openai.yaml:{index + 1}: "
                "alias interface values must be JSON-quoted YAML strings"
            ) from exc
        if not isinstance(value, str) or not value.strip():
            raise CatalogError(
                f"skills/{skill}/agents/openai.yaml:{index + 1}: "
                "alias interface values must be non-empty strings"
            )
        values[prefix.strip().removesuffix(":")] = value
    return values


def validate_extensions(root: Path, catalog: SkillCatalog) -> list[str]:
    """Validate richer registries and local skill surfaces against the manifest."""

    errors: list[str] = []
    expected = set(catalog.by_name)
    source_text: dict[str, str] = {}
    openai_text: dict[str, str] = {}
    for record in catalog.skills:
        source_text[record.name] = _read_required_source_text(
            root, root / record.path
        )
        openai_text[record.name] = _read_required_source_text(
            root, root / "skills" / record.name / "agents/openai.yaml"
        )

    skills_root = root / "skills"
    if not _managed_directory_exists(root, skills_root):
        raise CatalogError("missing managed source directory: skills")
    skill_dirs: list[str] = []
    for path in skills_root.iterdir():
        if path.name == "shared" or path.name.startswith("."):
            continue
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            continue
        try:
            skill_info = os.lstat(path / "SKILL.md")
        except FileNotFoundError:
            continue
        if stat.S_ISREG(skill_info.st_mode) and not stat.S_ISLNK(skill_info.st_mode):
            skill_dirs.append(path.name)
    skill_dirs.sort()
    errors.extend(
        _validate_exact_names(label="skills/", actual=skill_dirs, expected=expected)
    )

    app_registry = _load_json(root, APP_REGISTRY)
    topology_names = [
        str(entry["skill"])
        for entry in app_registry.get("skill_topologies", [])
        if isinstance(entry, dict) and entry.get("skill")
    ]
    errors.extend(
        _validate_exact_names(
            label=f"{APP_REGISTRY}:skill_topologies",
            actual=topology_names,
            expected=expected,
        )
    )
    topology_by_skill = {
        str(entry.get("skill")): entry
        for entry in app_registry.get("skill_topologies", [])
        if isinstance(entry, dict) and entry.get("skill")
    }
    deployment_roles = app_registry.get("deployment_roles", [])
    for alias, replacement in catalog.aliases.items():
        topology = topology_by_skill.get(alias, {})
        role_support = topology.get("role_support")
        expected_roles = (
            {str(role): "none" for role in deployment_roles}
            if isinstance(deployment_roles, list)
            else {}
        )
        if role_support != expected_roles:
            errors.append(
                f"{APP_REGISTRY}: deprecated alias {alias} must have no deployment "
                f"role; runtime placement belongs to {replacement}"
            )
        if topology.get("cloud_pairing") != []:
            errors.append(
                f"{APP_REGISTRY}: deprecated alias {alias} must have empty cloud_pairing"
            )
    for section in ("apps",):
        for index, entry in enumerate(app_registry.get(section, [])):
            if not isinstance(entry, dict) or not entry.get("skill"):
                continue
            skill_name = str(entry["skill"])
            if skill_name not in expected:
                errors.append(
                    f"{APP_REGISTRY}:{section}[{index}] references unknown skill {skill_name}"
                )
    documentation = app_registry.get("documentation", {})
    if isinstance(documentation, dict):
        for index, row in enumerate(documentation.get("cloud_matrix_rows", [])):
            if not isinstance(row, dict) or row.get("kind") != "workflow":
                continue
            skill_name = str(row.get("skill", ""))
            if skill_name not in expected:
                errors.append(
                    f"{APP_REGISTRY}:cloud_matrix_rows[{index}] references unknown skill "
                    f"{skill_name}"
                )

    requirements_text = _read_required_source_text(root, root / REQUIREMENTS_DOC)
    try:
        requirement_names = list(
            parse_requirement_skill_rows(requirements_text, catalog)
        )
    except CatalogError as exc:
        errors.append(f"{REQUIREMENTS_DOC}: {exc}")
        requirement_names = []
    errors.extend(
        _validate_exact_names(
            label=str(REQUIREMENTS_DOC),
            actual=requirement_names,
            expected=expected,
        )
    )
    for record in catalog.skills:
        text = source_text[record.name]
        match = FRONTMATTER_RE.match(text)
        if not match:
            errors.append(f"skills/{record.name}/SKILL.md: missing frontmatter")
            continue
        metadata = _frontmatter_metadata(match.group(1))
        deprecated = metadata.get("deprecated")
        replaced_by = metadata.get("replaced_by")
        if record.deprecated:
            if deprecated != "true":
                errors.append(
                    f"skills/{record.name}/SKILL.md: metadata.deprecated must be \"true\""
                )
            if replaced_by != record.replaced_by:
                errors.append(
                    f"skills/{record.name}/SKILL.md: metadata.replaced_by must be "
                    f"{record.replaced_by!r}"
                )
            warning_tokens = ("[!WARNING]", "deprecated", str(record.replaced_by))
            lower_text = text.lower()
            for token in warning_tokens:
                if token.lower() not in lower_text:
                    errors.append(
                        f"skills/{record.name}/SKILL.md: missing visible alias warning token "
                        f"{token!r}"
                    )
            try:
                interface = _parse_alias_openai_metadata(
                    openai_text[record.name],
                    skill=record.name,
                )
            except (CatalogError, OSError) as exc:
                errors.append(str(exc))
            else:
                prompt = interface["default_prompt"]
                for token in (f"${record.name}", f"${record.replaced_by}"):
                    if token not in prompt:
                        errors.append(
                            f"skills/{record.name}/agents/openai.yaml: "
                            f"default_prompt must mention {token}"
                        )
                if "deprecated" not in interface["short_description"].lower():
                    errors.append(
                        f"skills/{record.name}/agents/openai.yaml: "
                        "short_description must visibly say deprecated"
                    )
        elif deprecated is not None or replaced_by is not None:
            errors.append(
                f"skills/{record.name}/SKILL.md: canonical skill cannot declare alias metadata"
            )

    return errors


def expected_surfaces(root: Path, catalog: SkillCatalog) -> tuple[dict[Path, str], dict[Path, str]]:
    text_files: dict[Path, str] = {}
    links: dict[Path, str] = {}
    for relative in MANAGED_DOCS:
        path = root / relative
        current = _read_managed_text(root, path, required=True)
        assert current is not None
        text_files[path] = render_context_doc(current, catalog)
    for record in catalog.skills:
        text_files[root / COMMANDS_DIR / f"{record.name}.md"] = render_command(
            catalog, record
        )
        links[root / CURSOR_SKILLS_DIR / record.name] = f"../../skills/{record.name}"
    text_files[root / PRODUCT_REGISTRY] = render_product_registry(catalog)
    text_files[root / VALIDATION_REGISTRY] = render_validation_registry(root, catalog)
    text_files[root / ALIAS_MIGRATION_DOC] = render_alias_migration_doc(catalog)
    return text_files, links


def _write_text(root: Path, path: Path, content: str) -> bool:
    info = _managed_file_info(
        root,
        path,
        required=False,
        create_parent=True,
    )
    current = (
        _read_managed_text(root, path, required=True)
        if info is not None
        else None
    )
    if current == content:
        return False
    mode = stat.S_IMODE(info.st_mode) if info is not None else 0o644
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        content_bytes = content.encode("utf-8")
        offset = 0
        while offset < len(content_bytes):
            written = os.write(descriptor, content_bytes[offset:])
            if written <= 0:
                raise OSError(f"short write for managed output: {path}")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary_path, path)
        parent_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
    return True


def _stale_generated_artifacts(
    root: Path,
    catalog: SkillCatalog,
) -> tuple[list[Path], list[Path]]:
    """Find only obsolete artifacts bearing this generator's provenance."""

    expected_names = set(catalog.by_name)
    expected_command_files = {f"{name}.md" for name in expected_names}
    stale_commands: list[Path] = []
    command_dir = root / COMMANDS_DIR
    if _managed_directory_exists(root, command_dir):
        for path in sorted(command_dir.iterdir()):
            if path.name in expected_command_files:
                continue
            try:
                info = os.lstat(path)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                continue
            if info.st_nlink != 1:
                raise CatalogError(
                    f"stale command candidate has multiple hard links: "
                    f"{path.relative_to(root)}"
                )
            content = _read_managed_text(root, path, required=True)
            if content is not None and GENERATED_COMMAND_RE.match(content):
                stale_commands.append(path)

    stale_links: list[Path] = []
    cursor_dir = root / CURSOR_SKILLS_DIR
    if _managed_directory_exists(root, cursor_dir):
        for path in sorted(cursor_dir.iterdir()):
            if path.name in expected_names:
                continue
            try:
                info = os.lstat(path)
            except FileNotFoundError:
                continue
            if not stat.S_ISLNK(info.st_mode):
                continue
            target = os.readlink(path)
            if _has_generated_cursor_provenance(path, target):
                stale_links.append(path)
    return stale_commands, stale_links


def _check_surfaces(
    root: Path,
    catalog: SkillCatalog,
    text_files: dict[Path, str],
    links: dict[Path, str],
) -> list[str]:
    errors: list[str] = []
    for path, expected in sorted(text_files.items()):
        current = _read_managed_text(root, path, required=False)
        if current != expected:
            errors.append(f"stale generated file: {path.relative_to(root)}")
    for path, expected_target in sorted(links.items()):
        _ensure_managed_parent(root, path, create=False)
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            info = None
        if info is None or not stat.S_ISLNK(info.st_mode):
            errors.append(f"missing generated symlink: {path.relative_to(root)}")
            continue
        actual_target = os.readlink(path)
        if actual_target != expected_target:
            errors.append(
                f"stale generated symlink: {path.relative_to(root)} -> "
                f"{actual_target} (expected {expected_target})"
            )
    stale_commands, stale_links = _stale_generated_artifacts(root, catalog)
    errors.extend(
        f"stale generated file: {path.relative_to(root)}"
        for path in stale_commands
    )
    errors.extend(
        f"stale generated symlink: {path.relative_to(root)}"
        for path in stale_links
    )
    return errors


def _write_surfaces(
    root: Path,
    catalog: SkillCatalog,
    text_files: dict[Path, str],
    links: dict[Path, str],
) -> int:
    # Preflight every output before changing content so a malicious parent or
    # incompatible target fails before regeneration begins.
    for path in sorted(text_files):
        _managed_file_info(
            root,
            path,
            required=False,
            create_parent=True,
        )
    for path in sorted(links):
        _ensure_managed_parent(root, path, create=True)
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            continue
        if not stat.S_ISLNK(info.st_mode):
            raise CatalogError(f"refusing to replace non-symlink path: {path}")
    _stale_generated_artifacts(root, catalog)

    changed = sum(
        _write_text(root, path, content)
        for path, content in sorted(text_files.items())
    )
    for path, target in sorted(links.items()):
        _ensure_managed_parent(root, path, create=True)
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            info = None
        if info is not None and stat.S_ISLNK(info.st_mode) and os.readlink(path) == target:
            continue
        if info is not None and not stat.S_ISLNK(info.st_mode):
            raise CatalogError(f"refusing to replace non-symlink path: {path}")
        if info is not None:
            os.unlink(path)
        os.symlink(target, path)
        changed += 1

    stale_commands, stale_links = _stale_generated_artifacts(root, catalog)
    for path in stale_commands:
        content = _read_managed_text(root, path, required=True)
        if content is None or not GENERATED_COMMAND_RE.match(content):
            raise CatalogError(
                f"refusing to delete command without generated provenance: {path}"
            )
        os.unlink(path)
        changed += 1
    for path in stale_links:
        info = os.lstat(path)
        target = os.readlink(path) if stat.S_ISLNK(info.st_mode) else ""
        if not _has_generated_cursor_provenance(path, target):
            raise CatalogError(
                f"refusing to delete link without generated provenance: {path}"
            )
        os.unlink(path)
        changed += 1
    return changed


def main() -> int:
    args = parse_args()
    root = Path(os.path.abspath(args.root))
    try:
        _validate_root(root)
        catalog_path = root / "skills/catalog.yaml"
        schema_path = root / "skills/shared/skill_catalog.schema.json"
        _managed_file_info(root, catalog_path, required=True)
        _managed_file_info(root, schema_path, required=True)
        catalog = load_catalog(catalog_path, schema_path=schema_path)
        extension_errors = validate_extensions(root, catalog)
        if extension_errors:
            raise CatalogError("\n".join(extension_errors))
        text_files, links = expected_surfaces(root, catalog)
        if args.check:
            errors = _check_surfaces(root, catalog, text_files, links)
            if errors:
                for error in errors:
                    print(f"ERROR: {error}", file=sys.stderr)
                print(
                    "Run `python3 skills/shared/scripts/generate_skill_catalog.py --write`.",
                    file=sys.stderr,
                )
                return 1
            print(
                f"Canonical skill catalog is current: {len(catalog.skills)} skills, "
                f"{len(catalog.aliases)} aliases, sha256 {catalog.checksum}."
            )
            return 0
        changed = _write_surfaces(root, catalog, text_files, links)
        print(
            f"Generated {len(catalog.skills)} skill surfaces; changed {changed} paths; "
            f"sha256 {catalog.checksum}."
        )
        return 0
    except (CatalogError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

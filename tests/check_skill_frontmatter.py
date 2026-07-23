#!/usr/bin/env python3
"""Validate SKILL.md and agents/openai.yaml metadata contracts."""

import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised when PyYAML is absent locally
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.shared.skill_catalog import SkillRecord, load_catalog  # noqa: E402


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
MARKETPLACE_REQUIRED_BODY_SECTIONS = (
    "Prerequisites",
    "Workflow Overview",
    "When to Activate",
    "Troubleshooting",
)
MARKETPLACE_WORKFLOW_CODE_BLOCK_RE = re.compile(
    r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
MARKETPLACE_WORKFLOW_STRUCTURE_MARKERS = (
    "┌",
    "┐",
    "└",
    "┘",
    "│",
    "+--",
    "--+",
)
MARKETPLACE_WORKFLOW_FLOW_MARKERS = ("▼", "▶", "→", "->")
COMPATIBILITY_STATUSES = {
    "supported",
    "conditional",
    "blocked",
    "self-managed-10.4",
    "not-applicable",
    "delegated",
}
COMPATIBILITY_VERIFIED_DATE = "2026-07-02"
OPENAI_TOP_LEVEL_KEYS = {"interface", "dependencies", "policy"}
OPENAI_INTERFACE_KEYS = {
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
}
OPENAI_DEPENDENCY_KEYS = {"tools"}
OPENAI_TOOL_KEYS = {"type", "value", "description", "transport", "url"}


def _fallback_scalar(value: str) -> Any:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if value == "true":
        return True
    if value == "false":
        return False
    if value in {"null", "~"}:
        return None
    return value


def _fallback_mapping(block: str) -> dict[str, Any]:
    """Parse the small mapping subset used by repository metadata.

    The fallback intentionally supports only top-level scalars, folded/literal
    strings, nested mappings, and lists of scalars or mappings. That covers
    SKILL.md frontmatter plus canonical ``agents/openai.yaml`` tool
    dependencies without pretending to be a general YAML parser.
    """
    result: dict[str, Any] = {}
    lines = block.splitlines()
    index = 0

    def next_content_indent() -> tuple[int | None, str]:
        probe = index
        while probe < len(lines):
            candidate = lines[probe]
            if candidate.strip() and not candidate.lstrip().startswith("#"):
                return (
                    len(candidate) - len(candidate.lstrip(" ")),
                    candidate.strip(),
                )
            probe += 1
        return None, ""

    def consume_sequence(expected_indent: int) -> list[Any]:
        nonlocal index
        sequence: list[Any] = []
        while index < len(lines):
            raw = lines[index]
            if not raw.strip() or raw.lstrip().startswith("#"):
                index += 1
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent < expected_indent:
                break
            if indent != expected_indent or not raw.strip().startswith("-"):
                raise ValueError(
                    f"unsupported YAML sequence at line {index + 1}"
                )

            value = raw.strip()[1:].strip()
            index += 1
            if not value:
                child_indent, child_text = next_content_indent()
                if child_indent is None or child_indent <= expected_indent:
                    sequence.append(None)
                elif child_text.startswith("-"):
                    sequence.append(consume_sequence(child_indent))
                else:
                    sequence.append(consume_mapping(child_indent))
                continue

            if ":" not in value:
                sequence.append(_fallback_scalar(value))
                continue

            key, raw_value = value.split(":", 1)
            key = key.strip()
            if not key:
                raise ValueError(f"empty YAML key at line {index}")
            item: dict[str, Any] = {key: _fallback_scalar(raw_value)}
            child_indent, _ = next_content_indent()
            if child_indent is not None and child_indent > expected_indent:
                continuation = consume_mapping(child_indent)
                duplicate = set(item) & set(continuation)
                if duplicate:
                    raise ValueError(
                        f"duplicate YAML key {sorted(duplicate)[0]!r}"
                    )
                item.update(continuation)
            sequence.append(item)
        return sequence

    def consume_mapping(expected_indent: int) -> dict[str, Any]:
        nonlocal index
        mapping: dict[str, Any] = {}
        while index < len(lines):
            raw = lines[index]
            if not raw.strip() or raw.lstrip().startswith("#"):
                index += 1
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent < expected_indent:
                break
            if indent > expected_indent:
                raise ValueError(
                    f"unsupported YAML indentation at line {index + 1}"
                )
            line = raw.strip()
            if line.startswith("-") or ":" not in line:
                raise ValueError(
                    f"unsupported YAML construct at line {index + 1}"
                )
            key, raw_value = line.split(":", 1)
            key = key.strip()
            value = raw_value.strip()
            index += 1

            if value in {">", ">-", "|", "|-"}:
                parts: list[str] = []
                while index < len(lines):
                    continuation = lines[index]
                    if not continuation.strip():
                        parts.append("")
                        index += 1
                        continue
                    continuation_indent = len(continuation) - len(
                        continuation.lstrip(" ")
                    )
                    if continuation_indent <= expected_indent:
                        break
                    parts.append(continuation.strip())
                    index += 1
                separator = "\n" if value.startswith("|") else " "
                mapping[key] = separator.join(parts).strip()
                continue

            if not value:
                next_indent, next_text = next_content_indent()
                if next_indent is None or next_indent <= expected_indent:
                    mapping[key] = {}
                elif next_text.startswith("-"):
                    mapping[key] = consume_sequence(next_indent)
                else:
                    mapping[key] = consume_mapping(next_indent)
                continue

            mapping[key] = _fallback_scalar(value)
        return mapping

    result.update(consume_mapping(0))
    return result


def parse_frontmatter(block: str) -> dict[str, Any]:
    if yaml is not None:
        loaded = yaml.safe_load(block) or {}
        if not isinstance(loaded, dict):
            raise TypeError("YAML frontmatter must be a mapping")
        return loaded

    # Minimal fallback for local environments that have not installed
    # requirements-dev.txt yet. CI installs PyYAML and uses the full parser.
    return _fallback_mapping(block)


def has_marketplace_workflow_diagram(workflow: str) -> bool:
    """Return whether a workflow section contains a structured flow diagram."""

    for code_block in MARKETPLACE_WORKFLOW_CODE_BLOCK_RE.findall(workflow):
        structural_markers = {
            marker
            for marker in MARKETPLACE_WORKFLOW_STRUCTURE_MARKERS
            if marker in code_block
        }
        has_flow_direction = any(
            marker in code_block
            for marker in MARKETPLACE_WORKFLOW_FLOW_MARKERS
        )
        if len(structural_markers) >= 2 and has_flow_direction:
            return True
    return False


def check_openai_metadata(
    skill_dir: Path,
    record: SkillRecord | None = None,
) -> list[str]:
    errors: list[str] = []
    skill_name = skill_dir.name
    metadata_path = skill_dir / "agents" / "openai.yaml"
    if not metadata_path.is_file():
        return [f"{skill_name}: missing agents/openai.yaml"]

    try:
        document = parse_frontmatter(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"{skill_name}: invalid agents/openai.yaml: {exc}"]
    if not isinstance(document, dict):
        return [f"{skill_name}: agents/openai.yaml root must be a mapping"]

    unexpected_top_level = sorted(set(document) - OPENAI_TOP_LEVEL_KEYS)
    if unexpected_top_level:
        errors.append(
            f"{skill_name}: agents/openai.yaml contains unsupported top-level "
            f"field(s): {', '.join(unexpected_top_level)}"
        )

    interface = document.get("interface")
    if not isinstance(interface, dict):
        errors.append(
            f"{skill_name}: agents/openai.yaml must contain an interface mapping"
        )
        return errors
    unexpected_interface = sorted(set(interface) - OPENAI_INTERFACE_KEYS)
    if unexpected_interface:
        errors.append(
            f"{skill_name}: agents/openai.yaml interface contains unsupported "
            f"field(s): {', '.join(unexpected_interface)}"
        )

    for key in ("display_name", "short_description", "default_prompt"):
        value = interface.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(
                f"{skill_name}: agents/openai.yaml interface.{key} must be "
                "a non-empty string"
            )

    short_description = interface.get("short_description")
    if isinstance(short_description, str) and not 25 <= len(short_description) <= 64:
        errors.append(
            f"{skill_name}: agents/openai.yaml interface.short_description is "
            f"{len(short_description)} characters; expected 25-64"
        )
    default_prompt = interface.get("default_prompt")
    if isinstance(default_prompt, str) and f"${skill_name}" not in default_prompt:
        errors.append(
            f"{skill_name}: agents/openai.yaml interface.default_prompt must "
            f"explicitly mention ${skill_name}"
        )
    if record is not None and record.deprecated and isinstance(default_prompt, str):
        for token in (f"${record.name}", f"${record.replaced_by}"):
            if token not in default_prompt:
                errors.append(
                    f"{skill_name}: deprecated alias default_prompt must mention {token}"
                )

    for key in ("icon_small", "icon_large", "brand_color"):
        value = interface.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(
                f"{skill_name}: agents/openai.yaml interface.{key} must be a string"
            )

    policy = document.get("policy")
    if policy is not None:
        if not isinstance(policy, dict):
            errors.append(
                f"{skill_name}: agents/openai.yaml policy must be a mapping"
            )
        elif set(policy) - {"allow_implicit_invocation"}:
            errors.append(
                f"{skill_name}: agents/openai.yaml policy contains unsupported "
                "fields"
            )
        elif not isinstance(policy.get("allow_implicit_invocation"), bool):
            errors.append(
                f"{skill_name}: agents/openai.yaml "
                "policy.allow_implicit_invocation must be a boolean"
            )
    if record is not None and record.deprecated:
        if not isinstance(policy, dict) or policy.get("allow_implicit_invocation") is not False:
            errors.append(
                f"{skill_name}: deprecated alias must set "
                "policy.allow_implicit_invocation: false"
            )

    dependencies = document.get("dependencies")
    if dependencies is not None:
        if not isinstance(dependencies, dict):
            errors.append(
                f"{skill_name}: agents/openai.yaml dependencies must be a mapping"
            )
        else:
            unexpected_dependencies = sorted(
                set(dependencies) - OPENAI_DEPENDENCY_KEYS
            )
            if unexpected_dependencies:
                errors.append(
                    f"{skill_name}: agents/openai.yaml dependencies contains "
                    "unsupported field(s): " + ", ".join(unexpected_dependencies)
                )
            tools = dependencies.get("tools")
            if tools is not None and not isinstance(tools, list):
                errors.append(
                    f"{skill_name}: agents/openai.yaml dependencies.tools must "
                    "be a list"
                )
            elif isinstance(tools, list):
                for position, tool in enumerate(tools):
                    prefix = (
                        f"{skill_name}: agents/openai.yaml "
                        f"dependencies.tools[{position}]"
                    )
                    if not isinstance(tool, dict):
                        errors.append(f"{prefix} must be a mapping")
                        continue
                    unexpected_tool = sorted(set(tool) - OPENAI_TOOL_KEYS)
                    if unexpected_tool:
                        errors.append(
                            f"{prefix} contains unsupported field(s): "
                            + ", ".join(unexpected_tool)
                        )
                    if tool.get("type") != "mcp":
                        errors.append(f"{prefix}.type must be 'mcp'")
                    for field in ("value", "description", "transport", "url"):
                        field_value = tool.get(field)
                        if field == "value" or field_value is not None:
                            if not isinstance(field_value, str) or not field_value.strip():
                                errors.append(
                                    f"{prefix}.{field} must be a non-empty string"
                                )
    return errors


def check_skill(skill_dir: Path, record: SkillRecord | None = None) -> list[str]:
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
        status = metadata_value.get("splunk_cloud_10_5")
        if status not in COMPATIBILITY_STATUSES:
            errors.append(
                f"{dir_name}: metadata.splunk_cloud_10_5 must be one of "
                + ", ".join(sorted(COMPATIBILITY_STATUSES))
            )
        verified = metadata_value.get("compatibility_verified")
        if verified != COMPATIBILITY_VERIFIED_DATE:
            errors.append(
                f"{dir_name}: metadata.compatibility_verified must be "
                f"{COMPATIBILITY_VERIFIED_DATE}"
            )
        if record is not None and record.deprecated:
            if metadata_value.get("deprecated") != "true":
                errors.append(
                    f"{dir_name}: metadata.deprecated must be the string 'true'"
                )
            if metadata_value.get("replaced_by") != record.replaced_by:
                errors.append(
                    f"{dir_name}: metadata.replaced_by must be {record.replaced_by!r}"
                )
        elif record is not None and (
            "deprecated" in metadata_value or "replaced_by" in metadata_value
        ):
            errors.append(
                f"{dir_name}: canonical skill cannot declare deprecated/replaced_by metadata"
            )

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

    if record is not None:
        for section in MARKETPLACE_REQUIRED_BODY_SECTIONS:
            if not re.search(rf"^## {re.escape(section)}", body, re.MULTILINE):
                errors.append(
                    f"{dir_name}: SKILL.md missing marketplace-required "
                    f"{section!r} section"
                )

        if not re.search(r"^## (?:Examples|Commands)", body, re.MULTILINE):
            errors.append(
                f"{dir_name}: SKILL.md missing marketplace-required "
                "Examples or Commands section"
            )

        workflow = re.search(
            r"^## Workflow Overview[^\n]*\n(.*?)(?=^## |\Z)",
            body,
            re.MULTILINE | re.DOTALL,
        )
        if workflow is not None and not has_marketplace_workflow_diagram(
            workflow.group(1)
        ):
            errors.append(
                f"{dir_name}: SKILL.md Workflow Overview section "
                "missing a marketplace workflow diagram"
            )

    return errors


def main() -> int:
    catalog = load_catalog()
    skill_dirs = [(REPO_ROOT / record.path).parent for record in catalog.skills]

    if not skill_dirs:
        print("ERROR: no skill directories found under skills/", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    checked_count = 0
    for record, skill_dir in zip(catalog.skills, skill_dirs, strict=True):
        all_errors.extend(check_skill(skill_dir, record))
        all_errors.extend(check_openai_metadata(skill_dir, record))
        checked_count += 1

    if all_errors:
        print("Skill metadata errors:", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"All {checked_count} skills pass SKILL.md frontmatter and "
        "agents/openai.yaml checks."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

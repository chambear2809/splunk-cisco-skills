#!/usr/bin/env python3
"""Strict loader and semantic validator for the canonical skill catalog."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "skills" / "catalog.yaml"
SCHEMA_PATH = REPO_ROOT / "skills" / "shared" / "skill_catalog.schema.json"
SCHEMA_VERSION = 1
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_PATH_PATTERN = r"^skills/[a-z0-9-]+/SKILL\.md$"
SINGLE_LINE_TEXT_PATTERN = r"^\S(?:[^\r\n]*\S)?$"
MULTILINE_TEXT_PATTERN = r"^\S(?:[^\r]*\S)?$"
TOP_LEVEL_KEYS = {
    "schema_version",
    "skill_count",
    "alias_count",
    "shared_sections",
    "taxonomy",
    "skills",
}
SHARED_SECTION_KEYS = {"local_skill_mcp_server"}
TAXONOMY_KEYS = {"products", "capabilities"}
PRODUCT_KEYS = {"id", "name", "description"}
CAPABILITY_KEYS = {"product", "id", "name"}
SKILL_KEYS = {
    "name",
    "path",
    "target",
    "purpose",
    "command_summary",
    "product",
    "capability",
    "status",
    "replaced_by",
    "migration",
}
SKILL_REQUIRED_KEYS = {
    "name",
    "path",
    "target",
    "purpose",
    "command_summary",
    "product",
    "capability",
    "status",
}
STATUSES = {"canonical", "deprecated"}
MCP_SAFETY_TOKENS = (
    "code-level execution default is off",
    "SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1",
    "Pure-Python product resolution and bounded skill discovery never launch subprocesses",
    "Generic script execution is always mutation-gated",
    "SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION=1",
    "SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1",
    "matching plan hash and literal Boolean confirmation",
    "dependency-tree snapshot",
    "after the execution lock is acquired",
    "single-use",
    "separately reviewed single-operator server",
)


def command_handoff_boilerplate(skill_name: str) -> str:
    """Return the universal handoff appended after every generated summary."""

    return (
        f"Read and follow the instructions in skills/{skill_name}/SKILL.md to help "
        f"the user. If more detail is needed, also read "
        f"skills/{skill_name}/reference.md."
    )


class CatalogError(ValueError):
    """Raised when the canonical manifest violates its schema or semantics."""


@dataclass(frozen=True)
class ProductRecord:
    """One ordered product taxonomy node."""

    id: str
    name: str
    description: str

    def normalized(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "description": self.description}


@dataclass(frozen=True)
class CapabilityRecord:
    """One ordered capability taxonomy node owned by a product."""

    product: str
    id: str
    name: str

    def normalized(self) -> dict[str, str]:
        return {"product": self.product, "id": self.id, "name": self.name}


@dataclass(frozen=True)
class SkillRecord:
    """One canonical skill or deprecated compatibility alias."""

    name: str
    path: str
    target: str
    purpose: str
    command_summary: str
    product: str
    capability: str
    status: str
    replaced_by: str | None = None
    migration: str | None = None

    @property
    def deprecated(self) -> bool:
        return self.status == "deprecated"

    def normalized(self) -> dict[str, str]:
        payload = {
            "name": self.name,
            "path": self.path,
            "target": self.target,
            "purpose": self.purpose,
            "command_summary": self.command_summary,
            "product": self.product,
            "capability": self.capability,
            "status": self.status,
        }
        if self.replaced_by is not None:
            payload["replaced_by"] = self.replaced_by
        if self.migration is not None:
            payload["migration"] = self.migration
        return payload


@dataclass(frozen=True)
class SkillCatalog:
    """Validated immutable catalog data."""

    schema_version: int
    declared_skill_count: int
    declared_alias_count: int
    shared_sections: Mapping[str, str]
    products: tuple[ProductRecord, ...]
    capabilities: tuple[CapabilityRecord, ...]
    skills: tuple[SkillRecord, ...]
    source_path: Path

    @property
    def by_name(self) -> Mapping[str, SkillRecord]:
        return MappingProxyType({record.name: record for record in self.skills})

    @property
    def aliases(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                record.name: record.replaced_by
                for record in self.skills
                if record.deprecated and record.replaced_by is not None
            }
        )

    def normalized(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "skill_count": self.declared_skill_count,
            "alias_count": self.declared_alias_count,
            "shared_sections": dict(self.shared_sections),
            "taxonomy": {
                "products": [record.normalized() for record in self.products],
                "capabilities": [
                    record.normalized() for record in self.capabilities
                ],
            },
            "skills": [record.normalized() for record in self.skills],
        }

    @property
    def checksum(self) -> str:
        content = json.dumps(
            self.normalized(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    def entry_checksum(self, record: SkillRecord) -> str:
        content = json.dumps(
            {
                "schema_version": self.schema_version,
                "skill": record.normalized(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(content).hexdigest()


def parse_requirement_skill_rows(
    text: str, catalog: SkillCatalog
) -> tuple[str, ...]:
    """Parse requirement-table identities with exact manifest lifecycle labels."""

    row_re = re.compile(
        r"^\| `(?P<name>[a-z0-9]+(?:-[a-z0-9]+)*)`(?P<suffix>[^|]*) \|",
        flags=re.MULTILINE,
    )
    names: list[str] = []
    seen: set[str] = set()
    for match in row_re.finditer(text):
        name = match.group("name")
        suffix = match.group("suffix")
        record = catalog.by_name.get(name)
        expected_suffix = ""
        if record is not None and record.deprecated:
            expected_suffix = f" (**Deprecated** -> `{record.replaced_by}`)"
        if suffix != expected_suffix:
            raise CatalogError(
                f"requirement row for {name!r} has lifecycle suffix {suffix!r}; "
                f"expected {expected_suffix!r} from skills/catalog.yaml"
            )
        if name in seen:
            raise CatalogError(f"duplicate requirement row for skill {name!r}")
        seen.add(name)
        names.append(name)
    return tuple(names)


def _require_mapping(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogError(f"{location} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise CatalogError(f"{location} keys must be strings")
    return value


def _require_exact_keys(
    mapping: Mapping[str, object],
    allowed: set[str],
    required: set[str],
    location: str,
) -> None:
    unknown = sorted(set(mapping) - allowed)
    missing = sorted(required - set(mapping))
    if unknown:
        raise CatalogError(f"{location} contains unsupported keys: {', '.join(unknown)}")
    if missing:
        raise CatalogError(f"{location} is missing required keys: {', '.join(missing)}")


def _require_text(
    value: object,
    location: str,
    *,
    multiline: bool = False,
) -> str:
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{location} must be a non-empty string")
    if value != value.strip():
        raise CatalogError(f"{location} must not have leading or trailing whitespace")
    if "\r" in value:
        raise CatalogError(f"{location} must use LF newlines")
    if not multiline and "\n" in value:
        raise CatalogError(f"{location} must be a single-line string")
    return value


def _validate_alias_graph(records: tuple[SkillRecord, ...]) -> None:
    by_name = {record.name: record for record in records}
    for record in records:
        if record.status == "canonical":
            if record.replaced_by is not None:
                raise CatalogError(
                    f"skills[{record.name}]: canonical entries cannot define replaced_by"
                )
            if record.migration is not None:
                raise CatalogError(
                    f"skills[{record.name}]: canonical entries cannot define migration"
                )
            continue
        if record.replaced_by is None:
            raise CatalogError(
                f"skills[{record.name}]: deprecated entries require replaced_by"
            )
        if record.migration is None:
            raise CatalogError(
                f"skills[{record.name}]: deprecated entries require migration"
            )
        if record.replaced_by == record.name:
            raise CatalogError(f"skills[{record.name}]: replaced_by cannot reference itself")
        replacement = by_name.get(record.replaced_by)
        if replacement is None:
            raise CatalogError(
                f"skills[{record.name}]: replacement {record.replaced_by!r} does not exist"
            )

    for record in records:
        seen: set[str] = set()
        current = record
        while current.replaced_by is not None:
            if current.name in seen:
                chain = " -> ".join([*seen, current.name])
                raise CatalogError(f"alias cycle detected: {chain}")
            seen.add(current.name)
            target = by_name.get(current.replaced_by)
            if target is None:
                break
            current = target

    for record in records:
        if record.replaced_by is None:
            continue
        replacement = by_name[record.replaced_by]
        if replacement.status != "canonical":
            raise CatalogError(
                f"skills[{record.name}]: replacement {record.replaced_by!r} must be canonical"
            )
        if (record.product, record.capability) != (
            replacement.product,
            replacement.capability,
        ):
            raise CatalogError(
                f"skills[{record.name}]: deprecated alias product/capability must "
                f"match replacement {record.replaced_by!r}"
            )


def _validate_taxonomy(
    products: tuple[ProductRecord, ...],
    capabilities: tuple[CapabilityRecord, ...],
    skills: tuple[SkillRecord, ...],
) -> None:
    product_ids: set[str] = set()
    product_names: set[str] = set()
    for product in products:
        if product.id in product_ids:
            raise CatalogError(f"duplicate product id: {product.id}")
        if product.name in product_names:
            raise CatalogError(f"duplicate product name: {product.name}")
        product_ids.add(product.id)
        product_names.add(product.name)

    capability_keys: set[tuple[str, str]] = set()
    capability_names: set[tuple[str, str]] = set()
    for capability in capabilities:
        if capability.product not in product_ids:
            raise CatalogError(
                f"capability {capability.id!r} references unknown product "
                f"{capability.product!r}"
            )
        key = (capability.product, capability.id)
        name_key = (capability.product, capability.name)
        if key in capability_keys:
            raise CatalogError(
                f"duplicate capability id {capability.id!r} in {capability.product!r}"
            )
        if name_key in capability_names:
            raise CatalogError(
                f"duplicate capability name {capability.name!r} in {capability.product!r}"
            )
        capability_keys.add(key)
        capability_names.add(name_key)

    used_products: set[str] = set()
    used_capabilities: set[tuple[str, str]] = set()
    for skill in skills:
        if skill.product not in product_ids:
            raise CatalogError(
                f"skills[{skill.name}]: unknown product {skill.product!r}"
            )
        key = (skill.product, skill.capability)
        if key not in capability_keys:
            raise CatalogError(
                f"skills[{skill.name}]: unknown capability {skill.capability!r} "
                f"for product {skill.product!r}"
            )
        expected_path = f"skills/{skill.name}/SKILL.md"
        if skill.path != expected_path:
            raise CatalogError(
                f"skills[{skill.name}].path must be {expected_path!r}, got {skill.path!r}"
            )
        used_products.add(skill.product)
        used_capabilities.add(key)

    unused_products = sorted(product_ids - used_products)
    unused_capabilities = sorted(capability_keys - used_capabilities)
    if unused_products:
        raise CatalogError("unused taxonomy products: " + ", ".join(unused_products))
    if unused_capabilities:
        formatted = [
            f"{product}/{capability}"
            for product, capability in unused_capabilities
        ]
        raise CatalogError(
            "unused taxonomy capabilities: " + ", ".join(formatted)
        )


def _schema_properties(
    schema: Mapping[str, object],
    *,
    location: str,
    expected_keys: set[str],
    required_keys: set[str],
    extra_keywords: set[str] | None = None,
) -> dict[str, Any]:
    """Return properties after proving a JSON Schema object matches loader keys."""

    expected_schema_keys = {
        "type",
        "additionalProperties",
        "required",
        "properties",
    } | (extra_keywords or set())
    if set(schema) != expected_schema_keys:
        raise CatalogError(f"{location} JSON Schema keywords drifted from strict loader")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise CatalogError(
            f"{location} must describe a strict object with additionalProperties=false"
        )
    properties = _require_mapping(schema.get("properties"), f"{location}.properties")
    required = schema.get("required")
    if not isinstance(required, list) or any(
        not isinstance(item, str) for item in required
    ):
        raise CatalogError(f"{location}.required must be a string list")
    if set(properties) != expected_keys:
        raise CatalogError(
            f"{location}.properties drifted from strict loader keys"
        )
    if set(required) != required_keys or len(required) != len(set(required)):
        raise CatalogError(f"{location}.required drifted from strict loader keys")
    return properties


def _schema_array_items(value: object, *, location: str) -> dict[str, Any]:
    schema = _require_mapping(value, location)
    expected = {"type", "minItems", "uniqueItems", "items"}
    if set(schema) != expected:
        raise CatalogError(f"{location} array constraints drifted from strict loader")
    if (
        schema.get("type") != "array"
        or schema.get("minItems") != 1
        or schema.get("uniqueItems") is not True
    ):
        raise CatalogError(f"{location} array constraints drifted from strict loader")
    return _require_mapping(schema.get("items"), f"{location}.items")


def _require_schema_fragment(
    actual: object,
    expected: Mapping[str, object],
    *,
    location: str,
) -> None:
    if actual != expected:
        raise CatalogError(f"{location} constraints drifted from strict loader")


def validate_schema_contract(path: Path | None = None) -> None:
    """Fail when the documentation schema and strict loader contract diverge."""

    schema_path = (path or SCHEMA_PATH).resolve()
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"missing skill catalog schema: {schema_path}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"invalid skill catalog schema JSON: {exc}") from exc
    root = _require_mapping(schema, "skill catalog schema")
    if root.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise CatalogError("skill catalog schema must use JSON Schema draft 2020-12")
    root_properties = _schema_properties(
        root,
        location="skill catalog schema",
        expected_keys=TOP_LEVEL_KEYS,
        required_keys=TOP_LEVEL_KEYS,
        extra_keywords={"$schema", "$id", "title"},
    )
    _require_schema_fragment(
        root_properties["schema_version"],
        {"type": "integer", "const": SCHEMA_VERSION},
        location="schema.schema_version",
    )
    for count_field in ("skill_count", "alias_count"):
        _require_schema_fragment(
            root_properties[count_field],
            {"type": "integer", "minimum": 0},
            location=f"schema.{count_field}",
        )

    shared_properties = _schema_properties(
        _require_mapping(root_properties["shared_sections"], "schema.shared_sections"),
        location="schema.shared_sections",
        expected_keys=SHARED_SECTION_KEYS,
        required_keys=SHARED_SECTION_KEYS,
    )
    _require_schema_fragment(
        shared_properties["local_skill_mcp_server"],
        {
            "type": "string",
            "minLength": 1,
            "pattern": MULTILINE_TEXT_PATTERN,
        },
        location="schema.shared_sections.local_skill_mcp_server",
    )

    taxonomy_properties = _schema_properties(
        _require_mapping(root_properties["taxonomy"], "schema.taxonomy"),
        location="schema.taxonomy",
        expected_keys=TAXONOMY_KEYS,
        required_keys=TAXONOMY_KEYS,
    )
    product_items = _schema_array_items(
        taxonomy_properties["products"],
        location="schema.products",
    )
    product_properties = _schema_properties(
        product_items,
        location="schema.products.items",
        expected_keys=PRODUCT_KEYS,
        required_keys=PRODUCT_KEYS,
    )
    capability_items = _schema_array_items(
        taxonomy_properties["capabilities"],
        location="schema.capabilities",
    )
    capability_properties = _schema_properties(
        capability_items,
        location="schema.capabilities.items",
        expected_keys=CAPABILITY_KEYS,
        required_keys=CAPABILITY_KEYS,
    )
    identifier_fragment = {
        "type": "string",
        "minLength": 1,
        "pattern": NAME_RE.pattern,
    }
    text_fragment = {
        "type": "string",
        "minLength": 1,
        "pattern": SINGLE_LINE_TEXT_PATTERN,
    }
    for location, field in (
        ("schema.products.items.id", product_properties["id"]),
        ("schema.capabilities.items.product", capability_properties["product"]),
        ("schema.capabilities.items.id", capability_properties["id"]),
    ):
        _require_schema_fragment(field, identifier_fragment, location=location)
    for location, field in (
        ("schema.products.items.name", product_properties["name"]),
        ("schema.products.items.description", product_properties["description"]),
        ("schema.capabilities.items.name", capability_properties["name"]),
    ):
        _require_schema_fragment(field, text_fragment, location=location)

    skill_items = _schema_array_items(
        root_properties["skills"],
        location="schema.skills",
    )
    skill_properties = _schema_properties(
        skill_items,
        location="schema.skills.items",
        expected_keys=SKILL_KEYS,
        required_keys=SKILL_REQUIRED_KEYS,
        extra_keywords={"allOf"},
    )
    _require_schema_fragment(
        skill_properties["name"],
        {**identifier_fragment, "maxLength": 64},
        location="schema.skills.items.name",
    )
    _require_schema_fragment(
        skill_properties["path"],
        {"type": "string", "minLength": 1, "pattern": SKILL_PATH_PATTERN},
        location="schema.skills.items.path",
    )
    for field in ("target", "purpose", "command_summary"):
        _require_schema_fragment(
            skill_properties[field],
            text_fragment,
            location=f"schema.skills.items.{field}",
        )
    for field in ("product", "capability", "replaced_by"):
        _require_schema_fragment(
            skill_properties[field],
            identifier_fragment,
            location=f"schema.skills.items.{field}",
        )
    _require_schema_fragment(
        skill_properties["migration"],
        text_fragment,
        location="schema.skills.items.migration",
    )
    _require_schema_fragment(
        skill_properties["status"],
        {"type": "string", "enum": ["canonical", "deprecated"]},
        location="schema.skills.items.status",
    )

    conditions = skill_items.get("allOf")
    expected_conditions = [
        {
            "if": {
                "properties": {"status": {"const": "deprecated"}},
                "required": ["status"],
            },
            "then": {"required": ["replaced_by", "migration"]},
        },
        {
            "if": {
                "properties": {"status": {"const": "canonical"}},
                "required": ["status"],
            },
            "then": {
                "allOf": [
                    {"not": {"required": ["replaced_by"]}},
                    {"not": {"required": ["migration"]}},
                ]
            },
        },
    ]
    if conditions != expected_conditions:
        raise CatalogError("skill schema must encode canonical/deprecated alias conditions")


def _json_scalar(raw: str, *, line_number: int) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogError(
            f"catalog line {line_number}: scalar values must use deterministic JSON quoting"
        ) from exc
    if not isinstance(value, str):
        raise CatalogError(f"catalog line {line_number}: expected a quoted string")
    return value


def _parse_catalog_yaml(text: str) -> dict[str, Any]:
    """Parse the catalog's strict dependency-free YAML serialization.

    The manifest intentionally uses only fixed-order mappings, JSON-quoted
    single-line scalars, one literal block, and a sequence of flat mappings.
    Requiring this canonical shape makes duplicate keys, ordering drift, and
    emitter differences fail identically with or without PyYAML installed.
    """

    if "\r" in text:
        raise CatalogError("catalog must use LF newlines")
    if not text.endswith("\n"):
        raise CatalogError("catalog must end with exactly one LF newline")
    lines = text.splitlines()
    if any("\t" in line[: len(line) - len(line.lstrip())] for line in lines):
        raise CatalogError("catalog indentation must not contain tabs")

    index = 0

    def require(expected: str) -> None:
        nonlocal index
        actual = lines[index] if index < len(lines) else "<EOF>"
        if actual != expected:
            raise CatalogError(
                f"catalog line {index + 1}: expected {expected!r}, got {actual!r}"
            )
        index += 1

    require("schema_version: 1")
    if index >= len(lines) or not re.fullmatch(r"skill_count: \d+", lines[index]):
        raise CatalogError(f"catalog line {index + 1}: expected skill_count integer")
    skill_count = int(lines[index].split(": ", 1)[1])
    index += 1
    if index >= len(lines) or not re.fullmatch(r"alias_count: \d+", lines[index]):
        raise CatalogError(f"catalog line {index + 1}: expected alias_count integer")
    alias_count = int(lines[index].split(": ", 1)[1])
    index += 1
    require("shared_sections:")
    require("  local_skill_mcp_server: |-")
    shared_lines: list[str] = []
    while index < len(lines) and lines[index] != "taxonomy:":
        line = lines[index]
        if line == "":
            shared_lines.append("")
        elif line.startswith("    "):
            shared_lines.append(line[4:])
        else:
            raise CatalogError(
                f"catalog line {index + 1}: non-empty shared section lines require "
                "four-space indentation"
            )
        index += 1
    require("taxonomy:")
    require("  products:")
    products: list[dict[str, str]] = []
    product_order = ("id", "name", "description")
    while index < len(lines) and lines[index] != "  capabilities:":
        if not lines[index].startswith("    - id: "):
            raise CatalogError(
                f"catalog line {index + 1}: expected a taxonomy product id"
            )
        product = {
            "id": _json_scalar(
                lines[index][len("    - id: ") :], line_number=index + 1
            )
        }
        index += 1
        for key in product_order[1:]:
            prefix = f"      {key}: "
            if index >= len(lines) or not lines[index].startswith(prefix):
                raise CatalogError(
                    f"catalog line {index + 1}: expected taxonomy product {key}"
                )
            product[key] = _json_scalar(
                lines[index][len(prefix) :], line_number=index + 1
            )
            index += 1
        products.append(product)
    require("  capabilities:")
    capabilities: list[dict[str, str]] = []
    capability_order = ("product", "id", "name")
    while index < len(lines) and lines[index] != "skills:":
        if not lines[index].startswith("    - product: "):
            raise CatalogError(
                f"catalog line {index + 1}: expected a taxonomy capability product"
            )
        capability = {
            "product": _json_scalar(
                lines[index][len("    - product: ") :], line_number=index + 1
            )
        }
        index += 1
        for key in capability_order[1:]:
            prefix = f"      {key}: "
            if index >= len(lines) or not lines[index].startswith(prefix):
                raise CatalogError(
                    f"catalog line {index + 1}: expected taxonomy capability {key}"
                )
            capability[key] = _json_scalar(
                lines[index][len(prefix) :], line_number=index + 1
            )
            index += 1
        capabilities.append(capability)
    require("skills:")

    skills: list[dict[str, str]] = []
    required_order = (
        "name",
        "path",
        "target",
        "purpose",
        "command_summary",
        "product",
        "capability",
        "status",
    )
    while index < len(lines):
        if not lines[index].startswith("  - name: "):
            raise CatalogError(
                f"catalog line {index + 1}: expected a skill entry beginning with name"
            )
        entry: dict[str, str] = {
            "name": _json_scalar(
                lines[index][len("  - name: ") :], line_number=index + 1
            )
        }
        index += 1
        for key in required_order[1:]:
            prefix = f"    {key}: "
            if index >= len(lines) or not lines[index].startswith(prefix):
                actual = lines[index] if index < len(lines) else "<EOF>"
                raise CatalogError(
                    f"catalog line {index + 1}: expected {prefix!r}, got {actual!r}"
                )
            entry[key] = _json_scalar(
                lines[index][len(prefix) :], line_number=index + 1
            )
            index += 1
        for optional_key in ("replaced_by", "migration"):
            prefix = f"    {optional_key}: "
            if index < len(lines) and lines[index].startswith(prefix):
                entry[optional_key] = _json_scalar(
                    lines[index][len(prefix) :], line_number=index + 1
                )
                index += 1
        skills.append(entry)

    return {
        "schema_version": 1,
        "skill_count": skill_count,
        "alias_count": alias_count,
        "shared_sections": {"local_skill_mcp_server": "\n".join(shared_lines)},
        "taxonomy": {"products": products, "capabilities": capabilities},
        "skills": skills,
    }


def load_catalog(
    path: Path | None = None,
    *,
    schema_path: Path | None = None,
) -> SkillCatalog:
    """Load the catalog with strict schema and semantic validation."""

    source_path = (path or CATALOG_PATH).resolve()
    validate_schema_contract(schema_path)
    try:
        raw = _parse_catalog_yaml(source_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"missing canonical skill catalog: {source_path}") from exc

    root = _require_mapping(raw, "catalog")
    _require_exact_keys(root, TOP_LEVEL_KEYS, TOP_LEVEL_KEYS, "catalog")
    if root["schema_version"] != SCHEMA_VERSION:
        raise CatalogError(
            f"catalog.schema_version must be {SCHEMA_VERSION}, got {root['schema_version']!r}"
        )
    for count_key in ("skill_count", "alias_count"):
        value = root[count_key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise CatalogError(f"catalog.{count_key} must be a non-negative integer")

    shared_raw = _require_mapping(root["shared_sections"], "catalog.shared_sections")
    _require_exact_keys(
        shared_raw,
        SHARED_SECTION_KEYS,
        SHARED_SECTION_KEYS,
        "catalog.shared_sections",
    )
    shared_sections = {
        key: _require_text(
            shared_raw[key],
            f"catalog.shared_sections.{key}",
            multiline=True,
        )
        for key in sorted(shared_raw)
    }

    taxonomy_raw = _require_mapping(root["taxonomy"], "catalog.taxonomy")
    _require_exact_keys(
        taxonomy_raw,
        TAXONOMY_KEYS,
        TAXONOMY_KEYS,
        "catalog.taxonomy",
    )
    raw_products = taxonomy_raw["products"]
    raw_capabilities = taxonomy_raw["capabilities"]
    if not isinstance(raw_products, list) or not raw_products:
        raise CatalogError("catalog.taxonomy.products must be a non-empty sequence")
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise CatalogError("catalog.taxonomy.capabilities must be a non-empty sequence")
    products: list[ProductRecord] = []
    for index, raw_product in enumerate(raw_products):
        location = f"catalog.taxonomy.products[{index}]"
        product = _require_mapping(raw_product, location)
        _require_exact_keys(product, PRODUCT_KEYS, PRODUCT_KEYS, location)
        product_id = _require_text(product["id"], f"{location}.id")
        if not NAME_RE.fullmatch(product_id):
            raise CatalogError(f"{location}.id must be lowercase and hyphenated")
        products.append(
            ProductRecord(
                id=product_id,
                name=_require_text(product["name"], f"{location}.name"),
                description=_require_text(
                    product["description"], f"{location}.description"
                ),
            )
        )
    capabilities: list[CapabilityRecord] = []
    for index, raw_capability in enumerate(raw_capabilities):
        location = f"catalog.taxonomy.capabilities[{index}]"
        capability = _require_mapping(raw_capability, location)
        _require_exact_keys(
            capability, CAPABILITY_KEYS, CAPABILITY_KEYS, location
        )
        product_id = _require_text(
            capability["product"], f"{location}.product"
        )
        capability_id = _require_text(capability["id"], f"{location}.id")
        if not NAME_RE.fullmatch(product_id) or not NAME_RE.fullmatch(capability_id):
            raise CatalogError(
                f"{location}.product and .id must be lowercase and hyphenated"
            )
        capabilities.append(
            CapabilityRecord(
                product=product_id,
                id=capability_id,
                name=_require_text(capability["name"], f"{location}.name"),
            )
        )
    mcp_section = shared_sections["local_skill_mcp_server"]
    if not mcp_section.startswith("## Local Skill MCP Server\n"):
        raise CatalogError(
            "catalog.shared_sections.local_skill_mcp_server must start with its H2 heading"
        )
    normalized_mcp_section = re.sub(r"\s+", " ", mcp_section)
    missing_safety = [
        token
        for token in MCP_SAFETY_TOKENS
        if re.sub(r"\s+", " ", token) not in normalized_mcp_section
    ]
    if missing_safety:
        raise CatalogError(
            "local MCP safety section is missing required controls: "
            + ", ".join(missing_safety)
        )

    raw_skills = root["skills"]
    if not isinstance(raw_skills, list) or not raw_skills:
        raise CatalogError("catalog.skills must be a non-empty sequence")
    records: list[SkillRecord] = []
    seen_names: set[str] = set()
    for index, raw_entry in enumerate(raw_skills):
        location = f"catalog.skills[{index}]"
        entry = _require_mapping(raw_entry, location)
        _require_exact_keys(entry, SKILL_KEYS, SKILL_REQUIRED_KEYS, location)
        name = _require_text(entry["name"], f"{location}.name")
        if len(name) > 64 or not NAME_RE.fullmatch(name):
            raise CatalogError(
                f"{location}.name must be a lowercase hyphenated identifier up to 64 characters"
            )
        if name in seen_names:
            raise CatalogError(f"duplicate skill name: {name}")
        seen_names.add(name)
        status = _require_text(entry["status"], f"{location}.status")
        if status not in STATUSES:
            raise CatalogError(
                f"{location}.status must be one of: {', '.join(sorted(STATUSES))}"
            )
        replaced_by_raw = entry.get("replaced_by")
        replaced_by = (
            _require_text(replaced_by_raw, f"{location}.replaced_by")
            if replaced_by_raw is not None
            else None
        )
        migration_raw = entry.get("migration")
        migration = (
            _require_text(migration_raw, f"{location}.migration")
            if migration_raw is not None
            else None
        )
        command_summary = _require_text(
            entry["command_summary"], f"{location}.command_summary"
        )
        if command_summary == command_handoff_boilerplate(name):
            raise CatalogError(
                f"{location}.command_summary duplicates the generated command handoff; "
                "describe the skill-specific workflow instead"
            )
        if command_summary.startswith("#"):
            raise CatalogError(
                f"{location}.command_summary must be skill-specific prose, not a "
                "Markdown heading"
            )
        records.append(
            SkillRecord(
                name=name,
                path=_require_text(entry["path"], f"{location}.path"),
                target=_require_text(entry["target"], f"{location}.target"),
                purpose=_require_text(entry["purpose"], f"{location}.purpose"),
                command_summary=command_summary,
                product=_require_text(entry["product"], f"{location}.product"),
                capability=_require_text(
                    entry["capability"], f"{location}.capability"
                ),
                status=status,
                replaced_by=replaced_by,
                migration=migration,
            )
        )

    record_tuple = tuple(records)
    _validate_alias_graph(record_tuple)
    product_tuple = tuple(products)
    capability_tuple = tuple(capabilities)
    _validate_taxonomy(product_tuple, capability_tuple, record_tuple)
    alias_count = sum(record.deprecated for record in record_tuple)
    if root["skill_count"] != len(record_tuple):
        raise CatalogError(
            f"catalog.skill_count is {root['skill_count']}, expected {len(record_tuple)}"
        )
    if root["alias_count"] != alias_count:
        raise CatalogError(
            f"catalog.alias_count is {root['alias_count']}, expected {alias_count}"
        )

    return SkillCatalog(
        schema_version=SCHEMA_VERSION,
        declared_skill_count=root["skill_count"],
        declared_alias_count=root["alias_count"],
        shared_sections=MappingProxyType(shared_sections),
        products=product_tuple,
        capabilities=capability_tuple,
        skills=record_tuple,
        source_path=source_path,
    )

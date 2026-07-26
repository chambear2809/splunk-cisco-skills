#!/usr/bin/env python3
"""Offline semantic audit for repo-wide product and feature coverage."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.shared.skill_catalog import (  # noqa: E402
    CatalogError,
    SkillCatalog,
    load_catalog,
    parse_requirement_skill_rows,
)


SKILLS_DIR = REPO_ROOT / "skills"
APP_REGISTRY_PATH = SKILLS_DIR / "shared" / "app_registry.json"
APP_EVIDENCE_PATH = (
    SKILLS_DIR / "shared" / "references" / "splunkbase_registry_evidence.json"
)
PRODUCT_REGISTRY_PATH = SKILLS_DIR / "shared" / "skill_product_registry.json"
VALIDATION_REGISTRY_PATH = SKILLS_DIR / "shared" / "skill_validation_registry.json"
COVERAGE_MANIFEST_PATH = SKILLS_DIR / "shared" / "product_feature_coverage.json"

CATALOG_DOCS = (
    "AGENTS.md",
    "CLAUDE.md",
    "SKILL_REQUIREMENTS.md",
)

FEATURE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
SKILL_NAME_RE = re.compile(
    r"\b(?:cisco|splunk|widefield|galileo|lemonade)-[a-z0-9-]+\b"
)
HTTPS_URL_RE = re.compile(r"https://[^\s)>|]+")
MARKDOWN_SEPARATOR_RE = re.compile(r":?-{3,}:?\Z")
CATALOG_ROUTER_RE = re.compile(r"\brouter\b", flags=re.IGNORECASE)


@dataclass(frozen=True)
class FeatureCoverage:
    """One normalized row from a router-owned product or feature source."""

    feature_id: str
    name: str
    source_statuses: tuple[str, ...]
    owners: tuple[str, ...]
    boundary: str
    validation_evidence: str
    source_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterResult:
    """Normalized adapter output plus source-declared status values."""

    features: tuple[FeatureCoverage, ...]
    declared_statuses: frozenset[str]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_path(value: Any) -> Path:
    """Resolve a manifest path while requiring containment in the repository."""

    raw = Path(str(value))
    if not str(value).strip() or raw.is_absolute():
        raise ValueError(f"manifest path must be repository-relative: {value!r}")
    resolved = (REPO_ROOT / raw).resolve()
    if not resolved.is_relative_to(REPO_ROOT.resolve()):
        raise ValueError(f"manifest path escapes the repository: {value!r}")
    return resolved


def _clean_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def python_literal_assignment(path: Path, name: str) -> Any:
    """Read one literal module assignment without importing or executing it."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            )
        ):
            return ast.literal_eval(node.value)
    raise ValueError(
        f"{path.relative_to(REPO_ROOT)}: missing literal assignment {name}"
    )


def python_mapping_literal_field(path: Path, name: str, field: str) -> Any:
    """Read one literal field from a module-level dictionary assignment."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            )
            and isinstance(node.value, ast.Dict)
        ):
            continue
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == field:
                return ast.literal_eval(value)
    raise ValueError(
        f"{path.relative_to(REPO_ROOT)}: missing literal field {name}[{field!r}]"
    )


def load_appdynamics_taxonomy(path: Path) -> dict[str, Any]:
    """Load the flat AppDynamics taxonomy, with a dependency-free fallback."""

    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        yaml = None

    if yaml is not None:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("AppDynamics taxonomy must be a mapping")
        return loaded

    lines = path.read_text(encoding="utf-8").splitlines()
    result: dict[str, Any] = {}
    generated_from: list[str] = []
    features: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    index = 0

    while index < len(lines):
        line = lines[index]
        if line.startswith("generated_from:"):
            index += 1
            while index < len(lines) and lines[index].startswith("  - "):
                generated_from.append(_clean_scalar(lines[index][4:]))
                index += 1
            result["generated_from"] = generated_from
            continue
        if line.startswith("features:"):
            index += 1
            while index < len(lines):
                row_line = lines[index]
                if row_line.startswith("  - "):
                    current = {}
                    features.append(current)
                    content = row_line[4:]
                elif row_line.startswith("    ") and current is not None:
                    content = row_line[4:]
                elif not row_line.strip():
                    index += 1
                    continue
                else:
                    break

                if ":" not in content:
                    raise ValueError(
                        f"{path.relative_to(REPO_ROOT)}:{index + 1}: "
                        "unsupported taxonomy syntax"
                    )
                key, raw_value = content.split(":", 1)
                value = raw_value.strip()
                if value in {">", ">-", "|", "|-"}:
                    folded: list[str] = []
                    index += 1
                    while index < len(lines) and lines[index].startswith("      "):
                        folded.append(lines[index].strip())
                        index += 1
                    current[key.strip()] = " ".join(folded)
                    continue
                current[key.strip()] = _clean_scalar(value)
                index += 1
            result["features"] = features
            continue
        if line and not line.startswith(" ") and ":" in line:
            key, raw_value = line.split(":", 1)
            result[key.strip()] = _clean_scalar(raw_value)
        index += 1

    return result


def catalog_skills(path: Path, catalog: SkillCatalog) -> set[str]:
    text = path.read_text(encoding="utf-8")
    if path.name == "SKILL_REQUIREMENTS.md":
        return set(parse_requirement_skill_rows(text, catalog))
    return set(re.findall(r"^\| `([^`]+)` \|", text, flags=re.MULTILINE))


def check_catalogs(
    catalog: SkillCatalog,
    errors: list[str],
    summary: dict[str, Any],
) -> None:
    skills = set(catalog.by_name)
    for rel_path in CATALOG_DOCS:
        try:
            actual = catalog_skills(REPO_ROOT / rel_path, catalog)
        except CatalogError as exc:
            errors.append(f"{rel_path}: {exc}")
            actual = set()
        missing = sorted(skills - actual)
        extra = sorted(actual - skills)
        summary[f"{rel_path}:skills"] = len(actual)
        if missing:
            errors.append(f"{rel_path}: missing skill entries: {', '.join(missing)}")
        if extra:
            errors.append(f"{rel_path}: unknown skill entries: {', '.join(extra)}")

    ux_text = (REPO_ROOT / "SKILL_UX_CATALOG.md").read_text(encoding="utf-8")
    ux_rows = set(re.findall(r"^\| `([^`]+)` \|", ux_text, flags=re.MULTILINE))
    summary["SKILL_UX_CATALOG.md:skills"] = len(ux_rows)
    if ux_rows != skills:
        errors.append(
            "SKILL_UX_CATALOG.md: generated catalog is not in sync with "
            "skills/catalog.yaml"
        )


def check_app_registry(
    skills: set[str],
    errors: list[str],
    summary: dict[str, Any],
) -> None:
    registry = load_json(APP_REGISTRY_PATH)
    evidence = load_json(APP_EVIDENCE_PATH)
    apps = registry.get("apps", [])
    if not isinstance(apps, list) or not apps:
        errors.append("skills/shared/app_registry.json: apps must be a non-empty list")
        return

    numeric_ids: set[str] = set()
    missing_skill: list[str] = []
    duplicate_ids: set[str] = set()
    seen_ids: set[str] = set()
    for app in apps:
        if not isinstance(app, dict):
            errors.append(
                "skills/shared/app_registry.json: every app entry must be an object"
            )
            continue
        app_id = str(app.get("splunkbase_id", ""))
        app_name = str(app.get("app_name", "<unnamed>"))
        skill = str(app.get("skill", ""))
        if not skill or skill not in skills:
            missing_skill.append(
                f"{app_id or 'N/A'}:{app_name}->{skill or '<missing>'}"
            )
        if app_id:
            if app_id in seen_ids:
                duplicate_ids.add(app_id)
            seen_ids.add(app_id)
        if app_id.isdigit():
            numeric_ids.add(app_id)

    if missing_skill:
        errors.append(
            "app registry entries route to missing skills: " + ", ".join(missing_skill)
        )
    if duplicate_ids:
        errors.append(
            "app registry has duplicate splunkbase IDs: "
            + ", ".join(sorted(duplicate_ids))
        )

    evidence_ids = {
        str(app.get("splunkbase_id"))
        for app in evidence.get("apps", [])
        if isinstance(app, dict) and str(app.get("splunkbase_id", "")).isdigit()
    }
    if evidence.get("app_count") != len(numeric_ids):
        errors.append(
            "splunkbase evidence app_count does not match numeric registry entries: "
            f"{evidence.get('app_count')} != {len(numeric_ids)}"
        )
    if evidence_ids != numeric_ids:
        errors.append("splunkbase evidence IDs do not match numeric app registry IDs")

    summary["app_registry:apps"] = len(apps)
    summary["app_registry:numeric_apps"] = len(numeric_ids)
    summary["app_registry:routed_apps"] = len(apps) - len(missing_skill)


def check_product_registry(
    catalog: SkillCatalog,
    errors: list[str],
    summary: dict[str, Any],
) -> set[str]:
    """Validate and consume the generated product/capability ownership registry."""

    registry = load_json(PRODUCT_REGISTRY_PATH)
    provenance = registry.get("generated_from", {})
    if provenance.get("path") != "skills/catalog.yaml":
        errors.append(
            "skills/shared/skill_product_registry.json: generated_from.path "
            "must be skills/catalog.yaml"
        )
    if provenance.get("schema_version") != catalog.schema_version:
        errors.append(
            "skills/shared/skill_product_registry.json: generated schema version "
            "does not match skills/catalog.yaml"
        )
    if provenance.get("sha256") != catalog.checksum:
        errors.append(
            "skills/shared/skill_product_registry.json: generated checksum "
            "does not match skills/catalog.yaml"
        )

    raw_records = registry.get("skill_records", [])
    if not isinstance(raw_records, list):
        errors.append(
            "skills/shared/skill_product_registry.json: skill_records must be a list"
        )
        raw_records = []
    expected_records = [
        {
            "name": record.name,
            "status": record.status,
            "replaced_by": record.replaced_by,
        }
        for record in catalog.skills
    ]
    if raw_records != expected_records:
        errors.append(
            "skills/shared/skill_product_registry.json: lifecycle records "
            "do not match skills/catalog.yaml"
        )
    registry_skills = {
        str(record.get("name", ""))
        for record in raw_records
        if isinstance(record, dict) and record.get("name")
    }

    products = registry.get("products", [])
    if not isinstance(products, list):
        errors.append(
            "skills/shared/skill_product_registry.json: products must be a list"
        )
        products = []

    expected_products = {record.id: record for record in catalog.products}
    expected_capabilities = {
        (record.product, record.id): record for record in catalog.capabilities
    }
    seen_products: set[str] = set()
    seen_capabilities: set[tuple[str, str]] = set()
    assignments: dict[str, list[tuple[str, str]]] = {}

    for product in products:
        if not isinstance(product, dict):
            errors.append(
                "skills/shared/skill_product_registry.json: product entries "
                "must be objects"
            )
            continue
        product_id = str(product.get("id", ""))
        if product_id in seen_products:
            errors.append(f"product registry has duplicate product id: {product_id}")
        seen_products.add(product_id)
        expected_product = expected_products.get(product_id)
        if expected_product is None:
            errors.append(f"product registry has unknown product id: {product_id}")
        elif (
            product.get("name") != expected_product.name
            or product.get("description") != expected_product.description
        ):
            errors.append(f"product registry metadata drift for product: {product_id}")

        capabilities = product.get("capabilities", [])
        if not isinstance(capabilities, list):
            errors.append(f"product registry {product_id}: capabilities must be a list")
            continue
        for capability in capabilities:
            if not isinstance(capability, dict):
                errors.append(
                    f"product registry {product_id}: capability must be an object"
                )
                continue
            capability_id = str(capability.get("id", ""))
            capability_key = (product_id, capability_id)
            if capability_key in seen_capabilities:
                errors.append(
                    "product registry has duplicate capability: "
                    f"{product_id}/{capability_id}"
                )
            seen_capabilities.add(capability_key)
            expected_capability = expected_capabilities.get(capability_key)
            if expected_capability is None:
                errors.append(
                    "product registry has unknown capability: "
                    f"{product_id}/{capability_id}"
                )
            elif capability.get("name") != expected_capability.name:
                errors.append(
                    "product registry capability metadata drift: "
                    f"{product_id}/{capability_id}"
                )
            capability_skills = capability.get("skills", [])
            if not isinstance(capability_skills, list):
                errors.append(
                    f"product registry {product_id}/{capability_id}: "
                    "skills must be a list"
                )
                continue
            for skill in capability_skills:
                skill_name = str(skill)
                assignments.setdefault(skill_name, []).append(capability_key)

    if seen_products != set(expected_products):
        errors.append(
            "skills/shared/skill_product_registry.json: product IDs do not "
            "match skills/catalog.yaml"
        )
    if seen_capabilities != set(expected_capabilities):
        errors.append(
            "skills/shared/skill_product_registry.json: capabilities do not "
            "match skills/catalog.yaml"
        )

    for record in catalog.skills:
        actual = assignments.get(record.name, [])
        expected = [(record.product, record.capability)]
        if actual != expected:
            errors.append(
                f"product registry assignment for {record.name} is {actual!r}; "
                f"expected {expected!r}"
            )
    unknown_assignments = sorted(set(assignments) - set(catalog.by_name))
    if unknown_assignments:
        errors.append(
            "product registry assigns unknown skills: "
            + ", ".join(unknown_assignments)
        )

    summary["product_registry:products"] = len(seen_products)
    summary["product_registry:capabilities"] = len(seen_capabilities)
    summary["product_registry:skills"] = len(registry_skills)
    return registry_skills


def validation_registry_skills(
    catalog: SkillCatalog,
    errors: list[str],
) -> set[str]:
    registry = load_json(VALIDATION_REGISTRY_PATH)
    provenance = registry.get("generated_from", {})
    if (
        provenance.get("path") != "skills/catalog.yaml"
        or provenance.get("schema_version") != catalog.schema_version
        or provenance.get("sha256") != catalog.checksum
    ):
        errors.append(
            "skills/shared/skill_validation_registry.json: provenance does "
            "not match skills/catalog.yaml"
        )
    values = registry.get("skills", [])
    if not isinstance(values, list):
        errors.append(
            "skills/shared/skill_validation_registry.json: skills must be a list"
        )
        return set()
    return {str(value) for value in values}


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _extract_https_urls(text: str) -> list[str]:
    return [match.rstrip(".,;:`") for match in HTTPS_URL_RE.findall(text)]


def _slug(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("`", "")
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _markdown_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    body = stripped[1:-1] if stripped.endswith("|") else stripped[1:]
    return [
        cell.replace(r"\|", "|").strip()
        for cell in re.split(r"(?<!\\)\|", body)
    ]


def markdown_tables(path: Path) -> list[tuple[list[str], list[dict[str, str]]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    tables: list[tuple[list[str], list[dict[str, str]]]] = []
    index = 0
    while index + 1 < len(lines):
        headers = _markdown_cells(lines[index])
        separators = _markdown_cells(lines[index + 1])
        if (
            headers
            and len(headers) == len(separators)
            and all(MARKDOWN_SEPARATOR_RE.fullmatch(cell) for cell in separators)
        ):
            rows: list[dict[str, str]] = []
            index += 2
            while index < len(lines):
                cells = _markdown_cells(lines[index])
                if not cells:
                    break
                if len(cells) != len(headers):
                    raise ValueError(
                        f"{path.relative_to(REPO_ROOT)}:{index + 1}: "
                        "markdown table width does not match its header"
                    )
                rows.append(dict(zip(headers, cells, strict=True)))
                index += 1
            tables.append((headers, rows))
            continue
        index += 1
    return tables


def markdown_section_bullets(path: Path, heading: str) -> list[str]:
    """Return normalized, continuation-aware bullets under one H2 section."""

    lines = path.read_text(encoding="utf-8").splitlines()
    marker = f"## {heading}"
    try:
        index = lines.index(marker) + 1
    except ValueError as exc:
        raise ValueError(
            f"{path.relative_to(REPO_ROOT)}: missing section {marker!r}"
        ) from exc

    bullets: list[str] = []
    current: list[str] | None = None
    while index < len(lines) and not lines[index].startswith("## "):
        line = lines[index]
        if line.startswith("- "):
            if current is not None:
                bullets.append(" ".join(current).strip())
            current = [line[2:].strip()]
        elif current is not None and line.startswith("  "):
            current.append(line.strip())
        elif current is not None and not line.strip():
            bullets.append(" ".join(current).strip())
            current = None
        index += 1
    if current is not None:
        bullets.append(" ".join(current).strip())
    return bullets


def _markdown_skill_owners(value: str, router_skill: str) -> tuple[str, ...]:
    owners = SKILL_NAME_RE.findall(value)
    owners.append(router_skill)
    return _unique(owners)


def adapt_cisco_scan(router: dict[str, Any]) -> AdapterResult:
    catalog = load_json(repo_path(router["source_path"]))
    rows = catalog.get("products", [])
    if catalog.get("product_count") != len(rows):
        raise ValueError("Cisco catalog product_count does not match products")
    global_url = str(catalog.get("scan_source", {}).get("url", ""))
    features: list[FeatureCoverage] = []
    statuses: set[str] = set()
    for row in rows:
        row_id = str(row.get("id", "")).strip()
        status = str(row.get("automation_state", "")).strip()
        statuses.add(status)
        owners = _as_string_list(row.get("primary_skill"))
        owners.extend(_as_string_list(row.get("companion_skills")))
        if not owners:
            owners = [str(router["router_skill"])]
        if status == "automated" and (
            not row.get("primary_skill") or not isinstance(row.get("route"), dict)
        ):
            raise ValueError(
                f"{row_id}: automated Cisco rows require primary_skill and route"
            )
        boundary = str(
            row.get("manual_gap_reason") or row.get("notes") or ""
        ).strip()
        urls = _as_string_list(row.get("learn_more_url"))
        urls.extend(_as_string_list(global_url))
        features.append(
            FeatureCoverage(
                feature_id=row_id,
                name=str(row.get("display_name", "")).strip(),
                source_statuses=(status,),
                owners=_unique(owners),
                boundary=boundary,
                validation_evidence="Child completion validator or router gap report.",
                source_urls=_unique(urls),
            )
        )
    return AdapterResult(tuple(features), frozenset(statuses))


def adapt_security_catalog(router: dict[str, Any]) -> AdapterResult:
    catalog = load_json(repo_path(router["source_path"]))
    rows = catalog.get("entries", [])
    declared = {str(value) for value in catalog.get("statuses", [])}
    features: list[FeatureCoverage] = []
    for row in rows:
        owners = _as_string_list(row.get("route"))
        features.append(
            FeatureCoverage(
                feature_id=str(row.get("key", "")).strip(),
                name=str(row.get("name", "")).strip(),
                source_statuses=(str(row.get("status", "")).strip(),),
                owners=_unique(owners),
                boundary=str(row.get("notes", "")).strip(),
                validation_evidence=(
                    "Router resolution plus every routed child validator."
                ),
                source_urls=_unique(_as_string_list(row.get("source_urls"))),
            )
        )
    observed = {status for feature in features for status in feature.source_statuses}
    if observed - declared:
        raise ValueError(
            "security catalog uses statuses absent from its statuses declaration: "
            + ", ".join(sorted(observed - declared))
        )
    return AdapterResult(tuple(features), frozenset(declared))


def adapt_appdynamics_taxonomy(router: dict[str, Any]) -> AdapterResult:
    taxonomy = load_appdynamics_taxonomy(repo_path(router["source_path"]))
    rows = taxonomy.get("features", [])
    if not isinstance(rows, list):
        raise ValueError("AppDynamics taxonomy features must be a list")
    features: list[FeatureCoverage] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("AppDynamics taxonomy feature rows must be mappings")
        features.append(
            FeatureCoverage(
                feature_id=str(row.get("id", "")).strip(),
                name=str(row.get("feature", "")).strip(),
                source_statuses=(str(row.get("status", "")).strip(),),
                owners=_unique(_as_string_list(row.get("owner"))),
                boundary=str(row.get("apply_boundary", "")).strip(),
                validation_evidence=str(row.get("validation_method", "")).strip(),
                source_urls=_unique(_as_string_list(row.get("source_url"))),
            )
        )
    observed = {status for feature in features for status in feature.source_statuses}
    return AdapterResult(tuple(features), frozenset(observed))


def adapt_data_fabric_matrix(router: dict[str, Any]) -> AdapterResult:
    path = repo_path(router["source_path"])
    features: list[FeatureCoverage] = []
    for headers, rows in markdown_tables(path):
        required = {"Surface", "Product stage", "Repository owner", "Boundary"}
        if not required.issubset(headers):
            continue
        for row in rows:
            features.append(
                FeatureCoverage(
                    feature_id=_slug(row["Surface"]),
                    name=row["Surface"].strip(),
                    source_statuses=("documented_boundary",),
                    owners=_markdown_skill_owners(
                        row["Repository owner"], str(router["router_skill"])
                    ),
                    boundary=row["Boundary"].strip(),
                    validation_evidence=(
                        "Router coverage report, product matrix, and gap register."
                    ),
                )
            )
    return AdapterResult(tuple(features), frozenset({"documented_boundary"}))


def adapt_observability_matrix(router: dict[str, Any]) -> AdapterResult:
    path = repo_path(router["source_path"])
    features: list[FeatureCoverage] = []
    for headers, rows in markdown_tables(path):
        required = {
            "Surface",
            "Coverage",
            "What the skill renders",
            "Owning follow-up",
        }
        if not required.issubset(headers):
            continue
        for row in rows:
            statuses = tuple(re.findall(r"`([a-z_]+)`", row["Coverage"]))
            features.append(
                FeatureCoverage(
                    feature_id=_slug(row["Surface"]),
                    name=row["Surface"].strip(),
                    source_statuses=statuses,
                    owners=_markdown_skill_owners(
                        row["Owning follow-up"], str(router["router_skill"])
                    ),
                    boundary=row["Owning follow-up"].strip(),
                    validation_evidence=row["What the skill renders"].strip(),
                )
            )
    observed = {status for feature in features for status in feature.source_statuses}
    return AdapterResult(tuple(features), frozenset(observed))


def adapt_widefield_router(router: dict[str, Any]) -> AdapterResult:
    path = repo_path(router["source_path"])
    router_skill = str(router["router_skill"])
    action_bullets = markdown_section_bullets(path, "Action Model")
    child_skills = [
        match.group(1)
        for bullet in action_bullets
        if (match := re.fullmatch(r"`([a-z0-9-]+)`", bullet))
    ]
    if not child_skills:
        raise ValueError("WideField Action Model has no delegated child skills")
    runtime_path = repo_path(router["runtime_source_path"])
    runtime_children = {
        str(value)
        for value in python_mapping_literal_field(
            runtime_path, "PROFILE", "child_skills"
        )
    }
    if set(child_skills) != runtime_children:
        raise ValueError(
            "WideField delegated-child reference/runtime drift: "
            f"reference={sorted(child_skills)!r}, "
            f"runtime={sorted(runtime_children)!r}"
        )

    features: list[FeatureCoverage] = []
    child_boundary = (
        "The parent delegates child render/validate orchestration only; live "
        "mutation requires a documented child API path and the child's gate."
    )
    for child_skill in child_skills:
        features.append(
            FeatureCoverage(
                feature_id=f"child.{child_skill}",
                name=f"Delegated child: {child_skill}",
                source_statuses=("delegated_child",),
                owners=(child_skill,),
                boundary=child_boundary,
                validation_evidence=(
                    "Parent evidence preflight followed by the delegated child "
                    "validation surface."
                ),
            )
        )

    capability_bullets = markdown_section_bullets(path, "Capability Coverage")
    if not capability_bullets:
        raise ValueError("WideField Capability Coverage has no feature bullets")
    capability_boundary = (
        "The parent renders coverage and evidence assets without calling "
        "private or undocumented WideField APIs."
    )
    for bullet in capability_bullets:
        name = bullet.rstrip(".").strip()
        features.append(
            FeatureCoverage(
                feature_id=f"capability.{_slug(name)}",
                name=name,
                source_statuses=("rendered_capability",),
                owners=(router_skill,),
                boundary=capability_boundary,
                validation_evidence=(
                    "Parent validation checks capability-coverage.md and the "
                    "readiness evidence template."
                ),
            )
        )

    return AdapterResult(
        tuple(features),
        frozenset({"delegated_child", "rendered_capability"}),
    )


def adapt_coding_agent_router(router: dict[str, Any]) -> AdapterResult:
    path = repo_path(router["source_path"])
    router_skill = str(router["router_skill"])
    features: list[FeatureCoverage] = []
    observed: set[str] = set()
    agent_rows: list[dict[str, str]] = []
    destination_rows: list[dict[str, str]] = []
    for headers, rows in markdown_tables(path):
        if {"Agent", "Status", "Child skill"}.issubset(headers):
            agent_rows.extend(rows)
        if {"Destination", "Parent behavior"}.issubset(headers):
            destination_rows.extend(rows)
    if not agent_rows or not destination_rows:
        raise ValueError(
            "coding-agent reference must contain Agent and Destination matrices"
        )
    runtime_path = repo_path(router["runtime_source_path"])
    runtime_agents = {
        str(value)
        for value in python_literal_assignment(runtime_path, "VALID_AGENTS")
    }
    runtime_destinations = {
        str(value)
        for value in python_literal_assignment(
            runtime_path, "VALID_DESTINATIONS"
        )
    }
    matrix_agents = {
        row["Agent"].strip().strip("`") for row in agent_rows
    }
    matrix_destinations = {
        row["Destination"].strip().strip("`") for row in destination_rows
    }
    if matrix_agents != runtime_agents:
        raise ValueError(
            "coding-agent Agent Matrix/runtime drift: "
            f"reference={sorted(matrix_agents)!r}, "
            f"runtime={sorted(runtime_agents)!r}"
        )
    if matrix_destinations != runtime_destinations:
        raise ValueError(
            "coding-agent Destination Matrix/runtime drift: "
            f"reference={sorted(matrix_destinations)!r}, "
            f"runtime={sorted(runtime_destinations)!r}"
        )
    runtime_children = {
        str(python_literal_assignment(runtime_path, "CODEX_CHILD")),
        str(python_literal_assignment(runtime_path, "CLAUDE_CODE_CHILD")),
    }
    matrix_children = {
        child
        for row in agent_rows
        for child in SKILL_NAME_RE.findall(row["Child skill"])
    }
    if matrix_children != runtime_children:
        raise ValueError(
            "coding-agent child reference/runtime drift: "
            f"reference={sorted(matrix_children)!r}, "
            f"runtime={sorted(runtime_children)!r}"
        )

    parent_boundary = (
        "The parent may resolve and invoke a child render command, but it never "
        "writes agent profiles, installs hooks, or mutates collector or Splunk "
        "configuration."
    )
    for row in agent_rows:
        agent = row["Agent"].strip().strip("`")
        status = row["Status"].strip()
        observed.add(status)
        child_skills = SKILL_NAME_RE.findall(row["Child skill"])
        owners = _unique(child_skills or [router_skill])
        features.append(
            FeatureCoverage(
                feature_id=f"agent.{_slug(agent)}",
                name=f"Coding agent: {agent}",
                source_statuses=(status,),
                owners=owners,
                boundary=parent_boundary,
                validation_evidence=(
                    "Parent route resolution and the selected canonical child "
                    "validator; placeholders remain parent doctor findings."
                ),
            )
        )

    for row in destination_rows:
        destination = row["Destination"].strip().strip("`")
        status = "render_plan"
        observed.add(status)
        features.append(
            FeatureCoverage(
                feature_id=f"destination.{_slug(destination)}",
                name=f"Destination mode: {destination}",
                source_statuses=(status,),
                owners=(router_skill,),
                boundary=parent_boundary,
                validation_evidence=row["Parent behavior"].strip(),
            )
        )

    return AdapterResult(tuple(features), frozenset(observed))


def adapt_supported_addons(router: dict[str, Any]) -> AdapterResult:
    catalog = load_json(repo_path(router["source_path"]))
    glossary = catalog.get("official_glossary", {})
    entries = glossary.get("entries", [])
    routes = glossary.get("routes", {})
    if not isinstance(entries, list) or not isinstance(routes, dict):
        raise ValueError("Supported Add-ons glossary entries/routes are invalid")

    entry_keys = {
        str(entry.get("key", ""))
        for entry in entries
        if isinstance(entry, dict)
    }
    extra_routes = sorted(set(routes) - entry_keys)
    if extra_routes:
        raise ValueError(
            "Supported Add-ons routes have no glossary row: "
            + ", ".join(extra_routes)
        )
    profile_keys = {
        str(profile.get("key", ""))
        for profile in catalog.get("profiles", [])
        if isinstance(profile, dict)
    }
    features: list[FeatureCoverage] = []
    observed: set[str] = set()
    base = "https://help.splunk.com/en/supported-add-ons/splunk-supported-add-ons"

    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Supported Add-ons glossary rows must be objects")
        key = str(entry.get("key", "")).strip()
        route = routes.get(key, {})
        if not isinstance(route, dict):
            raise ValueError(f"{key}: Supported Add-ons route must be an object")
        status = str(route.get("status", "install_only_handoff")).strip()
        observed.add(status)
        profile = str(route.get("profile", "")).strip()
        if profile and profile not in profile_keys:
            raise ValueError(f"{key}: unknown Supported Add-ons profile {profile}")
        owner = str(route.get("handoff_skill", "")).strip()
        if status == "first_class_profile" and not profile:
            raise ValueError(f"{key}: first_class_profile requires a profile")
        if status == "handoff_profile" and not owner:
            raise ValueError(f"{key}: handoff_profile requires a handoff_skill")
        if not owner:
            owner = (
                str(router["router_skill"])
                if status == "first_class_profile"
                else "splunk-app-install"
            )
        docs = _as_string_list(entry.get("docs"))
        if not docs:
            docs = [f"{base}/{key}"]
        features.append(
            FeatureCoverage(
                feature_id=key,
                name=str(entry.get("name", "")).strip(),
                source_statuses=(status,),
                owners=(owner,),
                boundary=str(route.get("notes", "")).strip(),
                validation_evidence=(
                    "First-class profile validator, delegated readiness validator, "
                    "or generic install-only handoff validation."
                ),
                source_urls=_unique(docs),
            )
        )

    declared = {str(value) for value in catalog.get("supported_statuses", [])}
    if observed - declared:
        raise ValueError(
            "Supported Add-ons uses statuses absent from supported_statuses: "
            + ", ".join(sorted(observed - declared))
        )
    return AdapterResult(tuple(features), frozenset(declared))


ADAPTERS = {
    "appdynamics_taxonomy": adapt_appdynamics_taxonomy,
    "cisco_scan_catalog": adapt_cisco_scan,
    "coding_agent_markdown_router": adapt_coding_agent_router,
    "data_fabric_markdown_matrix": adapt_data_fabric_matrix,
    "observability_markdown_matrix": adapt_observability_matrix,
    "security_catalog": adapt_security_catalog,
    "supported_addons_catalog": adapt_supported_addons,
    "widefield_markdown_router": adapt_widefield_router,
}


def _dot_path(payload: Any, dotted_path: str) -> Any:
    value = payload
    for key in dotted_path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise KeyError(dotted_path)
        value = value[key]
    return value


def _load_provenance_payload(path: Path, source_format: str) -> Any:
    if source_format == "json":
        return load_json(path)
    if source_format == "yaml":
        return load_appdynamics_taxonomy(path)
    if source_format == "text":
        return path.read_text(encoding="utf-8")
    raise ValueError(f"unsupported provenance format: {source_format}")


def collect_provenance(
    router_id: str,
    entries: Any,
    max_age_days: int,
    as_of: date,
    errors: list[str],
) -> tuple[str, ...]:
    if not isinstance(entries, list) or not entries:
        errors.append(f"{router_id}: provenance must be a non-empty list")
        return ()

    urls: list[str] = []
    researched_dates: list[date] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"{router_id}: provenance[{index}] must be an object")
            continue
        rel_path = str(entry.get("path", ""))
        try:
            path = repo_path(rel_path)
        except ValueError as exc:
            errors.append(f"{router_id}: {exc}")
            continue
        if not path.is_file():
            errors.append(f"{router_id}: provenance file is missing: {rel_path}")
            continue
        source_format = str(entry.get("format", ""))
        try:
            payload = _load_provenance_payload(path, source_format)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{router_id}: cannot load provenance {rel_path}: {exc}")
            continue

        date_field = str(entry.get("date_field", "")).strip()
        date_pattern = str(entry.get("date_pattern", "")).strip()
        raw_dates: list[str] = []
        if date_field:
            try:
                raw_dates.extend(_as_string_list(_dot_path(payload, date_field)))
            except KeyError:
                errors.append(
                    f"{router_id}: provenance {rel_path} lacks date field {date_field}"
                )
        if date_pattern:
            if not isinstance(payload, str):
                errors.append(
                    f"{router_id}: date_pattern requires text provenance: {rel_path}"
                )
            else:
                match = re.search(date_pattern, payload)
                if match is None or "date" not in match.groupdict():
                    errors.append(
                        f"{router_id}: date_pattern did not capture 'date' in {rel_path}"
                    )
                else:
                    raw_dates.append(match.group("date"))
        for raw_date in raw_dates:
            try:
                parsed = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                errors.append(
                    f"{router_id}: invalid provenance date {raw_date!r} in {rel_path}"
                )
                continue
            researched_dates.append(parsed)
            age = (as_of - parsed).days
            if age < 0:
                errors.append(
                    f"{router_id}: provenance date {parsed} is after audit date {as_of}"
                )
            elif age > max_age_days:
                errors.append(
                    f"{router_id}: provenance {rel_path} is stale "
                    f"({age} days; maximum {max_age_days})"
                )

        for field in entry.get("url_fields", []):
            try:
                urls.extend(_as_string_list(_dot_path(payload, str(field))))
            except KeyError:
                errors.append(
                    f"{router_id}: provenance {rel_path} lacks URL field {field}"
                )
        if entry.get("extract_https_urls"):
            text = payload if isinstance(payload, str) else json.dumps(payload)
            urls.extend(_extract_https_urls(text))

    if not researched_dates:
        errors.append(f"{router_id}: provenance has no researched/verified date")
    unique_urls = _unique(urls)
    if not unique_urls:
        errors.append(f"{router_id}: provenance has no source URL")
    for url in unique_urls:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append(f"{router_id}: source URL must be absolute HTTPS: {url}")
    return unique_urls


def _snapshot(features: tuple[FeatureCoverage, ...]) -> tuple[int, str]:
    feature_ids = sorted(feature.feature_id for feature in features)
    content = "".join(f"{feature_id}\n" for feature_id in feature_ids).encode()
    return len(feature_ids), hashlib.sha256(content).hexdigest()


def _contract_snapshot(
    features: tuple[FeatureCoverage, ...],
    status_contracts: dict[str, Any],
) -> str:
    """Hash normalized semantic coverage fields independently of feature scope."""

    payload = [
        {
            "automation_boundaries": [
                {
                    "source_status": status,
                    "value": feature.boundary
                    or str(
                        status_contracts.get(status, {}).get(
                            "automation_boundary", ""
                        )
                    ).strip(),
                }
                for status in sorted(feature.source_statuses)
            ],
            "feature_id": feature.feature_id,
            "name": feature.name,
            "owners": sorted(feature.owners),
            "row_source_urls": sorted(feature.source_urls),
            "status_mappings": [
                {
                    "coverage_status": str(
                        status_contracts.get(status, {}).get(
                            "coverage_status", ""
                        )
                    ).strip(),
                    "source_status": status,
                }
                for status in sorted(feature.source_statuses)
            ],
            "source_statuses": sorted(feature.source_statuses),
            "validation_evidence": feature.validation_evidence,
        }
        for feature in sorted(features, key=lambda row: row.feature_id)
    ]
    content = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _expected_validator(skill: str) -> Path:
    return SKILLS_DIR / skill / "scripts" / "validate.sh"


def check_source_url(
    feature_label: str,
    url: str,
    allowed_hosts: set[str],
    errors: list[str],
) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        errors.append(
            f"{feature_label}: source URL must be absolute HTTPS: {url}"
        )
    elif parsed.hostname.lower() not in allowed_hosts:
        errors.append(
            f"{feature_label}: source host is not approved: {parsed.hostname}"
        )


def check_semantic_coverage(
    catalog: SkillCatalog,
    product_registry_skills: set[str],
    validation_skills: set[str],
    manifest_path: Path,
    as_of: date,
    errors: list[str],
    summary: dict[str, Any],
) -> None:
    try:
        manifest = load_json(manifest_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        errors.append(f"{manifest_path}: cannot load coverage manifest: {exc}")
        return
    if manifest.get("schema_version") != 1:
        errors.append(
            "skills/shared/product_feature_coverage.json: schema_version must be 1"
        )
    max_age_days = manifest.get("maximum_source_age_days")
    if not isinstance(max_age_days, int) or isinstance(max_age_days, bool):
        errors.append(
            "skills/shared/product_feature_coverage.json: "
            "maximum_source_age_days must be an integer"
        )
        return
    summary["coverage:audit_date"] = as_of.isoformat()
    summary["coverage:maximum_source_age_days"] = max_age_days
    allowed_coverage_statuses = {
        str(value) for value in manifest.get("allowed_coverage_statuses", [])
    }
    if not allowed_coverage_statuses:
        errors.append(
            "skills/shared/product_feature_coverage.json: "
            "allowed_coverage_statuses must be non-empty"
        )

    routers = manifest.get("routers", [])
    expected_router_count = manifest.get("router_count")
    if not isinstance(routers, list) or not routers:
        errors.append(
            "skills/shared/product_feature_coverage.json: routers must be non-empty"
        )
        return
    if expected_router_count != len(routers):
        errors.append(
            "skills/shared/product_feature_coverage.json: router_count does "
            f"not match routers ({expected_router_count} != {len(routers)})"
        )

    catalog_explicit_routers = {
        record.name
        for record in catalog.skills
        if record.status == "canonical" and CATALOG_ROUTER_RE.search(record.target)
    }
    manifest_explicit_routers = {
        str(router.get("router_skill", ""))
        for router in routers
        if isinstance(router, dict)
        and router.get("inventory_classification") == "catalog_explicit_router"
    }
    missing_catalog_routers = sorted(
        catalog_explicit_routers - manifest_explicit_routers
    )
    extra_catalog_routers = sorted(
        manifest_explicit_routers - catalog_explicit_routers
    )
    if missing_catalog_routers:
        errors.append(
            "coverage manifest omits canonical catalog routers: "
            + ", ".join(missing_catalog_routers)
        )
    if extra_catalog_routers:
        errors.append(
            "coverage manifest classifies non-router catalog targets as explicit "
            "routers: "
            + ", ".join(extra_catalog_routers)
        )
    summary["router_inventory:catalog_explicit"] = len(
        catalog_explicit_routers
    )
    summary["router_inventory:catalog_explicit_covered"] = len(
        catalog_explicit_routers & manifest_explicit_routers
    )

    seen_router_ids: set[str] = set()
    seen_router_skills: set[str] = set()
    global_feature_ids: set[str] = set()
    total_features = 0

    for router in routers:
        if not isinstance(router, dict):
            errors.append("coverage manifest router entries must be objects")
            continue
        router_id = str(router.get("id", "")).strip()
        router_skill = str(router.get("router_skill", "")).strip()
        adapter_name = str(router.get("adapter", "")).strip()
        inventory_classification = str(
            router.get("inventory_classification", "")
        ).strip()
        if inventory_classification not in {
            "catalog_explicit_router",
            "coverage_owner",
        }:
            errors.append(
                f"{router_id}: unsupported inventory_classification "
                f"{inventory_classification!r}"
            )
        if not FEATURE_ID_RE.fullmatch(router_id):
            errors.append(f"coverage manifest has invalid router id: {router_id!r}")
        if router_id in seen_router_ids:
            errors.append(f"coverage manifest has duplicate router id: {router_id}")
        seen_router_ids.add(router_id)
        if router_skill in seen_router_skills:
            errors.append(
                f"coverage manifest repeats router skill: {router_skill}"
            )
        seen_router_skills.add(router_skill)

        record = catalog.by_name.get(router_skill)
        if record is None:
            errors.append(f"{router_id}: router skill is missing: {router_skill}")
        elif record.status != "canonical":
            errors.append(
                f"{router_id}: router skill must be canonical: {router_skill}"
            )
        elif (
            inventory_classification == "catalog_explicit_router"
            and not CATALOG_ROUTER_RE.search(record.target)
        ):
            errors.append(
                f"{router_id}: catalog_explicit_router classification does not "
                "match the canonical target"
            )
        if router_skill not in product_registry_skills:
            errors.append(
                f"{router_id}: router skill is absent from product registry: "
                f"{router_skill}"
            )

        try:
            source_path = repo_path(router.get("source_path", ""))
            reference_path = repo_path(router.get("reference_path", ""))
            validation_path = repo_path(router.get("validation_path", ""))
        except ValueError as exc:
            errors.append(f"{router_id}: {exc}")
            continue
        for label, path in (
            ("source", source_path),
            ("reference", reference_path),
            ("validation", validation_path),
        ):
            if not path.is_file():
                errors.append(
                    f"{router_id}: {label} path is missing: "
                    f"{path.relative_to(REPO_ROOT)}"
                )
        expected_router_validation = _expected_validator(router_skill)
        if validation_path != expected_router_validation:
            errors.append(
                f"{router_id}: validation_path must be "
                f"{expected_router_validation.relative_to(REPO_ROOT)}"
            )

        global_source_urls = collect_provenance(
            router_id,
            router.get("provenance"),
            max_age_days,
            as_of,
            errors,
        )
        allowed_source_hosts = {
            str(value).lower()
            for value in router.get("allowed_source_hosts", [])
            if str(value).strip()
        }
        if not allowed_source_hosts:
            errors.append(f"{router_id}: allowed_source_hosts must be non-empty")
        for url in global_source_urls:
            check_source_url(
                f"{router_id}:provenance",
                url,
                allowed_source_hosts,
                errors,
            )
        summary[f"router:{router_id}:source_urls"] = len(global_source_urls)

        adapter = ADAPTERS.get(adapter_name)
        if adapter is None:
            errors.append(f"{router_id}: unsupported adapter: {adapter_name}")
            continue
        try:
            adapter_result = adapter(router)
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            errors.append(f"{router_id}: adapter failed: {exc}")
            continue

        features = adapter_result.features
        if not features:
            errors.append(f"{router_id}: adapter produced no feature rows")
            continue
        count, feature_hash = _snapshot(features)
        expected_count = router.get("feature_count")
        expected_hash = str(router.get("feature_ids_sha256", ""))
        if expected_count != count:
            errors.append(
                f"{router_id}: feature_count drift: expected {expected_count}, "
                f"actual {count}"
            )
        if expected_hash != feature_hash:
            errors.append(
                f"{router_id}: feature ID snapshot drift: expected "
                f"{expected_hash or '<missing>'}, actual {feature_hash}"
            )
        contracts = router.get("status_contracts", {})
        if not isinstance(contracts, dict) or not contracts:
            errors.append(f"{router_id}: status_contracts must be non-empty")
            contracts = {}
        contract_hash = _contract_snapshot(features, contracts)
        expected_contract_hash = str(
            router.get("feature_contracts_sha256", "")
        )
        if expected_contract_hash != contract_hash:
            errors.append(
                f"{router_id}: feature contract snapshot drift: expected "
                f"{expected_contract_hash or '<missing>'}, actual {contract_hash}"
            )
        declared_statuses = adapter_result.declared_statuses
        missing_contracts = sorted(declared_statuses - set(contracts))
        if missing_contracts:
            errors.append(
                f"{router_id}: source statuses lack contracts: "
                + ", ".join(missing_contracts)
            )
        reserved_statuses = {
            str(value) for value in router.get("reserved_source_statuses", [])
        }
        extra_contracts = sorted(
            set(contracts) - declared_statuses - reserved_statuses
        )
        if extra_contracts:
            errors.append(
                f"{router_id}: status contracts are not declared by the source: "
                + ", ".join(extra_contracts)
            )
        require_row_boundary_statuses = {
            str(value)
            for value in router.get("require_row_boundary_statuses", [])
        }
        require_row_validation = bool(router.get("require_row_validation"))
        local_ids: set[str] = set()

        for feature in features:
            feature_label = f"{router_id}:{feature.feature_id}"
            if not FEATURE_ID_RE.fullmatch(feature.feature_id):
                errors.append(f"{feature_label}: invalid stable feature id")
            if feature.feature_id in local_ids:
                errors.append(f"{feature_label}: duplicate stable feature id")
            local_ids.add(feature.feature_id)
            if feature_label in global_feature_ids:
                errors.append(f"{feature_label}: duplicate global feature id")
            global_feature_ids.add(feature_label)
            if not feature.name:
                errors.append(f"{feature_label}: feature name is missing")
            if not feature.source_statuses or any(
                not status for status in feature.source_statuses
            ):
                errors.append(f"{feature_label}: coverage status is missing")
            if len(set(feature.source_statuses)) != len(feature.source_statuses):
                errors.append(f"{feature_label}: duplicate coverage status")

            effective_boundaries: list[str] = []
            for status in feature.source_statuses:
                contract = contracts.get(status)
                if not isinstance(contract, dict):
                    continue
                coverage_status = str(
                    contract.get("coverage_status", "")
                ).strip()
                if coverage_status not in allowed_coverage_statuses:
                    errors.append(
                        f"{feature_label}: {status} maps to unsupported coverage "
                        f"status {coverage_status!r}"
                    )
                contract_boundary = str(
                    contract.get("automation_boundary", "")
                ).strip()
                if not contract_boundary:
                    errors.append(
                        f"{router_id}: status contract {status} lacks an "
                        "automation_boundary"
                    )
                effective_boundaries.append(
                    feature.boundary or contract_boundary
                )
            if any(
                status in require_row_boundary_statuses
                for status in feature.source_statuses
            ) and not feature.boundary:
                errors.append(
                    f"{feature_label}: source row requires an explicit "
                    "automation boundary"
                )
            if not effective_boundaries or any(
                not boundary for boundary in effective_boundaries
            ):
                errors.append(
                    f"{feature_label}: no effective automation boundary"
                )
            if require_row_validation and not feature.validation_evidence:
                errors.append(
                    f"{feature_label}: source row lacks validation evidence"
                )

            if not feature.owners:
                errors.append(f"{feature_label}: no owning skill")
            for owner in feature.owners:
                owner_record = catalog.by_name.get(owner)
                if owner_record is None:
                    errors.append(
                        f"{feature_label}: owner skill does not exist: {owner}"
                    )
                    continue
                if owner_record.status != "canonical":
                    errors.append(
                        f"{feature_label}: owner must be canonical, got "
                        f"{owner} ({owner_record.status})"
                    )
                if owner not in product_registry_skills:
                    errors.append(
                        f"{feature_label}: owner absent from product registry: "
                        f"{owner}"
                    )
                validator = _expected_validator(owner)
                if not validator.is_file():
                    errors.append(
                        f"{feature_label}: owner validation surface is missing: "
                        f"{validator.relative_to(REPO_ROOT)}"
                    )
                if owner not in validation_skills:
                    errors.append(
                        f"{feature_label}: owner absent from validation registry: "
                        f"{owner}"
                    )

            row_urls = feature.source_urls or global_source_urls
            if not row_urls:
                errors.append(f"{feature_label}: no source provenance URL")
            for url in row_urls:
                check_source_url(
                    feature_label,
                    url,
                    allowed_source_hosts,
                    errors,
                )

        summary[f"router:{router_id}:features"] = count
        summary[f"router:{router_id}:feature_ids_sha256"] = feature_hash
        summary[f"router:{router_id}:feature_contracts_sha256"] = contract_hash
        total_features += count

    summary["router_contracts:covered"] = len(seen_router_ids)
    summary["router_contracts:expected"] = expected_router_count
    summary["router_contracts:features"] = total_features


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit repo-wide product and feature coverage contracts."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable audit output.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=COVERAGE_MANIFEST_PATH,
        help="Coverage manifest to audit (relative paths remain repo-relative).",
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=date.today(),
        metavar="YYYY-MM-DD",
        help="Freshness audit date (defaults to today).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    summary: dict[str, Any] = {}
    catalog = load_catalog()
    skills = set(catalog.by_name)
    summary["skills:manifest"] = len(skills)

    check_catalogs(catalog, errors, summary)
    check_app_registry(skills, errors, summary)
    product_registry_skills = check_product_registry(catalog, errors, summary)
    validation_skills = validation_registry_skills(catalog, errors)
    check_semantic_coverage(
        catalog,
        product_registry_skills,
        validation_skills,
        args.manifest.resolve(),
        args.as_of,
        errors,
        summary,
    )

    payload = {"ok": not errors, "summary": summary, "errors": errors}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif errors:
        print("Product/feature coverage audit failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print("Product/feature coverage audit passed.")
        for key in sorted(summary):
            print(f"- {key}: {summary[key]}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

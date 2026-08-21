"""Adversarial tests for the canonical skill manifest and generated surfaces."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from skills.shared.skill_catalog import (
    CATALOG_PATH,
    MCP_SAFETY_TOKENS,
    SCHEMA_PATH,
    CatalogError,
    command_handoff_boilerplate,
    load_catalog,
    parse_requirement_skill_rows,
    validate_schema_contract,
)
from tests.check_skill_frontmatter import check_openai_metadata, parse_frontmatter


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "skills/shared/scripts/generate_skill_catalog.py"
def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _one_skill_manifest(
    *,
    target: str = r"Target | C:\collector",
    purpose: str = "Purpose | safe and deterministic.",
) -> str:
    safety = load_catalog().shared_sections["local_skill_mcp_server"]
    lines = [
        "schema_version: 1",
        "skill_count: 1",
        "alias_count: 0",
        "shared_sections:",
        "  local_skill_mcp_server: |-",
        *(f"    {line}" if line else "" for line in safety.splitlines()),
        "taxonomy:",
        "  products:",
        f"    - id: {_quoted('sample-product')}",
        f"      name: {_quoted('Sample Product')}",
        f"      description: {_quoted('Sample product taxonomy.')}",
        "  capabilities:",
        f"    - product: {_quoted('sample-product')}",
        f"      id: {_quoted('sample-capability')}",
        f"      name: {_quoted('Sample Capability')}",
        "skills:",
        f"  - name: {_quoted('sample-skill')}",
        f"    path: {_quoted('skills/sample-skill/SKILL.md')}",
        f"    target: {_quoted(target)}",
        f"    purpose: {_quoted(purpose)}",
        f"    command_summary: {_quoted('Unique generated command summary.')}",
        f"    product: {_quoted('sample-product')}",
        f"    capability: {_quoted('sample-capability')}",
        f"    status: {_quoted('canonical')}",
    ]
    return "\n".join(lines) + "\n"


def _legacy_context() -> str:
    return "\n".join(
        [
            "# Context",
            "",
            "BEFORE-CATALOG-SENTINEL",
            "",
            "## Skill Catalog",
            "",
            "| Skill | Target | Main purpose |",
            "| --- | --- | --- |",
            "| `old-skill` | old | old |",
            "",
            "## Splunk MCP Server",
            "",
            "BETWEEN-SECTIONS-SENTINEL",
            "",
            "## Local Skill MCP Server",
            "",
            "Old unsafe section.",
            "",
            "## Credentials",
            "",
            "AFTER-SECTIONS-SENTINEL",
            "",
        ]
    )


def _write_fixture(root: Path) -> None:
    (root / "skills/shared").mkdir(parents=True)
    shutil.copyfile(SCHEMA_PATH, root / "skills/shared/skill_catalog.schema.json")
    (root / "skills/catalog.yaml").write_text(
        _one_skill_manifest(), encoding="utf-8"
    )
    skill_dir = root / "skills/sample-skill"
    (skill_dir / "agents").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: sample-skill
description: "Sample canonical workflow. Use when exercising generator tests."
compatibility: "Not applicable."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Sample Skill
""",
        encoding="utf-8",
    )
    (skill_dir / "agents/openai.yaml").write_text(
        """interface:
  display_name: "Sample Skill"
  short_description: "Exercise canonical catalog generation"
  default_prompt: "Use $sample-skill for the fixture."
""",
        encoding="utf-8",
    )
    context = _legacy_context()
    (root / "AGENTS.md").write_text(context, encoding="utf-8")
    (root / "CLAUDE.md").write_text(context, encoding="utf-8")
    (root / "SKILL_REQUIREMENTS.md").write_text(
        "| Skill | Requirement |\n| --- | --- |\n| `sample-skill` | test |\n",
        encoding="utf-8",
    )
    (root / "skills/shared/app_registry.json").write_text(
        json.dumps(
            {
                "apps": [],
                "skill_topologies": [{"skill": "sample-skill"}],
                "documentation": {"cloud_matrix_rows": []},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "skills/shared/skill_validation_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "description": "Maintained evidence extension.",
                "skills": ["old-skill"],
                "evidence": {},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _run_generator(root: Path, mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), mode, "--root", str(root)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_catalog(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "catalog.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _skill_block(text: str, name: str) -> tuple[list[str], int, int]:
    lines = text.splitlines()
    needle = f"  - name: {_quoted(name)}"
    start = lines.index(needle)
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("  - name: ")),
        len(lines),
    )
    return lines, start, end


def _replace_skill_field(text: str, name: str, field: str, value: str) -> str:
    lines, start, end = _skill_block(text, name)
    prefix = f"    {field}: "
    for index in range(start + 1, end):
        if lines[index].startswith(prefix):
            lines[index] = prefix + _quoted(value)
            return "\n".join(lines) + "\n"
    status_index = next(
        index for index in range(start + 1, end) if lines[index].startswith("    status: ")
    )
    insert_at = status_index + 1
    if field == "migration":
        replaced_index = next(
            (
                index
                for index in range(status_index + 1, end)
                if lines[index].startswith("    replaced_by: ")
            ),
            None,
        )
        if replaced_index is not None:
            insert_at = replaced_index + 1
    lines.insert(insert_at, prefix + _quoted(value))
    return "\n".join(lines) + "\n"


def _append_fixture_alias(text: str) -> str:
    lines = text.rstrip().splitlines()
    lines.extend(
        [
            '  - name: "fixture-alias"',
            '    path: "skills/fixture-alias/SKILL.md"',
            '    target: "Fixture compatibility alias"',
            '    purpose: "Fixture compatibility alias for generator tests"',
            '    command_summary: "Fixture compatibility alias."',
            '    product: "shared-and-cross-product"',
            '    capability: "cisco-cross-product-routing"',
            '    status: "deprecated"',
            '    replaced_by: "cisco-product-setup"',
            '    migration: "Fixture migration boundary."',
        ]
    )
    result = "\n".join(lines) + "\n"
    result = _increment_catalog_count(result, "skill_count")
    return _increment_catalog_count(result, "alias_count")


def _increment_catalog_count(text: str, field: str) -> str:
    pattern = rf"(?m)^({re.escape(field)}: )(\d+)$"
    result, replacements = re.subn(
        pattern,
        lambda match: f"{match.group(1)}{int(match.group(2)) + 1}",
        text,
        count=1,
    )
    if replacements != 1:
        raise AssertionError(f"catalog is missing exactly one {field} field")
    return result


def _increment_alias_count(text: str) -> str:
    return _increment_catalog_count(text, "alias_count")


def test_repository_manifest_is_the_complete_versioned_identity_source() -> None:
    catalog = load_catalog()
    disk_skills = {
        path.parent.name
        for path in (REPO_ROOT / "skills").glob("*/SKILL.md")
        if path.parent.name != "shared"
    }

    assert catalog.schema_version == 1
    assert catalog.declared_skill_count == len(catalog.skills)
    assert catalog.declared_alias_count == len(catalog.aliases)
    assert set(catalog.by_name) == disk_skills
    assert not catalog.aliases
    for legacy, canonical in catalog.aliases.items():
        assert catalog.by_name[legacy].deprecated
        assert catalog.by_name[legacy].replaced_by == canonical
        assert catalog.by_name[legacy].migration
        assert catalog.by_name[canonical].status == "canonical"
        assert catalog.by_name[canonical].replaced_by is None


def test_normalized_checksum_is_semantic_and_reproducible(tmp_path: Path) -> None:
    catalog = load_catalog()
    copied = _write_catalog(tmp_path, CATALOG_PATH.read_text(encoding="utf-8"))
    reloaded = load_catalog(copied)
    normalized = json.dumps(
        catalog.normalized(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert reloaded.checksum == catalog.checksum
    assert hashlib.sha256(normalized).hexdigest() == catalog.checksum


def test_command_summary_cannot_duplicate_generated_handoff(tmp_path: Path) -> None:
    duplicate = _replace_skill_field(
        _one_skill_manifest(),
        "sample-skill",
        "command_summary",
        command_handoff_boilerplate("sample-skill"),
    )

    with pytest.raises(CatalogError, match="duplicates the generated command handoff"):
        load_catalog(_write_catalog(tmp_path, duplicate), schema_path=SCHEMA_PATH)


def test_command_summary_cannot_be_a_markdown_heading(tmp_path: Path) -> None:
    heading = _replace_skill_field(
        _one_skill_manifest(),
        "sample-skill",
        "command_summary",
        "# /sample-skill",
    )

    with pytest.raises(CatalogError, match="not a Markdown heading"):
        load_catalog(_write_catalog(tmp_path, heading), schema_path=SCHEMA_PATH)


def test_manifest_survives_strip_trailing_whitespace_unchanged(
    tmp_path: Path,
) -> None:
    original = CATALOG_PATH.read_text(encoding="utf-8")
    stripped = "\n".join(line.rstrip(" \t") for line in original.splitlines()) + "\n"

    assert any(line == "" for line in original.splitlines()[5:49])
    assert all(line == line.rstrip(" \t") for line in original.splitlines())
    assert stripped == original
    reloaded = load_catalog(_write_catalog(tmp_path, stripped))
    assert reloaded.checksum == load_catalog().checksum


def test_one_entry_drives_all_identity_outputs_and_migration_is_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)

    first = _run_generator(root, "--write")
    assert first.returncode == 0, first.stderr
    check = _run_generator(root, "--check")
    assert check.returncode == 0, check.stderr
    second = _run_generator(root, "--write")
    assert second.returncode == 0, second.stderr
    assert "changed 0 paths" in second.stdout

    catalog = load_catalog(
        root / "skills/catalog.yaml",
        schema_path=root / "skills/shared/skill_catalog.schema.json",
    )
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    claude = (root / "CLAUDE.md").read_text(encoding="utf-8")
    for text in (agents, claude):
        assert "<!-- END GENERATED SKILL CATALOG -->\n\n## Splunk MCP Server" in text
        assert (
            "<!-- END GENERATED LOCAL SKILL MCP SAFETY -->\n\n## Credentials"
            in text
        )
        for sentinel in (
            "BEFORE-CATALOG-SENTINEL",
            "BETWEEN-SECTIONS-SENTINEL",
            "AFTER-SECTIONS-SENTINEL",
        ):
            assert text.count(sentinel) == 1
        assert r"Target \| C:\\collector" in text
        assert r"Purpose \| safe and deterministic." in text
        assert text.endswith("\n") and not text.endswith("\n\n")

    product_registry = json.loads(
        (root / "skills/shared/skill_product_registry.json").read_text(
            encoding="utf-8"
        )
    )
    validation_registry = json.loads(
        (root / "skills/shared/skill_validation_registry.json").read_text(
            encoding="utf-8"
        )
    )
    assert product_registry["generated_from"]["sha256"] == catalog.checksum
    assert product_registry["schema_version"] == 2
    assert product_registry["skill_records"] == [
        {"name": "sample-skill", "status": "canonical", "replaced_by": None}
    ]
    assert product_registry["products"][0]["capabilities"][0]["skills"] == [
        "sample-skill"
    ]
    assert validation_registry["generated_from"]["sha256"] == catalog.checksum
    assert validation_registry["skills"] == ["sample-skill"]
    assert validation_registry["description"] == "Maintained evidence extension."
    migration_doc = (
        root / "skills/shared/deprecated_skill_aliases.md"
    ).read_text(encoding="utf-8")
    assert catalog.checksum in migration_doc
    assert "No deprecated aliases are currently declared." in migration_doc
    command = (root / ".claude/commands/sample-skill.md").read_text(encoding="utf-8")
    assert "Unique generated command summary." in command
    assert "skills/sample-skill/SKILL.md" in command
    assert (root / ".cursor/skills/sample-skill").readlink().as_posix() == (
        "../../skills/sample-skill"
    )


def test_check_reports_and_write_cleans_only_provenance_owned_stale_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    assert _run_generator(root, "--write").returncode == 0

    stale_command = root / ".claude/commands/removed-skill.md"
    stale_command.write_text(
        "<!-- Generated from skills/catalog.yaml; schema: 1; "
        f"entry-sha256: {'0' * 64}. -->\nobsolete\n",
        encoding="utf-8",
    )
    hand_command = root / ".claude/commands/hand-authored.md"
    hand_command.write_text("Hand-authored command.\n", encoding="utf-8")
    stale_link = root / ".cursor/skills/removed-skill"
    stale_link.symlink_to("../../skills/removed-skill")
    hand_link = root / ".cursor/skills/hand-authored"
    hand_link.symlink_to("../../manual/hand-authored")
    manual_alias_link = root / ".cursor/skills/my-link"
    manual_alias_link.symlink_to("../../skills/sample-skill")

    check = _run_generator(root, "--check")
    output = check.stdout + check.stderr
    assert check.returncode == 1
    assert "removed-skill.md" in output
    assert ".cursor/skills/removed-skill" in output

    write = _run_generator(root, "--write")
    assert write.returncode == 0, write.stderr
    assert not stale_command.exists()
    assert not stale_link.is_symlink()
    assert hand_command.read_text(encoding="utf-8") == "Hand-authored command.\n"
    assert hand_link.is_symlink()
    assert hand_link.readlink().as_posix() == "../../manual/hand-authored"
    assert manual_alias_link.is_symlink()
    assert manual_alias_link.readlink().as_posix() == "../../skills/sample-skill"
    assert _run_generator(root, "--check").returncode == 0


@pytest.mark.parametrize("managed_name", ["AGENTS.md", "CLAUDE.md"])
def test_write_refuses_symlinked_managed_text_without_outside_write(
    tmp_path: Path,
    managed_name: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    outside = tmp_path / f"outside-{managed_name}"
    outside.write_text("OUTSIDE-SENTINEL\n", encoding="utf-8")
    managed = root / managed_name
    managed.unlink()
    managed.symlink_to(outside)

    result = _run_generator(root, "--write")

    assert result.returncode == 2
    assert "regular file" in result.stderr
    assert outside.read_text(encoding="utf-8") == "OUTSIDE-SENTINEL\n"


def test_write_refuses_symlinked_parent_without_outside_write(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    outside = tmp_path / "outside-commands"
    outside.mkdir()
    (root / ".claude").symlink_to(outside, target_is_directory=True)
    original_agents = (root / "AGENTS.md").read_text(encoding="utf-8")

    result = _run_generator(root, "--write")

    assert result.returncode == 2
    assert "managed parent must be a real directory" in result.stderr
    assert list(outside.iterdir()) == []
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == original_agents


def test_write_refuses_symlinked_manifest_skill_directory(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    skill_dir = root / "skills/sample-skill"
    outside = tmp_path / "outside-skill"
    skill_dir.rename(outside)
    skill_dir.symlink_to(outside, target_is_directory=True)

    result = _run_generator(root, "--write")

    assert result.returncode == 2
    assert "managed parent must be a real directory" in result.stderr
    assert not (root / ".cursor/skills/sample-skill").exists()


@pytest.mark.parametrize(
    "relative_source",
    ["skills/sample-skill/SKILL.md", "skills/sample-skill/agents/openai.yaml"],
)
def test_write_refuses_symlinked_manifest_source_file(
    tmp_path: Path,
    relative_source: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    source = root / relative_source
    outside = tmp_path / source.name
    source.rename(outside)
    source.symlink_to(outside)

    result = _run_generator(root, "--write")

    assert result.returncode == 2
    assert "managed source must be a regular file" in result.stderr
    assert not (root / ".cursor/skills/sample-skill").exists()


def test_write_refuses_multi_link_managed_file(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    outside = tmp_path / "outside-hardlink"
    outside.write_text("OUTSIDE-HARDLINK\n", encoding="utf-8")
    agents = root / "AGENTS.md"
    agents.unlink()
    os.link(outside, agents)

    result = _run_generator(root, "--write")

    assert result.returncode == 2
    assert "exactly one hard link" in result.stderr
    assert outside.read_text(encoding="utf-8") == "OUTSIDE-HARDLINK\n"


def test_write_keeps_cursor_non_symlink_replacement_refusal(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    cursor_dir = root / ".cursor/skills"
    cursor_dir.mkdir(parents=True)
    collision = cursor_dir / "sample-skill"
    collision.write_text("do not replace\n", encoding="utf-8")

    result = _run_generator(root, "--write")

    assert result.returncode == 2
    assert "refusing to replace non-symlink path" in result.stderr
    assert collision.read_text(encoding="utf-8") == "do not replace\n"


@pytest.mark.parametrize(
    ("relative", "content", "message"),
    [
        (
            "skills/shared/app_registry.json",
            '{"apps":[],"apps":[],"skill_topologies":[],"documentation":{}}\n',
            "duplicate JSON key",
        ),
        (
            "skills/shared/skill_validation_registry.json",
            '{"schema_version":1,"description":"x","skills":[],"evidence":'
            '{"sample-skill":{"live_read_only":{"status":"not-recorded",'
            '"targets":[],"last_verified":null,"evidence":[],"notes":"x"},'
            '"live_read_only":{"status":"not-recorded","targets":[],'
            '"last_verified":null,"evidence":[],"notes":"x"}}}}\n',
            "duplicate JSON key",
        ),
        (
            "skills/shared/app_registry.json",
            '{"apps":[],"skill_topologies":[],"documentation":{},"weight":NaN}\n',
            "non-finite JSON constant",
        ),
        (
            "skills/shared/skill_validation_registry.json",
            '{"schema_version":1,"description":"x","skills":[],'
            '"evidence":{},"weight":Infinity}\n',
            "non-finite JSON constant",
        ),
    ],
)
def test_maintained_json_extensions_reject_lossy_inputs_before_write(
    tmp_path: Path,
    relative: str,
    content: str,
    message: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    (root / relative).write_text(content, encoding="utf-8")
    original_agents = (root / "AGENTS.md").read_text(encoding="utf-8")

    result = _run_generator(root, "--write")

    assert result.returncode == 2
    assert message in result.stderr
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == original_agents


def test_duplicate_and_omitted_entries_fail_closed(tmp_path: Path) -> None:
    original = CATALOG_PATH.read_text(encoding="utf-8")
    catalog = load_catalog()
    lines, start, end = _skill_block(original, catalog.skills[0].name)
    duplicate = lines[start:end]
    duplicated = "\n".join(
        [
            *lines[:],
            *duplicate,
        ]
    ) + "\n"
    duplicated = duplicated.replace(
        f"skill_count: {catalog.declared_skill_count}",
        f"skill_count: {catalog.declared_skill_count + 1}",
        1,
    )
    with pytest.raises(CatalogError, match="duplicate skill name"):
        load_catalog(_write_catalog(tmp_path, duplicated))

    lines = original.splitlines()
    last_start = max(
        index for index, line in enumerate(lines) if line.startswith("  - name: ")
    )
    omitted = "\n".join(lines[:last_start]) + "\n"
    with pytest.raises(CatalogError, match="catalog.skill_count"):
        load_catalog(_write_catalog(tmp_path, omitted))


def test_alias_chains_cycles_and_invalid_targets_fail_closed(tmp_path: Path) -> None:
    original = _append_fixture_alias(CATALOG_PATH.read_text(encoding="utf-8"))
    legacy = "fixture-alias"
    canonical = "cisco-product-setup"

    missing = _replace_skill_field(original, legacy, "replaced_by", "missing-skill")
    with pytest.raises(CatalogError, match="does not exist"):
        load_catalog(_write_catalog(tmp_path, missing))

    chain = _replace_skill_field(original, canonical, "status", "deprecated")
    chain = _replace_skill_field(
        chain, canonical, "replaced_by", "cisco-collaboration-setup"
    )
    chain = _replace_skill_field(
        chain, canonical, "migration", "Fixture migration boundary."
    )
    chain = _increment_alias_count(chain)
    with pytest.raises(CatalogError, match="must be canonical"):
        load_catalog(_write_catalog(tmp_path, chain))

    cycle = _replace_skill_field(original, canonical, "status", "deprecated")
    cycle = _replace_skill_field(cycle, canonical, "replaced_by", legacy)
    cycle = _replace_skill_field(
        cycle, canonical, "migration", "Fixture migration boundary."
    )
    cycle = _increment_alias_count(cycle)
    with pytest.raises(CatalogError, match="alias cycle detected"):
        load_catalog(_write_catalog(tmp_path, cycle))

    wrong_product = _replace_skill_field(
        original, legacy, "product", "splunk-cloud-platform"
    )
    with pytest.raises(CatalogError, match="product/capability must match"):
        load_catalog(_write_catalog(tmp_path, wrong_product))

    wrong_capability = _replace_skill_field(
        original, legacy, "capability", "fleet-runtime-and-topology"
    )
    with pytest.raises(CatalogError, match="product/capability must match"):
        load_catalog(_write_catalog(tmp_path, wrong_capability))

    alias_lines, alias_start, alias_end = _skill_block(original, legacy)
    alias_without_migration = "\n".join(
        line
        for index, line in enumerate(alias_lines)
        if not (
            alias_start < index < alias_end
            and line.startswith("    migration: ")
        )
    ) + "\n"
    with pytest.raises(CatalogError, match="deprecated entries require migration"):
        load_catalog(_write_catalog(tmp_path, alias_without_migration))

    canonical_migration = _replace_skill_field(
        original,
        canonical,
        "migration",
        "Canonical entries must not carry alias migration metadata.",
    )
    with pytest.raises(CatalogError, match="canonical entries cannot define migration"):
        load_catalog(_write_catalog(tmp_path, canonical_migration))


def test_description_and_safety_drift_are_detected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    assert _run_generator(root, "--write").returncode == 0
    agents = root / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            "Purpose \\| safe and deterministic.",
            "Purpose \\| drifted.",
            1,
        ),
        encoding="utf-8",
    )
    check = _run_generator(root, "--check")
    assert check.returncode == 1
    assert "AGENTS.md" in check.stderr

    original = CATALOG_PATH.read_text(encoding="utf-8")
    token = MCP_SAFETY_TOKENS[0]
    assert token in original
    unsafe = original.replace(token, "execution control removed", 1)
    with pytest.raises(CatalogError, match="missing required controls"):
        load_catalog(_write_catalog(tmp_path, unsafe))


def test_schema_contract_is_exercised_by_every_load(tmp_path: Path) -> None:
    validate_schema_contract()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema["properties"]["skills"]["items"]["properties"]["status"]["enum"] = [
        "canonical"
    ]
    bad_schema = tmp_path / "bad-schema.json"
    bad_schema.write_text(json.dumps(schema), encoding="utf-8")

    with pytest.raises(CatalogError, match="status constraints drifted"):
        load_catalog(CATALOG_PATH, schema_path=bad_schema)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    del schema["properties"]["skills"]["items"]["allOf"]
    bad_schema.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(CatalogError, match="JSON Schema keywords drifted"):
        load_catalog(CATALOG_PATH, schema_path=bad_schema)


def test_every_schema_facet_is_pinned_to_the_strict_loader(tmp_path: Path) -> None:
    base = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    mutations = (
        (("additionalProperties",), True),
        (("properties", "schema_version", "type"), "number"),
        (("properties", "skill_count", "minimum"), -1),
        (
            (
                "properties",
                "shared_sections",
                "properties",
                "local_skill_mcp_server",
                "minLength",
            ),
            0,
        ),
        (("properties", "taxonomy", "additionalProperties"), True),
        (("properties", "taxonomy", "properties", "products", "type"), "object"),
        (("properties", "taxonomy", "properties", "products", "minItems"), 0),
        (("properties", "taxonomy", "properties", "products", "uniqueItems"), False),
        (
            (
                "properties",
                "taxonomy",
                "properties",
                "products",
                "items",
                "properties",
                "id",
                "pattern",
            ),
            "^wrong$",
        ),
        (
            (
                "properties",
                "taxonomy",
                "properties",
                "capabilities",
                "items",
                "properties",
                "name",
                "type",
            ),
            "number",
        ),
        (("properties", "skills", "minItems"), 0),
        (("properties", "skills", "uniqueItems"), False),
        (
            ("properties", "skills", "items", "additionalProperties"),
            True,
        ),
        (
            (
                "properties",
                "skills",
                "items",
                "properties",
                "name",
                "maxLength",
            ),
            65,
        ),
        (
            (
                "properties",
                "skills",
                "items",
                "properties",
                "path",
                "pattern",
            ),
            "^wrong$",
        ),
        (
            (
                "properties",
                "skills",
                "items",
                "properties",
                "purpose",
                "minLength",
            ),
            0,
        ),
        (
            (
                "properties",
                "skills",
                "items",
                "properties",
                "product",
                "pattern",
            ),
            "^wrong$",
        ),
        (
            (
                "properties",
                "skills",
                "items",
                "properties",
                "status",
                "enum",
            ),
            ["canonical"],
        ),
        (
            (
                "properties",
                "skills",
                "items",
                "properties",
                "migration",
                "pattern",
            ),
            "^wrong$",
        ),
        (("properties", "skills", "items", "allOf"), []),
    )
    for position, (path, value) in enumerate(mutations):
        schema = json.loads(json.dumps(base))
        target = schema
        for component in path[:-1]:
            target = target[component]
        target[path[-1]] = value
        schema_path = tmp_path / f"bad-schema-{position}.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        with pytest.raises(CatalogError):
            load_catalog(CATALOG_PATH, schema_path=schema_path)


def test_schema_is_valid_draft_2020_12_and_accepts_normalized_catalog() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator_class = jsonschema.validators.validator_for(schema)
    validator_class.check_schema(schema)
    validator_class(schema).validate(load_catalog().normalized())


def _valid_evidence_record() -> dict[str, object]:
    return {
        "status": "pass",
        "targets": ["Zulu target", "Alpha target"],
        "last_verified": "2026-07-19",
        "evidence": ["https://example.invalid/z", "https://example.invalid/a"],
        "notes": "Sanitized evidence.",
    }


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("unknown_top", "unsupported top-level fields"),
        ("unknown_field", "unknown fields"),
        ("missing_field", "missing fields"),
        ("unknown_dimension", "unknown dimensions"),
        ("invalid_status", "expected one of"),
        ("invalid_date", "must use YYYY-MM-DD"),
        ("invalid_reference", "existing repository-relative file"),
        ("duplicate_target", "must not contain duplicate values"),
    ),
)
def test_validation_registry_extension_fails_closed(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    path = root / "skills/shared/skill_validation_registry.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    record = _valid_evidence_record()
    payload["evidence"] = {"sample-skill": {"live_read_only": record}}
    if mutation == "unknown_top":
        payload["unexpected"] = True
    elif mutation == "unknown_field":
        record["unexpected"] = True
    elif mutation == "missing_field":
        del record["notes"]
    elif mutation == "unknown_dimension":
        payload["evidence"]["sample-skill"] = {"unexpected": record}
    elif mutation == "invalid_status":
        record["status"] = "maybe"
    elif mutation == "invalid_date":
        record["last_verified"] = "2026-02-30"
    elif mutation == "invalid_reference":
        record["evidence"] = ["../outside.json"]
    elif mutation == "duplicate_target":
        record["targets"] = ["same", "same"]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    result = _run_generator(root, "--write")

    assert result.returncode == 2
    assert expected in result.stderr


def test_validation_evidence_is_canonicalized_deterministically(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_fixture(root)
    path = root / "skills/shared/skill_validation_registry.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["evidence"] = {
        "sample-skill": {
            "live_apply_e2e": _valid_evidence_record(),
            "live_read_only": _valid_evidence_record(),
            "integration_mock": _valid_evidence_record(),
        }
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    result = _run_generator(root, "--write")

    assert result.returncode == 0, result.stderr
    rendered = json.loads(path.read_text(encoding="utf-8"))
    skill_evidence = rendered["evidence"]["sample-skill"]
    assert list(skill_evidence) == [
        "integration_mock",
        "live_read_only",
        "live_apply_e2e",
    ]
    for record in skill_evidence.values():
        assert list(record) == [
            "status",
            "targets",
            "last_verified",
            "evidence",
            "notes",
        ]
        assert record["targets"] == ["Alpha target", "Zulu target"]
        assert record["evidence"] == [
            "https://example.invalid/a",
            "https://example.invalid/z",
        ]


def test_alias_openai_yaml_is_exact_and_rejects_prompt_residue() -> None:
    catalog = load_catalog()
    for legacy, canonical in catalog.aliases.items():
        skill_dir = REPO_ROOT / "skills" / legacy
        path = skill_dir / "agents/openai.yaml"
        document = parse_frontmatter(path.read_text(encoding="utf-8"))
        assert set(document) == {"interface", "policy"}
        assert set(document["interface"]) == {
            "display_name",
            "short_description",
            "default_prompt",
        }
        assert document["policy"] == {"allow_implicit_invocation": False}
        assert f"${legacy}" in document["interface"]["default_prompt"]
        assert f"${canonical}" in document["interface"]["default_prompt"]
        assert check_openai_metadata(skill_dir, catalog.by_name[legacy]) == []
        residue = path.read_text(encoding="utf-8").replace(
            "policy:", "    stale legacy prompt residue\npolicy:", 1
        )
        with pytest.raises(Exception):
            parse_frontmatter(residue)


def test_generated_alias_commands_name_only_existing_canonical_local_docs() -> None:
    catalog = load_catalog()
    for legacy, canonical in catalog.aliases.items():
        command = (REPO_ROOT / ".claude/commands" / f"{legacy}.md").read_text(
            encoding="utf-8"
        )
        local_paths = re.findall(
            r"skills/[a-z0-9-]+/(?:SKILL|reference)\.md",
            command,
        )
        assert local_paths
        assert f"skills/{legacy}/SKILL.md" in local_paths
        assert f"skills/{canonical}/SKILL.md" in local_paths
        assert f"skills/{canonical}/reference.md" in local_paths
        assert f"skills/{legacy}/reference.md" not in local_paths
        for relative in local_paths:
            assert (REPO_ROOT / relative).is_file(), relative


def test_generated_alias_migration_guide_covers_every_manifest_alias() -> None:
    catalog = load_catalog()
    text = (
        REPO_ROOT / "skills/shared/deprecated_skill_aliases.md"
    ).read_text(encoding="utf-8")

    assert catalog.checksum in text
    if not catalog.aliases:
        assert "No deprecated aliases are currently declared." in text
        return
    for legacy, canonical in catalog.aliases.items():
        record = catalog.by_name[legacy]
        assert record.migration
        escaped = record.migration.replace("|", r"\|")
        assert f"| `{legacy}` | `{canonical}` | {escaped} |" in text

    for token in (
        "--max-data-size",
        "dbinspect/archive audit",
        "direct-token transport",
        "direct restore shell",
        "regional endpoint health checks",
        "Enterprise app enable/disable",
        "endpoint/instance-ID skeleton",
        "MDM/registration operator runbooks",
    ):
        assert token in text


def test_machine_visible_promises_match_supported_canonical_boundaries() -> None:
    catalog = load_catalog()
    ingest = catalog.by_name["splunk-ingest-actions-setup"]
    knowledge = catalog.by_name["splunk-knowledge-objects-setup"]
    gateway = catalog.by_name["splunk-secure-gateway-setup"]

    assert "eval, mask, and drop" in ingest.purpose
    assert "route-s3 stages" in ingest.purpose
    assert "field knowledge" not in knowledge.purpose.lower()
    assert "saved searches" in knowledge.purpose
    assert "Apply only Splunk Enterprise" in gateway.purpose
    assert "Cloud is render/support-only" in gateway.purpose

    machine_surfaces = {}
    for name in (ingest.name, knowledge.name, gateway.name):
        skill_text = (REPO_ROOT / "skills" / name / "SKILL.md").read_text(
            encoding="utf-8"
        )
        frontmatter = re.match(r"\A---\n(.*?)\n---", skill_text, re.DOTALL)
        assert frontmatter is not None
        machine_surfaces[name] = (
            parse_frontmatter(frontmatter.group(1))["description"],
            parse_frontmatter(
                (REPO_ROOT / "skills" / name / "agents/openai.yaml").read_text(
                    encoding="utf-8"
                )
            )["interface"],
        )
    ingest_description, ingest_interface = machine_surfaces[ingest.name]
    assert "route-s3" in ingest_description and "stages only" in ingest_description
    assert "stage only the RFS destination" in ingest_interface["default_prompt"]
    knowledge_description, knowledge_interface = machine_surfaces[knowledge.name]
    assert "field knowledge" not in knowledge_description.lower()
    assert "field knowledge" not in knowledge_interface["default_prompt"].lower()
    gateway_description, gateway_interface = machine_surfaces[gateway.name]
    assert "Apply only" in gateway_description
    assert "Cloud is no-probe, no-REST" in gateway_interface["default_prompt"]

    ingest_template = (
        REPO_ROOT / "skills/splunk-ingest-actions-setup/template.example"
    ).read_text(encoding="utf-8")
    gateway_template = (
        REPO_ROOT / "skills/splunk-secure-gateway-setup/template.example"
    ).read_text(encoding="utf-8")
    assert "stages only the RFS destination" in ingest_template
    assert "no live configure API" in gateway_template
    assert "Cloud supports plain render only" in gateway_template

    app_registry = json.loads(
        (REPO_ROOT / "skills/shared/app_registry.json").read_text(encoding="utf-8")
    )
    topologies = {
        entry["skill"]: entry for entry in app_registry["skill_topologies"]
    }
    ingest_note = topologies[ingest.name]["notes"]
    assert "Eval, mask, and drop rules are applied" in ingest_note
    assert "Route-s3 applies only RFS destination staging" in ingest_note
    assert "rulesets-API rule handoff" in ingest_note
    gateway_note = topologies[gateway.name]["notes"]
    assert "Only Splunk Enterprise search-tier app enable/disable is live-applied" in gateway_note
    assert "placeholder skeleton" in gateway_note
    assert "Cloud is render/support-only with no local probe or live REST" in gateway_note

    requirements = (REPO_ROOT / "SKILL_REQUIREMENTS.md").read_text(encoding="utf-8")
    ingest_row = next(
        line
        for line in requirements.splitlines()
        if line.startswith("| `splunk-ingest-actions-setup` |")
    )
    for endpoint in (
        "configs/conf-props",
        "configs/conf-transforms",
        "configs/conf-outputs",
        "edit_ingest_rulesets",
    ):
        assert endpoint in ingest_row
    assert "topology-appropriate deploy step" in ingest_row


def test_requirements_rows_use_exact_manifest_lifecycle_suffix() -> None:
    catalog = load_catalog()
    text = (REPO_ROOT / "SKILL_REQUIREMENTS.md").read_text(encoding="utf-8")

    assert set(parse_requirement_skill_rows(text, catalog)) == set(catalog.by_name)
    canonical = next(record.name for record in catalog.skills if not record.deprecated)
    row = next(
        line for line in text.splitlines() if line.startswith(f"| `{canonical}` |")
    )
    malformed = text.replace(
        row,
        row.replace(
            f"| `{canonical}` |",
            f"| `{canonical}` (**Deprecated** -> `fixture-alias`) |",
            1,
        ),
        1,
    )
    with pytest.raises(CatalogError, match="lifecycle suffix"):
        parse_requirement_skill_rows(malformed, catalog)


def test_catalog_generation_has_no_network_or_subprocess_dependency() -> None:
    forbidden = {"http", "httpx", "requests", "socket", "subprocess", "urllib"}
    for path in (
        REPO_ROOT / "skills/shared/skill_catalog.py",
        GENERATOR,
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        assert imported.isdisjoint(forbidden)


def test_manifest_changes_trigger_every_dependent_precommit_check() -> None:
    config = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hook_ids = (
        "canonical-skill-catalog-fresh",
        "skill-ux-catalog-fresh",
        "deployment-docs-fresh",
        "skill-validation-matrix-fresh",
        "splunk-compatibility-fresh",
    )
    for hook_id in hook_ids:
        match = re.search(
            rf"^      - id: {re.escape(hook_id)}\n(.*?)(?=^      - id: |\Z)",
            config,
            flags=re.MULTILINE | re.DOTALL,
        )
        assert match is not None, hook_id
        assert r"skills/catalog\.yaml" in match.group(1), hook_id

    canonical_hook = re.search(
        r"^      - id: canonical-skill-catalog-fresh\n(.*?)(?=^      - id: |\Z)",
        config,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert canonical_hook is not None
    assert r"skills/shared/deprecated_skill_aliases\.md" in canonical_hook.group(1)

    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    canonical_check = "generate_skill_catalog.py --check"
    assert canonical_check in workflow
    assert workflow.index(canonical_check) < workflow.index(
        "generate_skill_ux_catalog.py --check"
    )


def test_contributor_docs_name_only_the_manifest_as_identity_source() -> None:
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    architecture = (REPO_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "Add the skill identity exactly once to `skills/catalog.yaml`" in contributing
    assert "generate_skill_catalog.py --write" in contributing
    assert "generate_skill_catalog.py --check" in contributing
    assert "Do not hand-edit the generated catalog sections" in contributing
    assert "Versioned canonical source for every skill identity" in architecture
    assert "Generated product-first projection" in architecture

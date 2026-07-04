from __future__ import annotations

from pathlib import Path

from tests import check_skill_frontmatter as metadata_check


def test_fallback_parser_supports_nested_skill_and_interface_metadata(
    monkeypatch,
) -> None:
    monkeypatch.setattr(metadata_check, "yaml", None)
    parsed = metadata_check.parse_frontmatter(
        '''
name: sample-skill
description: >-
  Do sample work. Use when a sample is requested.
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
interface:
  display_name: "Sample Skill"
  short_description: "Run a representative sample workflow"
  default_prompt: "Use $sample-skill to run a sample workflow."
policy:
  allow_implicit_invocation: false
dependencies:
  tools:
    - type: "mcp"
      value: "github"
      description: "GitHub MCP server"
      transport: "streamable_http"
      url: "https://api.githubcopilot.com/mcp/"
'''
    )

    assert parsed["description"] == (
        "Do sample work. Use when a sample is requested."
    )
    assert parsed["metadata"] == {
        "splunk_cloud_10_5": "not-applicable",
        "compatibility_verified": "2026-07-02",
    }
    assert parsed["interface"]["default_prompt"] == (
        "Use $sample-skill to run a sample workflow."
    )
    assert parsed["policy"] == {"allow_implicit_invocation": False}
    assert parsed["dependencies"]["tools"] == [
        {
            "type": "mcp",
            "value": "github",
            "description": "GitHub MCP server",
            "transport": "streamable_http",
            "url": "https://api.githubcopilot.com/mcp/",
        }
    ]


def test_openai_metadata_rejects_legacy_root_schema(tmp_path: Path) -> None:
    skill_dir = tmp_path / "legacy-skill"
    agents_dir = skill_dir / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "openai.yaml").write_text(
        '''
display_name: "Legacy Skill"
short_description: "Legacy metadata that has enough characters"
default_prompt: "Use $legacy-skill to do work."
'''.lstrip(),
        encoding="utf-8",
    )

    errors = metadata_check.check_openai_metadata(skill_dir)

    assert any("unsupported top-level" in error for error in errors)
    assert any("interface mapping" in error for error in errors)


def test_openai_metadata_validates_tool_dependencies(tmp_path: Path) -> None:
    skill_dir = tmp_path / "dependency-skill"
    agents_dir = skill_dir / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "openai.yaml").write_text(
        '''
interface:
  display_name: "Dependency Skill"
  short_description: "Exercise canonical MCP dependency metadata"
  default_prompt: "Use $dependency-skill to exercise dependencies."
dependencies:
  tools:
    - type: "mcp"
      value: "github"
      description: "GitHub MCP server"
      transport: "streamable_http"
      url: "https://api.githubcopilot.com/mcp/"
'''.lstrip(),
        encoding="utf-8",
    )

    assert metadata_check.check_openai_metadata(skill_dir) == []

    text = (agents_dir / "openai.yaml").read_text(encoding="utf-8")
    (agents_dir / "openai.yaml").write_text(
        text.replace('type: "mcp"', 'type: "shell"'),
        encoding="utf-8",
    )
    errors = metadata_check.check_openai_metadata(skill_dir)
    assert any("type must be 'mcp'" in error for error in errors)


def test_all_catalog_openai_metadata_matches_interface_contract() -> None:
    errors: list[str] = []
    for skill_dir in sorted(metadata_check.SKILLS_DIR.iterdir()):
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
            errors.extend(metadata_check.check_openai_metadata(skill_dir))

    assert not errors, "\n".join(errors)

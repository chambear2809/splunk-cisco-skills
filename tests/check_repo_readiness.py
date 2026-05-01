#!/usr/bin/env python3
"""Repository readiness checks for public contribution workflows."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

REQUIRED_TOP_LEVEL = [
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "CHANGELOG.md",
    ".gitattributes",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/skill_request.md",
    "agent/run-splunk-cisco-skills-mcp.py",
    "agent/register-codex-splunk-cisco-skills-mcp.sh",
    "agent/splunk_cisco_skills_mcp/__init__.py",
    "agent/splunk_cisco_skills_mcp/core.py",
    "agent/splunk_cisco_skills_mcp/server.py",
    "requirements-agent.txt",
]

UNSAFE_SECRET_EXAMPLE_RE = re.compile(
    r"\b(?:echo|printf)\b[^\n]*(?:"
    r"the_secret|device_secret_here|the_[a-z0-9_]*(?:secret|key|token)|"
    r"<[^>\n]*(?:password|secret|token|api[_-]?key)[^>\n]*>"
    r")[^\n]*(?:>\s*/tmp/|>>\s*/tmp/)",
    re.IGNORECASE,
)

DOC_PATHS_FOR_SECRET_EXAMPLES = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "rules",
    "skills",
    ".github",
]

TRACKED_ARTIFACT_PATTERNS = [
    re.compile(r"^credentials$"),
    re.compile(r"(^|/)template\.local$"),
    re.compile(r"^sc4s-rendered/"),
    re.compile(r"^sc4snmp-rendered/"),
    re.compile(r"^splunk-enterprise-k8s-rendered/"),
    re.compile(r"^splunk-mcp-rendered/(?!run-splunk-mcp\.js$)"),
    re.compile(r"^splunk-ta/_unpacked/"),
    re.compile(r"^splunk-ta/.*\.(?:tgz|tar\.gz|spl|rpm|deb)$"),
]


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [line for line in result.stdout.splitlines() if line]


def skill_names() -> list[str]:
    return sorted(
        path.name
        for path in SKILLS_DIR.iterdir()
        if path.is_dir() and path.name != "shared" and not path.name.startswith(".")
    )


def catalog_skills(doc_path: Path) -> set[str]:
    text = doc_path.read_text(encoding="utf-8")
    return set(re.findall(r"\| `([^`]+)` \|", text))


def iter_secret_doc_files() -> list[Path]:
    paths: list[Path] = []
    for rel in DOC_PATHS_FOR_SECRET_EXAMPLES:
        base = REPO_ROOT / rel
        if base.is_file():
            paths.append(base)
        elif base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and path.suffix in {".md", ".mdc", ".example", ".sh"}:
                    paths.append(path)
    return sorted(set(paths))


def check_required_files(errors: list[str]) -> None:
    for rel in REQUIRED_TOP_LEVEL:
        if not (REPO_ROOT / rel).exists():
            errors.append(f"missing required contributor file: {rel}")


def check_catalog_sync(errors: list[str]) -> None:
    expected = set(skill_names())
    for rel in ["README.md", "AGENTS.md", "CLAUDE.md"]:
        actual = catalog_skills(REPO_ROOT / rel)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            errors.append(f"{rel}: missing skill catalog entries: {', '.join(missing)}")
        if extra:
            errors.append(f"{rel}: unknown skill catalog entries: {', '.join(extra)}")


def check_cursor_and_claude_commands(errors: list[str]) -> None:
    for skill in skill_names():
        cursor_link = REPO_ROOT / ".cursor" / "skills" / skill
        expected_target = f"../../skills/{skill}"
        if not cursor_link.is_symlink():
            errors.append(f".cursor/skills/{skill}: missing symlink")
        else:
            actual_target = cursor_link.readlink().as_posix().rstrip("/")
            if actual_target != expected_target:
                errors.append(
                    f".cursor/skills/{skill}: points to {actual_target}, expected {expected_target}"
                )

        command_file = REPO_ROOT / ".claude" / "commands" / f"{skill}.md"
        if not command_file.exists():
            errors.append(f".claude/commands/{skill}.md: missing Claude command")
        elif f"skills/{skill}/SKILL.md" not in command_file.read_text(encoding="utf-8"):
            errors.append(f".claude/commands/{skill}.md: does not reference its SKILL.md")


def check_no_tracked_local_artifacts(errors: list[str]) -> None:
    for rel in tracked_files():
        for pattern in TRACKED_ARTIFACT_PATTERNS:
            if pattern.search(rel):
                errors.append(f"local/generated artifact is tracked: {rel}")
                break


def check_secret_examples(errors: list[str]) -> None:
    for path in iter_secret_doc_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if UNSAFE_SECRET_EXAMPLE_RE.search(line):
                errors.append(f"{rel}:{lineno}: unsafe inline secret-file example")


def check_smoke_script_no_sudo_password(errors: list[str]) -> None:
    path = REPO_ROOT / "skills/shared/scripts/smoke_sc4x_live.sh"
    text = path.read_text(encoding="utf-8")
    if "SPLUNK_SSH_PASS" in text or "sudo -S" in text:
        errors.append(
            "skills/shared/scripts/smoke_sc4x_live.sh must not embed SSH passwords into sudo commands"
        )


def check_mcp_tool_schema(errors: list[str]) -> None:
    required_root = {"name", "description", "version", "author", "tools"}
    required_tool = {
        "_key",
        "name",
        "title",
        "description",
        "category",
        "tags",
        "time_range",
        "row_limiter",
        "spl",
        "arguments",
        "examples",
    }
    for path in sorted(SKILLS_DIR.glob("*/mcp_tools.json")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            errors.append(f"{rel}: root must be a JSON object")
            continue
        missing_root = sorted(required_root - set(data))
        if missing_root:
            errors.append(f"{rel}: missing root keys: {', '.join(missing_root)}")
        tools = data.get("tools")
        if not isinstance(tools, list) or not tools:
            errors.append(f"{rel}: tools must be a non-empty list")
            continue
        seen_keys: set[str] = set()
        seen_names: set[str] = set()
        for index, tool in enumerate(tools):
            if not isinstance(tool, dict):
                errors.append(f"{rel}: tools[{index}] must be an object")
                continue
            missing_tool = sorted(required_tool - set(tool))
            if missing_tool:
                errors.append(f"{rel}: tools[{index}] missing keys: {', '.join(missing_tool)}")
            key = str(tool.get("_key", ""))
            name = str(tool.get("name", ""))
            if key in seen_keys:
                errors.append(f"{rel}: duplicate tool _key: {key}")
            if name in seen_names:
                errors.append(f"{rel}: duplicate tool name: {name}")
            seen_keys.add(key)
            seen_names.add(name)
            if not str(tool.get("spl", "")).strip():
                errors.append(f"{rel}: tools[{index}] has empty SPL")


def check_registry_skill_refs(errors: list[str]) -> None:
    registry_path = REPO_ROOT / "skills/shared/app_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    known_skills = set(skill_names())
    for section in ("apps", "skill_topologies"):
        entries = registry.get(section, [])
        if not isinstance(entries, list):
            errors.append(f"skills/shared/app_registry.json: {section} must be a list")
            continue
        for index, entry in enumerate(entries):
            skill = entry.get("skill") if isinstance(entry, dict) else None
            if skill and skill not in known_skills:
                errors.append(
                    f"skills/shared/app_registry.json: {section}[{index}] references unknown skill {skill}"
                )


def check_local_mcp_server_config(errors: list[str]) -> None:
    """Both MCP configs must register the local skill server through python3.

    The server depends on `mcp[cli]` and `PyYAML`; whichever interpreter is
    invoked must have those installed (see README "Local MCP Agent Server").
    """
    for rel in (".mcp.json", ".cursor/mcp.json"):
        path = REPO_ROOT / rel
        if not path.is_file():
            errors.append(f"{rel}: missing MCP configuration file")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel}: invalid JSON: {exc}")
            continue
        servers = payload.get("mcpServers", {})
        local = servers.get("splunk-cisco-skills")
        if not isinstance(local, dict):
            errors.append(f"{rel}: missing splunk-cisco-skills server entry")
            continue
        command = str(local.get("command", ""))
        if not re.search(r"python3?(\b|$)", command):
            errors.append(
                f"{rel}: splunk-cisco-skills server must use a python3 command, got {command!r}"
            )
        args = local.get("args") or []
        if not args or "run-splunk-cisco-skills-mcp.py" not in str(args[0]):
            errors.append(
                f"{rel}: splunk-cisco-skills server must reference run-splunk-cisco-skills-mcp.py"
            )


def main() -> int:
    errors: list[str] = []
    check_required_files(errors)
    check_catalog_sync(errors)
    check_cursor_and_claude_commands(errors)
    check_no_tracked_local_artifacts(errors)
    check_secret_examples(errors)
    check_smoke_script_no_sudo_password(errors)
    check_mcp_tool_schema(errors)
    check_registry_skill_refs(errors)
    check_local_mcp_server_config(errors)

    if errors:
        print("Repository readiness errors:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("Repository readiness checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

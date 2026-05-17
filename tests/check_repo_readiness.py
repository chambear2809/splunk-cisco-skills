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
    "SKILL_REQUIREMENTS.md",
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

AGENT_SKILLS_CALLOUTS = {
    "README.md": [
        "https://agentskills.io/specification",
        "https://agentskills.io/skill-creation/best-practices",
        "https://agentskills.io/skill-creation/evaluating-skills",
        "tests/check_skill_frontmatter.py",
        "tests/check_repo_readiness.py",
    ],
    "CONTRIBUTING.md": [
        "https://agentskills.io/specification",
        "https://agentskills.io/skill-creation/best-practices",
        "https://agentskills.io/skill-creation/evaluating-skills",
    ],
    ".github/pull_request_template.md": [
        "Agent Skills specification",
        "https://agentskills.io/specification",
    ],
}

LOCAL_ARTIFACT_ROOTS = [
    "cisco-isovalent-platform-rendered",
    "cisco-secure-email-web-gateway-rendered",
    "cisco-thousandeyes-mcp-rendered",
    "galileo-agent-control-rendered",
    "galileo-platform-rendered",
    "sc4s-rendered",
    "sc4snmp-rendered",
    "splunk-admin-doctor-rendered",
    "splunk-agent-management-rendered",
    "splunk-ai-ml-toolkit-rendered",
    "splunk-appdynamics-setup-rendered",
    "splunk-cloud-acs-allowlist-rendered",
    "splunk-cloud-data-manager-rendered",
    "splunk-connect-for-otlp-rendered",
    "splunk-data-source-readiness-doctor-rendered",
    "splunk-db-connect-rendered",
    "splunk-deployment-server-rendered",
    "splunk-edge-processor-rendered",
    "splunk-enterprise-k8s-rendered",
    "splunk-federated-search-rendered",
    "splunk-hec-service-rendered",
    "splunk-indexer-cluster-rendered",
    "splunk-ingest-processor-rendered",
    "splunk-license-manager-rendered",
    "splunk-live-validation-runs",
    "splunk-monitoring-console-rendered",
    "splunk-observability-ai-agent-monitoring-rendered",
    "splunk-observability-aws-integration-rendered",
    "splunk-observability-aws-lambda-apm-rendered",
    "splunk-observability-azure-integration-rendered",
    "splunk-observability-cisco-ai-pod-rendered",
    "splunk-observability-cisco-intersight-rendered",
    "splunk-observability-cisco-nexus-rendered",
    "splunk-observability-cloud-integration-rendered",
    "splunk-observability-dashboard-rendered",
    "splunk-observability-database-monitoring-rendered",
    "splunk-observability-deep-native-rendered",
    "splunk-observability-gcp-integration-rendered",
    "splunk-observability-isovalent-rendered",
    "splunk-observability-k8s-auto-instrumentation-rendered",
    "splunk-observability-k8s-frontend-rum-rendered",
    "splunk-observability-native-rendered",
    "splunk-observability-nvidia-gpu-rendered",
    "splunk-observability-otel-rendered",
    "splunk-observability-thousandeyes-rendered",
    "splunk-oncall-rendered",
    "splunk-platform-pki-rendered",
    "splunk-platform-restart-rendered",
    "splunk-public-exposure-rendered",
    "splunk-search-head-cluster-rendered",
    "splunk-smartstore-rendered",
    "splunk-soar-rendered",
    "splunk-spl2-pipeline-kit-rendered",
    "splunk-universal-forwarder-rendered",
    "splunk-workload-management-rendered",
    "ta-for-indexers-rendered",
]

TRACKED_ARTIFACT_PATTERNS = [
    re.compile(r"^credentials$"),
    re.compile(r"(^|/)template\.local$"),
    *[re.compile(rf"^{re.escape(root)}/") for root in LOCAL_ARTIFACT_ROOTS],
    re.compile(r"^splunk-mcp-rendered/(?!run-splunk-mcp\.js$)"),
    re.compile(r"^splunk-ta/_unpacked/"),
    re.compile(r"^splunk-ta/.*\.(?:tgz|tar\.gz|spl|rpm|deb|msi|dmg|pkg|txz|p5p|Z)$"),
    re.compile(r"^splunk-ta/\.latest-splunk-universal-forwarder-.*\.json$"),
]

REQUIRED_GITIGNORE_LINES = [
    "credentials",
    "**/template.local",
    *[f"/{root}/" for root in LOCAL_ARTIFACT_ROOTS],
    "/splunk-mcp-rendered/*",
    "!/splunk-mcp-rendered/run-splunk-mcp.js",
    "splunk-ta/_unpacked/",
    "splunk-ta/*.tgz",
    "splunk-ta/*.spl",
    "splunk-ta/*.tar.gz",
    "splunk-ta/*.rpm",
    "splunk-ta/*.deb",
    "splunk-ta/*.msi",
    "splunk-ta/*.dmg",
    "splunk-ta/*.pkg",
    "splunk-ta/*.txz",
    "splunk-ta/*.p5p",
    "splunk-ta/*.Z",
    "splunk-ta/.latest-splunk-enterprise-*.json",
    "splunk-ta/.latest-splunk-universal-forwarder-*.json",
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
        if path.is_dir()
        and path.name != "shared"
        and not path.name.startswith(".")
        and (path / "SKILL.md").is_file()
    )


def catalog_skills(doc_path: Path) -> set[str]:
    text = doc_path.read_text(encoding="utf-8")
    return set(re.findall(r"^\| `([^`]+)` \|", text, flags=re.MULTILINE))


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
    readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for required_link in ("SKILL_UX_CATALOG.md", "SKILL_REQUIREMENTS.md"):
        if required_link not in readme_text:
            errors.append(f"README.md: missing operator catalog link: {required_link}")

    for rel in ["AGENTS.md", "CLAUDE.md"]:
        actual = catalog_skills(REPO_ROOT / rel)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            errors.append(f"{rel}: missing skill catalog entries: {', '.join(missing)}")
        if extra:
            errors.append(f"{rel}: unknown skill catalog entries: {', '.join(extra)}")


def check_skill_requirements_catalog(errors: list[str]) -> None:
    doc_path = REPO_ROOT / "SKILL_REQUIREMENTS.md"
    if not doc_path.exists():
        return
    expected = set(skill_names())
    actual = catalog_skills(doc_path)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        errors.append(
            "SKILL_REQUIREMENTS.md: missing skill requirement entries: "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "SKILL_REQUIREMENTS.md: unknown skill requirement entries: "
            + ", ".join(extra)
        )


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


def check_gitignore_local_artifacts(errors: list[str]) -> None:
    gitignore_path = REPO_ROOT / ".gitignore"
    lines = [
        line.strip()
        for line in gitignore_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    line_set = set(lines)
    for required in REQUIRED_GITIGNORE_LINES:
        if required not in line_set:
            errors.append(f".gitignore: missing local artifact ignore rule: {required}")

    seen: dict[str, int] = {}
    for lineno, line in enumerate(lines, start=1):
        if line in seen:
            errors.append(f".gitignore:{lineno}: duplicate ignore rule also appears at logical line {seen[line]}")
        else:
            seen[line] = lineno


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


def check_agent_skills_callouts(errors: list[str]) -> None:
    for rel, required_fragments in AGENT_SKILLS_CALLOUTS.items():
        path = REPO_ROOT / rel
        if not path.exists():
            errors.append(f"{rel}: missing Agent Skills specification callout file")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [fragment for fragment in required_fragments if fragment not in text]
        if missing:
            errors.append(
                f"{rel}: missing Agent Skills specification callout fragment(s): "
                + ", ".join(missing)
            )


def check_skill_script_references(errors: list[str]) -> None:
    """Ensure UI-advertised safe-first/validation skill scripts exist.

    Skill bodies sometimes mention scripts that are generated into rendered
    output directories. The UI metadata commands, however, should only point at
    repository-local scripts that already exist.
    """
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name == "shared":
            continue
        metadata_path = skill_dir / "agents/openai.yaml"
        if not metadata_path.exists():
            continue
        corpus = metadata_path.read_text(encoding="utf-8")
        script_pattern = re.compile(rf"skills/{re.escape(skill_dir.name)}/scripts/[A-Za-z0-9_.-]+")
        for match in sorted(set(script_pattern.findall(corpus))):
            script_path = REPO_ROOT / match
            if not script_path.is_file():
                errors.append(f"{match}: referenced by skill UI metadata but missing")


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
    check_skill_requirements_catalog(errors)
    check_cursor_and_claude_commands(errors)
    check_no_tracked_local_artifacts(errors)
    check_gitignore_local_artifacts(errors)
    check_secret_examples(errors)
    check_smoke_script_no_sudo_password(errors)
    check_agent_skills_callouts(errors)
    check_skill_script_references(errors)
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

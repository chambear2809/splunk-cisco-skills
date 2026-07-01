"""Regression coverage for Galileo instance URL intake across Galileo skills."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GALILEO_CONSOLE_URL = "https://console.demo-v2.galileocloud.io/"
GALILEO_API_BASE = "https://api.demo-v2.galileocloud.io"
GALILEO_MCP_URL = "https://api.demo-v2.galileocloud.io/mcp/http/mcp"


def run_cmd(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_all_galileo_skill_entrypoints_require_console_url_intake() -> None:
    skill_files = sorted((REPO_ROOT / "skills").glob("galileo-*/SKILL.md"))
    assert skill_files

    for path in skill_files:
        text = path.read_text(encoding="utf-8")
        assert "## Required Intake" in text, path
        assert "Galileo instance console URL" in text, path
        assert GALILEO_CONSOLE_URL in text, path
        assert "--galileo-console-url" in text, path


def test_all_galileo_setup_scripts_accept_console_url() -> None:
    setup_scripts = sorted((REPO_ROOT / "skills").glob("galileo-*/scripts/setup.sh"))
    assert setup_scripts

    for setup in setup_scripts:
        result = run_cmd("bash", str(setup), "--help")
        assert "--galileo-console-url" in result.stdout + result.stderr, setup


def test_platform_render_uses_user_supplied_console_url(tmp_path: Path) -> None:
    output_dir = tmp_path / "platform"
    run_cmd(
        "bash",
        "skills/galileo-platform-setup/scripts/setup.sh",
        "--render",
        "--galileo-console-url",
        GALILEO_CONSOLE_URL,
        "--output-dir",
        str(output_dir),
        "--json",
    )

    readiness = json.loads(
        (output_dir / "readiness/readiness-report.json").read_text(encoding="utf-8")
    )
    assert readiness["galileo"]["console_url"] == GALILEO_CONSOLE_URL
    assert readiness["galileo"]["api_base"] == GALILEO_API_BASE
    assert readiness["galileo"]["healthcheck_url"] == f"{GALILEO_API_BASE}/v2/healthcheck"
    runtime_env = (output_dir / "runtime/python-opentelemetry-env.sh").read_text(
        encoding="utf-8"
    )
    assert f"export GALILEO_CONSOLE_URL='{GALILEO_CONSOLE_URL}'" in runtime_env


def test_platform_template_requires_galileo_url_intake(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        "skills/galileo-platform-setup/scripts/setup.sh",
        "--render",
        "--spec",
        "skills/galileo-platform-setup/template.example",
        "--output-dir",
        str(tmp_path / "platform-template"),
        "--json",
        check=False,
    )

    assert result.returncode != 0
    assert "Galileo instance URL intake is required" in result.stdout + result.stderr


def test_agent_control_render_preserves_user_supplied_console_url(tmp_path: Path) -> None:
    output_dir = tmp_path / "agent-control"
    run_cmd(
        "bash",
        "skills/galileo-agent-control-setup/scripts/setup.sh",
        "--render",
        "--galileo-console-url",
        GALILEO_CONSOLE_URL,
        "--output-dir",
        str(output_dir),
        "--json",
    )

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    apply_plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    coverage = json.loads((output_dir / "coverage-report.json").read_text(encoding="utf-8"))
    handoff = (output_dir / "handoff.md").read_text(encoding="utf-8")
    readiness = (output_dir / "server/external-server-readiness.md").read_text(
        encoding="utf-8"
    )

    assert metadata["galileo_console_url"] == GALILEO_CONSOLE_URL
    assert apply_plan["galileo_console_url"] == GALILEO_CONSOLE_URL
    assert coverage["defaults"]["galileo_console_url"] == GALILEO_CONSOLE_URL
    assert GALILEO_CONSOLE_URL in handoff
    assert GALILEO_CONSOLE_URL in readiness


def test_mcp_render_derives_mcp_url_from_user_supplied_console_url(tmp_path: Path) -> None:
    output_dir = tmp_path / "mcp"
    run_cmd(
        "bash",
        "skills/galileo-mcp-server-setup/scripts/setup.sh",
        "--render",
        "--client",
        "cursor",
        "--galileo-console-url",
        GALILEO_CONSOLE_URL,
        "--output-dir",
        str(output_dir),
    )

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    cursor_config = json.loads((output_dir / "mcp/cursor.mcp.json").read_text(encoding="utf-8"))
    assert metadata["galileo_console_url"] == GALILEO_CONSOLE_URL
    assert metadata["mcp_url"] == GALILEO_MCP_URL
    assert GALILEO_MCP_URL in json.dumps(cursor_config)

    dry_run = run_cmd(
        "bash",
        "skills/galileo-mcp-server-setup/scripts/setup.sh",
        "--render",
        "--dry-run",
        "--json",
        "--client",
        "cursor",
        "--galileo-console-url",
        GALILEO_CONSOLE_URL,
        "--output-dir",
        str(tmp_path / "mcp-dry-run"),
    )
    plan = json.loads(dry_run.stdout)
    assert plan["galileo_console_url"] == GALILEO_CONSOLE_URL
    assert plan["mcp_url"] == GALILEO_MCP_URL

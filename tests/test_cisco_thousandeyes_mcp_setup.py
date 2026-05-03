"""Regressions for cisco-thousandeyes-mcp-setup rendering."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/cisco-thousandeyes-mcp-setup/scripts/setup.sh"


def run_setup(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(SETUP), *args],
        cwd=REPO_ROOT,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def rendered_text(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def make_token_file(tmp_path: Path) -> Path:
    token = tmp_path / "te-token"
    token.write_text("TE_BEARER_TOKEN_SHOULD_NOT_LEAK", encoding="utf-8")
    token.chmod(0o600)
    return token


def test_render_all_clients_produces_expected_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    token = make_token_file(tmp_path)
    result = run_setup(
        "--render",
        "--client",
        "cursor,claude,codex,vscode,kiro",
        "--auth",
        "bearer",
        "--te-token-file",
        str(token),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    for f in (
        "mcp/cursor.mcp.json",
        "mcp/claude.mcp.json",
        "mcp/codex-register-te-mcp.sh",
        "mcp/vscode.mcp.json",
        "mcp/kiro.mcp.json",
        "mcp/README.md",
        "metadata.json",
    ):
        assert (output / f).is_file(), f"Missing rendered file: {f}"
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["skill"] == "cisco-thousandeyes-mcp-setup"
    assert metadata["te_mcp_url"] == "https://api.thousandeyes.com/mcp"
    # Rate-limit + write-tool warnings must be in the README.
    readme = (output / "mcp" / "README.md").read_text(encoding="utf-8")
    assert "240 req/min" in readme
    assert "Run Instant Test" in readme


def test_token_value_never_appears_in_rendered_output(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    token = make_token_file(tmp_path)
    result = run_setup(
        "--render",
        "--client",
        "cursor,claude,codex,vscode,kiro",
        "--auth",
        "bearer",
        "--te-token-file",
        str(token),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    assert "TE_BEARER_TOKEN_SHOULD_NOT_LEAK" not in rendered_text(output)


@pytest.mark.parametrize(
    "flag", ["--te-token", "--access-token", "--token", "--bearer-token", "--api-token"]
)
def test_direct_secret_flags_are_rejected(flag: str, tmp_path: Path) -> None:
    result = run_setup(
        "--render",
        "--client",
        "cursor",
        flag,
        "INLINE_SHOULD_NOT_LEAK",
    )
    assert result.returncode == 1
    assert "--te-token-file" in combined_output(result)
    assert "INLINE_SHOULD_NOT_LEAK" not in combined_output(result)


def test_dry_run_json_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    token = make_token_file(tmp_path)
    args = [
        "--render",
        "--client",
        "cursor,claude",
        "--auth",
        "bearer",
        "--te-token-file",
        str(token),
        "--dry-run",
        "--json",
    ]
    first = run_setup(*args)
    second = run_setup(*args)
    assert first.returncode == 0, combined_output(first)
    assert second.returncode == 0, combined_output(second)
    first_json = json.loads(first.stdout)
    second_json = json.loads(second.stdout)
    assert first_json == second_json
    assert first_json["skill"] == "cisco-thousandeyes-mcp-setup"


def test_idempotent_re_render(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    token = make_token_file(tmp_path)
    args = [
        "--render",
        "--client",
        "cursor,claude",
        "--auth",
        "bearer",
        "--te-token-file",
        str(token),
        "--output-dir",
        str(output),
    ]
    first = run_setup(*args)
    second = run_setup(*args)
    assert first.returncode == 0, combined_output(first)
    assert second.returncode == 0, combined_output(second)
    cursor_first = (output / "mcp" / "cursor.mcp.json").read_text(encoding="utf-8")
    second_run_output = output / "mcp" / "cursor.mcp.json"
    assert second_run_output.read_text(encoding="utf-8") == cursor_first


def test_codex_script_uses_token_file_at_runtime(tmp_path: Path) -> None:
    """Codex registration shell must read the token file at runtime, not embed it."""
    output = tmp_path / "rendered"
    token = make_token_file(tmp_path)
    result = run_setup(
        "--render",
        "--client",
        "codex",
        "--auth",
        "bearer",
        "--te-token-file",
        str(token),
        "--output-dir",
        str(output),
    )
    assert result.returncode == 0, combined_output(result)
    script = (output / "mcp" / "codex-register-te-mcp.sh").read_text(encoding="utf-8")
    assert 'cat "${TOKEN_FILE}"' in script
    assert "TE_BEARER_TOKEN_SHOULD_NOT_LEAK" not in script
    # The Codex script must invoke `codex mcp add ...` and reference the
    # canonical TE MCP URL.
    assert "codex mcp add" in script
    assert "https://api.thousandeyes.com/mcp" in script

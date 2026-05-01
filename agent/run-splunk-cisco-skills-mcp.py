#!/usr/bin/env python3
"""Run the repo-local Splunk Cisco skills MCP server over stdio."""

import os
import sys
from pathlib import Path

RUNNER_PATH = Path(__file__).resolve()
REPO_ROOT = RUNNER_PATH.parents[1]
AGENT_DIR = RUNNER_PATH.parent


def _maybe_reexec_repo_venv() -> None:
    """Prefer the repo-local venv without requiring GUI clients to inherit it."""
    if os.environ.get("SPLUNK_CISCO_SKILLS_MCP_NO_VENV") == "1":
        return
    if os.environ.get("SPLUNK_CISCO_SKILLS_MCP_REEXECED") == "1":
        return

    venv_dir = REPO_ROOT / ".venv"
    if Path(sys.prefix).resolve() == venv_dir.resolve():
        return

    candidates = [
        venv_dir / "bin" / "python3",
        venv_dir / "bin" / "python",
    ]
    for candidate in candidates:
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        os.environ["SPLUNK_CISCO_SKILLS_MCP_REEXECED"] = "1"
        os.execv(str(candidate), [str(candidate), str(RUNNER_PATH), *sys.argv[1:]])


_maybe_reexec_repo_venv()

sys.path.insert(0, str(AGENT_DIR))

try:
    from splunk_cisco_skills_mcp.server import main
except ModuleNotFoundError as exc:
    if exc.name in {"mcp", "yaml"}:
        print(
            f"Missing Python dependency '{exc.name}' for the local agent server. "
            "Install with: pip install -r requirements-agent.txt",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    raise


if __name__ == "__main__":
    main()

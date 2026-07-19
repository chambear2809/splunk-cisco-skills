#!/usr/bin/env python3
"""Run the repo-local Splunk Cisco skills MCP server over stdio."""

# Defer annotation evaluation so this launcher parses on the entry interpreter
# (e.g. macOS system Python 3.9 used by GUI clients) before it re-execs into the
# repo .venv. Without this, PEP 604 unions like ``Path | None`` raise TypeError
# at import time on Python < 3.10.
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

RUNNER_PATH = Path(__file__).resolve()
REPO_ROOT = RUNNER_PATH.parents[1]
AGENT_DIR = RUNNER_PATH.parent


def _require_isolated_python() -> None:
    if not sys.flags.isolated:
        print(
            "Refusing non-isolated Python startup. Run: python3 -I "
            "agent/run-splunk-cisco-skills-mcp.py",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _trusted_repo_venv(venv_dir: Path, candidate: Path) -> Path | None:
    """Return a checked venv launcher whose parent chain is not shared-writable."""
    if not hasattr(os, "geteuid"):
        try:
            return candidate
        except OSError:
            return None  # Windows ACL validation is outside this POSIX launcher.
    owner = os.geteuid()
    for directory in (REPO_ROOT, venv_dir, venv_dir / "bin"):
        try:
            metadata = directory.lstat()
        except OSError:
            return None
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != owner
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            return None

    try:
        link_metadata = candidate.lstat()
        resolved = candidate.resolve(strict=True)
        target_metadata = resolved.stat()
    except OSError:
        return None
    if link_metadata.st_uid != owner:
        return None
    trusted = (
        stat.S_ISREG(target_metadata.st_mode)
        and target_metadata.st_uid in {0, owner}
        and not target_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        and os.access(resolved, os.X_OK)
    )
    # Execute through the venv launcher rather than its resolved base-Python
    # target so Python still discovers pyvenv.cfg and venv site-packages. The
    # checked parent chain prevents another OS user from swapping the launcher;
    # the repository owner is already inside this server's trust boundary.
    return candidate if trusted else None


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
    saw_candidate = False
    for candidate in candidates:
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        saw_candidate = True
        trusted_interpreter = _trusted_repo_venv(venv_dir, candidate)
        if trusted_interpreter is None:
            continue
        child_env = os.environ.copy()
        child_env["SPLUNK_CISCO_SKILLS_MCP_REEXECED"] = "1"
        # Re-exec alone does not activate a virtual environment. Prepending its
        # bin directory ensures Python helpers launched by Bash skill scripts
        # resolve the same dependency set as this MCP process.
        bin_dir = str(venv_dir / "bin")
        current_path = child_env.get("PATH", "")
        child_env["PATH"] = (
            bin_dir if not current_path else f"{bin_dir}{os.pathsep}{current_path}"
        )
        os.execve(
            str(trusted_interpreter),
            [str(trusted_interpreter), "-I", str(RUNNER_PATH), *sys.argv[1:]],
            child_env,
        )
    if saw_candidate:
        print(
            "Refusing untrusted repo .venv: it must be owned by the current user "
            "and not writable by group or others.",
            file=sys.stderr,
        )
        raise SystemExit(1)


_require_isolated_python()
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

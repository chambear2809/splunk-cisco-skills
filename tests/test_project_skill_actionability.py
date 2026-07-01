#!/usr/bin/env python3
"""Project-wide actionability and entrypoint regressions for skills."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


SKILLS_DIR = REPO_ROOT / "skills"

ACTION_CUES = (
    "--apply",
    "--install",
    "--execute",
    "--phase",
    "--all",
    "--configure-only",
    "--install-only",
    "--uninstall",
    "--send-alert",
    "--install-splunk-app",
    "--cleanup",
    "--discover",
    "--discover-metrics",
    "--indexes-only",
    "--settings-only",
    "--enable-inputs",
    "--macros-only",
    "--accelerate",
    "--sync",
    "--run-now",
    "--action",
    "--daily-ingest-gb",
    "compute and print",
    "sizing",
    "with no flags, runs full setup",
    "with no flags, installs the app",
    "default operation is --install",
    "default with no mode is install",
    "render-only",
    "--render",
    "--validate",
)


def skill_dirs() -> list[Path]:
    return sorted(
        path
        for path in SKILLS_DIR.iterdir()
        if path.is_dir()
        and path.name != "shared"
        and not path.name.startswith(".")
        and (path / "SKILL.md").is_file()
    )


def run_help(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def run_json(*args: str) -> dict:
    result = subprocess.run(
        ["bash", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_every_skill_has_working_setup_and_validate_entrypoints() -> None:
    failures: list[str] = []
    for skill in skill_dirs():
        setup = skill / "scripts/setup.sh"
        validate = skill / "scripts/validate.sh"
        if not setup.is_file():
            failures.append(f"{skill.name}: missing scripts/setup.sh")
            continue
        if not validate.is_file():
            failures.append(f"{skill.name}: missing scripts/validate.sh")
            continue

        setup_help = run_help(setup)
        if setup_help.returncode != 0:
            failures.append(f"{skill.name}: setup.sh --help failed: {setup_help.stdout}{setup_help.stderr}")
        validate_help = run_help(validate)
        if validate_help.returncode != 0:
            failures.append(f"{skill.name}: validate.sh --help failed: {validate_help.stdout}{validate_help.stderr}")

    assert not failures, "\n".join(failures)


def test_every_setup_help_advertises_a_task_or_action_surface() -> None:
    failures: list[str] = []
    for skill in skill_dirs():
        result = run_help(skill / "scripts/setup.sh")
        help_text = (result.stdout + result.stderr).lower()
        if not any(cue in help_text for cue in ACTION_CUES):
            failures.append(f"{skill.name}: setup.sh --help does not advertise render, validate, apply, install, or task execution")

    assert not failures, "\n".join(failures)


def test_routers_can_execute_routed_action_plans_in_dry_run_mode() -> None:
    security = run_json(
        "skills/splunk-security-portfolio-setup/scripts/setup.sh",
        "--product",
        "security content update",
        "--execute",
        "--dry-run",
        "--json",
    )
    assert security["would_execute"] == [
        "bash",
        "skills/splunk-security-content-update-setup/scripts/setup.sh",
        "--install",
    ]

    asa = run_json(
        "skills/splunk-supported-addons-setup/scripts/setup.sh",
        "--profile",
        "Cisco ASA",
        "--execute",
        "--dry-run",
        "--json",
    )
    assert asa["would_execute"] == [
        "bash",
        "skills/cisco-asa-ta-setup/scripts/setup.sh",
        "--all",
    ]

    mysql = run_json(
        "skills/splunk-supported-addons-setup/scripts/setup.sh",
        "--phase",
        "install-command",
        "--profile",
        "MySQL",
        "--json",
    )
    assert mysql["command"] == [
        "bash",
        "skills/splunk-database-ta-setup/scripts/setup.sh",
        "--install",
        "--products",
        "mysql",
    ]

#!/usr/bin/env python3
"""Parent router for coding-agent observability setup skills."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from skills.shared.coding_agent_o11y.common import (
    REPO_ROOT,
    UsageError,
    command_failed,
    print_payload,
    reject_secret_argv,
    shell_join,
    write_json,
    write_text,
)


SKILL_NAME = "splunk-observability-coding-agent-instrumentation-setup"
CODEX_CHILD = "splunk-observability-codex-instrumentation-setup"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "splunk-observability-coding-agent-instrumentation-rendered"
VALID_AGENTS = {"codex", "future"}
VALID_DESTINATIONS = {"local-collector", "external-collector", "direct", "all"}


def child_command(agent: str, destination: str) -> list[str]:
    if agent != "codex":
        raise UsageError(f"agent {agent!r} is a future placeholder and has no child implementation yet")
    return [
        "bash",
        f"skills/{CODEX_CHILD}/scripts/setup.sh",
        "--render",
        "--destination",
        destination,
    ]


def orchestration_plan(agent: str, destination: str) -> dict[str, Any]:
    command = child_command(agent, destination)
    warnings = []
    if destination in {"external-collector", "all"}:
        warnings.append("external collector child render requires explicit trace and metric endpoints")
    if destination in {"direct", "all"}:
        warnings.append("direct Splunk ingest is OTLP/HTTP traces and metrics only; native logs stay disabled")
    return {
        "skill": SKILL_NAME,
        "agent": agent,
        "destination": destination,
        "child_skill": CODEX_CHILD,
        "router_only": True,
        "would_execute": command,
        "warnings": warnings,
    }


def render_plan(output_dir: Path, plan: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "coding-agent-orchestration-plan.json", plan)
    lines = [
        "# Coding Agent O11y Orchestration Plan",
        "",
        f"- Agent: `{plan['agent']}`",
        f"- Destination: `{plan['destination']}`",
        f"- Child skill: `{plan['child_skill']}`",
        f"- Router only: `{str(plan['router_only']).lower()}`",
        "",
        "## Child Command",
        "",
        "```bash",
        shell_join(plan["would_execute"]),
        "```",
        "",
    ]
    if plan["warnings"]:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in plan["warnings"])
        lines.append("")
    write_text(output_dir / "doctor-report.md", "\n".join(lines))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--render", action="store_true")
    modes.add_argument("--validate", action="store_true")
    modes.add_argument("--doctor", action="store_true")
    modes.add_argument("--discover", action="store_true")
    modes.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--agent", choices=sorted(VALID_AGENTS), default="codex")
    parser.add_argument("--destination", choices=sorted(VALID_DESTINATIONS), default="local-collector")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in argv
    try:
        reject_secret_argv(argv)
        args = parse_args(argv)
        output_dir = Path(args.output_dir).expanduser().resolve()
        if args.discover:
            payload = {
                "agents": sorted(VALID_AGENTS),
                "implemented_agents": ["codex"],
                "destinations": sorted(VALID_DESTINATIONS),
                "parent_is_router_only": True,
            }
            print_payload(payload, args.json)
            return 0
        plan = orchestration_plan(args.agent, args.destination)
        if args.execute:
            if args.dry_run:
                if args.json:
                    print(json.dumps(plan, indent=2, sort_keys=True))
                else:
                    print(shell_join(plan["would_execute"]))
                return 0
            return subprocess.run(plan["would_execute"], cwd=REPO_ROOT, check=False).returncode
        if args.validate:
            render_plan(output_dir, plan)
            payload = {"ok": True, "output_dir": str(output_dir), "router_only": True}
            print_payload(payload, args.json)
            return 0
        render_plan(output_dir, plan)
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print(f"rendered coding-agent orchestration plan -> {output_dir}")
        return 0
    except Exception as exc:
        return command_failed(exc, json_output)


if __name__ == "__main__":
    raise SystemExit(main())

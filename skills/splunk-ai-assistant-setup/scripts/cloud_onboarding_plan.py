#!/usr/bin/env python3
"""Render the Splunk AI Assistant onboarding handoff plan."""

from __future__ import annotations

import argparse
import json
import shlex
from typing import Any


SETUP_SCRIPT = "skills/splunk-ai-assistant-setup/scripts/setup.sh"
VALIDATE_SCRIPT = "skills/splunk-ai-assistant-setup/scripts/validate.sh"
APP_NAME = "Splunk_AI_Assistant_Cloud"
SPLUNKBASE_ID = "7245"
LATEST_VERIFIED_APP_VERSION = "2.0.0"


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def install_command(app_version: str | None) -> str:
    command = ["bash", SETUP_SCRIPT, "--install"]
    if app_version:
        command.extend(["--app-version", app_version])
    return shell_join(command)


def cloud_plan(args: argparse.Namespace) -> dict[str, Any]:
    steps = [
        {
            "name": "Install or update public Splunkbase app",
            "automation": "supported",
            "command": install_command(args.app_version),
        },
        {
            "name": "Validate app visibility and REST reachability",
            "automation": "supported",
            "command": shell_join(["bash", VALIDATE_SCRIPT]),
        },
        {
            "name": "Open the app in Splunk Web and complete eligible Cloud-side onboarding",
            "automation": "manual-gate",
            "details": [
                "Use the public Splunkbase install path; do not private-upload the app archive.",
                "Confirm the stack is in a supported AWS or Azure commercial region, or an eligible IL2 FedRAMP deployment.",
                "Agent Mode in 2.0.0 is limited to supported AWS commercial regions and requires Splunk platform 10.1+.",
                "In IL2 FedRAMP, Agent Mode is unavailable, data for training/fine-tuning defaults off, and Model Runtime uses Splunk-hosted models only.",
                "If the UI blocks onboarding, open a Splunk Support or Cloud App Request and include app ID 7245.",
            ],
        },
        {
            "name": "Re-run validation after onboarding",
            "automation": "supported",
            "command": shell_join(["bash", VALIDATE_SCRIPT, "--expect-configured", "true"]),
        },
    ]
    if args.stack:
        steps.insert(
            1,
            {
                "name": "Confirm ACS stack context",
                "automation": "operator-check",
                "command": shell_join(["acs", "--stack", args.stack, "status", "current-stack"]),
            },
        )
    if args.support_case:
        steps[2]["details"].append(f"Track Cloud-side progress in support case {args.support_case}.")
    return {
        "workflow": "splunk-ai-assistant-cloud-onboarding",
        "mode": "plan-only",
        "platform": "cloud",
        "app": APP_NAME,
        "splunkbase_id": SPLUNKBASE_ID,
        "latest_verified_version": LATEST_VERIFIED_APP_VERSION,
        "steps": steps,
        "notes": [
            "Splunk AI Assistant for SPL was renamed to Splunk AI Assistant in the 2.0.0 documentation.",
            "This plan does not collect secrets and does not drive browser-only Cloud onboarding screens.",
            "Cloud installs remain ACS/public Splunkbase only; Enterprise cloud-connected activation uses setup.sh handlers instead.",
            "After install, use the app UI to review Context settings and Model Runtime.",
        ],
    }


def enterprise_plan(args: argparse.Namespace) -> dict[str, Any]:
    steps = [
        {
            "name": "Install or update public Splunkbase app",
            "automation": "supported",
            "command": install_command(args.app_version),
        },
        {
            "name": "Submit cloud-connected onboarding form",
            "automation": "supported",
            "command": shell_join(
                [
                    "bash",
                    SETUP_SCRIPT,
                    "--submit-onboarding-form",
                    "--email",
                    "<contact-email>",
                    "--region",
                    args.region or "usa",
                    "--company-name",
                    "<company-name>",
                    "--tenant-name",
                    "<tenant-name>",
                ]
            ),
        },
        {
            "name": "Complete activation from local activation-code file",
            "automation": "supported-with-secret-file",
            "command": shell_join(
                [
                    "bash",
                    SETUP_SCRIPT,
                    "--complete-onboarding",
                    "--activation-code-file",
                    "/path/to/saia_activation_code",
                ]
            ),
        },
        {
            "name": "Validate configured state",
            "automation": "supported",
            "command": shell_join(
                ["bash", VALIDATE_SCRIPT, "--expect-configured", "true", "--expect-onboarded", "true"]
            ),
        },
    ]
    return {
        "workflow": "splunk-ai-assistant-enterprise-onboarding",
        "mode": "plan-only",
        "platform": "enterprise",
        "app": APP_NAME,
        "splunkbase_id": SPLUNKBASE_ID,
        "latest_verified_version": LATEST_VERIFIED_APP_VERSION,
        "steps": steps,
        "notes": [
            "Splunk AI Assistant for SPL was renamed to Splunk AI Assistant in the 2.0.0 documentation.",
            "For unpinned latest installs, prefer Splunk Enterprise 9.3+ based on the current Splunkbase compatibility listing.",
            "Activation codes and proxy passwords must be stored in local files, never chat or command-line arguments.",
            "The search head must be able to reach Splunk-managed cloud services on HTTPS.",
            "Agent Mode is not enabled by this Cloud Connected workflow; it is Cloud-region gated.",
        ],
    }


def render_text(plan: dict[str, Any]) -> str:
    lines = [
        f"Workflow: {plan['workflow']}",
        f"Platform: {plan['platform']}",
        f"App: {plan['app']} ({plan['splunkbase_id']})",
        f"Latest verified version: {plan['latest_verified_version']}",
        "",
        "Steps:",
    ]
    for index, step in enumerate(plan["steps"], start=1):
        lines.append(f"{index}. {step['name']} [{step['automation']}]")
        if step.get("command"):
            lines.append(f"   {step['command']}")
        for detail in step.get("details", []):
            lines.append(f"   - {detail}")
    lines.append("")
    lines.append("Notes:")
    lines.extend(f"- {note}" for note in plan["notes"])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk AI Assistant onboarding plan.")
    parser.add_argument("--platform", choices=["cloud", "enterprise"], default="cloud")
    parser.add_argument("--stack", help="Optional Splunk Cloud stack name for ACS status commands")
    parser.add_argument("--app-version", help="Optional Splunkbase app version pin")
    parser.add_argument("--support-case", help="Optional Splunk Support case number for Cloud tracking")
    parser.add_argument("--region", help="Enterprise onboarding region token, for example usa")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = cloud_plan(args) if args.platform == "cloud" else enterprise_plan(args)
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        print(render_text(plan), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

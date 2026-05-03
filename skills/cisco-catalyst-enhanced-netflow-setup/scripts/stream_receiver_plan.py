#!/usr/bin/env python3
"""Render the Splunk Stream receiver handoff for Enhanced NetFlow."""

from __future__ import annotations

import argparse
import json
import shlex
from typing import Any


ENHANCED_NETFLOW_SETUP = "skills/cisco-catalyst-enhanced-netflow-setup/scripts/setup.sh"
ENHANCED_NETFLOW_VALIDATE = "skills/cisco-catalyst-enhanced-netflow-setup/scripts/validate.sh"
STREAM_SETUP = "skills/splunk-stream-setup/scripts/setup.sh"
STREAM_VALIDATE = "skills/splunk-stream-setup/scripts/validate.sh"


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def enterprise_command(parts: list[str]) -> str:
    return "SPLUNK_PLATFORM=enterprise " + shell_join(parts)


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    stream_command = enterprise_command(
        [
            "bash",
            STREAM_SETUP,
            "--install",
            "--configure-streamfwd",
            "--ip-addr",
            args.forwarder_ip,
            "--port",
            args.stream_port,
            "--splunk-web-url",
            args.splunk_web_url,
            "--ssl-verify",
            args.ssl_verify,
            "--netflow-ip",
            args.netflow_ip,
            "--netflow-port",
            args.netflow_port,
            "--netflow-decoder",
            args.netflow_decoder,
        ]
    )
    steps = [
        {
            "name": "Install Enhanced NetFlow mappings on the parsing target",
            "automation": "supported",
            "command": enterprise_command(["bash", ENHANCED_NETFLOW_SETUP, "--install"]),
        },
        {
            "name": "Configure Splunk Stream receiver on the same forwarder-side target",
            "automation": "supported-by-splunk-stream-setup",
            "command": stream_command,
        },
        {
            "name": "Validate Stream receiver path",
            "automation": "supported",
            "command": enterprise_command(["bash", STREAM_VALIDATE]),
        },
        {
            "name": "Validate Enhanced NetFlow mappings and consumer apps",
            "automation": "supported",
            "command": enterprise_command(["bash", ENHANCED_NETFLOW_VALIDATE]),
        },
    ]
    return {
        "workflow": "cisco-catalyst-enhanced-netflow-stream-receiver-handoff",
        "mode": "plan-only",
        "app": "splunk_app_stream_ipfix_cisco_hsl",
        "splunkbase_id": "6872",
        "receiver": {
            "forwarder_ip": args.forwarder_ip,
            "stream_port": args.stream_port,
            "splunk_web_url": args.splunk_web_url,
            "netflow_ip": args.netflow_ip,
            "netflow_port": args.netflow_port,
            "netflow_decoder": args.netflow_decoder,
        },
        "steps": steps,
        "notes": [
            "This add-on supplies mappings only; Splunk_TA_stream owns the receiver.",
            "Run these commands against a customer-controlled forwarder or standalone Splunk instance, not the Splunk Cloud search tier.",
            "Open firewall and network ACLs for the NetFlow/IPFIX exporter path before validation.",
        ],
    }


def render_text(plan: dict[str, Any]) -> str:
    lines = [
        f"Workflow: {plan['workflow']}",
        f"App: {plan['app']} ({plan['splunkbase_id']})",
        "",
        "Receiver:",
    ]
    for key, value in plan["receiver"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("Steps:")
    for index, step in enumerate(plan["steps"], start=1):
        lines.append(f"{index}. {step['name']} [{step['automation']}]")
        lines.append(f"   {step['command']}")
    lines.append("")
    lines.append("Notes:")
    lines.extend(f"- {note}" for note in plan["notes"])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Enhanced NetFlow Stream receiver handoff.")
    parser.add_argument("--forwarder-ip", default="<forwarder-ip>")
    parser.add_argument("--stream-port", default="8889")
    parser.add_argument("--splunk-web-url", default="https://<search-head>:8000")
    parser.add_argument("--ssl-verify", choices=["true", "false"], default="false")
    parser.add_argument("--netflow-ip", default="0.0.0.0")
    parser.add_argument("--netflow-port", default="9995")
    parser.add_argument("--netflow-decoder", choices=["netflow", "sflow"], default="netflow")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = build_plan(args)
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        print(render_text(plan), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

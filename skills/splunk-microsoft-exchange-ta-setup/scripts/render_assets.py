#!/usr/bin/env python3
"""Render package-verified Microsoft Exchange supported add-on assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-microsoft-exchange-ta-rendered"

APPS = [
    {"app": "TA-Exchange-ClientAccess", "id": "3225", "version": "4.1.0"},
    {"app": "TA-Exchange-Mailbox", "id": "3225", "version": "4.1.0"},
    {"app": "TA-SMTP-Reputation", "id": "3225", "version": "4.1.0"},
    {"app": "TA-Windows-Exchange-IIS", "id": "3225", "version": "4.1.0"},
    {"app": "SA-ExchangeIndex", "id": "5663", "version": "4.0.4"},
]

SOURCETYPES = [
    "MSExchange:2013:MessageTracking",
    "MSExchange:2013:MailboxAudit",
    "MSExchange:2013:AdminAudit",
    "MSExchange:2013:RPCClientAccess",
    "MSExchange:2013:Topology",
    "MSExchange:Reputation",
    "WinEventLog:Exchange",
    "MSWindows:2013EWS:IIS",
]

COMPONENTS: dict[str, dict[str, Any]] = {
    "client_access": {
        "app": "TA-Exchange-ClientAccess",
        # Each input is an explicit (stanza, sourcetype) pair so the renderer
        # never silently drops or misorders entries.
        "inputs": [
            ("[monitor://C:\\Program Files\\Microsoft\\Exchange Server\\V15\\Logging\\RPC Client Access]", "MSExchange:2013:RPCClientAccess"),
            ("[script://.\\bin\\exchangepowershell.cmd v15 get-hoststats_2013.ps1]", "MSExchange:2013:Topology"),
            ("[script://.\\bin\\exchangepowershell.cmd v15 get-throttling-policies_2010_2013.ps1]", "MSExchange:2013:ThrottlingPolicy"),
        ],
    },
    "mailbox": {
        "app": "TA-Exchange-Mailbox",
        "inputs": [
            ("[WinEventLog://Exchange Auditing]", "WinEventLog:Exchange"),
            ("[monitor://C:\\Program Files\\Microsoft\\Exchange Server\\V15\\TransportRoles\\Logs\\MessageTracking]", "MSExchange:2013:MessageTracking"),
            ("[script://.\\bin\\exchangepowershell.cmd v15 get-mailboxstats_2013.ps1]", "MSExchange:2013:Database-Stats"),
        ],
    },
    "smtp_reputation": {
        "app": "TA-SMTP-Reputation",
        "inputs": [
            ("[script://.\\bin\\reputation.ps1]", "MSExchange:Reputation"),
        ],
    },
    "iis": {
        "app": "TA-Windows-Exchange-IIS",
        "inputs": [
            ("[monitor://C:\\inetpub\\logs\\LogFiles\\W3SVC*\\*.log]", "MSWindows:2013EWS:IIS"),
        ],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Microsoft Exchange supported add-on assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--products", default="exchange", help="Product selector; only exchange is supported.")
    parser.add_argument("--index", default="msexchange", help="Exchange event index.")
    parser.add_argument("--perfmon-index", default="perfmon")
    parser.add_argument("--windows-index", default="windows")
    parser.add_argument("--wineventlog-index", default="wineventlog")
    parser.add_argument("--msad-index", default="msad")
    parser.add_argument("--server-name", default="exchange01")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def validate_products(raw: str) -> list[str]:
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if values != ["exchange"]:
        raise SystemExit("ERROR: Microsoft Exchange renderer supports --products exchange")
    return values


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_plan(args: argparse.Namespace) -> str:
    rows = [f"| `{app['app']}` | `{app['id']}` | `{app['version']}` |" for app in APPS]
    return f"""# Microsoft Exchange Supported Add-on Setup Plan

Primary Exchange index: `{args.index}`
Indexes app defines: `{args.index}`, `{args.perfmon_index}`, `{args.windows_index}`, `{args.wineventlog_index}`, `{args.msad_index}`

| App | Splunkbase | Verified |
| --- | --- | --- |
{chr(10).join(rows)}

## Guardrails

- Install the Exchange bundle and `SA-ExchangeIndex` together for package-aligned knowledge and indexes.
- Deploy component collection only to reviewed Windows collection owners.
- Use `splunk-windows-ta-setup` for general Windows Event Log and Perfmon prerequisite validation.
"""


def render_inputs(args: argparse.Namespace) -> str:
    lines = [
        "# Starter local/inputs.conf overlay fragments from extracted Exchange component apps.",
        "# These stanzas are disabled for review and must be enabled only on the correct Exchange collection owner.",
        "",
    ]
    for component in COMPONENTS.values():
        lines += [f"# {component['app']}"]
        for stanza, sourcetype in component["inputs"]:
            lines += [
                stanza,
                "disabled = 1",
                f"sourcetype = {sourcetype}",
                f"index = {args.index}",
                f"host = {args.server_name}",
                "",
            ]
    lines += [
        "# Package perfmon stanzas retain their component defaults; map them to the perfmon index when enabled.",
        "[perfmon://MSExchange_Throttling_2013]",
        "disabled = 1",
        f"index = {args.perfmon_index}",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_collection_placement(args: argparse.Namespace) -> str:
    lines = [
        "# Exchange Collection Placement",
        "",
        "Install search-time knowledge on search heads and index-time props/transforms where required by topology.",
        "Deploy enabled Exchange collection stanzas only to Windows hosts that own the Exchange role being collected.",
        "",
        "| Component | Package Source Types |",
        "| --- | --- |",
    ]
    for component in COMPONENTS.values():
        sourcetypes = [sourcetype for _stanza, sourcetype in component["inputs"]]
        lines.append(f"| `{component['app']}` | {', '.join(f'`{item}`' for item in sourcetypes)} |")
    lines += [
        "",
        "Run Windows TA readiness for Event Log, Perfmon, and host inventory prerequisites before enabling high-volume Exchange inputs.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_install_commands(args: argparse.Namespace) -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 3225 --app-version 4.1.0 --no-update  # Exchange component bundle
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 5663 --app-version 4.0.4 --no-update  # SA-ExchangeIndex

bash skills/splunk-windows-ta-setup/scripts/setup.sh --help
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack microsoft_exchange
"""


def render_validation(args: argparse.Namespace) -> str:
    sourcetypes = ",".join(f'"{item}"' for item in SOURCETYPES)
    return f"""# Microsoft Exchange validation searches

index={args.index} sourcetype IN ({sourcetypes})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype host source
| convert ctime(first_seen) ctime(last_seen)

index IN ({args.index},{args.perfmon_index},{args.windows_index},{args.wineventlog_index},{args.msad_index}) (sourcetype=WinEventLog:Exchange OR sourcetype=MSWindows:2013EWS:IIS OR sourcetype=MSExchange:*)
| stats count dc(host) as hosts by index sourcetype

index=_internal source=*splunkd.log* (TA-Exchange-ClientAccess OR TA-Exchange-Mailbox OR TA-SMTP-Reputation OR TA-Windows-Exchange-IIS OR SA-ExchangeIndex)
| stats count values(log_level) as levels by component
"""


def render_assets(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output_dir).expanduser().resolve() / "splunk-microsoft-exchange-ta"
    files = [
        "collection-placement.md",
        "inputs.local.conf.template",
        "install-commands.sh",
        "metadata.json",
        "profile-plan.md",
        "validation-searches.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(output), "files": files}
    metadata = {
        "apps": APPS,
        "components": COMPONENTS,
        "indexes": {
            "msexchange": args.index,
            "perfmon": args.perfmon_index,
            "windows": args.windows_index,
            "wineventlog": args.wineventlog_index,
            "msad": args.msad_index,
        },
        "source_pack": "microsoft_exchange",
    }
    write_file(output / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True))
    write_file(output / "profile-plan.md", render_plan(args))
    write_file(output / "inputs.local.conf.template", render_inputs(args))
    write_file(output / "collection-placement.md", render_collection_placement(args))
    write_file(output / "install-commands.sh", render_install_commands(args), executable=True)
    write_file(output / "validation-searches.spl", render_validation(args))
    return {"ok": True, "dry_run": False, "output_dir": str(output), "files": sorted(files)}


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Output: {payload.get('output_dir', '')}")
        if payload.get("files"):
            print("Files: " + ", ".join(payload["files"]))


def main() -> int:
    args = parse_args()
    validate_products(args.products)
    if args.phase == "list":
        emit({"ok": True, "products": ["exchange"], "apps": APPS, "sourcetypes": SOURCETYPES}, args.json)
        return 0
    emit(render_assets(args), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

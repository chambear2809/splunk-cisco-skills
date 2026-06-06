#!/usr/bin/env python3
"""Render reviewable Splunk Add-on for Microsoft Sysmon assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-sysmon-ta-rendered"

APP_NAME = "Splunk_TA_microsoft_sysmon"
SPLUNKBASE_ID = "5709"
LATEST_VERIFIED_VERSION = "5.0.0"

SYSMON_SOURCE = "XmlWinEventLog:Microsoft-Windows-Sysmon/Operational"
EVENTTYPES = [
    "ms-sysmon-network",
    "ms-sysmon-process",
    "ms-sysmon-filemod",
    "ms-sysmon-regmod",
    "ms-sysmon-wmimod",
    "ms-sysmon-dns",
    "ms-sysmon-service",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk_TA_microsoft_sysmon assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--index", default="sysmon", help="Target Sysmon event index.")
    parser.add_argument("--mode", choices=("endpoint", "wec"), default="endpoint", help="Endpoint UF or Windows Event Collector mode.")
    parser.add_argument("--wec-host", default="WinEventLogForwardHost", help="Host placeholder used by package WEC transform.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(args: argparse.Namespace) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {APP_NAME} (Splunkbase {SPLUNKBASE_ID}).",
        "# Render exactly one mode: endpoint OR WEC. Do not deploy both for the",
        "# same endpoint population, or Sysmon events will be duplicated.",
        "",
    ]
    if args.mode == "endpoint":
        lines += [
            "[WinEventLog://Microsoft-Windows-Sysmon/Operational]",
            "disabled = false",
            "renderXml = 1",
            f"source = {SYSMON_SOURCE}",
            f"index = {args.index}",
            "",
        ]
    else:
        lines += [
            "[WinEventLog://WEC-Sysmon]",
            "disabled = false",
            "renderXml = 1",
            f"source = {SYSMON_SOURCE}",
            "sourcetype = XmlWinEventLog:WEC-Sysmon",
            f"host = {args.wec_host}",
            f"index = {args.index}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_account_setup(args: argparse.Namespace) -> str:
    return f"""# {APP_NAME} Deployment Runbook

This add-on has no cloud API account. It normalizes Microsoft Sysmon XML event
logs collected from Windows Universal Forwarders or a Windows Event Collector.

## Endpoint mode

Deploy the rendered `[WinEventLog://Microsoft-Windows-Sysmon/Operational]`
stanza to endpoints running Sysmon. Use `splunk-universal-forwarder-setup` or
`splunk-agent-management-setup` for rollout.

## WEC mode

Deploy `[WinEventLog://WEC-Sysmon]` only to the Windows Event Collector host.
The package default sets `source = {SYSMON_SOURCE}` and
`sourcetype = XmlWinEventLog:WEC-Sysmon`.

## Duplicate-ingest guardrail

Do not enable endpoint direct collection and WEC collection for the same host
population. This renderer emits one mode at a time (`--mode {args.mode}`) to
make the ownership explicit.

## Sysmon configuration

Install Sysmon from Microsoft Sysinternals with an approved enterprise
configuration before enabling the input. The add-on ships CIM field aliases,
eventtypes, tags, and lookups; it does not install Sysmon itself.
"""


def render_install_commands(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {SPLUNKBASE_ID}
bash skills/splunk-sysmon-ta-setup/scripts/setup.sh --create-index --index {args.index}

# Roll out the rendered deployment app via splunk-universal-forwarder-setup or splunk-agent-management-setup.
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack sysmon
"""


def render_validation_spl(args: argparse.Namespace) -> str:
    return f"""# {APP_NAME} validation searches

index={args.index} source="{SYSMON_SOURCE}" sourcetype IN ("XmlWinEventLog","XmlWinEventLog:WEC-Sysmon","XmlWinEventLog:Microsoft-Windows-Sysmon/Operational")
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype source EventCode EventID
| convert ctime(first_seen) ctime(last_seen)

index={args.index} source="{SYSMON_SOURCE}" (EventCode=1 OR EventID=1 OR EventCode=3 OR EventID=3 OR EventCode=22 OR EventID=22)
| stats count by EventCode EventID Image DestinationHostname QueryName

| eventcount summarize=false index={args.index}

index=_internal source=*splunkd.log* ({APP_NAME} OR Sysmon OR "WEC-Sysmon")
| stats count values(log_level) as levels by sourcetype
"""


def render_plan_md(args: argparse.Namespace) -> str:
    return f"""# {APP_NAME} Setup Plan

Add-on: `{APP_NAME}` (Splunkbase `{SPLUNKBASE_ID}`, verified `{LATEST_VERIFIED_VERSION}`)
Event index: `{args.index}`
Mode: `{args.mode}`

## Role Placement

| Role | Support |
| --- | --- |
| `search-tier` | required for knowledge objects and CIM |
| `heavy-forwarder` | supported for Windows Event Collector collection |
| `indexer` | supported for parsing/props placement in self-managed deployments |
| `universal-forwarder` | supported for endpoint collection |
| `external-collector` | none |

## Package Defaults

| Mode | Stanza | Source / source type |
| --- | --- | --- |
| endpoint | `[WinEventLog://Microsoft-Windows-Sysmon/Operational]` | source `{SYSMON_SOURCE}` |
| wec | `[WinEventLog://WEC-Sysmon]` | source `{SYSMON_SOURCE}`, sourcetype `XmlWinEventLog:WEC-Sysmon` |

## CIM Eventtypes

{", ".join(f"`{item}`" for item in EVENTTYPES)}

## Guardrails

- Render and deploy one mode only for a given endpoint population.
- Keep broad Windows Security `XmlWinEventLog` readiness separate; Sysmon
  readiness is constrained to source `{SYSMON_SOURCE}`.
- Hand off Universal Forwarder or deployment-server rollout to
  `splunk-universal-forwarder-setup` / `splunk-agent-management-setup`.
"""


def render_assets(args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-sysmon-ta"
    files = [
        "account-setup.md",
        "inputs.local.conf.template",
        "install-commands.sh",
        "metadata.json",
        "profile-plan.md",
        "validation-searches.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(profile_dir), "files": files}
    metadata = {
        "app_name": APP_NAME,
        "splunkbase_id": SPLUNKBASE_ID,
        "latest_verified_version": LATEST_VERIFIED_VERSION,
        "index": args.index,
        "mode": args.mode,
        "source": SYSMON_SOURCE,
        "source_package": f"splunk-ta/_unpacked/{APP_NAME}-{LATEST_VERIFIED_VERSION}/{APP_NAME}",
        "eventtypes": EVENTTYPES,
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args))
    write_file(profile_dir / "inputs.local.conf.template", render_inputs(args))
    write_file(profile_dir / "account-setup.md", render_account_setup(args))
    write_file(profile_dir / "install-commands.sh", render_install_commands(args), executable=True)
    write_file(profile_dir / "validation-searches.spl", render_validation_spl(args))
    return {
        "ok": True,
        "dry_run": False,
        "output_dir": str(profile_dir),
        "files": sorted(path.name for path in profile_dir.iterdir() if path.is_file()),
    }


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if "files" in payload:
        print(f"App: {APP_NAME} (Splunkbase {SPLUNKBASE_ID})")
        print(f"Output: {payload['output_dir']}")
        print("Files: " + ", ".join(payload["files"]))
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    args = parse_args()
    if args.phase == "list":
        emit(
            {
                "ok": True,
                "app_name": APP_NAME,
                "splunkbase_id": SPLUNKBASE_ID,
                "modes": ["endpoint", "wec"],
                "source": SYSMON_SOURCE,
                "eventtypes": EVENTTYPES,
            },
            args.json,
        )
        return 0
    emit(render_assets(args), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
